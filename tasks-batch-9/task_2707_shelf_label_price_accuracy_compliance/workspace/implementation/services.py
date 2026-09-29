"""Derived-counter recomputation and the cascade chains."""
from datetime import timedelta
from fractions import Fraction

import calc
from core import (
    CERTIFICATION_VALID_DAYS,
    DB,
    POSTURE_AUDIT_WINDOW_DAYS,
    SUSPENSION_SCORE_FLOOR,
    apply_changes,
    insert,
    now,
    rows,
    touch,
)


# ------------------------------------------------------------------ lookups
def jurisdiction_of_store(store):
    return DB["jurisdictions"][store["jurisdiction_id"]]


def jurisdiction_of_file(price_change_file):
    return DB["jurisdictions"][price_change_file["jurisdiction_id"]]


def store_of_associate(associate):
    return DB["stores"][associate["store_id"]]


def jurisdiction_of_associate(associate):
    return jurisdiction_of_store(store_of_associate(associate))


def file_of_line(line):
    return DB["price_change_files"][line["price_change_file_id"]]


def audit_of_scan_line(scan_line):
    return DB["scanner_audits"][scan_line["scanner_audit_id"]]


def audit_scan_lines(audit_id):
    return [r for r in rows("scan_lines") if r["scanner_audit_id"] == audit_id]


def file_lines(file_id):
    return [r for r in rows("price_change_lines") if r["price_change_file_id"] == file_id]


def inspection_findings(inspection_id):
    return [
        r
        for r in rows("inspection_findings")
        if r["regulatory_inspection_id"] == inspection_id
    ]


def associate_actions(associate_id):
    return [
        r for r in rows("accountability_actions") if r["associate_id"] == associate_id
    ]


# ------------------------------------------------------------------ store
def label_backlog_count(store_id):
    total = 0
    for task in DB["label_tasks"].values():
        if task["store_id"] != store_id:
            continue
        if task["placement_status"] not in ("UNPLACED", "REJECTED"):
            continue
        line = DB["price_change_lines"].get(task["price_change_line_id"])
        if line is not None and line["line_status"] == "WITHDRAWN":
            continue
        total += 1
    return total


def derive_store_counters(store):
    """Recompute every derived counter from live rows, backlog first, then posture.

    Returns the derived field map without writing it, so a read capability can
    project live values without mutating the stored row.
    """
    store_id = store["id"]
    inspection_ids = {
        i["id"] for i in DB["regulatory_inspections"].values() if i["store_id"] == store_id
    }
    open_findings = 0
    escalated_findings = 0
    for finding in DB["inspection_findings"].values():
        if finding["regulatory_inspection_id"] not in inspection_ids:
            continue
        if finding["status"] in ("OPEN", "REMEDIATION_PLANNED"):
            open_findings += 1
        elif finding["status"] == "ESCALATED":
            escalated_findings += 1

    edge = now() - timedelta(days=POSTURE_AUDIT_WINDOW_DAYS)
    failed_30d = 0
    for audit in DB["scanner_audits"].values():
        if audit["store_id"] != store_id or audit["status"] != "CLOSED":
            continue
        if audit["outcome"] != "FAIL" or audit["closed_at"] is None:
            continue
        if audit["closed_at"] >= edge:
            failed_30d += 1

    signage_violations = sum(
        1
        for sign in DB["promo_signage"].values()
        if sign["store_id"] == store_id
        and sign["status"] in ("EXPIRED_PENDING_REMOVAL", "NON_COMPLIANT")
    )

    backlog = label_backlog_count(store_id)

    liability = 0
    paid_total = 0
    for claim in DB["refund_claims"].values():
        if claim["store_id"] != store_id:
            continue
        if claim["status"] in ("PENDING", "APPROVED"):
            liability += claim["claimed_amount_cents"]
        elif claim["status"] == "PAID":
            paid_total += claim["claimed_amount_cents"]

    cumulative = 0
    for inspection in DB["regulatory_inspections"].values():
        if inspection["store_id"] != store_id or inspection["status"] != "CLOSED":
            continue
        cumulative += inspection["assessed_penalty_cents"] or 0

    executed_files = sum(
        1
        for f in DB["price_change_files"].values()
        if f["status"] == "EXECUTED" and store_id in (f["scope_store_ids"] or [])
    )

    return {
        "label_backlog_count": backlog,
        "open_finding_count": open_findings,
        "escalated_finding_count": escalated_findings,
        "failed_audit_count_30d": failed_30d,
        "signage_violation_count": signage_violations,
        "refund_liability_outstanding_cents": liability,
        "refund_paid_total_cents": paid_total,
        "cumulative_penalty_exposure_cents": cumulative,
        "executed_file_count": executed_files,
        "compliance_posture": calc.posture_verdict(
            open_findings, escalated_findings, failed_30d, backlog, signage_violations
        ),
    }


def recompute_store(store):
    """Full recompute of every derived counter, persisted onto the store row."""
    apply_changes(store, derive_store_counters(store))
    return store


