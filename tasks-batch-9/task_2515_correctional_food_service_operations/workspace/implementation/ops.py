"""Shared cascade operations, lookup shorthands and small route helpers.

Every function here implements a hop named explicitly in PRD section 3, and
follows the cascade discipline of section 2.10: a row whose persisted fields
net-change has its own version incremented by 1 and updated_at refreshed.
"""
from core import (
    ApiError, DB, all_rows, base_row, insert, now_logical, page, public,
    require_row, respond_list, touch,
)
from calc import (
    MISSED_MEAL_ESCALATION_THRESHOLD, GRIEVANCE_BREACH_ESCALATION_THRESHOLD,
    CORRECTIVE_ACTION_SCORE_FLOOR, D, apply_ledger, contract_facilities,
    derive_posture, facility_batches, is_sharp, refresh_facility,
    refresh_inmate, rows_where,
)

# --------------------------------------------------------------------------
# Path / body reference lookups (ladder priorities 8 and 9)
# --------------------------------------------------------------------------
def need_contract(row_id):
    return require_row("service_contracts", row_id, "ERR_SERVICE_CONTRACT_NOT_FOUND")


def need_facility(row_id):
    return require_row("facilities", row_id, "ERR_FACILITY_NOT_FOUND")


def need_cycle(row_id):
    return require_row("menu_cycles", row_id, "ERR_MENU_CYCLE_NOT_FOUND")


def need_cycle_item(row_id):
    return require_row("menu_cycle_items", row_id, "ERR_MENU_CYCLE_ITEM_NOT_FOUND")


def need_inmate(row_id):
    return require_row("inmates", row_id, "ERR_INMATE_NOT_FOUND")


def need_diet_order(row_id):
    return require_row("diet_orders", row_id, "ERR_DIET_ORDER_NOT_FOUND")


def need_population_count(row_id):
    return require_row("population_counts", row_id, "ERR_POPULATION_COUNT_NOT_FOUND")


def need_forecast(row_id):
    return require_row("meal_forecasts", row_id, "ERR_MEAL_FORECAST_NOT_FOUND")


def need_batch(row_id):
    return require_row("production_batches", row_id, "ERR_PRODUCTION_BATCH_NOT_FOUND")


def need_worker(row_id):
    return require_row("inmate_workers", row_id, "ERR_INMATE_WORKER_NOT_FOUND")


def need_issuance(row_id):
    return require_row("tool_issuances", row_id, "ERR_TOOL_ISSUANCE_NOT_FOUND")


def need_incident(row_id):
    return require_row("contraband_incidents", row_id, "ERR_CONTRABAND_INCIDENT_NOT_FOUND")


def need_service_record(row_id):
    return require_row("meal_service_records", row_id, "ERR_MEAL_SERVICE_RECORD_NOT_FOUND")


def need_substitution(row_id):
    return require_row("menu_substitutions", row_id, "ERR_MENU_SUBSTITUTION_NOT_FOUND")


def need_grievance(row_id):
    return require_row("grievances", row_id, "ERR_GRIEVANCE_NOT_FOUND")


def contract_of(facility):
    return DB.col("service_contracts").get(facility["contract_id"])


def facility_of_id(facility_id):
    return DB.col("facilities").get(facility_id)


def paged(rows, limit, offset):
    """Listing response for endpoints that had to validate pagination early."""
    window, total = page(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Terminal-state guard (ladder priority 16)
# --------------------------------------------------------------------------
def not_terminal(row, field, terminals):
    if row.get(field) in terminals:
        raise ApiError("ERR_ALREADY_TERMINAL")


def require_state(row, field, allowed):
    if row.get(field) not in allowed:
        raise ApiError("ERR_INVALID_STATE")


# --------------------------------------------------------------------------
# Facility derived state
# --------------------------------------------------------------------------
def sync_facility(facility, force=False):
    """Reconcile every derived counter and the posture; bump when anything
    net-changed, or unconditionally when the PRD names an explicit bump."""
    changed = refresh_facility(facility)
    if force or changed:
        touch(facility)
    return changed


def sync_inmate(inmate, force=False):
    changed = refresh_inmate(inmate)
    if force or changed:
        touch(inmate)
    return changed


def census_after_diet_change(inmates, facilities, skip=()):
    """Reconcile the two census counters over their source rows. Rows already
    touched by the caller are passed in `skip` so they are not bumped twice."""
    seen = set()
    for inmate in inmates:
        if inmate is None or inmate["id"] in seen:
            continue
        seen.add(inmate["id"])
        changed = refresh_inmate(inmate)
        if changed and inmate["id"] not in skip:
            touch(inmate)
    for facility in facilities:
        if facility is None or facility["id"] in seen:
            continue
        seen.add(facility["id"])
        changed = refresh_facility(facility)
        if changed and facility["id"] not in skip:
            touch(facility)


# --------------------------------------------------------------------------
# Lockdown cascade hops 3 and 4 (PRD 3.6)
# --------------------------------------------------------------------------
LOCKDOWN_DISCARD_STAGES = ("PLANNED", "COOKED", "CHILLED")
LOCKDOWN_WORK_AREAS = ("COOK_CHILL", "SERVING_LINE")


def discard_batches_for_lockdown(facility):
    """Hop 3: a LOCKDOWN posture discards every in-flight batch."""
    discarded = []
    for batch in facility_batches(facility["id"]):
        if batch["production_stage"] in LOCKDOWN_DISCARD_STAGES:
            batch["production_stage"] = "DISCARDED"
            if batch["qa_status"] == "QA_PENDING":
                batch["qa_status"] = "QA_HELD"
            touch(batch)
            discarded.append(batch)
    return discarded


def unassign_line_workers(facility):
    """Hop 4: because batches were discarded, cook-chill and serving-line
    details are cleared. Bakery and sanitation details are kept."""
    cleared = []
    for worker in rows_where("inmate_workers", facility_id=facility["id"]):
        if worker["assignment_status"] != "ASSIGNED":
            continue
        if worker.get("work_area") not in LOCKDOWN_WORK_AREAS:
            continue
        worker["assignment_status"] = "UNASSIGNED"
        worker["work_area"] = None
        touch(worker)
        cleared.append(worker)
    return cleared


def raise_system_incident(facility, issuance, narrative=None):
    """The fan-out of a tool declared unaccounted: a system-reported incident."""
    sharp = is_sharp(issuance["tool_class"])
    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "inmate_worker_id": issuance["issued_to_worker_id"],
        "related_tool_issuance_id": issuance["id"],
        "item_class": "SHARP" if sharp else "FOOD_DIVERSION",
        "severity": "CRITICAL" if sharp else "MAJOR",
        "narrative": narrative or "Tool declared unaccounted at shift-end count.",
        "status": "OPEN",
        "sanction_type": None,
        "discovered_by_user_id": "system",
        "discovered_at": now_logical(),
        "disposition_by_user_id": None,
    })
    return insert("contraband_incidents", row)


