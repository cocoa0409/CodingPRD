"""All derived quantities, roll-ups and cascades."""
import math
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from core import (
    add_business_days,
    count_business_days_after_through,
    dec,
    fmt_instant,
    money,
    parse_instant,
    rhu,
    roll_forward,
    store,
    whole,
    whole_days_truncated,
)

# ------------------------------------------------------------------ constants

FILING_DEADLINE_DAYS = {
    "FORM_10Q": {"LARGE_ACCELERATED": 40, "ACCELERATED": 40, "NON_ACCELERATED": 45},
    "FORM_10K": {"LARGE_ACCELERATED": 60, "ACCELERATED": 75, "NON_ACCELERATED": 90},
}
DEADLINE_CUTOFF_TIME_UTC = time(17, 30, 0)

MILESTONE_ORDER = ["CLOSE", "REVIEW", "CERTIFICATION", "FILING"]
MILESTONE_BUFFER_HOURS = {
    "CLOSE_TO_REVIEW": 48,
    "REVIEW_TO_CERTIFICATION": 48,
    "CERTIFICATION_TO_FILING": 12,
}
REQUIRED_FILING_SLACK_BUSINESS_DAYS = 1
NO_SLACK_SENTINEL = 9999

SCOPE_BASE_WEIGHT = {
    "REVENUE": 30,
    "LEGAL_CONTINGENCY": 25,
    "OPERATIONS": 20,
    "IR_COMMUNICATIONS": 15,
    "IT_CONTROLS": 10,
}
OFFICER_SUPPORT_MULTIPLIER = Decimal("1.5")
EXCEPTION_ESCALATION = {
    "NONE": Decimal("1.0"),
    "LOW": Decimal("1.1"),
    "MEDIUM": Decimal("1.4"),
    "HIGH": Decimal("2.0"),
}
SCOPE_WEIGHT_CAP = Decimal("45")
COVERAGE_REQUIRED_PCT = Decimal("100.00")
SUBCERT_PREP_WINDOW_HOURS = 72
MEMBER_CONCURRENT_SUBCERT_CAP = 2

TIE_OUT_MAX_BP = 10000
TIER_TIGHT_MAX_BP = 50
TIER_MEDIUM_MAX_BP = 200
TIER_MULTIPLIERS = {"TIGHT": Decimal("1.00"), "MEDIUM": Decimal("0.75"), "WIDE": Decimal("0.50")}

RECONCILIATION_TOLERANCE = Decimal("0.01")

MATERIALITY_REPORTABLE_PCT = Decimal("5.00")
CURRENT_REPORT_BUSINESS_DAYS = 4

CORRECTION_RESTATEMENT_PCT = Decimal("5.00")
CORRECTION_REVISION_PCT = Decimal("1.00")

DEFICIENCY_MATERIAL_WEAKNESS_PCT = Decimal("5.00")
DEFICIENCY_SIGNIFICANT_PCT = Decimal("1.50")
DEFICIENCY_TIER_FACTOR = {
    "DEFICIENCY": Decimal("1.0"),
    "SIGNIFICANT_DEFICIENCY": Decimal("2.0"),
    "MATERIAL_WEAKNESS": Decimal("4.0"),
}
COMPENSATING_CONTROL_CREDIT = Decimal("0.60")
NO_CREDIT = Decimal("1.00")

CERT_TYPES_ORDER = ["CEO_302", "CFO_302", "CEO_906", "CFO_906"]
REQUIRED_CERT_TYPES = {
    "FORM_10Q": ["CEO_302", "CFO_302"],
    "FORM_10K": ["CEO_302", "CFO_302", "CEO_906", "CFO_906"],
}

SUBCERT_LIVE_STATUSES = ("PENDING", "SUBMITTED", "EXCEPTION_NOTED")
SUBCERT_NUMERATOR_STATUSES = ("SUBMITTED", "EXCEPTION_NOTED")
OPEN_EVENT_STATUSES = ("UNASSESSED", "REPORTABLE")
OPEN_MILESTONE_STATUSES = ("PLANNED", "IN_PROGRESS")


# ------------------------------------------------------------------ charter

def refresh_charter_derived(charter):
    members = store.where("member", charter_id=charter["id"])
    active = [m for m in members if m["status"] == "ACTIVE"]
    charter["active_voting_member_count"] = len([m for m in active if m["voting"] is True])
    charter["covered_functions"] = sorted({m["function"] for m in active})


def charter_quorum_ok(charter):
    return charter["active_voting_member_count"] >= charter["min_quorum_count"]


