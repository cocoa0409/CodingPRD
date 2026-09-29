"""The harvest desk: lanes, sampling crews, sampling visits, pick calls and
delivery appointments."""
import string
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import derive
import validation as v
from authz import (GROWER, GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                   QUALITY_LAB_TECH, SCALE_OPERATOR, auth, own)
from common import (CLOCK, D, add_hours, add_minutes, by_created_asc, fail,
                    new_record, q3, read_body, respond, respond_list, rows,
                    touch, utc_date)
from lookup import contract_in, contract_writable, find, not_suspended

bp = Blueprint("harvest", __name__)

UPPER_HYPHEN = set(string.ascii_uppercase + "-")
ZERO3 = Decimal("0.000")
SAMPLING_CONTRACT_STATES = ("DRAFT", "OFFERED", "ACTIVE")


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a_start, a_end) meets [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


# --------------------------------------------------------------------------
# Crush-pad lanes
# --------------------------------------------------------------------------
@bp.post("/grower-relations/crush-pad-lanes")
def create_lane():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR)
    body = read_body()
    lane_code = v.req_str(body, "lane_code", 1, 16)
    daily_capacity_tons = v.req_num(body, "daily_capacity_tons", 3, exclusive_min=0)
    buffer_minutes = v.opt_int(body, "turnaround_buffer_minutes", minimum=0, default=30)
    max_load_tons = v.opt_num(body, "max_load_tons", 3, exclusive_min=0,
                              default=D("40.0"))
    status = v.opt_enum(body, "status", ("OPEN", "CLOSED"), "OPEN")

    for other in rows("lanes"):
        if other["lane_code"] == lane_code:
            fail("ERR_DUPLICATE_CODE", "Lane code '%s' already exists." % lane_code)

    row = new_record("lanes", {
        "lane_code": lane_code,
        "daily_capacity_tons": daily_capacity_tons,
        "turnaround_buffer_minutes": buffer_minutes,
        "max_load_tons": max_load_tons,
        "status": status,
    })
    return respond(derive.lane_json(row), 201)


@bp.get("/grower-relations/crush-pad-lanes/<lane_id>")
def get_lane(lane_id):
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, SCALE_OPERATOR)
    return respond(derive.lane_json(find("lanes", lane_id)))


@bp.get("/grower-relations/crush-pad-lanes")
def list_lanes():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, SCALE_OPERATOR)
    limit, offset = v.pagination()
    status = v.filt("status")
    items = rows("lanes")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.lane_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Sampling crews
# --------------------------------------------------------------------------
@bp.post("/grower-relations/sampling-crews")
def create_crew():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR)
    body = read_body()
    crew_code = v.req_str(body, "crew_code", 1, 16)
    region_code = v.req_str(body, "region_code", 2, 16, UPPER_HYPHEN)
    max_concurrent = v.opt_int(body, "max_concurrent_visits", minimum=1, default=2)

    for other in rows("crews"):
        if other["crew_code"] == crew_code:
            fail("ERR_DUPLICATE_CODE", "Crew code '%s' already exists." % crew_code)

    row = new_record("crews", {
        "crew_code": crew_code,
        "region_code": region_code,
        "max_concurrent_visits": max_concurrent,
    })
    return respond(derive.crew_json(row), 201)


@bp.get("/grower-relations/sampling-crews/<crew_id>")
def get_crew(crew_id):
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, QUALITY_LAB_TECH)
    return respond(derive.crew_json(find("crews", crew_id)))


@bp.get("/grower-relations/sampling-crews")
def list_crews():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, QUALITY_LAB_TECH)
    limit, offset = v.pagination()
    region_code = v.filt("region_code")
    items = rows("crews")
    if region_code is not None:
        items = [r for r in items if r["region_code"] == region_code]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.crew_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Sampling visits
