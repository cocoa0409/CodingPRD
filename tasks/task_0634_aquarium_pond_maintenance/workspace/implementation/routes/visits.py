"""ServiceVisit + WaterTest endpoints (PRD §3.3, §3.4, §3.5)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import visit_view, water_test_view
import common as C

bp = Blueprint("visits", __name__)

READ_ROLES = {"AccountManager", "Dispatcher", "FieldTech", "CustomerOwner"}


def _tech_double_booked(technician_id, start, end, exclude_visit_id=None):
    """True if [start,end) overlaps a SCHEDULED/IN_PROGRESS visit for this tech.
    Half-open: touching endpoints do not conflict (PRD §3.3)."""
    for v in store.visits.values():
        if v["id"] == exclude_visit_id:
            continue
        if v["technician_id"] != technician_id:
            continue
        if v["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        v_start = C.parse_iso(v["scheduled_start"])
        v_end = C.parse_iso(v["scheduled_end"])
        if C.half_open_overlap(start, end, v_start, v_end):
            return True
    return False


@bp.post("/aquatics/visits")
def book_visit():
    _, role = get_auth()
    require_roles(role, {"Dispatcher"})
    data = C.require_body(request.get_json(silent=True))
    system_id = C.req_str(data, "system_id")
    technician_id = C.req_str(data, "technician_id")
    scheduled_start = C.req_datetime(data, "scheduled_start")
    scheduled_end = C.req_datetime(data, "scheduled_end")
    expected_system_version = C.req_int(data, "expected_system_version")
    visit_kind = C.req_enum(data, "visit_kind", {"ROUTINE", "EMERGENCY"},
                            allow_missing=True, default="ROUTINE")
    emergency_call_id = data.get("emergency_call_id")

    # existence (priority 4): system, technician, optional emergency call
    system = store.systems.get(system_id)
    if system is None:
        raise ApiError("ERR_NOT_FOUND", "System not found.")
    tech = store.technicians.get(technician_id)
    if tech is None:
        raise ApiError("ERR_NOT_FOUND", "Technician not found.")
    if emergency_call_id is not None and emergency_call_id not in store.emergencies:
        raise ApiError("ERR_NOT_FOUND", "Emergency call not found.")

    s_dt = C.parse_iso(scheduled_start)
    e_dt = C.parse_iso(scheduled_end)

    # double-booking (priority 9) — runs before kind/window/OCC per PRD §3.12
    if _tech_double_booked(technician_id, s_dt, e_dt):
        raise ApiError("ERR_TECH_DOUBLE_BOOKED", "Technician double-booked.")

    # visit-kind consistency (priority 12)
    if visit_kind == "EMERGENCY" and emergency_call_id is None:
        raise ApiError("ERR_VISIT_KIND_MISMATCH", "EMERGENCY visit requires emergency_call_id.")
    if visit_kind == "ROUTINE" and emergency_call_id is not None:
        raise ApiError("ERR_VISIT_KIND_MISMATCH", "ROUTINE visit must omit emergency_call_id.")

    # window ordering (priority 13): scheduled_start < scheduled_end (half-open)
    if not (s_dt < e_dt):
        raise ApiError("ERR_BAD_WINDOW", "scheduled_start must be before scheduled_end.")

    # OCC (priority 15)
    if expected_system_version != system["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale system version.")

    rec = C.make_record({
        "system_id": system_id,
        "technician_id": technician_id,
        "visit_kind": visit_kind,
        "emergency_call_id": emergency_call_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "labor_minutes": 0,
        "status": "SCHEDULED",
        "total_cents": 0,
        "invoice_id": None,
    })
    store.visits[rec["id"]] = rec
    # successful booking increments target system version by 1
    C.touch(system)
    return object_response(visit_view(rec), 201)


@bp.get("/aquatics/visits/<vid>")
def get_visit(vid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = store.visits.get(vid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    return object_response(visit_view(rec))


@bp.get("/aquatics/visits")
def list_visits():
    _, role = get_auth()
    require_roles(role, {"AccountManager", "Dispatcher", "FieldTech"})
    limit, offset = C.parse_pagination(request.args)
    system_id = request.args.get("system_id")
    technician_id = request.args.get("technician_id")
    emergency_call_id = request.args.get("emergency_call_id")
    status = request.args.get("status")
    recs = list(store.visits.values())
    if system_id is not None:
        recs = [v for v in recs if v["system_id"] == system_id]
    if technician_id is not None:
        recs = [v for v in recs if v["technician_id"] == technician_id]
    if emergency_call_id is not None:
        recs = [v for v in recs if v["emergency_call_id"] == emergency_call_id]
    if status is not None:
        recs = [v for v in recs if v["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([visit_view(r) for r in page], limit, offset, total)


@bp.post("/aquatics/visits/<vid>/start")
def start_visit(vid):
    user_id, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.visits.get(vid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED visit may be started.")
    system = store.systems.get(rec["system_id"])
    # tech-identity match (priority 6)
    acting_tech = C.technician_for_user(user_id)
    if acting_tech is None or acting_tech["id"] != rec["technician_id"]:
        raise ApiError("ERR_TECH_MISMATCH", "Acting tech is not the assigned tech.")
    # system must be ACTIVE
    if system is None or system["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Target system must be ACTIVE.")
    # reef certification (priority 7)
    assigned_tech = store.technicians.get(rec["technician_id"])
    if system["system_kind"] == "REEF" and not assigned_tech["certified_for_reef"]:
        raise ApiError("ERR_TECH_NOT_CERTIFIED", "Reef work requires a certified technician.")
    rec["status"] = "IN_PROGRESS"
    C.touch(rec)
    return object_response(visit_view(rec))


@bp.post("/aquatics/visits/<vid>/complete")
def complete_visit(vid):
    user_id, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.visits.get(vid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS visit may be completed.")
    data = C.require_body(request.get_json(silent=True))
    labor_minutes = C.req_int(data, "labor_minutes", minimum=0)
    consumable_lines = C.parse_consumable_lines(data)
    serviced_ids = data.get("serviced_equipment_ids") or []
    if not isinstance(serviced_ids, list):
        raise ApiError("ERR_INVALID_REQUEST", "serviced_equipment_ids must be a list.")
    # existence of serviced equipment
    for eid in serviced_ids:
        if eid not in store.equipment:
            raise ApiError("ERR_NOT_FOUND", "Serviced equipment not found.")

    rec["labor_minutes"] = labor_minutes

    system = store.systems.get(rec["system_id"])
    contract = store.contracts.get(system["contract_id"])

    # compute total
    total = C.compute_visit_total(rec, contract, consumable_lines)
    rec["total_cents"] = total
    rec["status"] = "COMPLETED"

    # create invoice
    source_kind = "EMERGENCY_TRIP" if rec["visit_kind"] == "EMERGENCY" else "VISIT"
    inv = C.create_invoice(contract["id"], source_kind, rec["id"], total)
    rec["invoice_id"] = inv["id"]
    C.touch(rec)
    C.recompute_account_balance(contract)

    # advance serviced equipment media schedules
    # PRD §3.3: last_serviced_on is the visit's completion date — the server's
    # logical-clock "now" (PRD §3.11), not wall-clock time.
    completion_date = C.clock_iso()
    for eid in serviced_ids:
        eq = store.equipment[eid]
        eq["last_serviced_on"] = completion_date
        sys_of_eq = store.systems.get(eq["system_id"])
        eq["media_due_on"] = C.compute_media_due_on(eq, sys_of_eq)
        C.touch(eq)

    # resolve linked emergency call
    if rec["visit_kind"] == "EMERGENCY" and rec["emergency_call_id"]:
        call = store.emergencies.get(rec["emergency_call_id"])
        if call is not None and call["status"] == "DISPATCHED":
            call["status"] = "RESOLVED"
            C.touch(call)

    return object_response(visit_view(rec))


@bp.post("/aquatics/visits/<vid>/dispute")
def dispute_visit(vid):
    user_id, role = get_auth()
    require_roles(role, {"CustomerOwner"})
    rec = store.visits.get(vid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    # ownership check (priority 3) before state? PRD §2.6/§3.12: ownership (3)
    # comes before existence-of-downstream/state. Here the visit must exist
    # first (path existence). Then ownership, then state.
    system = store.systems.get(rec["system_id"])
    contract = store.contracts.get(system["contract_id"]) if system else None
    if contract is None or contract["customer_user_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller does not own this contract.")
    if rec["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Only a COMPLETED visit may be disputed.")
    # invoice must not be PAID
    inv = store.invoices.get(rec["invoice_id"]) if rec["invoice_id"] else None
    if inv is not None and inv["status"] == "PAID":
        raise ApiError("ERR_INVALID_STATE", "A paid visit cannot be disputed.")
    rec["status"] = "DISPUTED"
    C.touch(rec)
    if inv is not None:
        inv["status"] = "VOID"
        C.touch(inv)
        C.recompute_account_balance(contract)
    return object_response(visit_view(rec))


@bp.post("/aquatics/visits/<vid>/rework")
def rework_visit(vid):
    user_id, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.visits.get(vid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    if rec["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", "Only a DISPUTED visit may be reworked.")
    acting_tech = C.technician_for_user(user_id)
    if acting_tech is None or acting_tech["id"] != rec["technician_id"]:
        raise ApiError("ERR_TECH_MISMATCH", "Acting tech is not the assigned tech.")
    rec["status"] = "IN_PROGRESS"
    rec["invoice_id"] = None
    rec["total_cents"] = 0
    C.touch(rec)
    return object_response(visit_view(rec))


@bp.post("/aquatics/visits/<vid>/cancel")
def cancel_visit(vid):
    _, role = get_auth()
    require_roles(role, {"Dispatcher"})
    rec = store.visits.get(vid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED visit may be cancelled.")
    rec["status"] = "CANCELLED"
    C.touch(rec)
    # compensation for emergency visit
    if rec["visit_kind"] == "EMERGENCY" and rec["emergency_call_id"]:
        call = store.emergencies.get(rec["emergency_call_id"])
        if call is not None and call["status"] == "DISPATCHED":
            call["status"] = "OPEN"
            call["dispatched_visit_id"] = None
            C.touch(call)
    return object_response(visit_view(rec))


# ===========================================================================
# WaterTest
# ===========================================================================
@bp.post("/aquatics/visits/<vid>/water-tests")
def create_water_test(vid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    visit = store.visits.get(vid)
    if visit is None:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    if visit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Water tests require an IN_PROGRESS visit.")
    data = C.require_body(request.get_json(silent=True))
    parameter = C.req_enum(data, "parameter",
                           {"ALKALINITY", "NITRATE", "PHOSPHATE", "PH", "AMMONIA"})
    measured_value = C.req_number(data, "measured_value", minimum=0)
    target_value = C.req_number(data, "target_value", minimum=0)
    product_strength = C.req_number(data, "product_strength_ppm_per_ml", exclusive_min=0)

    system = store.systems.get(visit["system_id"])
    dose = C.compute_dose_ml(system, measured_value, target_value, product_strength)

    rec = {
        "id": store.new_id(),
        "created_at": store.now_iso(),
        "visit_id": vid,
        "parameter": parameter,
        "measured_value": measured_value,
        "target_value": target_value,
        "product_strength_ppm_per_ml": product_strength,
        "recommended_dose_ml": dose,
    }
    store.water_tests[rec["id"]] = rec
    return object_response(water_test_view(rec), 201)


@bp.get("/aquatics/visits/<vid>/water-tests")
def list_water_tests(vid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    if vid not in store.visits:
        raise ApiError("ERR_NOT_FOUND", "Visit not found.")
    limit, offset = C.parse_pagination(request.args)
    parameter = request.args.get("parameter")
    recs = [w for w in store.water_tests.values() if w["visit_id"] == vid]
    if parameter is not None:
        recs = [w for w in recs if w["parameter"] == parameter]
    page, total = C.paginate(recs, limit, offset)
    return array_response([water_test_view(r) for r in page], limit, offset, total)