# --------------------------------------------------------------------------
# Contract-level corrective-action cascade (PRD 3.7, 3.8, 3.9)
# --------------------------------------------------------------------------
def escalate_facilities(contract):
    """corrective_action_required := true across the contract's facilities,
    then the posture waterfall is re-evaluated (never relaxed)."""
    for facility in contract_facilities(contract["id"]):
        facility["corrective_action_required"] = True
        facility["kitchen_posture"] = derive_posture(facility)
        touch(facility)


def apply_escalation_thresholds(contract):
    if int(contract["missed_meal_total"]) >= MISSED_MEAL_ESCALATION_THRESHOLD:
        escalate_facilities(contract)
    elif int(contract["grievance_sla_breach_count"]) >= GRIEVANCE_BREACH_ESCALATION_THRESHOLD:
        escalate_facilities(contract)


def apply_missed_meal_escalation(contract):
    if int(contract["missed_meal_total"]) >= MISSED_MEAL_ESCALATION_THRESHOLD:
        escalate_facilities(contract)


def apply_breach_escalation(contract):
    if int(contract["grievance_sla_breach_count"]) >= GRIEVANCE_BREACH_ESCALATION_THRESHOLD:
        escalate_facilities(contract)


def apply_close_out_verdict(contract):
    """Contract close hop 1 and 2: the flag is assigned, not one-way raised."""
    below = D(contract["performance_score"]) < CORRECTIVE_ACTION_SCORE_FLOOR
    for facility in contract_facilities(contract["id"]):
        facility["corrective_action_required"] = bool(below)
        facility["kitchen_posture"] = derive_posture(facility)
        touch(facility)


def recompute_contract_ledger(contract):
    apply_ledger(contract)
    touch(contract)


# --------------------------------------------------------------------------
# Reconciliation snapshot invalidation (PRD 3.9)
# --------------------------------------------------------------------------
def invalidate_reconciliation(contract):
    """RECONCILING -> ACTIVE. The incrementally maintained ledgers survive;
    every reconciliation output is reset."""
    contract["status"] = "ACTIVE"
    contract["ld_variant"] = None
    contract["reconciled_at"] = None
    for field in ("raw_liquidated_damages_cents", "substitution_surcharge_cents",
                  "liquidated_damages_cents", "cost_recovery_credit_cents",
                  "net_liquidated_damages_cents", "gross_food_cost_cents"):
        contract[field] = 0
    for field in ("cost_cents_per_meal_day_actual", "substitution_rate_pct",
                  "performance_score"):
        contract[field] = D("0.00")


LEDGER_VIEW_FIELDS = (
    "total_trays_served",
    "meal_days_served",
    "missed_meal_total",
    "substitution_rate_pct",
    "grievance_sla_breach_count",
    "raw_liquidated_damages_cents",
    "substitution_surcharge_cents",
    "liquidated_damages_cents",
    "cost_recovery_credit_cents",
    "net_liquidated_damages_cents",
    "performance_score",
    "ld_variant",
)

SHARPS_VIEW_FIELDS = (
    "sharps_authorized_count",
    "sharps_on_board_count",
    "sharps_issued_count",
    "sharps_unaccounted_count",
    "sharps_audit_shortfall",
    "open_sharps_discrepancy_count",
    "kitchen_posture",
)


def view(row, fields):
    return dict((f, row.get(f)) for f in fields)