# --------------------------------------------------------------------------
@bp.post("/grower-relations/sampling-visits")
def create_visit():
    auth(HARVEST_COORDINATOR)
    body = read_body()

    contract_id = v.req_id(body, "contract_id")
    contract = find("contracts", contract_id)
    block_id = v.req_id(body, "block_id")
    block = find("blocks", block_id)
    crew_id = v.req_id(body, "crew_id")
    crew = find("crews", crew_id)

    window_start = v.req_dt(body, "window_start")
    window_end = v.req_dt(body, "window_end")
    v.window(window_start, window_end)

    # rank 20
    contract_in(contract, SAMPLING_CONTRACT_STATES)

    # rank 34 -- crew saturation
    busy = 0
    for visit in rows("visits"):
        if visit["crew_id"] != crew["id"] or visit["status"] != "SCHEDULED":
            continue
        if overlaps(window_start, window_end, visit["window_start"],
                    visit["window_end"]):
            busy += 1
    if busy >= int(crew["max_concurrent_visits"]):
        fail("ERR_CREW_WINDOW_OVERLAP_LIMIT",
             "The crew already holds %d overlapping scheduled visits." % busy)

    # rank 41 -- the block must be allocated to the contract
    if derive.allocation_for(contract["id"], block["id"]) is None:
        fail("ERR_BLOCK_NOT_ALLOCATED",
             "The block is not allocated to this contract.")

    # rank 42 -- territory
    grower = find("growers", block["grower_id"])
    if crew["region_code"] != grower["region_code"]:
        fail("ERR_CREW_REGION_MISMATCH",
             "The crew's region '%s' does not cover the producer's region '%s'."
             % (crew["region_code"], grower["region_code"]))

    row = new_record("visits", {
        "contract_id": contract["id"],
        "block_id": block["id"],
        "crew_id": crew["id"],
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "measured_brix": None,
        "measured_ta_gl": None,
        "measured_ph": None,
        "measured_rot_pct": None,
        "sampled_at": None,
        "maturity_flag": None,
    })
    touch(crew)
    return respond(derive.visit_json(row), 201)


@bp.post("/grower-relations/sampling-visits/<visit_id>/record")
def record_visit(visit_id):
    auth(HARVEST_COORDINATOR)
    visit = find("visits", visit_id)
    body = read_body()
    brix = v.req_num(body, "measured_brix", 1, exclusive_min=0, maximum=40)
    ta_gl = v.req_num(body, "measured_ta_gl", 1, exclusive_min=0, maximum=20)
    ph = v.req_num(body, "measured_ph", 2, exclusive_min=0, maximum=5)
    rot_pct = v.req_num(body, "measured_rot_pct", 1, minimum=0, maximum=100)

    contract = find("contracts", visit["contract_id"])
    contract_writable(contract)
    if visit["status"] != "SCHEDULED":
        fail("ERR_VALIDATION",
             "The sampling visit is '%s' and can no longer be recorded."
             % visit["status"])

    spec = find("specs", contract["quality_spec_id"])
    visit["measured_brix"] = brix
    visit["measured_ta_gl"] = ta_gl
    visit["measured_ph"] = ph
    visit["measured_rot_pct"] = rot_pct
    visit["sampled_at"] = CLOCK.now
    visit["maturity_flag"] = ("PICK_READY" if brix >= D(spec["min_brix_pick_call"])
                              else "IMMATURE")
    visit["status"] = "COMPLETED"
    touch(visit)

    block = find("blocks", visit["block_id"])
    touch(block)
    return respond(derive.visit_json(visit))


@bp.get("/grower-relations/sampling-visits/<visit_id>")
def get_visit(visit_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         QUALITY_LAB_TECH, GROWER)
    visit = find("visits", visit_id)
    contract = find("contracts", visit["contract_id"])
    own(user_id, role, contract["grower_id"])
    return respond(derive.visit_json(visit))


