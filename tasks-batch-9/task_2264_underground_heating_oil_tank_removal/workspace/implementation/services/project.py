"""TankProject derived state, cascades and the recomputation order of §2.7."""

from decimal import Decimal

import calculations as calc
from db import assign, db, mark, sort_rows

OPEN_PROJECT_EXCLUDED = ("CLOSED_SETTLED", "VOID")
PENDING_SAMPLE_STATUSES = ("COLLECTED", "IN_TRANSIT", "AT_LAB")
LIVE_FIELD_STATUSES = ("SCHEDULED", "MOBILIZED", "IN_PROGRESS")
LIVE_NOTIFICATION_STATUSES = ("OPEN", "RESERVED", "THIRD_PARTY_REVIEW")


# ---------------------------------------------------------------------------
# child collections
# ---------------------------------------------------------------------------

def children(table, project_id):
    rows = [row for row in getattr(db, table).values()
            if row.get("tank_project_id") == project_id]
    return sort_rows(rows)


def crew_bookings(crew_id):
    """Live bookings of one crew, in creation order (calendar candidates)."""
    rows = [row for row in db.work_orders.values()
            if row.get("crew_id") == crew_id
            and row["field_status"] in LIVE_FIELD_STATUSES]
    return sort_rows(rows)


def property_of(project):
    return db.properties.get(project["property_id"])


def current_round_samples(project, statuses=None):
    rows = [s for s in children("soil_samples", project["id"])
            if s["sampling_round"] == project["sampling_round"]]
    if statuses is not None:
        rows = [s for s in rows if s["status"] in statuses]
    return rows


# ---------------------------------------------------------------------------
# nfa_blocker_set
# ---------------------------------------------------------------------------

def compute_blockers(project):
    project_id = project["id"]
    blockers = []

    if project["contamination_class"] != "CLEAN":
        blockers.append("CONTAMINATION_NOT_CLEARED")

    if current_round_samples(project, PENDING_SAMPLE_STATUSES):
        blockers.append("SAMPLES_PENDING")

    samples = children("soil_samples", project_id)
    invalidated = [s for s in samples
                   if s["sampling_round"] == project["sampling_round"]
                   and s["status"] == "INVALIDATED"]
    for sample in invalidated:
        retests = [r for r in samples
                   if r.get("retest_of_sample_id") == sample["id"] and r["status"] == "RESULTED"]
        if not retests:
            blockers.append("INVALIDATED_SAMPLE_WITHOUT_RETEST")
            break

    if [co for co in children("change_orders", project_id)
            if co["status"] in ("DRAFT", "SUBMITTED")]:
        blockers.append("OPEN_CHANGE_ORDER")

    if project["contamination_disclosure_required"]:
        acknowledged = [d for d in children("disclosures", project_id)
                        if d["disclosure_kind"] == "CONTAMINATION_FINDINGS"
                        and d["status"] == "ACKNOWLEDGED"]
        if not acknowledged:
            blockers.append("CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED")

    if [p for p in children("permits", project_id)
            if p["permit_type"] == "MUNICIPAL_DECOMMISSION"
            and p["status"] in ("REVOKED", "EXPIRED")]:
        blockers.append("PERMIT_REVOKED")

    if not [w for w in children("work_orders", project_id)
            if w["field_status"] == "FIELD_COMPLETE"]:
        blockers.append("FIELD_WORK_INCOMPLETE")

    return sorted(set(blockers))


def recompute_blockers(project):
    assign(project, "nfa_blockers", compute_blockers(project))


# ---------------------------------------------------------------------------
# approved scope + remediation cost + insurance waterfall
# ---------------------------------------------------------------------------

def approved_change_orders(project):
    return [co for co in children("change_orders", project["id"])
            if co["status"] == "APPROVED"]


def recompute_approved_scope(project):
    total = calc.dec(project["baseline_scope_cubic_yards"])
    for co in approved_change_orders(project):
        total += calc.dec(co["additional_cubic_yards"])
    assign(project, "approved_scope_cubic_yards", total)


def recompute_cost(project):
    """Step 1 per-line rounding, step 2 exact integer sum, step 3 mobilization."""
    lines_total_cents = 0
    for co in approved_change_orders(project):  # created_at ASC
        amount = calc.line_amount_cents(
            co["additional_cubic_yards"], co["unit_rate_cents"], co["disposal_class"])
        assign(co, "line_amount_cents", amount)
        lines_total_cents += amount
    if not project["remediation_started"]:
        cost = 0
    else:
        cost = calc.BASE_MOBILIZATION_CENTS + lines_total_cents
    assign(project, "remediation_cost_cents", cost)
    run_waterfall(project)


def run_waterfall(project):
    """SCAFFOLD calculations.insurance_reserve_allocation — pure integer cents."""
    prop = property_of(project)
    target_cents = int(project["remediation_cost_cents"])
    notifications = children("insurance_notifications", project["id"])
    live = [n for n in notifications if n["status"] != "CLOSED"]

    cap1 = int(prop["first_party_coverage_limit_cents"]) if prop else 0
    first_party = min(target_cents, cap1)

    has_tender = any(n["notification_kind"] == "THIRD_PARTY_LIABILITY"
                     and n["status"] in LIVE_NOTIFICATION_STATUSES
                     for n in notifications)
    cap2 = int(prop["third_party_sublimit_cents"]) if (prop and has_tender) else 0
    third_party = min(target_cents - first_party, cap2)

    homeowner = target_cents - first_party - third_party
    reserve = first_party + third_party

    for notification in live:
        assign(notification, "first_party_allocated_cents", first_party)
        assign(notification, "third_party_allocated_cents", third_party)
        assign(notification, "homeowner_out_of_pocket_cents", homeowner)
        assign(notification, "reserve_amount_cents", reserve)
        if third_party > 0:
            assign(notification, "status", "THIRD_PARTY_REVIEW")
        elif reserve > 0:
            assign(notification, "status", "RESERVED")
        else:
            assign(notification, "status", "OPEN")


