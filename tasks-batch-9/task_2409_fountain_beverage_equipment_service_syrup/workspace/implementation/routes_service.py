"""Service calls, van dispatch and the van parts ledger (PRD 3.8)."""

from flask import Blueprint, g

from calc import service_call_severity, van_window_overlap
from cascade import release_call_parts
from core import (
    CALL_STATUSES,
    RESOLUTION_CODES,
    SEVERITIES,
    SYMPTOM_CODES,
    Ladder,
    body,
    db,
    endpoint,
    f_dt,
    f_int,
    f_str,
    fail,
    get_call,
    get_unit,
    get_van_stock,
    interval_ok,
    new_id,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    present,
    q_str,
    require,
    require_outlet_ownership,
    sort_rows,
    stamp_new,
    touch,
)
from serialize import ser_call, ser_van_stock

bp = Blueprint("service", __name__)

SERVICEABLE = ("IN_SERVICE", "SERVICE_HOLD")


# ===========================================================================
# Service calls
# ===========================================================================
@bp.post("/service-calls")
@endpoint(["OutletManager", "NetworkAdmin"])
def create_call():
    payload = body()
    # rung 3
    unit_id = f_str(payload, "dispenser_unit_id", required=True)
    reported_raw, reported_at = f_dt(payload, "reported_at", required=True)
    symptom_code = f_str(payload, "symptom_code", required=True, enum=SYMPTOM_CODES)
    # rung 5
    unit = get_unit(unit_id)
    outlet = db.outlets[unit["outlet_id"]]
    # rung 6
    require_outlet_ownership(outlet["id"])
    # rung 10
    require(
        unit["status"] in SERVICEABLE,
        "ERR_UNIT_NOT_SERVICEABLE",
        "The dispenser unit is not serviceable.",
    )
    # rung 20
    require(
        reported_at <= now(),
        "ERR_TIMESTAMP_IN_FUTURE",
        "reported_at must be at or before the logical clock.",
    )

    score, severity = service_call_severity(symptom_code, outlet, unit)
    call = {
        "id": new_id(),
        "dispenser_unit_id": unit["id"],
        "reported_at": reported_raw,
        "_reported_at": reported_at,
        "symptom_code": symptom_code,
        "severity_score": score,
        "severity": severity,
        "status": "OPEN",
        "van_code": None,
        "scheduled_window_start": None,
        "scheduled_window_end": None,
        "_window_start": None,
        "_window_end": None,
        "assigned_tech_user_id": None,
        "reserved_part_stock_id": None,
        "reserved_part_units": 0,
        "consumed_part_units": 0,
        "escalation_count": 0,
        "resolution_code": None,
    }
    stamp_new(call)
    db.calls[call["id"]] = call
    return ok(ser_call(call), 201)


@bp.get("/service-calls/<cid>")
@endpoint(["NetworkAdmin", "ServiceTechnician", "ComplianceOfficer", "OutletManager"])
def read_call(cid):
    return ok(ser_call(get_call(cid)))


@bp.get("/service-calls")
@endpoint(["NetworkAdmin", "ServiceTechnician", "ComplianceOfficer", "OutletManager"])
def list_calls():
    limit, offset = pagination()
    unit_id = q_str("dispenser_unit_id")
    stock_id = q_str("reserved_part_stock_id")
    status = q_str("status", enum=CALL_STATUSES)
    severity = q_str("severity", enum=SEVERITIES)
    rows = list(db.calls.values())
    if unit_id is not None:
        rows = [r for r in rows if r["dispenser_unit_id"] == unit_id]
    if stock_id is not None:
        rows = [r for r in rows if r["reserved_part_stock_id"] == stock_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_call(r) for r in page], limit, offset, total)


