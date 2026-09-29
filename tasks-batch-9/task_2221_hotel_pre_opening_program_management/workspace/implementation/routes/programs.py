"""Pre-opening program endpoints (PRD §3.1, §3.3, §3.8, §3.9)."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
import guards
import repo
import response
import tx
import validate as v
from db import db as store
from errors import ApiError
from middleware import ALL_ROLES, actor, require
from services import derive
from validate import round_half_up

bp = Blueprint("programs", __name__)


def _new_program(data, body):
    ts = db.stamp()
    return {
        "id": db.new_id(),
        "property_name": data["property_name"],
        "brand_code": data["brand_code"],
        "room_count": data["room_count"],
        "construction_start_date": data["construction_start_date"],
        "target_opening_date": data["target_opening_date"],
        "licensing_buffer_days": data["licensing_buffer_days"],
        "rework_buffer_days": data["rework_buffer_days"],
        "slip_tolerance_days": data["slip_tolerance_days"],
        "storage_capacity_pallets": data["storage_capacity_pallets"],
        "relocation_rate_cents": data["relocation_rate_cents"],
        "guarantee_penalty_cents": data["guarantee_penalty_cents"],
        "room_night_ceiling": data["room_night_ceiling"],
        "contingency_liability_cap_cents": data["contingency_liability_cap_cents"],
        "stabilization_window_days": data["stabilization_window_days"],
        "schedule_state": "PLANNING",
        "commercial_state": "BOOKING_CLOSED",
        "readiness_posture": "MOBILIZING",
        "readiness_score": 0.0,
        "projected_opening_date_optimistic": None,
        "projected_opening_date_committed": None,
        "projected_opening_date": None,
        "schedule_slip_days": 0,
        "critical_path_milestone_count": 0,
        "open_critical_punch_count": 0,
        "required_system_count": 0,
        "certified_system_count": 0,
        "issued_mandatory_permit_count": 0,
        "hiring_plan_count": 0,
        "departments_ready_count": 0,
        "committed_room_nights": 0,
        "contingency_liability_cents": 0,
        "payroll_accrual_cents": 0,
        "cost_at_completion_commitment_cents": 0,
        "cost_at_completion_accrual_cents": 0,
        "soft_opening_date": None,
        "baselined_by_user_id": None,
        "soft_opening_authorized_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


@bp.post("/pre-opening/programs")
@require("ProgramDirector")
def create_program():
    body = v.body()
    property_name = v.req_str(body, "property_name", 1, 120)
    brand_code = v.req_str(body, "brand_code", 2, 12)
    room_count = v.req_int(body, "room_count", minimum=1)
    construction_raw, construction_date = v.req_date(body, "construction_start_date")
    target_raw, target_date = v.req_date(body, "target_opening_date")
    if not target_date > construction_date:
        raise v.bad("target_opening_date must be strictly after construction_start_date.")
    storage_capacity_pallets = v.req_int(body, "storage_capacity_pallets", minimum=1)
    relocation_rate_cents = v.req_int(body, "relocation_rate_cents", minimum=0)
    guarantee_penalty_cents = v.req_int(body, "guarantee_penalty_cents", minimum=0)
    room_night_ceiling = v.req_int(body, "room_night_ceiling", minimum=0)
    contingency_cap = v.req_int(body, "contingency_liability_cap_cents", minimum=0)
    licensing_buffer_days = v.opt_int(body, "licensing_buffer_days", 14, 0, 120)
    rework_buffer_days = v.opt_int(body, "rework_buffer_days", 3, 0, 60)
    slip_tolerance_days = v.opt_int(body, "slip_tolerance_days", 10, 0, 120)
    stabilization_window_days = v.opt_int(body, "stabilization_window_days", 30, 0, 365)

    program = _new_program({
        "property_name": property_name,
        "brand_code": brand_code,
        "room_count": room_count,
        "construction_start_date": construction_raw,
        "target_opening_date": target_raw,
        "licensing_buffer_days": licensing_buffer_days,
        "rework_buffer_days": rework_buffer_days,
        "slip_tolerance_days": slip_tolerance_days,
        "storage_capacity_pallets": storage_capacity_pallets,
        "relocation_rate_cents": relocation_rate_cents,
        "guarantee_penalty_cents": guarantee_penalty_cents,
        "room_night_ceiling": room_night_ceiling,
        "contingency_liability_cap_cents": contingency_cap,
        "stabilization_window_days": stabilization_window_days,
    }, body)
    store.programs[program["id"]] = program
    tx.commit()
    return response.created(repo.serialize(program))


@bp.get("/pre-opening/programs")
@require(*ALL_ROLES)
def list_programs():
    posture = v.q_enum("readiness_posture", repo.POSTURES)
    schedule_state = v.q_enum("schedule_state", repo.SCHEDULE_STATES)
    items = db.sort_created(list(store.programs.values()))
    if posture:
        items = [p for p in items if p["readiness_posture"] == posture]
    if schedule_state:
        items = [p for p in items if p["schedule_state"] == schedule_state]
    page, meta = v.paginate(items)
    return response.ok_list(repo.serialize_many(page), meta)


@bp.get("/pre-opening/programs/<program_id>")
@require(*ALL_ROLES)
def read_program(program_id):
    program = repo.get_program(program_id)
    return response.ok(repo.serialize(program))


@bp.get("/pre-opening/programs/<program_id>/readiness")
@require(*ALL_ROLES)
def read_readiness(program_id):
    program = repo.get_program(program_id)
    systems_ratio, staffing_ratio, permit_ratio, schedule_term = derive.posture_components(program)
    optimistic = program["projected_opening_date_optimistic"]
    committed = program["projected_opening_date_committed"]
    if optimistic and committed:
        gap = (clock.parse_date_strict(committed) - clock.parse_date_strict(optimistic)).days
    else:
        gap = None
    return response.ok({
        "readiness_posture": program["readiness_posture"],
        "readiness_score": program["readiness_score"],
        "systems_ratio": float(round_half_up(systems_ratio, 4)),
        "staffing_ratio": float(round_half_up(staffing_ratio, 4)),
        "permit_ratio": float(round_half_up(permit_ratio, 4)),
        "schedule_term": float(round_half_up(schedule_term, 4)),
        "schedule_slip_days": program["schedule_slip_days"],
        "projected_opening_date_optimistic": optimistic,
        "projected_opening_date_committed": committed,
        "variant_gap_days": gap,
        "cost_at_completion_commitment_cents": program["cost_at_completion_commitment_cents"],
        "cost_at_completion_accrual_cents": program["cost_at_completion_accrual_cents"],
        "payroll_accrual_cents": program["payroll_accrual_cents"],
        "contingency_liability_cents": program["contingency_liability_cents"],
        "committed_room_nights": program["committed_room_nights"],
    })


@bp.post("/pre-opening/programs/<program_id>/baseline-schedule")
@require("ProgramDirector")
def baseline_schedule(program_id):
    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    if program["schedule_state"] != "PLANNING":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Only a PLANNING program may be baselined.")
    milestones = repo.milestones_of(program_id)
    if not milestones:
        raise ApiError("ERR_SCHEDULE_EMPTY")
    deps = repo.dependencies_of_program(program_id)
    from services import schedule as schedule_service
    if schedule_service.has_cycle(milestones, deps):
        raise ApiError("ERR_DEPENDENCY_CYCLE")

    program["schedule_state"] = "BASELINED"
    program["baselined_by_user_id"] = actor()
    derive.refresh(program, run_schedule=True)
    tx.commit(program["id"])
    return response.ok(repo.serialize(program))


@bp.post("/pre-opening/programs/<program_id>/recompute-schedule")
@require("ProgramDirector", "ConstructionManager")
def recompute_schedule(program_id):
    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    if not repo.milestones_of(program_id):
        raise ApiError("ERR_SCHEDULE_EMPTY")
    derive.refresh(program, run_schedule=True)
    tx.commit(program["id"])
    return response.ok(repo.serialize(program))


@bp.post("/pre-opening/programs/<program_id>/open-booking")
@require("CommercialDirector")
def open_booking(program_id):
    program = repo.get_program(program_id)
    guards.ensure_not_stabilized(program)
    current = program["commercial_state"]
    if current not in ("BOOKING_CLOSED", "BOOKING_SUSPENDED"):
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Booking may only be opened from BOOKING_CLOSED or BOOKING_SUSPENDED.")
    if current == "BOOKING_CLOSED":
        if program["schedule_state"] not in ("CONSTRUCTION_COMPLETE", "LICENSING", "SOFT_OPENING"):
            raise ApiError("ERR_INVALID_PROGRAM_STATE",
                           "The delivery dimension does not permit opening booking.")
    guards.ensure_not_frozen(program)

    program["commercial_state"] = "BOOKING_OPEN"
    if current == "BOOKING_SUSPENDED":
        for block in repo.blocks_of(program_id):
            if block["state"] == "AT_RISK" and not derive.is_pre_opening(
                    program, block["arrival_date"]):
                block["state"] = "ACCEPTED"
                block["at_risk_reason"] = None
                block["_guaranteed"] = False
    derive.reconcile(program)
    tx.commit(program["id"])
    return response.ok(repo.serialize(program))


@bp.post("/pre-opening/programs/<program_id>/suspend-booking")
@require("CommercialDirector")
def suspend_booking(program_id):
    program = repo.get_program(program_id)
    v.body()
    guards.ensure_not_stabilized(program)
    if program["commercial_state"] != "BOOKING_OPEN":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Only a BOOKING_OPEN program may be suspended.")
    program["commercial_state"] = "BOOKING_SUSPENDED"
    derive.reconcile(program)
    tx.commit(program["id"])
    return response.ok(repo.serialize(program))


@bp.post("/pre-opening/programs/<program_id>/authorize-soft-opening")
@require("ProgramDirector")
def authorize_soft_opening(program_id):
    body = v.body()
    program = repo.get_program(program_id)
    soft_raw, soft_date = v.req_date(body, "soft_opening_date")

    # tier 6 -- segregation of duties precedes state admissibility (PRD §2.10)
    if program["baselined_by_user_id"] and actor() == program["baselined_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The baselining director may not authorize the soft opening.")
    guards.ensure_not_stabilized(program)
    if program["schedule_state"] != "LICENSING":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Soft opening may only be authorized from LICENSING.")
    guards.ensure_not_frozen(program)
    if program["issued_mandatory_permit_count"] != 4:
        raise ApiError("ERR_MANDATORY_PERMIT_NOT_ISSUED")
    if program["open_critical_punch_count"] != 0:
        raise ApiError("ERR_CRITICAL_PUNCH_OPEN")
    if program["certified_system_count"] != program["required_system_count"]:
        raise ApiError("ERR_SYSTEM_NOT_CERTIFIED")
    if program["hiring_plan_count"] < 1 or (
            program["departments_ready_count"] != program["hiring_plan_count"]):
        raise ApiError("ERR_DEPARTMENT_NOT_READY")
    committed = program["projected_opening_date_committed"]
    if not committed:
        raise ApiError("ERR_SOFT_OPENING_DATE_INVALID")
    if soft_date < clock.today() or soft_date > clock.parse_date_strict(committed):
        raise ApiError("ERR_SOFT_OPENING_DATE_INVALID")

    program["schedule_state"] = "SOFT_OPENING"
    program["soft_opening_date"] = soft_raw
    program["soft_opening_authorized_by_user_id"] = actor()
    derive.refresh(program)
    tx.commit(program["id"])
    return response.ok(repo.serialize(program))


@bp.post("/pre-opening/programs/<program_id>/transition-to-stabilized")
@require("ProgramDirector")
def transition_to_stabilized(program_id):
    program = repo.get_program(program_id)
    if program["schedule_state"] != "SOFT_OPENING":
        raise ApiError("ERR_INVALID_PROGRAM_STATE",
                       "Stabilization is only possible from SOFT_OPENING.")
    for item in repo.punch_items_of(program_id):
        if item["state"] != "VERIFIED":
            raise ApiError("ERR_PUNCH_LIST_OPEN")
    for order in repo.orders_of(program_id):
        if order["state"] == "COMMITTED":
            raise ApiError("ERR_OSE_ORDER_PENDING")
    soft = program["soft_opening_date"]
    if not soft:
        raise ApiError("ERR_STABILIZATION_WINDOW_NOT_ELAPSED")
    threshold = clock.parse_date_strict(soft) + timedelta(
        days=program["stabilization_window_days"])
    if clock.today() < threshold:
        raise ApiError("ERR_STABILIZATION_WINDOW_NOT_ELAPSED")

    program["schedule_state"] = "STABILIZED"
    if program["commercial_state"] == "BOOKING_OPEN":
        program["commercial_state"] = "SELLING_STABILIZED"
    for block in repo.blocks_of(program_id):
        if block["state"] == "GUARANTEED":
            block["state"] = "HONORED"
            block["at_risk_reason"] = None
            block["contingency_cents"] = 0
    derive.reconcile(program)
    tx.commit(program["id"])
    return response.ok(repo.serialize(program))