def store_projection(store):
    """A live projection of the store: derived counters recomputed, nothing written."""
    projected = dict(store)
    projected.update(derive_store_counters(store))
    return projected


def recompute_stores(store_ids):
    for store_id in store_ids:
        store = DB["stores"].get(store_id)
        if store is not None:
            recompute_store(store)


# ------------------------------------------------------------------ associate
def recompute_associate(associate, allow_suspend=True):
    actions = associate_actions(associate["id"])
    issued = [a for a in actions if a["status"] == "ISSUED"]
    verified = sum(
        1
        for task in DB["label_tasks"].values()
        if task["placed_by_associate_id"] == associate["id"]
        and task["placement_status"] == "VERIFIED"
    )
    variant = jurisdiction_of_associate(associate)["accountability_variant"]
    score = calc.accountability_score([a["score_weight"] for a in issued], verified, variant)
    apply_changes(
        associate,
        {
            "issued_action_count": len(issued),
            "verified_placement_count": verified,
            "accountability_score": score,
        },
    )
    if (
        allow_suspend
        and associate["training_status"] == "CERTIFIED"
        and Fraction(str(score)) < SUSPENSION_SCORE_FLOOR
    ):
        suspend_associate(associate)
    return associate


def suspend_associate(associate):
    """CERTIFIED -> SUSPENDED plus the label-task reset and posture chain."""
    apply_changes(associate, {"training_status": "SUSPENDED"})
    affected = []
    for task in rows("label_tasks"):
        if task["assigned_associate_id"] != associate["id"]:
            continue
        changes = {}
        if task["placement_status"] == "PLACED":
            changes["placement_status"] = "UNPLACED"
            changes["placed_by_associate_id"] = None
            changes["placed_at"] = None
        if task["print_status"] == "PRINTED" and task["placement_status"] != "VERIFIED":
            changes["print_status"] = "REPRINT_REQUIRED"
            changes["printed_label_serial"] = None
        if changes and apply_changes(task, changes):
            if task["store_id"] not in affected:
                affected.append(task["store_id"])
    recompute_stores(affected)


def issue_action(associate, trigger_code, action_type, issued_by_ref, source_ref=None):
    action = insert(
        "accountability_actions",
        {
            "associate_id": associate["id"],
            "trigger_code": trigger_code,
            "action_type": action_type,
            "status": "ISSUED",
            "score_weight": calc.action_weight(action_type),
            "source_ref": source_ref,
            "issued_by_ref": issued_by_ref,
            "void_reason": None,
        },
    )
    recompute_associate(associate)
    return action


def stamp_certification(associate):
    return now() + timedelta(days=CERTIFICATION_VALID_DAYS)


# ------------------------------------------------------------------ file / line
def line_counts(file_id):
    """(line_count, verified_line_count) — non-WITHDRAWN lines, and VERIFIED ones."""
    total = 0
    verified = 0
    for line in DB["price_change_lines"].values():
        if line["price_change_file_id"] != file_id:
            continue
        if line["line_status"] == "WITHDRAWN":
            continue
        total += 1
        if line["line_status"] == "VERIFIED":
            verified += 1
    return total, verified


def line_tasks(line_id):
    return [r for r in rows("label_tasks") if r["price_change_line_id"] == line_id]


def on_task_created(line):
    """PriceChangeLine PENDING -> TASKED, possibly DISTRIBUTED -> PARTIALLY_EXECUTED."""
    if line["line_status"] == "PENDING":
        apply_changes(line, {"line_status": "TASKED"})
    price_file = file_of_line(line)
    if price_file["status"] == "DISTRIBUTED":
        apply_changes(price_file, {"status": "PARTIALLY_EXECUTED"})


def on_task_printed(line):
    """PriceChangeLine TASKED -> LABELED."""
    if line["line_status"] == "TASKED":
        apply_changes(line, {"line_status": "LABELED"})


def on_task_placed(line):
    """PriceChangeLine FAILED -> LABELED."""
    if line["line_status"] == "FAILED":
        apply_changes(line, {"line_status": "LABELED"})


def on_task_rejected(line):
    """PriceChangeLine LABELED -> FAILED."""
    if line["line_status"] == "LABELED":
        apply_changes(line, {"line_status": "FAILED"})


def on_task_verified(line):
    """Cascade hop 2: line LABELED -> VERIFIED, hop 3 completion, hop 4 stores."""
    if line["line_status"] == "LABELED":
        apply_changes(line, {"line_status": "VERIFIED"})
    maybe_complete_file(file_of_line(line))


def maybe_complete_file(price_file):
    if price_file["status"] != "PARTIALLY_EXECUTED":
        return
    total, verified = line_counts(price_file["id"])
    if total >= 1 and verified == total:
        apply_changes(price_file, {"status": "EXECUTED"})
        recompute_stores(list(price_file["scope_store_ids"] or []))