@bp.post("/service-calls/<cid>/dispatch")
@endpoint(["ServiceTechnician"])
def dispatch_call(cid):
    payload = body()
    state = {}
    ladder = Ladder()

    def shape():
        state["van_code"] = f_str(payload, "van_code", required=True)
        state["start_raw"], state["start"] = f_dt(payload, "scheduled_window_start", required=True)
        state["end_raw"], state["end"] = f_dt(payload, "scheduled_window_end", required=True)
        state["part_sku"] = f_str(payload, "part_sku")
        state["part_units"] = f_int(payload, "part_units", ge=0)
        if state["part_sku"] is not None and not present(payload, "part_units"):
            fail("ERR_INVALID_REQUEST", "part_units is required when part_sku is supplied.")

    def path_exists():
        state["call"] = get_call(cid)
        state["unit"] = db.units[state["call"]["dispenser_unit_id"]]

    def state_legal():
        call = state["call"]
        require(
            call["status"] in ("OPEN", "ESCALATED"),
            "ERR_INVALID_STATE_TRANSITION",
            "Only an OPEN or ESCALATED call can be dispatched.",
        )
        require(
            call["escalation_count"] <= 2,
            "ERR_INVALID_STATE_TRANSITION",
            "The call has exhausted its escalations.",
        )

    def serviceable():
        require(
            state["unit"]["status"] in SERVICEABLE,
            "ERR_UNIT_NOT_SERVICEABLE",
            "The dispenser unit is not serviceable.",
        )

    def interval():
        interval_ok(state["start"], state["end"])

    def van_clash():
        require(
            not van_window_overlap(
                state["van_code"], state["start"], state["end"], exclude_call_id=state["call"]["id"]
            ),
            "ERR_VAN_WINDOW_CONFLICT",
            "The requested van window collides with another call on this van.",
        )

    def part_on_van():
        if state["part_sku"] is None:
            state["stock"] = None
            return
        matches = [
            row
            for row in db.van_stocks.values()
            if row["van_code"] == state["van_code"] and row["part_sku"] == state["part_sku"]
        ]
        require(
            len(matches) >= 1,
            "ERR_PART_NOT_ON_VAN",
            "Part %s is not loaded on van %s." % (state["part_sku"], state["van_code"]),
        )
        state["stock"] = matches[0]

    def part_available():
        stock = state.get("stock")
        if stock is None:
            return
        require(
            stock["on_van_units"] >= state["part_units"],
            "ERR_INSUFFICIENT_VAN_PARTS",
            "The van holds fewer than %s units of %s." % (state["part_units"], state["part_sku"]),
        )

    ladder.add(3, shape).add(4, path_exists).add(9, state_legal).add(10, serviceable)
    ladder.add(21, interval).add(24, van_clash).add(25, part_on_van).add(26, part_available)
    ladder.run()

    call = state["call"]
    call["van_code"] = state["van_code"]
    call["scheduled_window_start"] = state["start_raw"]
    call["scheduled_window_end"] = state["end_raw"]
    call["_window_start"] = state["start"]
    call["_window_end"] = state["end"]
    call["assigned_tech_user_id"] = g.user_id
    call["status"] = "DISPATCHED"

    stock = state.get("stock")
    units = state["part_units"] or 0
    if stock is not None and units > 0:
        stock["on_van_units"] = stock["on_van_units"] - units
        stock["reserved_units"] = stock["reserved_units"] + units
        touch(stock)
        call["reserved_part_stock_id"] = stock["id"]
        call["reserved_part_units"] = units
    touch(call)
    return ok(ser_call(call))


@bp.post("/service-calls/<cid>/arrive-on-site")
@endpoint(["ServiceTechnician"])
def arrive_on_site(cid):
    # rung 4
    call = get_call(cid)
    # rung 9
    require(
        call["status"] == "DISPATCHED",
        "ERR_INVALID_STATE_TRANSITION",
        "Only a DISPATCHED call can be arrived at.",
    )
    # rung 11
    require(
        g.user_id == call["assigned_tech_user_id"],
        "ERR_TECHNICIAN_NOT_ASSIGNED",
        "Only the technician holding the dispatch may act on this call.",
    )
    call["status"] = "ON_SITE"
    touch(call)
    return ok(ser_call(call))


@bp.post("/service-calls/<cid>/resolve")
@endpoint(["ServiceTechnician"])
def resolve_call(cid):
    payload = body()
    # rung 3
    resolution_code = f_str(payload, "resolution_code", required=True, enum=RESOLUTION_CODES)
    consumed = f_int(payload, "consumed_part_units", default=0, ge=0)
    # rung 4
    call = get_call(cid)
    # rung 9
    require(
        call["status"] == "ON_SITE",
        "ERR_INVALID_STATE_TRANSITION",
        "Only an ON_SITE call can be resolved.",
    )
    # rung 11
    require(
        g.user_id == call["assigned_tech_user_id"],
        "ERR_TECHNICIAN_NOT_ASSIGNED",
        "Only the technician holding the dispatch may act on this call.",
    )
    # rung 27
    require(
        consumed <= call["reserved_part_units"],
        "ERR_CONSUMED_EXCEEDS_RESERVED",
        "consumed_part_units exceeds the reservation held by this call.",
    )

    held = call["reserved_part_units"]
    stock = db.van_stocks.get(call["reserved_part_stock_id"]) if call["reserved_part_stock_id"] else None
    if stock is not None and held:
        stock["reserved_units"] = max(0, stock["reserved_units"] - held)
        stock["consumed_units"] = stock["consumed_units"] + consumed
        stock["on_van_units"] = stock["on_van_units"] + (held - consumed)
        touch(stock)
    call["consumed_part_units"] = consumed
    call["resolution_code"] = resolution_code
    call["reserved_part_units"] = 0
    call["reserved_part_stock_id"] = None
    call["status"] = "RESOLVED"
    touch(call)
    return ok(ser_call(call))