@bp.get("/grower-relations/sampling-visits")
def list_visits():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, QUALITY_LAB_TECH)
    limit, offset = v.pagination()
    contract_id = v.filt("contract_id")
    block_id = v.filt("block_id")
    crew_id = v.filt("crew_id")
    status = v.filt("status")
    maturity_flag = v.filt("maturity_flag")
    items = rows("visits")
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if block_id is not None:
        items = [r for r in items if r["block_id"] == block_id]
    if crew_id is not None:
        items = [r for r in items if r["crew_id"] == crew_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if maturity_flag is not None:
        items = [r for r in items if r["maturity_flag"] == maturity_flag]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.visit_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Pick calls
# --------------------------------------------------------------------------
@bp.post("/grower-relations/pick-calls")
def create_pick_call():
    auth(HARVEST_COORDINATOR)
    body = read_body()

    contract_id = v.req_id(body, "contract_id")
    contract = find("contracts", contract_id)
    block_id = v.req_id(body, "block_id")
    block = find("blocks", block_id)

    target_pick_at = v.req_dt(body, "target_pick_at")
    estimated_tons = v.req_num(body, "estimated_tons", 3, exclusive_min=0)

    # rank 20
    contract_in(contract, ("ACTIVE",))
    # rank 31
    not_suspended(find("growers", contract["grower_id"]))

    # rank 32 -- the maturity gate comes before scheduling is considered
    spec = find("specs", contract["quality_spec_id"])
    pick_ready = False
    for visit in rows("visits"):
        if visit["contract_id"] != contract["id"] or visit["block_id"] != block["id"]:
            continue
        if visit["status"] != "COMPLETED" or visit["maturity_flag"] != "PICK_READY":
            continue
        if D(visit["measured_rot_pct"]) < D(spec["rot_rejection_pct"]):
            pick_ready = True
            break
    if not pick_ready:
        fail("ERR_BLOCK_NOT_PICK_READY",
             "The block has no completed PICK_READY sampling visit within the "
             "rot rejection threshold.")

    # rank 37 -- the notice gate
    if target_pick_at < add_hours(CLOCK.now, int(contract["min_pick_notice_hours"])):
        fail("ERR_INSUFFICIENT_PICK_NOTICE",
             "target_pick_at must be at least %d hours after the current instant."
             % int(contract["min_pick_notice_hours"]))

    # rank 41
    if derive.allocation_for(contract["id"], block["id"]) is None:
        fail("ERR_BLOCK_NOT_ALLOCATED",
             "The block is not allocated to this contract.")

    # rank 43
    if block["grower_id"] != contract["grower_id"] or block["status"] == "RETIRED":
        fail("ERR_BLOCK_GROWER_MISMATCH",
             "The block must belong to the contract's producer and must not be "
             "retired.")

    row = new_record("pick_calls", {
        "contract_id": contract["id"],
        "block_id": block["id"],
        "target_pick_at": target_pick_at,
        "estimated_tons": estimated_tons,
        "issued_at": None,
        "notice_hours": None,
        "ack_deadline_at": None,
        "acknowledged_at": None,
        "revision_count": 0,
        "status": "ISSUED",
    })
    cascades.stamp_issuance(row, contract)
    return respond(derive.pick_call_json(row), 201)


@bp.post("/grower-relations/pick-calls/<pick_call_id>/acknowledge")
def acknowledge_pick_call(pick_call_id):
    user_id, role = auth(GROWER)
    call = find("pick_calls", pick_call_id)
    contract = find("contracts", call["contract_id"])
    own(user_id, role, contract["grower_id"])

    contract_writable(contract)
    if call["status"] != "ISSUED":
        fail("ERR_PICK_CALL_STATE_INVALID",
             "The pick call is '%s' and cannot be acknowledged." % call["status"])
    if call["ack_deadline_at"] is None or not CLOCK.now < call["ack_deadline_at"]:
        fail("ERR_ACK_WINDOW_CLOSED",
             "The acknowledgement window has closed.")

    call["acknowledged_at"] = CLOCK.now
    call["status"] = "ACKNOWLEDGED"
    touch(call)
    return respond(derive.pick_call_json(call))


@bp.post("/grower-relations/pick-calls/<pick_call_id>/revise")
def revise_pick_call(pick_call_id):
    auth(HARVEST_COORDINATOR)
    call = find("pick_calls", pick_call_id)
    body = read_body()
    revised_target = v.req_dt(body, "revised_target_pick_at")
    revised_tons = v.opt_num(body, "revised_estimated_tons", 3, exclusive_min=0)

    contract = find("contracts", call["contract_id"])
    contract_writable(contract)

    if call["status"] != "ACKNOWLEDGED":
        fail("ERR_PICK_CALL_STATE_INVALID",
             "Only an acknowledged pick call may be revised (it is '%s')."
             % call["status"])
    if int(call["revision_count"]) >= calc.MAX_PICK_CALL_REVISIONS:
        fail("ERR_MAX_PICK_CALL_REVISIONS_EXCEEDED",
             "The pick call has already been revised %d times."
             % calc.MAX_PICK_CALL_REVISIONS)
    if revised_target < add_hours(CLOCK.now, int(contract["min_pick_notice_hours"])):
        fail("ERR_INSUFFICIENT_PICK_NOTICE",
             "revised_target_pick_at must be at least %d hours after the current "
             "instant." % int(contract["min_pick_notice_hours"]))

    call["target_pick_at"] = revised_target
    if revised_tons is not None:
        call["estimated_tons"] = revised_tons
    call["revision_count"] = int(call["revision_count"]) + 1
    call["status"] = "ISSUED"
    cascades.stamp_issuance(call, contract)
    cascades.cancel_scheduled_appointments(call)
    touch(call)
    return respond(derive.pick_call_json(call))


@bp.get("/grower-relations/pick-calls/<pick_call_id>")
def get_pick_call(pick_call_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         SCALE_OPERATOR, GROWER)
    call = find("pick_calls", pick_call_id)
    contract = find("contracts", call["contract_id"])
    own(user_id, role, contract["grower_id"])
    return respond(derive.pick_call_json(call))


@bp.get("/grower-relations/pick-calls")
def list_pick_calls():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, SCALE_OPERATOR)
    limit, offset = v.pagination()
    contract_id = v.filt("contract_id")
    block_id = v.filt("block_id")
    status = v.filt("status")
    items = rows("pick_calls")
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if block_id is not None:
        items = [r for r in items if r["block_id"] == block_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.pick_call_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)


