"""Shared domain helpers: row lookups, the certificate-status mirror, risk
re-scoring, allowable recomputation, route roll-ups and cascade fragments.
"""
from calc import (
    HOLD_THRESHOLD,
    initial_assessment_score,
    monthly_allowable_cents,
    ongoing_surveillance_score,
    risk_factors,
    stop_liters_committed,
)
from core import ApiError, db, now, order_key, touch

# ---------------------------------------------------------------- lookups
def get_branch(branch_id, error_id="ERR_BRANCH_NOT_FOUND"):
    row = db.branches.get(branch_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_patient(patient_id):
    row = db.patients.get(patient_id)
    if row is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    return row


def get_qualifying_test(test_id):
    row = db.qualifying_tests.get(test_id)
    if row is None:
        raise ApiError("ERR_QUALIFYING_TEST_NOT_FOUND")
    return row


def get_cmn(cmn_id):
    row = db.cmns.get(cmn_id)
    if row is None:
        raise ApiError("ERR_CMN_NOT_FOUND")
    return row


def get_contract(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return row


def get_equipment_unit(unit_id):
    row = db.equipment_units.get(unit_id)
    if row is None:
        raise ApiError("ERR_EQUIPMENT_UNIT_NOT_FOUND")
    return row


def get_placement(placement_id):
    row = db.placements.get(placement_id)
    if row is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND")
    return row


def get_route(route_id):
    row = db.routes.get(route_id)
    if row is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND")
    return row


def get_route_stop(stop_id):
    row = db.route_stops.get(stop_id)
    if row is None:
        raise ApiError("ERR_ROUTE_STOP_NOT_FOUND")
    return row


def get_recall_notice(notice_id):
    row = db.recall_notices.get(notice_id)
    if row is None:
        raise ApiError("ERR_RECALL_NOTICE_NOT_FOUND")
    return row


def get_travel_authorization(auth_id):
    row = db.travel_authorizations.get(auth_id)
    if row is None:
        raise ApiError("ERR_TRAVEL_AUTHORIZATION_NOT_FOUND")
    return row


# ------------------------------------------------- certificate status mirror
def patient_cmns(patient_id):
    return [c for c in db.cmns.values() if c["patient_id"] == patient_id]


def newest_cmn(patient_id):
    rows = patient_cmns(patient_id)
    if not rows:
        return None
    rows.sort(key=order_key, reverse=True)
    return rows[0]


def rederive_cmn_mirror(patient, touched_ids=()):
    """Mirror the newest certificate's status onto the patient.

    A write against the newest certificate always re-stamps the mirror (and
    therefore bumps the patient row); a write against an older certificate
    only touches the patient when the mirrored value actually changes.
    """
    newest = newest_cmn(patient["id"])
    value = newest["status"] if newest else "NONE"
    if newest is not None and newest["id"] in tuple(touched_ids):
        patient["current_cmn_status"] = value
        touch(patient)
        return True
    if patient["current_cmn_status"] != value:
        patient["current_cmn_status"] = value
        touch(patient)
        return True
    return False


# ------------------------------------------------------------- risk scoring
def apply_risk_variant(patient, variant):
    factors = risk_factors(patient)
    if variant == "INITIAL_ASSESSMENT":
        score = initial_assessment_score(factors)
    else:
        score = ongoing_surveillance_score(factors)
    patient["oxygen_safety_risk_score"] = score
    patient["risk_variant_applied"] = variant
    patient["compliance_hold"] = score >= HOLD_THRESHOLD
    touch(patient)
    return score


# ---------------------------------------------------------- monthly allowable
def recompute_allowable(contract):
    contract["monthly_allowable_cents"] = monthly_allowable_cents(contract)
    return contract["monthly_allowable_cents"]


# ------------------------------------------------------------- route helpers
def route_stops(route_id):
    return [s for s in db.route_stops.values() if s["route_id"] == route_id]


def stop_sort_key(stop):
    return (stop["window_start_utc"], stop["created_at"], stop["_seq"])


def resequence_route(route):
    """Renumber every non-cancelled stop by window start; bump rows that move."""
    stops = [s for s in route_stops(route["id"]) if s["status"] != "CANCELLED"]
    stops.sort(key=stop_sort_key)
    for index, stop in enumerate(stops, start=1):
        if stop["sequence_index"] != index:
            stop["sequence_index"] = index
            touch(stop)


def recompute_route_rollups(route):
    stops = route_stops(route["id"])
    total = 0
    refills = 0
    planned = 0
    for stop in stops:
        if stop["status"] in ("PLANNED", "COMPLETED", "MISSED"):
            total += stop["liters_committed"]
        if stop["stop_type"] == "PORTABLE_REFILL" and stop["status"] in (
            "PLANNED",
            "COMPLETED",
        ):
            refills += 1
        if stop["status"] == "PLANNED":
            planned += 1
    route["total_o2_liters_committed"] = total
    route["refill_slots_used"] = refills
    route["planned_stop_count"] = planned
    return route


def bubble_up_route(route):
    """A DISPATCHED route with no PLANNED stops left completes itself."""
    if route["status"] != "DISPATCHED":
        return False
    stops = route_stops(route["id"])
    if not stops:
        return False
    for stop in stops:
        if stop["status"] not in ("COMPLETED", "MISSED", "CANCELLED"):
            return False
    route["status"] = "COMPLETED"
    route["planned_stop_count"] = 0
    touch(route)
    return True


def stop_liters(stop):
    return stop_liters_committed(stop["stop_type"], stop["cylinders_requested"])


# --------------------------------------------------------- contract helpers
def contracts_for_cmn(cmn_id):
    return [c for c in db.contracts.values() if c["cmn_id"] == cmn_id]


def contracts_for_patient(patient_id):
    return [c for c in db.contracts.values() if c["patient_id"] == patient_id]


def placements_for_contract(contract_id, statuses=None):
    rows = [p for p in db.placements.values() if p["contract_id"] == contract_id]
    if statuses is not None:
        rows = [p for p in rows if p["status"] in statuses]
    return sorted(rows, key=order_key)


def suspend_contracts_for_cmn(cmn, reason):
    """Suspend every billing-open contract resting on this certificate."""
    count = 0
    for contract in sorted(contracts_for_cmn(cmn["id"]), key=order_key):
        if contract["billing_status"] in ("ACCRUING", "CAP_REACHED"):
            contract["billing_status"] = "SUSPENDED"
            contract["suspension_reason"] = reason
            touch(contract)
            count += 1
    return count


def open_contract_exists(patient_id):
    for contract in db.contracts.values():
        if contract["patient_id"] == patient_id and contract["billing_status"] != "CLOSED":
            return True
    return False


def contract_has_recalled_equipment(contract_id):
    for placement in db.placements.values():
        if (
            placement["contract_id"] == contract_id
            and placement["status"] == "RECALLED_OUT_OF_SERVICE"
        ):
            return True
    return False


def clock_sweep(new_clock):
    """Expire due certificates and suspend the contracts resting on them."""
    expired = 0
    suspended = 0
    cmns = sorted(db.cmns.values(), key=order_key)
    for cmn in cmns:
        if cmn["status"] != "ACTIVE":
            continue
        due = cmn.get("recert_due_date")
        if due is None:
            continue
        if not isinstance(due, str):
            due = due.isoformat()
        # Whole-date comparison: YYYY-MM-DD strings order lexicographically.
        if not due < new_clock.date().isoformat():
            continue
        cmn["status"] = "EXPIRED"
        touch(cmn)
        expired += 1
        suspended += suspend_contracts_for_cmn(cmn, "CMN_EXPIRED")
        patient = db.patients.get(cmn["patient_id"])
        if patient is not None:
            rederive_cmn_mirror(patient, (cmn["id"],))
    return expired, suspended