@bp.post("/service-calls/<cid>/escalate")
@endpoint(["ServiceTechnician"])
def escalate_call(cid):
    payload = body()
    # rung 3
    f_str(payload, "escalation_reason_code", required=True)
    # rung 4
    call = get_call(cid)
    # rung 9
    require(
        call["status"] == "ON_SITE",
        "ERR_INVALID_STATE_TRANSITION",
        "Only an ON_SITE call can be escalated.",
    )
    # rung 11
    require(
        g.user_id == call["assigned_tech_user_id"],
        "ERR_TECHNICIAN_NOT_ASSIGNED",
        "Only the technician holding the dispatch may act on this call.",
    )
    # rung 12
    require(
        call["escalation_count"] < 2,
        "ERR_ESCALATION_LIMIT_REACHED",
        "This call has already been escalated twice.",
    )

    release_call_parts(call)
    call["escalation_count"] = call["escalation_count"] + 1
    call["van_code"] = None
    call["scheduled_window_start"] = None
    call["scheduled_window_end"] = None
    call["_window_start"] = None
    call["_window_end"] = None
    call["assigned_tech_user_id"] = None
    call["status"] = "ESCALATED"
    touch(call)
    return ok(ser_call(call))


@bp.post("/service-calls/<cid>/cancel")
@endpoint(["OutletManager", "NetworkAdmin"])
def cancel_call(cid):
    # rung 4
    call = get_call(cid)
    unit = db.units[call["dispenser_unit_id"]]
    # rung 6
    require_outlet_ownership(unit["outlet_id"])
    # rung 9
    require(
        call["status"] in ("OPEN", "DISPATCHED"),
        "ERR_INVALID_STATE_TRANSITION",
        "Only an OPEN or DISPATCHED call can be cancelled.",
    )
    release_call_parts(call)
    call["status"] = "CANCELLED"
    touch(call)
    return ok(ser_call(call))


# ===========================================================================
# Van part stocks
# ===========================================================================
@bp.post("/van-part-stocks")
@endpoint(["NetworkAdmin"])
def create_van_stock():
    payload = body()
    # rung 3
    van_code = f_str(payload, "van_code", required=True)
    part_sku = f_str(payload, "part_sku", required=True)
    on_van_units = f_int(payload, "on_van_units", required=True, ge=0)
    # rung 30
    for row in db.van_stocks.values():
        if row["van_code"] == van_code and row["part_sku"] == part_sku:
            fail("ERR_DUPLICATE_VAN_PART", "This van already carries part %s." % part_sku)

    stock = {
        "id": new_id(),
        "van_code": van_code,
        "part_sku": part_sku,
        "on_van_units": on_van_units,
        "reserved_units": 0,
        "consumed_units": 0,
        "initial_units": on_van_units,
        "restocked_units": 0,
    }
    stamp_new(stock)
    db.van_stocks[stock["id"]] = stock
    return ok(ser_van_stock(stock), 201)


@bp.get("/van-part-stocks/<vid>")
@endpoint(["NetworkAdmin", "ServiceTechnician"])
def read_van_stock(vid):
    return ok(ser_van_stock(get_van_stock(vid)))


@bp.get("/van-part-stocks")
@endpoint(["NetworkAdmin", "ServiceTechnician"])
def list_van_stocks():
    limit, offset = pagination()
    van_code = q_str("van_code")
    part_sku = q_str("part_sku")
    rows = list(db.van_stocks.values())
    if van_code is not None:
        rows = [r for r in rows if r["van_code"] == van_code]
    if part_sku is not None:
        rows = [r for r in rows if r["part_sku"] == part_sku]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_van_stock(r) for r in page], limit, offset, total)


@bp.post("/van-part-stocks/<vid>/restock")
@endpoint(["NetworkAdmin"])
def restock_van_stock(vid):
    payload = body()
    # rung 3
    units = f_int(payload, "units", required=True, ge=0)
    # rung 4
    stock = get_van_stock(vid)
    stock["on_van_units"] = stock["on_van_units"] + units
    stock["restocked_units"] = stock["restocked_units"] + units
    touch(stock)
    return ok(ser_van_stock(stock))