def charter_coverage_ok(charter):
    covered = set(charter["covered_functions"])
    return all(fn in covered for fn in charter["required_functions"])


# ------------------------------------------------------------------ cycle deadlines

def cycle_deadlines(form_type, filer_status, period_end_day, internal_buffer_days):
    days = FILING_DEADLINE_DAYS[form_type][filer_status]
    raw_day = period_end_day + timedelta(days=days)
    rolled = roll_forward(raw_day)
    statutory = datetime.combine(rolled, DEADLINE_CUTOFF_TIME_UTC, tzinfo=timezone.utc)
    internal = statutory - timedelta(days=internal_buffer_days)
    return statutory, internal


# ------------------------------------------------------------------ milestones / slack

def milestone_slack(cycle, planned_end):
    deadline = parse_instant(cycle["statutory_deadline_utc"])
    calendar_days = whole_days_truncated(deadline, planned_end)
    business_days = count_business_days_after_through(planned_end.date(), deadline.date())
    return calendar_days, business_days


def recompute_cycle_slack(cycle):
    rows = [
        m
        for m in store.where("milestone", cycle_id=cycle["id"])
        if m["status"] in OPEN_MILESTONE_STATUSES
    ]
    if not rows:
        cycle["min_slack_days_calendar"] = NO_SLACK_SENTINEL
        cycle["min_slack_days_business"] = NO_SLACK_SENTINEL
        return
    cycle["min_slack_days_calendar"] = min(m["slack_calendar_days"] for m in rows)
    cycle["min_slack_days_business"] = min(m["slack_business_days"] for m in rows)


def breach_sweep(cycle, log):
    """Move open milestones whose planned end lies strictly before now to BREACHED."""
    now = store.clock.now()
    for milestone in store.where("milestone", cycle_id=cycle["id"]):
        if milestone["status"] in OPEN_MILESTONE_STATUSES:
            if parse_instant(milestone["planned_end_utc"]) < now:
                milestone["status"] = "BREACHED"
                log.touch(milestone)
    recompute_cycle_slack(cycle)


def predecessor_kind(kind):
    index = MILESTONE_ORDER.index(kind)
    if index == 0:
        return None
    return MILESTONE_ORDER[index - 1]


def buffer_hours_for(pred, kind):
    return MILESTONE_BUFFER_HOURS["%s_TO_%s" % (pred, kind)]


# ------------------------------------------------------------------ sub-certifications

def subcert_scope_weight(scope_area, is_officer, exception_severity):
    base = dec(SCOPE_BASE_WEIGHT[scope_area])
    officer_factor = OFFICER_SUPPORT_MULTIPLIER if is_officer else Decimal("1.0")
    escalation = EXCEPTION_ESCALATION[exception_severity]
    product = base * officer_factor * escalation
    picked = product if product > base else base
    rounded = rhu(picked, 2)
    if rounded > SCOPE_WEIGHT_CAP:
        rounded = SCOPE_WEIGHT_CAP
    return float(rhu(rounded, 2))


def prep_window(due_instant):
    return due_instant - timedelta(hours=SUBCERT_PREP_WINDOW_HOURS), due_instant


def recompute_total_assigned_scope_weight(cycle):
    rows = [
        r
        for r in store.where("subcert", cycle_id=cycle["id"])
        if r["status"] in SUBCERT_LIVE_STATUSES
    ]
    total = sum((dec(r["scope_weight"]) for r in rows), Decimal("0"))
    cycle["total_assigned_scope_weight"] = float(rhu(total, 2))


def recompute_certification_coverage_pct(cycle):
    rows = [
        r
        for r in store.where("subcert", cycle_id=cycle["id"])
        if r["status"] in SUBCERT_LIVE_STATUSES
    ]
    if not rows:
        cycle["certification_coverage_pct"] = 0.00
        return
    denominator = sum((dec(r["scope_weight"]) for r in rows), Decimal("0"))
    numerator = sum(
        (dec(r["scope_weight"]) for r in rows if r["status"] in SUBCERT_NUMERATOR_STATUSES),
        Decimal("0"),
    )
    if denominator == 0:
        cycle["certification_coverage_pct"] = 0.00
        return
    cycle["certification_coverage_pct"] = float(rhu(numerator / denominator * Decimal("100"), 2))


def recompute_open_material_event_count(cycle):
    rows = [
        e
        for e in store.where("event", cycle_id=cycle["id"])
        if e["assessment_status"] in OPEN_EVENT_STATUSES
    ]
    cycle["open_material_event_count"] = len(rows)