# ---------------------------------------------------------------------------
# contamination classification + volumes
# ---------------------------------------------------------------------------

def recompute_contamination(project):
    resulted = current_round_samples(project, ("RESULTED",))
    max_tph, max_benzene, klass = calc.classify(resulted)
    assign(project, "max_tph_mg_kg", max_tph)
    assign(project, "max_benzene_mg_kg", max_benzene)
    assign(project, "contamination_class", klass)
    if klass in ("ELEVATED", "GROSS"):
        assign(project, "contamination_disclosure_required", True)
    return klass


def clear_classification(project):
    assign(project, "contamination_class", "UNCLASSIFIED")
    assign(project, "max_tph_mg_kg", None)
    assign(project, "max_benzene_mg_kg", None)


def set_provisional_grid_volume(project):
    impacted = [s for s in current_round_samples(project, ("RESULTED",))
                if calc.dec(s["tph_mg_kg"]) > calc.TPH_ACTION_MG_KG]
    volume = calc.provisional_grid_volume(impacted)
    assign(project, "remediation_volume_cubic_yards", volume)
    assign(project, "remediation_volume_basis", "PROVISIONAL_GRID")


def set_final_surveyed_volume(project):
    volume = calc.final_surveyed_volume(project["hauled_tons"])
    assign(project, "remediation_volume_cubic_yards", volume)
    assign(project, "remediation_volume_basis", "FINAL_SURVEYED")


# ---------------------------------------------------------------------------
# state transitions
# ---------------------------------------------------------------------------

def enter_remediation_active(project, recompute_volume=True):
    if project["contamination_class"] in ("ELEVATED", "GROSS"):
        assign(project, "contamination_disclosure_required", True)
    assign(project, "remediation_started", True)
    if recompute_volume:
        set_provisional_grid_volume(project)
    assign(project, "status", "REMEDIATION_ACTIVE")
    recompute_cost(project)


def evaluate_round_completion(project):
    """SAMPLING -> ASSESSED -> {CLEARED | REMEDIATION_ACTIVE} (§3.6)."""
    if project["status"] != "SAMPLING":
        return
    pending = current_round_samples(project, PENDING_SAMPLE_STATUSES)
    resulted = current_round_samples(project, ("RESULTED",))
    if pending or not resulted:
        return
    assign(project, "status", "ASSESSED")
    klass = recompute_contamination(project)
    if klass == "CLEAN":
        assign(project, "status", "CLEARED")
    elif klass in ("ELEVATED", "GROSS"):
        enter_remediation_active(project)


def abort_work_order(work_order, reason):
    assign(work_order, "field_status", "ABORTED")
    assign(work_order, "abort_reason", reason)
    if work_order["billing_status"] in ("UNBILLED", "BILLABLE", "INVOICED"):
        assign(work_order, "billing_status", "WRITTEN_OFF")


def void_project(project):
    """SURVEYED -> VOID plus its three-part cascade (§3.2)."""
    assign(project, "status", "VOID")
    for permit in children("permits", project["id"]):
        if permit["status"] in ("SUBMITTED", "ISSUED"):
            assign(permit, "status", "REVOKED")
            assign(permit, "revocation_reason", "HOMEOWNER_DECLINED")
    for work_order in children("work_orders", project["id"]):
        if work_order["field_status"] in LIVE_FIELD_STATUSES:
            abort_work_order(work_order, "PROJECT_VOIDED")
    decrement_open_projects(project)
    recompute_blockers(project)


def settle_project(project):
    """CLOSED_NFA -> CLOSED_SETTLED plus its cascade (§3.9)."""
    assign(project, "status", "CLOSED_SETTLED")
    for notification in children("insurance_notifications", project["id"]):
        if notification["status"] in LIVE_NOTIFICATION_STATUSES:
            assign(notification, "status", "CLOSED")
    decrement_open_projects(project)
    recompute_blockers(project)


def decrement_open_projects(project):
    prop = property_of(project)
    if prop is not None:
        assign(prop, "open_project_count", max(0, int(prop["open_project_count"]) - 1))


def increment_open_projects(prop):
    assign(prop, "open_project_count", int(prop["open_project_count"]) + 1)


def bump_project_version(project):
    """Explicitly documented +1 (§2.4): sweep survey, change-order create,
    trust-fund-claim create."""
    mark(project)


def open_change_order_count(project):
    return len([co for co in children("change_orders", project["id"])
                if co["status"] in ("DRAFT", "SUBMITTED")])


def summary(project):
    return {
        "status": project["status"],
        "contamination_class": project["contamination_class"],
        "approved_scope_cubic_yards": _num(project["approved_scope_cubic_yards"]),
        "remediation_volume_cubic_yards": _num(project["remediation_volume_cubic_yards"]),
        "remediation_volume_basis": project["remediation_volume_basis"],
        "remediation_cost_cents": project["remediation_cost_cents"],
        "nfa_blockers": list(project["nfa_blockers"]),
        "open_change_order_count": open_change_order_count(project),
        "current_round_sample_count": len(current_round_samples(project)),
        "version": project["version"],
    }


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value
