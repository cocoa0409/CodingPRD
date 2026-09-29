"""Shared domain services: lookups, derived counters, cascades, calendars."""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

import db
from errors import ApiError
from services import calc


# ---------------------------------------------------------------------------
# Existence (ladder rungs 6-17 for path params, rung 19 for body references)
# ---------------------------------------------------------------------------
def _need(collection, entity_id, error_id):
    row = collection.get(entity_id) if isinstance(entity_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def need_club(club_id):
    return _need(db.clubs, club_id, "ERR_CLUB_NOT_FOUND")


def need_model(model_id):
    return _need(db.equipment_models, model_id, "ERR_MODEL_NOT_FOUND")


def need_equipment(equipment_id):
    return _need(db.equipment, equipment_id, "ERR_EQUIPMENT_NOT_FOUND")


def need_contract(contract_id):
    return _need(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")


def need_technician(technician_id):
    return _need(db.technicians, technician_id, "ERR_TECHNICIAN_NOT_FOUND")


def need_visit(visit_id):
    return _need(db.visits, visit_id, "ERR_VISIT_NOT_FOUND")


def need_call(call_id):
    return _need(db.calls, call_id, "ERR_CALL_NOT_FOUND")


def need_assignment(assignment_id):
    return _need(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def need_part(part_id):
    return _need(db.parts, part_id, "ERR_PART_NOT_FOUND")


def need_part_order(order_id):
    return _need(db.part_orders, order_id, "ERR_PART_ORDER_NOT_FOUND")


def need_downtime_event(event_id):
    return _need(db.downtime_events, event_id, "ERR_DOWNTIME_EVENT_NOT_FOUND")


def need_quote(quote_id):
    return _need(db.quotes, quote_id, "ERR_QUOTE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def club_equipment(club_id):
    return db.ordered(db.equipment, lambda e: e["club_id"] == club_id)


def club_contracts(club_id):
    return db.ordered(db.contracts, lambda c: c["club_id"] == club_id)


def contract_of(row):
    return db.contracts.get(row.get("contract_id"))


def club_id_of_contract(contract_id):
    contract = db.contracts.get(contract_id)
    return contract["club_id"] if contract else None


def model_category_of(equipment_row):
    model = db.equipment_models.get(equipment_row["model_id"])
    return model["category"] if model else None


# ---------------------------------------------------------------------------
# Condition score, pm status and the derived fleet counters
# ---------------------------------------------------------------------------
def condition_fields(equipment_row, extra=None):
    """The health-score triple for a machine, computed from a candidate view."""
    view = dict(equipment_row)
    if extra:
        view.update(extra)
    model = db.equipment_models.get(view["model_id"])
    cutoff = db.now() - timedelta(days=calc.TRAILING_WINDOW_DAYS)
    recent = []
    for row in db.calls.values():
        if row["equipment_id"] != view["id"] or row["status"] != "RESOLVED":
            continue
        resolved_at = db.parse_iso(row.get("resolved_at"))
        if resolved_at is not None and resolved_at >= cutoff:
            recent.append(row)
    if len(recent) >= calc.FAILURE_VARIANT_MIN_CALLS:
        variant = "FAILURE_BASED"
        counts = Counter(row["severity"] for row in recent)
        score = calc.failure_based_score(counts, view.get("downtime_minutes_ytd", 0))
    else:
        variant = "USAGE_BASED"
        life = model["expected_service_life_hours"] if model else 1
        age_years = calc.whole_years(view["install_date"], db.now())
        score = calc.usage_based_score(view.get("usage_hours", 0), life, age_years)
    threshold = calc.replacement_threshold(view.get("support_status"))
    return {
        "health_score": score,
        "health_score_variant": variant,
        "replacement_recommended": score <= threshold,
    }


def pm_status_fields(equipment_row, extra=None):
    view = dict(equipment_row)
    if extra:
        view.update(extra)
    model = db.equipment_models.get(view["model_id"])
    interval = model["pm_interval_hours"] if model else 1
    return {
        "pm_status": calc.pm_status_for(
            view.get("usage_hours", 0),
            view.get("usage_hours_at_last_pm", 0),
            interval,
        )
    }


def refresh_equipment_condition(equipment_row, extra=None):
    """Apply the condition triple (plus any caller changes) as one mutation."""
    changes = dict(extra or {})
    changes.update(condition_fields(equipment_row, changes))
    return db.apply_changes(equipment_row, changes)


def recompute_club_counters(club_id):
    club = db.clubs.get(club_id)
    if club is None:
        return
    fleet = club_equipment(club_id)
    db.apply_changes(club, {
        "covered_unit_count": len(fleet),
        "open_safety_lockout_count": len(
            [e for e in fleet if e["lifecycle_status"] == "TAGGED_OUT"]
        ),
    })


def contract_fleet_fields(club_id):
    fleet = club_equipment(club_id)
    covered = len(fleet)
    candidates = len([e for e in fleet if e["replacement_recommended"]])
    obsolete = len([e for e in fleet if e["support_status"] == "UNSUPPORTED"])
    return {
        "obsolete_unit_count": obsolete,
        "replacement_candidate_count": candidates,
        "fleet_renewal_risk": calc.fleet_risk(candidates, covered),
    }


def recompute_contract_fleet(club_id):
    fields = contract_fleet_fields(club_id)
    for contract in club_contracts(club_id):
        db.apply_changes(contract, dict(fields))


def recompute_fleet_derivations(club_id):
    """Club counters first, then every covering contract's risk view."""
    recompute_club_counters(club_id)
    recompute_contract_fleet(club_id)


def refresh_pm_compliance(contract):
    return db.apply_changes(contract, {
        "pm_compliance_pct": calc.pm_compliance_pct(
            contract["pm_visits_completed_count"],
            contract["pm_visits_missed_count"],
        )
    })


# ---------------------------------------------------------------------------
# Safety lockout
# ---------------------------------------------------------------------------
def tag_out_equipment(equipment_row, reason):
    """Drive a machine into TAGGED_OUT and refresh the club's lockout counter."""
    db.apply_changes(equipment_row, {
        "lifecycle_status": "TAGGED_OUT",
        "safety_lockout_reason": reason,
    })
    recompute_club_counters(equipment_row["club_id"])


# ---------------------------------------------------------------------------
# Technician calendar and the routing selector
# ---------------------------------------------------------------------------
def held_assignments(technician_id):
    return [
        a for a in db.assignments.values()
        if a["technician_id"] == technician_id
        and a["status"] in calc.HELD_ASSIGNMENT_STATUSES
    ]


def has_window_conflict(technician_id, start_at, end_at):
    """Half-open intervals with a symmetric 45-minute travel buffer."""
    buffer_delta = timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)
    for existing in held_assignments(technician_id):
        existing_start = db.parse_iso(existing["start_at"])
        existing_end = db.parse_iso(existing["end_at"])
        if start_at < existing_end + buffer_delta and existing_start < end_at + buffer_delta:
            return True
    return False


def has_capacity(technician, planned_minutes):
    return technician["committed_minutes"] + planned_minutes <= technician["max_committed_minutes"]


def check_named_technician(technician, club, category, equipment_row, start_at, end_at,
                          planned_minutes):
    """Explicitly named technician: each failure surfaces its own code."""
    if technician["region_code"] != club["region_code"]:
        raise ApiError("ERR_TECHNICIAN_REGION_MISMATCH")
    if category not in technician["skill_categories"]:
        raise ApiError("ERR_TECHNICIAN_SKILL_MISMATCH")
    if technician["duty_status"] != "ON_DUTY":
        raise ApiError("ERR_TECHNICIAN_OFF_DUTY")
    if has_window_conflict(technician["id"], start_at, end_at):
        raise ApiError("ERR_TECHNICIAN_WINDOW_CONFLICT")
    if not has_capacity(technician, planned_minutes):
        raise ApiError("ERR_TECHNICIAN_CAPACITY_EXCEEDED")
    return technician


def route_technician(club, category, equipment_row, start_at, end_at, planned_minutes):
    """Automatic routing: the eligible pool, ordered by load then seniority."""
    tagged_out = equipment_row["lifecycle_status"] == "TAGGED_OUT"
    pool = []
    for technician in db.ordered(db.technicians):
        if technician["duty_status"] != "ON_DUTY":
            continue
        if technician["region_code"] != club["region_code"]:
            continue
        if category not in technician["skill_categories"]:
            continue
        if tagged_out and not technician["is_safety_inspector"]:
            continue
        if has_window_conflict(technician["id"], start_at, end_at):
            continue
        if not has_capacity(technician, planned_minutes):
            continue
        pool.append(technician)
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_TECHNICIAN")
    pool.sort(key=lambda t: (t["committed_minutes"], t["created_at"], t["_seq"]))
    return pool[0]


def create_assignment(technician, start_at, end_at, service_call_id=None,
                      preventive_visit_id=None):
    planned = calc.minutes_between(start_at, end_at)
    row = db.base_row()
    row.update({
        "technician_id": technician["id"],
        "service_call_id": service_call_id,
        "preventive_visit_id": preventive_visit_id,
        "start_at": db.iso(start_at),
        "end_at": db.iso(end_at),
        "planned_minutes": planned,
        "status": "RESERVED",
        "release_reason": None,
    })
    db.assignments[row["id"]] = row
    db.apply_changes(technician, {
        "committed_minutes": technician["committed_minutes"] + planned
    })
    return row


def find_assignment(service_call_id=None, preventive_visit_id=None, statuses=None):
    for row in db.ordered(db.assignments):
        if service_call_id is not None and row["service_call_id"] != service_call_id:
            continue
        if preventive_visit_id is not None and row["preventive_visit_id"] != preventive_visit_id:
            continue
        if statuses is not None and row["status"] not in statuses:
            continue
        return row
    return None


def confirm_assignment(assignment):
    """RESERVED -> CONFIRMED; committed minutes are unchanged."""
    if assignment is None:
        return None
    if assignment["status"] == "RESERVED":
        db.apply_changes(assignment, {"status": "CONFIRMED"})
    return assignment


def complete_assignment(assignment):
    """CONFIRMED -> COMPLETED; the committed minutes are returned."""
    if assignment is None:
        return None
    if assignment["status"] in calc.HELD_ASSIGNMENT_STATUSES:
        _return_minutes(assignment)
        db.apply_changes(assignment, {"status": "COMPLETED"})
    return assignment


def release_assignment(assignment, reason):
    """RESERVED|CONFIRMED -> RELEASED; the committed minutes are returned."""
    if assignment is None:
        return None
    if assignment["status"] in calc.HELD_ASSIGNMENT_STATUSES:
        _return_minutes(assignment)
        db.apply_changes(assignment, {
            "status": "RELEASED",
            "release_reason": reason,
        })
    return assignment


def _return_minutes(assignment):
    technician = db.technicians.get(assignment["technician_id"])
    if technician is None:
        return
    db.apply_changes(technician, {
        "committed_minutes": technician["committed_minutes"] - assignment["planned_minutes"]
    })