def recompute_unresolved_deficiency_weight(cycle):
    total = Decimal("0")
    filings = [
        f
        for f in store.where("filing", cycle_id=cycle["id"])
        if f["status"] in ("SUBMITTED", "AMENDED_SUPERSEDED")
    ]
    for filing in filings:
        corrections = [
            c
            for c in store.where("correction", filing_id=filing["id"])
            if c["status"] in ("DRAFT", "ASSESSED", "CLOSED")
        ]
        for correction in corrections:
            for deficiency in store.where("deficiency", correction_id=correction["id"]):
                if deficiency["status"] == "OPEN":
                    total += dec(deficiency["deficiency_weight"])
    cycle["unresolved_deficiency_weight"] = float(rhu(total, 2))


# ------------------------------------------------------------------ tie-out

def _raw_variance_bp(item):
    source = dec(item["source_record_value"])
    if source == 0:
        return TIE_OUT_MAX_BP
    reported = dec(item["reported_value"])
    ratio = abs(reported - source) / abs(source) * Decimal(TIE_OUT_MAX_BP)
    return whole(ratio)


def recompute_tie_out(document, log, new_item_ids=()):
    """Normative five-step derivation over the document's non-waived item set."""
    items = sorted(
        store.where("tie_out_item", document_id=document["id"]), key=lambda r: r["_seq"]
    )
    live = [i for i in items if i["status"] != "WAIVED"]

    # STEP 1
    snapshot = {}
    for item in live:
        snapshot[item["id"]] = _raw_variance_bp(item)

    # STEP 2
    total = sum(snapshot.values())
    document["tie_out_total_variance_bp"] = total

    # STEP 3
    if total <= TIER_TIGHT_MAX_BP:
        multiplier = TIER_MULTIPLIERS["TIGHT"]
    elif total <= TIER_MEDIUM_MAX_BP:
        multiplier = TIER_MULTIPLIERS["MEDIUM"]
    else:
        multiplier = TIER_MULTIPLIERS["WIDE"]
    document["tie_out_tier_multiplier"] = float(multiplier)

    # STEP 4
    for item in live:
        raw = snapshot[item["id"]]
        effective = int(math.floor(dec(item["tolerance_bp"]) * multiplier))
        previous_status = item["status"]
        item["raw_variance_bp"] = raw
        item["effective_tolerance_bp"] = effective
        item["status"] = "MATCHED" if raw <= effective else "VARIANCE"
        if item["status"] != previous_status and item["id"] not in new_item_ids:
            log.touch(item)

    # STEP 5
    if not live:
        document["tie_out_status"] = "NOT_STARTED"
    elif all(i["status"] == "MATCHED" for i in live):
        document["tie_out_status"] = "PASSED"
    else:
        document["tie_out_status"] = "FAILED"


def tie_out_failure_cascade(document, log):
    """Hops three through five of the tie-out cascade of PRD 3.6."""
    if document["tie_out_status"] != "FAILED":
        return
    if document["status"] != "APPROVED":
        return
    document["status"] = "CHANGES_REQUESTED"
    document["revision_round"] = document["revision_round"] + 1
    document["change_note"] = "auto: tie-out variance detected"
    log.touch(document)
    cycle = store.get("cycle", document["cycle_id"])
    if cycle is None:
        return
    if document["doc_type"] == "PERIODIC_FILING" and cycle["status"] == "FILING_READY":
        cycle["status"] = "REVIEW_OPEN"
        for cert in store.where("officer_cert", cycle_id=cycle["id"]):
            if cert["status"] in ("ELIGIBLE", "SIGNED"):
                cert["status"] = "REVOKED"
                cert["signed_utc"] = None
                cert["attestation_text"] = None
                log.touch(cert)
        recompute_certification_coverage_pct(cycle)
        log.touch(cycle)


# ------------------------------------------------------------------ adjusted measures

def reconcile_measure(measure):
    items = measure["reconciliation_items"] or []
    total = sum((dec(entry.get("amount", 0)) for entry in items), Decimal("0"))
    reconciliation_sum = rhu(total, 2)
    gap = rhu(dec(measure["adjusted_value"]) - (dec(measure["comparable_gaap_value"]) + reconciliation_sum), 2)
    prominence_ok = measure["gaap_prominence_index"] <= measure["adjusted_prominence_index"]
    measure["reconciliation_sum"] = float(reconciliation_sum)
    measure["reconciliation_gap"] = float(gap)
    measure["prominence_ok"] = prominence_ok
    reconciled_ok = abs(gap) <= RECONCILIATION_TOLERANCE
    if not reconciled_ok:
        measure["status"] = "REJECTED"
    elif not prominence_ok:
        measure["status"] = "PROMINENCE_FAILED"
    else:
        measure["status"] = "RECONCILED"