# --------------------------------------------------------------------------
# Delivery appointments
# --------------------------------------------------------------------------
@bp.post("/grower-relations/delivery-appointments")
def create_appointment():
    user_id, role = auth(HARVEST_COORDINATOR, GROWER)
    body = read_body()

    pick_call_id = v.req_id(body, "pick_call_id")
    call = find("pick_calls", pick_call_id)
    contract = find("contracts", call["contract_id"])
    own(user_id, role, contract["grower_id"])

    lane_id = v.req_id(body, "lane_id")
    lane = find("lanes", lane_id)

    window_start = v.req_dt(body, "window_start")
    window_end = v.req_dt(body, "window_end")
    v.window(window_start, window_end)
    planned_tons = v.req_num(body, "planned_tons", 3, exclusive_min=0)

    # rank 20
    contract_writable(contract)
    # rank 21
    if call["status"] != "ACKNOWLEDGED":
        fail("ERR_PICK_CALL_STATE_INVALID",
             "The pick call is '%s'; only an acknowledged call may be served."
             % call["status"])
    # rank 23
    if lane["status"] != "OPEN":
        fail("ERR_LANE_CLOSED", "The crush-pad lane is closed.")
    # rank 31 -- outranks every scheduling question on this endpoint
    not_suspended(find("growers", contract["grower_id"]))

    # rank 33 -- lane exclusivity against the buffered windows
    buffer_minutes = int(lane["turnaround_buffer_minutes"])
    for other in derive.lane_appointments(lane["id"]):
        buffered_start = add_minutes(other["window_start"], -buffer_minutes)
        buffered_end = add_minutes(other["window_end"], buffer_minutes)
        if overlaps(window_start, window_end, buffered_start, buffered_end):
            fail("ERR_LANE_WINDOW_CONFLICT",
                 "The requested window overlaps a buffered appointment on this "
                 "lane.")

    # rank 35 -- the delivery envelope
    target = call["target_pick_at"]
    latest = add_hours(target, calc.DELIVERY_GRACE_HOURS)
    if window_start < target or window_start > latest:
        fail("ERR_APPOINTMENT_OUTSIDE_PICK_WINDOW",
             "window_start must fall between target_pick_at and %d hours after it."
             % calc.DELIVERY_GRACE_HOURS)

    # rank 44 -- the lane's daily tonnage
    day = utc_date(window_start)
    day_total = ZERO3
    for other in derive.lane_appointments(lane["id"]):
        if utc_date(other["window_start"]) == day:
            day_total += D(other["planned_tons"])
    if q3(day_total + planned_tons) > D(lane["daily_capacity_tons"]):
        fail("ERR_LANE_DAILY_CAPACITY_EXCEEDED",
             "The lane's daily capacity for %s would be exceeded." % day.isoformat())

    # rank 45 -- the single-load ceiling
    if planned_tons > D(lane["max_load_tons"]):
        fail("ERR_LOAD_EXCEEDS_LANE_MAX",
             "planned_tons exceeds the lane's max_load_tons.")

    row = new_record("appointments", {
        "pick_call_id": call["id"],
        "lane_id": lane["id"],
        "window_start": window_start,
        "window_end": window_end,
        "planned_tons": planned_tons,
        "status": "SCHEDULED",
    })
    touch(lane)
    touch(call)
    return respond(derive.appointment_json(row), 201)