def supersede_file(price_file, replacement):
    """The widest cascade of the price-file half of the domain."""
    apply_changes(
        price_file,
        {"superseded_by_file_id": replacement["id"], "status": "SUPERSEDED"},
    )
    affected = []
    for line in file_lines(price_file["id"]):
        if line["line_status"] in ("VERIFIED", "WITHDRAWN"):
            continue
        apply_changes(line, {"line_status": "WITHDRAWN"})
        for task in line_tasks(line["id"]):
            if task["placement_status"] == "VERIFIED":
                continue
            apply_changes(
                task,
                {"print_status": "REPRINT_REQUIRED", "printed_label_serial": None},
            )
            if task["store_id"] not in affected:
                affected.append(task["store_id"])
    recompute_stores(affected)


# ------------------------------------------------------------------ signage
def refresh_signage(sign):
    store = DB["stores"][sign["store_id"]]
    juris = jurisdiction_of_store(store)
    apply_changes(
        sign,
        {
            "missing_disclosure_codes": calc.missing_disclosures(sign, juris),
            "compliance_state": calc.signage_compliance_state(sign["status"]),
        },
    )
    return sign


def missing_for(sign):
    store = DB["stores"][sign["store_id"]]
    return calc.missing_disclosures(sign, jurisdiction_of_store(store))


def amend_jurisdiction_cascade(juris):
    """Re-derive every non-REMOVED sign of the jurisdiction, then each store."""
    store_ids = [s["id"] for s in rows("stores") if s["jurisdiction_id"] == juris["id"]]
    affected = []
    for sign in rows("promo_signage"):
        if sign["store_id"] not in store_ids or sign["status"] == "REMOVED":
            continue
        changed = apply_changes(
            sign,
            {
                "missing_disclosure_codes": calc.missing_disclosures(sign, juris),
                "compliance_state": calc.signage_compliance_state(sign["status"]),
            },
        )
        if changed and sign["store_id"] not in affected:
            affected.append(sign["store_id"])
    recompute_stores(store_ids)


# ------------------------------------------------------------------ audits
def audit_counts(audit_id):
    sample = 0
    over = 0
    under = 0
    for line in DB["scan_lines"].values():
        if line["scanner_audit_id"] != audit_id:
            continue
        sample += 1
        if line["classification"] == "OVERCHARGE":
            over += 1
        elif line["classification"] == "UNDERCHARGE":
            under += 1
    return sample, over, under


def audit_failure_cascade(audit, juris):
    """Hop 1 through 4 of the deepest chain in the service."""
    aisle = DB["aisles"][audit["aisle_id"]]
    candidate_id = aisle["assigned_associate_id"]
    if candidate_id is None:
        return
    candidate = DB["associates"].get(candidate_id)
    if candidate is None:
        return
    if candidate["training_status"] not in ("UNTRAINED", "IN_TRAINING", "CERTIFIED"):
        return
    has_warning = any(
        a["status"] == "ISSUED" and a["action_type"] == "WRITTEN_WARNING"
        for a in associate_actions(candidate_id)
    )
    action_type = calc.audit_failure_action_type(
        has_warning, audit["error_rate_pct"], juris["scanner_error_rate_threshold_pct"]
    )
    issue_action(candidate, "AUDIT_FAIL", action_type, "system", audit["id"])


def inspections_for_audit(audit_id):
    return [
        r for r in rows("regulatory_inspections") if r["scanner_audit_id"] == audit_id
    ]


# ------------------------------------------------------------------ inspections
def considered_findings(inspection_id):
    return [
        f for f in inspection_findings(inspection_id) if f["status"] != "WAIVED"
    ]


def recompute_penalty(inspection, juris):
    """Pinned order: count considered, tier, components, sum, scale once, cap."""
    considered = considered_findings(inspection["id"])
    audit = DB["scanner_audits"].get(inspection["scanner_audit_id"])
    audit_failed = audit is not None and audit["outcome"] == "FAIL"
    exposure, parts = calc.penalty_exposure(
        considered,
        juris["penalty_per_violation_cents"],
        audit_failed,
        juris["penalty_max_cents"],
    )
    for finding in considered:
        apply_changes(finding, {"penalty_component_cents": parts[finding["id"]]})
    apply_changes(
        inspection,
        {"finding_count": len(considered), "penalty_exposure_cents": exposure},
    )
    return exposure


def escalate_findings(inspection):
    for finding in inspection_findings(inspection["id"]):
        if finding["status"] in ("OPEN", "REMEDIATION_PLANNED"):
            apply_changes(finding, {"status": "ESCALATED"})


def audit_claims(audit_id):
    """Refund claims whose scan line belongs to this audit."""
    scan_ids = {r["id"] for r in DB["scan_lines"].values() if r["scanner_audit_id"] == audit_id}
    return [r for r in rows("refund_claims") if r["scan_line_id"] in scan_ids]


# ------------------------------------------------------------------ label serial
def mint_label_serial(store_id):
    from core import STATE

    seq = STATE["print_seq"].get(store_id, 0) + 1
    STATE["print_seq"][store_id] = seq
    return "LBL-%06d" % seq