def recompute_measure_gate(document):
    measures = store.where("measure", document_id=document["id"])
    if not measures:
        document["measure_gate_status"] = "NO_MEASURES"
        return
    if any(m["status"] in ("DRAFT", "REJECTED") for m in measures):
        document["measure_gate_status"] = "BLOCKED_RECONCILIATION"
        return
    if any(m["status"] == "PROMINENCE_FAILED" for m in measures):
        document["measure_gate_status"] = "BLOCKED_PROMINENCE"
        return
    document["measure_gate_status"] = "CLEARED"


# ------------------------------------------------------------------ question bank

def recompute_qa_gate(document):
    items = store.where("qa_item", script_document_id=document["id"])
    blocked = any(i["risk_tier"] == "HIGH" and i["status"] != "CLEARED" for i in items)
    document["qa_gate_status"] = "BLOCKED" if blocked else "CLEARED"


# ------------------------------------------------------------------ material events

def event_severity_score(magnitude_amount, materiality_base_amount):
    ratio = abs(dec(magnitude_amount)) / abs(dec(materiality_base_amount)) * Decimal("100")
    if ratio > Decimal("100.00"):
        ratio = Decimal("100.00")
    return float(rhu(ratio, 2))


def current_report_deadline(discovered_instant):
    target = add_business_days(discovered_instant.date(), CURRENT_REPORT_BUSINESS_DAYS)
    return fmt_instant(datetime.combine(target, DEADLINE_CUTOFF_TIME_UTC, tzinfo=timezone.utc))


def block_eligible_certifications(cycle, log):
    for cert in store.where("officer_cert", cycle_id=cycle["id"]):
        if cert["status"] == "ELIGIBLE":
            cert["status"] = "BLOCKED"
            log.touch(cert)


def release_blocked_certifications(cycle, log):
    if cycle["status"] != "CERTIFICATION_OPEN":
        return
    if cycle["open_material_event_count"] != 0:
        return
    for cert in store.where("officer_cert", cycle_id=cycle["id"]):
        if cert["status"] == "BLOCKED":
            cert["status"] = "ELIGIBLE"
            log.touch(cert)


# ------------------------------------------------------------------ corrections

def correction_materiality(correction, method):
    if method == "IRON_CURTAIN":
        numerator = abs(
            dec(correction["error_amount"]) + dec(correction["cumulative_prior_uncorrected_amount"])
        )
        denominator = abs(dec(correction["prior_period_pretax_income"]))
    else:
        numerator = abs(dec(correction["error_amount"]))
        denominator = abs(dec(correction["current_period_pretax_income"]))
    pct = rhu(numerator / denominator * Decimal("100"), 2)
    if pct >= CORRECTION_RESTATEMENT_PCT:
        classification = "RESTATEMENT"
    elif pct >= CORRECTION_REVISION_PCT:
        classification = "REVISION"
    else:
        classification = "IMMATERIAL"
    return float(pct), classification


def score_deficiency(deficiency, correction):
    magnitude_ratio = abs(dec(deficiency["magnitude_amount"])) / abs(
        dec(correction["current_period_pretax_income"])
    )
    exposure_pct = dec(deficiency["likelihood_pct"]) * magnitude_ratio
    credit = COMPENSATING_CONTROL_CREDIT if deficiency["compensating_control_present"] else NO_CREDIT
    materiality_pct = dec(correction["materiality_pct"])
    picked = exposure_pct if exposure_pct > materiality_pct else materiality_pct
    if picked > Decimal("100.00"):
        picked = Decimal("100.00")
    severity_score = rhu(picked * credit, 2)
    if severity_score >= DEFICIENCY_MATERIAL_WEAKNESS_PCT:
        severity = "MATERIAL_WEAKNESS"
    elif severity_score >= DEFICIENCY_SIGNIFICANT_PCT:
        severity = "SIGNIFICANT_DEFICIENCY"
    else:
        severity = "DEFICIENCY"
    weight = rhu(severity_score * DEFICIENCY_TIER_FACTOR[severity], 2)
    deficiency["severity_score"] = float(severity_score)
    deficiency["severity"] = severity
    deficiency["deficiency_weight"] = float(weight)