@bp.post("/grower-relations/delivery-appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    auth(HARVEST_COORDINATOR)
    appointment = find("appointments", appointment_id)
    body = read_body()
    v.free_text(body, "reason")

    call = find("pick_calls", appointment["pick_call_id"])
    contract = find("contracts", call["contract_id"])
    contract_writable(contract)

    if appointment["status"] != "SCHEDULED":
        fail("ERR_APPOINTMENT_NOT_OPEN",
             "The appointment is '%s' and cannot be cancelled."
             % appointment["status"])

    appointment["status"] = "CANCELLED"
    touch(appointment)
    cascades.touch_lane(appointment["lane_id"])
    touch(call)
    return respond(derive.appointment_json(appointment))


@bp.get("/grower-relations/delivery-appointments/<appointment_id>")
def get_appointment(appointment_id):
    user_id, role = auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR,
                         SCALE_OPERATOR, QUALITY_LAB_TECH, GROWER)
    appointment = find("appointments", appointment_id)
    call = find("pick_calls", appointment["pick_call_id"])
    contract = find("contracts", call["contract_id"])
    own(user_id, role, contract["grower_id"])
    return respond(derive.appointment_json(appointment))


@bp.get("/grower-relations/delivery-appointments")
def list_appointments():
    auth(GROWER_RELATIONS_MANAGER, HARVEST_COORDINATOR, SCALE_OPERATOR,
         QUALITY_LAB_TECH)
    limit, offset = v.pagination()
    pick_call_id = v.filt("pick_call_id")
    lane_id = v.filt("lane_id")
    status = v.filt("status")
    items = rows("appointments")
    if pick_call_id is not None:
        items = [r for r in items if r["pick_call_id"] == pick_call_id]
    if lane_id is not None:
        items = [r for r in items if r["lane_id"] == lane_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = by_created_asc(items)
    total = len(items)
    return respond_list([derive.appointment_json(r) for r in v.page(items, limit, offset)],
                        total, limit, offset)
