"""Reactive service calls: filing, dispatch, arrival, parts cycle, resolution."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import calc, credit, domain, parts as parts_service, validate

bp = Blueprint("calls", __name__)


def _club_of_call(call):
    return domain.club_id_of_contract(call["contract_id"])


def _scope_from_body(ctx, body):
    """A ClubManager filing a call is confined to its own club (rung 3).

    The scope is resolved from whichever reference the body carries and can be
    resolved without a lookup failure; a body naming nothing resolvable falls
    through to the ordinary body-referenced existence checks of rung 19.
    """
    if ctx["role"] != middleware.CLUB_MANAGER:
        return
    contract_id = body.get("contract_id")
    if isinstance(contract_id, str):
        contract = db.contracts.get(contract_id)
        if contract is not None:
            middleware.require_club_scope(ctx, contract["club_id"])
            return
    equipment_id = body.get("equipment_id")
    if isinstance(equipment_id, str):
        equipment_row = db.equipment.get(equipment_id)
        if equipment_row is not None:
            middleware.require_club_scope(ctx, equipment_row["club_id"])


@bp.post("/fleetcare/service-calls")
def create_call():
    ctx = middleware.auth(middleware.CLUB_MANAGER, middleware.SERVICE_COORDINATOR)
    body = middleware.body()
    _scope_from_body(ctx, body)
    contract_id = validate.identifier(body, "contract_id")
    equipment_id = validate.identifier(body, "equipment_id")
    severity = validate.enum(body, "severity", calc.SEVERITIES)
    symptom_code = validate.string(body, "symptom_code", min_len=1, max_len=40)
    injury = validate.boolean(body, "injury_reported", default=False)

    contract = domain.need_contract(contract_id)
    equipment_row = domain.need_equipment(equipment_id)

    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    # Rung 35 sits in the safety band and therefore outranks rung 37.
    if injury and severity != "CRITICAL":
        raise ApiError("ERR_INJURY_SEVERITY_MISMATCH")
    if equipment_row["club_id"] != contract["club_id"]:
        raise ApiError("ERR_EQUIPMENT_CLUB_MISMATCH")
    for existing in db.calls.values():
        if existing["equipment_id"] != equipment_id:
            continue
        if existing["status"] in calc.LIVE_CALL_STATUSES:
            raise ApiError("ERR_DUPLICATE_OPEN_CALL")

    reported_at = db.now()
    already_tagged_out = equipment_row["lifecycle_status"] == "TAGGED_OUT"
    row = db.base_row()
    row.update({
        "contract_id": contract_id,
        "equipment_id": equipment_id,
        "assigned_technician_id": None,
        "severity": severity,
        "symptom_code": symptom_code,
        "injury_reported": injury,
        "reported_at": db.iso(reported_at),
        "dispatched_at": None,
        "arrived_at": None,
        "resolved_at": None,
        "sla_target_minutes": calc.sla_target_minutes(
            contract["sla_response_minutes"], severity
        ),
        "response_minutes": None,
        "sla_met": None,
        "status": "OPEN",
        "resolution_code": None,
        "cancellation_reason": None,
        "safety_review_required": bool(injury or already_tagged_out),
        "safety_clearance_technician_id": None,
        "parts_hold_count": 0,
    })
    db.calls[row["id"]] = row

    # An injury locks the machine out; otherwise a serviceable machine goes DOWN
    # and a machine that was already TAGGED_OUT stays locked out.
    if injury:
        domain.tag_out_equipment(equipment_row, "MEMBER_INJURY")
    elif equipment_row["lifecycle_status"] == "IN_SERVICE":
        db.apply_changes(equipment_row, {"lifecycle_status": "DOWN"})
    # The downtime meter starts the instant the fault was reported.
    credit.open_event(contract, equipment_row, row, reported_at)
    domain.recompute_club_counters(equipment_row["club_id"])
    return response.created_response(row)


@bp.get("/fleetcare/service-calls")
def list_calls():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.calls, {
        "contract_id": response.arg("contract_id"),
        "equipment_id": response.arg("equipment_id"),
        "assigned_technician_id": response.arg("assigned_technician_id"),
        "status": response.arg("status"),
        "severity": response.arg("severity"),
    })


@bp.get("/fleetcare/service-calls/<call_id>")
def read_call(call_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    call = domain.need_call(call_id)
    middleware.require_club_scope(ctx, _club_of_call(call))
    return response.object_response(call)


@bp.post("/fleetcare/service-calls/<call_id>/dispatch")
def dispatch_call(call_id):
    middleware.auth(middleware.SERVICE_COORDINATOR)
    call = domain.need_call(call_id)
    body = middleware.body()
    start_at = validate.instant(body, "start_at")
    technician_id = validate.identifier(body, "technician_id", required=False)
    named = domain.need_technician(technician_id) if technician_id is not None else None

    contract = db.contracts.get(call["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if call["status"] != "OPEN":
        raise ApiError("ERR_CALL_INVALID_STATE")

    equipment_row = domain.need_equipment(call["equipment_id"])
    club = db.clubs.get(contract["club_id"])
    category = domain.model_category_of(equipment_row)
    planned_minutes = calc.SEVERITY_PLANNED_MINUTES[call["severity"]]
    end_at = start_at + db.minutes(planned_minutes)

    # Rung 33 sits in the safety band, above region, skill, duty and calendar.
    tagged_out = equipment_row["lifecycle_status"] == "TAGGED_OUT"
    if named is not None:
        if tagged_out and not named["is_safety_inspector"]:
            raise ApiError("ERR_SAFETY_CERTIFICATION_REQUIRED")
        technician = domain.check_named_technician(
            named, club, category, equipment_row, start_at, end_at, planned_minutes
        )
    else:
        technician = domain.route_technician(
            club, category, equipment_row, start_at, end_at, planned_minutes
        )

    db.apply_changes(call, {
        "status": "DISPATCHED",
        "dispatched_at": db.now_iso(),
        "assigned_technician_id": technician["id"],
    })
    domain.create_assignment(technician, start_at, end_at, service_call_id=call["id"])
    return response.object_response(call)


@bp.post("/fleetcare/service-calls/<call_id>/arrive")
def arrive_call(call_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    call = domain.need_call(call_id)
    middleware.require_assigned(ctx, call["assigned_technician_id"])
    if call["status"] != "DISPATCHED":
        raise ApiError("ERR_CALL_INVALID_STATE")

    arrived_at = db.now()
    response_minutes = calc.minutes_between(db.parse_iso(call["reported_at"]), arrived_at)
    db.apply_changes(call, {
        "status": "ON_SITE",
        "arrived_at": db.iso(arrived_at),
        "response_minutes": response_minutes,
        # Landing exactly on the target counts as met.
        "sla_met": response_minutes <= call["sla_target_minutes"],
    })
    domain.confirm_assignment(
        domain.find_assignment(service_call_id=call["id"], statuses=("RESERVED",))
    )
    return response.object_response(call)


@bp.post("/fleetcare/service-calls/<call_id>/parts-hold")
def place_parts_hold(call_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    call = domain.need_call(call_id)
    middleware.require_assigned(ctx, call["assigned_technician_id"])
    body = middleware.body()
    part_id = validate.identifier(body, "part_id")
    qty = validate.integer(body, "qty", minimum=1)
    source = validate.enum(body, "source", calc.PART_SOURCES)

    part = domain.need_part(part_id)
    if call["status"] != "ON_SITE":
        raise ApiError("ERR_CALL_INVALID_STATE")

    equipment_row = domain.need_equipment(call["equipment_id"])
    contract = domain.need_contract(call["contract_id"])
    if part["model_id"] != equipment_row["model_id"]:
        raise ApiError("ERR_PART_MODEL_MISMATCH")
    if call["parts_hold_count"] >= calc.PARTS_HOLD_LIMIT:
        raise ApiError("ERR_PARTS_HOLD_LIMIT")
    bucket = parts_service.source_bucket(source)
    if part[bucket] < qty:
        raise ApiError("ERR_PART_OUT_OF_STOCK")
    if part["lifecycle_status"] == "OBSOLETE" and source == "NEW":
        raise ApiError("ERR_PART_SOURCE_UNAVAILABLE")

    covered = parts_service.is_covered(contract["parts_inclusion"], part["category"])
    if covered and contract["parts_allowance_remaining_cents"] <= 0:
        raise ApiError("ERR_PARTS_ALLOWANCE_EXHAUSTED")

    order = parts_service.allocate(call, contract, part, qty, source)
    db.apply_changes(call, {
        "status": "PARTS_HOLD",
        "parts_hold_count": call["parts_hold_count"] + 1,
    })
    return response.created_response(order)


@bp.post("/fleetcare/service-calls/<call_id>/resume")
def resume_call(call_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    call = domain.need_call(call_id)
    middleware.require_assigned(ctx, call["assigned_technician_id"])
    if call["status"] != "PARTS_HOLD":
        raise ApiError("ERR_CALL_INVALID_STATE")
    for order in db.part_orders.values():
        if order["service_call_id"] == call["id"] and order["status"] == "ALLOCATED":
            raise ApiError("ERR_UNRESOLVED_PART_ORDER")

    # arrived_at, response_minutes and sla_met are deliberately left untouched.
    db.apply_changes(call, {"status": "ON_SITE"})
    return response.object_response(call)


@bp.post("/fleetcare/service-calls/<call_id>/resolve")
def resolve_call(call_id):
    ctx = middleware.auth(middleware.FIELD_TECHNICIAN)
    call = domain.need_call(call_id)
    middleware.require_assigned(ctx, call["assigned_technician_id"])
    body = middleware.body()
    resolution_code = validate.string(body, "resolution_code", min_len=1, max_len=40)
    clearance_id = validate.identifier(body, "safety_clearance_technician_id",
                                       required=False)
    clearance = domain.need_technician(clearance_id) if clearance_id is not None else None

    if call["status"] != "ON_SITE":
        raise ApiError("ERR_CALL_INVALID_STATE")
    if call["safety_review_required"]:
        if clearance is None or not clearance["is_safety_inspector"]:
            raise ApiError("ERR_SAFETY_CLEARANCE_REQUIRED")
    if clearance is not None and clearance["id"] == call["assigned_technician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    resolved_at = db.now()
    db.apply_changes(call, {
        "status": "RESOLVED",
        "resolved_at": db.iso(resolved_at),
        "resolution_code": resolution_code,
        "safety_clearance_technician_id": clearance_id,
    })
    domain.complete_assignment(
        domain.find_assignment(service_call_id=call["id"],
                               statuses=calc.HELD_ASSIGNMENT_STATUSES)
    )

    contract = db.contracts.get(call["contract_id"])
    equipment_row = db.equipment.get(call["equipment_id"])
    club = db.clubs.get(contract["club_id"]) if contract else None

    # ---- hop one: the downtime event closes with the provisional variant ----
    event = credit.event_for_call(call["id"], statuses=("OPEN",))
    if event is not None and contract is not None and club is not None:
        credit.close_event(event, contract, club)

    # ---- hop two: the ledger and the machine's lifecycle absorb the closure -
    changes = {}
    if event is not None:
        changes["downtime_minutes_ytd"] = (
            equipment_row["downtime_minutes_ytd"] + (event["downtime_minutes"] or 0)
        )
        db.apply_changes(contract, {
            "credit_provisional_cents":
                contract["credit_provisional_cents"] + (event["provisional_credit_cents"] or 0)
        })
    if equipment_row["lifecycle_status"] == "DOWN":
        changes["lifecycle_status"] = "IN_SERVICE"
    elif equipment_row["lifecycle_status"] == "TAGGED_OUT" and clearance is not None:
        changes["lifecycle_status"] = "IN_SERVICE"
        changes["last_safety_clearance_at"] = db.iso(resolved_at)
        changes["safety_lockout_reason"] = None

    # ---- hops three and four: the condition triple is re-derived ------------
    domain.refresh_equipment_condition(equipment_row, changes)
    # ---- hop five: the contract's renewal-risk view follows -----------------
    domain.recompute_contract_fleet(equipment_row["club_id"])
    # The club's lockout counter is recomputed last.
    domain.recompute_club_counters(equipment_row["club_id"])
    return response.object_response(call)


@bp.post("/fleetcare/service-calls/<call_id>/cancel")
def cancel_call(call_id):
    ctx = middleware.auth(middleware.SERVICE_COORDINATOR, middleware.CLUB_MANAGER)
    call = domain.need_call(call_id)
    middleware.require_club_scope(ctx, _club_of_call(call))
    body = middleware.body()
    reason = validate.string(body, "reason", min_len=1)
    if call["status"] not in ("OPEN", "DISPATCHED"):
        raise ApiError("ERR_CALL_INVALID_STATE")

    was_dispatched = call["status"] == "DISPATCHED"
    db.apply_changes(call, {
        "status": "CANCELLED",
        "cancellation_reason": reason,
    })
    event = credit.event_for_call(call["id"], statuses=("OPEN",))
    if event is not None:
        credit.waive_event(event, "CALL_CANCELLED")
    equipment_row = db.equipment.get(call["equipment_id"])
    if equipment_row is not None and equipment_row["lifecycle_status"] == "DOWN":
        db.apply_changes(equipment_row, {"lifecycle_status": "IN_SERVICE"})
    if was_dispatched:
        domain.release_assignment(
            domain.find_assignment(service_call_id=call["id"], statuses=("RESERVED",)),
            "CALL_CANCELLED",
        )
    return response.object_response(call)