# ------------------------------------------------------------------ filings

def filing_accession(cycle):
    rows = sorted(store.where("filing", cycle_id=cycle["id"]), key=lambda r: (r["created_at"], r["_seq"]))
    sequence = len(rows) + 1
    return "%s-%s-%d" % (cycle["form_type"], cycle["fiscal_period_label"], sequence)


def certifications_complete(cycle):
    required = REQUIRED_CERT_TYPES[cycle["form_type"]]
    signed = {
        c["cert_type"]
        for c in store.where("officer_cert", cycle_id=cycle["id"])
        if c["status"] == "SIGNED"
    }
    return all(cert_type in signed for cert_type in required)


def unsigned_cert_types(cycle):
    required = REQUIRED_CERT_TYPES[cycle["form_type"]]
    signed = {
        c["cert_type"]
        for c in store.where("officer_cert", cycle_id=cycle["id"])
        if c["status"] == "SIGNED"
    }
    return [cert_type for cert_type in CERT_TYPES_ORDER if cert_type in required and cert_type not in signed]


def cycle_has_live_subcert_scope(cycle):
    return any(
        r["status"] in SUBCERT_LIVE_STATUSES for r in store.where("subcert", cycle_id=cycle["id"])
    )


# ------------------------------------------------------------------ readiness

REMAINING_REQUIRED_KINDS = {
    "PLANNING": ["CLOSE", "REVIEW", "FILING"],
    "CLOSE_OPEN": ["CLOSE", "REVIEW", "FILING"],
    "REVIEW_OPEN": ["REVIEW", "FILING"],
    "CERTIFICATION_OPEN": ["FILING"],
    "FILING_READY": [],
    "FILED": [],
    "AMENDED": [],
    "ABANDONED": [],
}


def missing_milestone_kinds(cycle):
    required = set(REMAINING_REQUIRED_KINDS.get(cycle["status"], []))
    present = {m["kind"] for m in store.where("milestone", cycle_id=cycle["id"])}
    return [kind for kind in MILESTONE_ORDER if kind in required and kind not in present]


def has_milestone_of_kind(cycle, kind):
    return any(m["kind"] == kind for m in store.where("milestone", cycle_id=cycle["id"]))


def all_milestones_of_kind_complete(cycle, kind):
    rows = [m for m in store.where("milestone", cycle_id=cycle["id"]) if m["kind"] == kind]
    return all(m["status"] == "COMPLETE" for m in rows)


def deficiency_gate_blocked(cycle):
    if dec(cycle["unresolved_deficiency_weight"]) > Decimal("0.00"):
        return True
    return cycle["restatement_stage"] in ("UNDER_EVALUATION", "RESTATEMENT_DECLARED")


def filing_ready_blockers(cycle):
    """The distinct error ids a DECLARE_FILING_READY would raise right now,
    ordered by ascending ladder priority (PRD 2.11)."""
    blockers = []
    if cycle["status"] == "ABANDONED":
        blockers.append("ERR_ENTITY_TERMINAL")
    elif cycle["status"] != "CERTIFICATION_OPEN":
        blockers.append("ERR_INVALID_STATE")
    charter = store.get("charter", cycle["charter_id"])
    if charter is None or charter["status"] != "ADOPTED":
        blockers.append("ERR_CHARTER_NOT_ADOPTED")
    if charter is not None:
        if not charter_quorum_ok(charter):
            blockers.append("ERR_QUORUM_NOT_MET")
        if not charter_coverage_ok(charter):
            blockers.append("ERR_FUNCTION_COVERAGE_GAP")
    if cycle["open_material_event_count"] != 0:
        blockers.append("ERR_OPEN_MATERIAL_EVENT")
    if deficiency_gate_blocked(cycle):
        blockers.append("ERR_DEFICIENCY_OPEN")
    if not has_milestone_of_kind(cycle, "FILING"):
        blockers.append("ERR_MILESTONE_MISSING")
    if not certifications_complete(cycle):
        blockers.append("ERR_CERTIFICATIONS_INCOMPLETE")
    if cycle["min_slack_days_business"] < REQUIRED_FILING_SLACK_BUSINESS_DAYS:
        blockers.append("ERR_MILESTONE_SLACK_EXHAUSTED")
    from core import LADDER_PRIORITY

    unique = []
    for error_id in blockers:
        if error_id not in unique:
            unique.append(error_id)
    unique.sort(key=lambda code: LADDER_PRIORITY[code])
    return unique
