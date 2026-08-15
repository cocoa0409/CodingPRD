"""Routes: clock, growers, groves, maturity tests, crews, harvest assignments."""
import math
from datetime import timedelta

from flask import Blueprint, request

from core import (
    DB, CLOCK, D, now, iso_ms, err, ok_object, ok_list, require_roles, body,
    req_field, as_int, as_num, as_str, as_bool, as_enum, opt_bool, parse_dt,
    parse_date, paginate, new_entity, touch, get_or_404, sort_asc, sort_desc,
    STAFF_ROLES,
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_DUPLICATE_ENTITY,
    ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION, ERR_GROVE_QUARANTINED,
    ERR_GROVE_RETIRED, ERR_GROWER_NOT_ACTIVE, ERR_GROWER_OWNERSHIP_MISMATCH,
    ERR_MATURITY_TEST_REQUIRED, ERR_MATURITY_NOT_PASSING, ERR_MATURITY_TEST_EXPIRED,
    ERR_ASSIGNMENT_WINDOW_NOT_OPEN, ERR_CREW_WINDOW_OVERLAP,
    ERR_CREW_CAPACITY_EXCEEDED, ERR_CREW_NOT_ACTIVE,
)
from domain import (
    VARIETIES, VARIETY_MINIMUMS, MATURITY_VALIDITY_HOURS, grove_posture,
    current_maturity_test, maturity_gate, ser_grower, ser_grove,
    ser_maturity_test, ser_crew, ser_assignment,
)
from core import rhu

bp = Blueprint("core1", __name__)

ALL_READ = STAFF_ROLES  # six staff roles


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/_clock/set_current_utc")
def set_clock():
    require_roles(["PackinghouseAdmin"])
    b = body()
    dt = parse_dt(req_field(b, "to_iso8601"), "to_iso8601")
    CLOCK["now"] = dt
    return ok_object({"current_utc": iso_ms(dt)}, 200)


# ---------------------------------------------------------------------------
# Growers
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/growers")
def create_grower():
    require_roles(["PackinghouseAdmin"])
    b = body()
    code = as_str(req_field(b, "grower_code"), "grower_code")
    name = as_str(req_field(b, "display_name"), "display_name")
    for g in DB["growers"].values():
        if g["grower_code"] == code:
            err(ERR_DUPLICATE_ENTITY, 409, f"grower_code already exists: {code}")
    g = new_entity()
    g.update(
        grower_code=code,
        display_name=name,
        status="ACTIVE",
        advance_outstanding_cents=0,
        caretaking_balance_cents=0,
    )
    DB["growers"][g["id"]] = g
    return ok_object(ser_grower(g), 201)


@bp.get("/packinghouse/growers")
def list_growers():
    require_roles(ALL_READ)
    items = sort_asc(DB["growers"].values())
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, pag = paginate(items)
    return ok_list([ser_grower(g) for g in page], pag)


@bp.get("/packinghouse/growers/<rid>")
def get_grower(rid):
    uid, role = require_roles(ALL_READ + ["Grower"])
    if role == "Grower" and uid != rid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may only read its own record")
    g = get_or_404("growers", rid, "Grower")
    return ok_object(ser_grower(g))


def _grower_action(rid, allowed_from, target):
    require_roles(["PoolAccountant"])
    g = get_or_404("growers", rid, "Grower")
    if g["status"] not in allowed_from:
        err(
            ERR_INVALID_STATE_TRANSITION,
            409,
            f"Grower in status {g['status']} cannot transition to {target}",
        )
    return g


@bp.post("/packinghouse/growers/<rid>/suspend")
def suspend_grower(rid):
    g = _grower_action(rid, {"ACTIVE"}, "SUSPENDED")
    g["status"] = "SUSPENDED"
    touch(g)
    return ok_object(ser_grower(g))


@bp.post("/packinghouse/growers/<rid>/reinstate")
def reinstate_grower(rid):
    g = _grower_action(rid, {"SUSPENDED"}, "ACTIVE")
    g["status"] = "ACTIVE"
    touch(g)
    return ok_object(ser_grower(g))


def cancel_grower_open_ct_orders(grower_id):
    grove_ids = {gr["id"] for gr in DB["groves"].values() if gr["grower_id"] == grower_id}
    for o in DB["ct_orders"].values():
        if o["grove_id"] in grove_ids and o["status"] in {"REQUESTED", "SCHEDULED"}:
            o["status"] = "CANCELLED"
            touch(o)


@bp.post("/packinghouse/growers/<rid>/terminate")
def terminate_grower(rid):
    g = _grower_action(rid, {"ACTIVE", "SUSPENDED"}, "TERMINATED")
    if g["advance_outstanding_cents"] != 0 or g["caretaking_balance_cents"] != 0:
        err(
            ERR_GROWER_NOT_ACTIVE,
            409,
            "Grower has outstanding advances or caretaking balance",
        )
    g["status"] = "TERMINATED"
    touch(g)
    cancel_grower_open_ct_orders(g["id"])
    return ok_object(ser_grower(g))


# ---------------------------------------------------------------------------
# Groves
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/groves")
def create_grove():
    require_roles(["PackinghouseAdmin"])
    b = body()
    grower_id = as_str(req_field(b, "grower_id"), "grower_id")
    grower = DB["growers"].get(grower_id)
    if grower is None:
        err(ERR_NOT_FOUND, 404, f"Grower not found: {grower_id}")
    block_code = as_str(req_field(b, "block_code"), "block_code")
    variety = as_enum(req_field(b, "variety"), "variety", VARIETIES)
    acreage = as_num(req_field(b, "acreage"), "acreage")
    if D(acreage) <= 0:
        err(ERR_INVALID_REQUEST, 400, "acreage must be > 0")
    county_code = as_str(req_field(b, "county_code"), "county_code")
    enrolled = opt_bool(b, "caretaking_enrolled", False)
    for g in DB["groves"].values():
        if g["grower_id"] == grower_id and g["block_code"] == block_code:
            err(
                ERR_DUPLICATE_ENTITY,
                409,
                f"block_code already exists for grower: {block_code}",
            )
    g = new_entity()
    g.update(
        grower_id=grower_id,
        block_code=block_code,
        variety=variety,
        acreage=acreage,
        county_code=county_code,
        caretaking_enrolled=enrolled,
        lifecycle_status="PRODUCTIVE",
    )
    DB["groves"][g["id"]] = g
    return ok_object(ser_grove(g), 201)


def _grower_scope_groves(items, role, uid):
    if role == "Grower":
        items = [g for g in items if g["grower_id"] == uid]
    return items


@bp.get("/packinghouse/groves")
def list_groves():
    uid, role = require_roles(ALL_READ + ["Grower"])
    items = sort_asc(DB["groves"].values())
    items = _grower_scope_groves(items, role, uid)
    for f in ("grower_id", "variety", "lifecycle_status"):
        v = request.args.get(f)
        if v is not None:
            items = [g for g in items if g[f] == v]
    qp = request.args.get("quarantine_posture")
    if qp is not None:
        items = [g for g in items if grove_posture(g) == qp]
    page, pag = paginate(items)
    return ok_list([ser_grove(g) for g in page], pag)


@bp.get("/packinghouse/groves/<rid>")
def get_grove(rid):
    uid, role = require_roles(ALL_READ + ["Grower"])
    g = get_or_404("groves", rid, "Grove")
    if role == "Grower" and g["grower_id"] != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may only read its own groves")
    return ok_object(ser_grove(g))


@bp.post("/packinghouse/groves/<rid>/retire")
def retire_grove(rid):
    require_roles(["PackinghouseAdmin"])
    g = get_or_404("groves", rid, "Grove")
    if g["lifecycle_status"] != "PRODUCTIVE":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Grove is already RETIRED")
    for a in DB["assignments"].values():
        if a["grove_id"] == rid and a["status"] in {"SCHEDULED", "IN_PROGRESS"}:
            err(
                ERR_INVALID_STATE_TRANSITION,
                409,
                "Grove has harvest assignments in SCHEDULED or IN_PROGRESS",
            )
    for d in DB["deliveries"].values():
        if d["grove_id"] == rid and d["processing_status"] in {
            "RECEIVED",
            "IN_DEGREENING",
            "READY_TO_SORT",
        }:
            err(
                ERR_INVALID_STATE_TRANSITION,
                409,
                "Grove has deliveries still being processed",
            )
    g["lifecycle_status"] = "RETIRED"
    touch(g)
    for o in DB["ct_orders"].values():
        if o["grove_id"] == rid and o["status"] in {"REQUESTED", "SCHEDULED"}:
            o["status"] = "CANCELLED"
            touch(o)
    return ok_object(ser_grove(g))


# ---------------------------------------------------------------------------
# Maturity tests
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/groves/<grove_id>/maturity-tests")
def create_maturity_test(grove_id):
    require_roles(["QualityInspector"])
    grove = get_or_404("groves", grove_id, "Grove")
    b = body()
    sampled_at = parse_dt(req_field(b, "sampled_at"), "sampled_at")
    brix = as_num(req_field(b, "brix"), "brix")
    acid_pct = as_num(req_field(b, "acid_pct"), "acid_pct")
    juice_pct = as_num(req_field(b, "juice_pct"), "juice_pct")
    if D(brix) <= 0:
        err(ERR_INVALID_REQUEST, 400, "brix must be > 0")
    if D(acid_pct) <= 0:
        err(ERR_INVALID_REQUEST, 400, "acid_pct must be > 0")
    if D(juice_pct) <= 0 or D(juice_pct) > 100:
        err(ERR_INVALID_REQUEST, 400, "juice_pct must be in (0, 100]")
    expected = as_int(req_field(b, "expected_grove_version"), "expected_grove_version")
    if expected != grove["version"]:
        err(ERR_STALE_VERSION, 412, "expected_grove_version is stale")

    # maturity_evaluation: round FIRST, compare SECOND
    ratio = rhu(D(brix) / D(acid_pct), 2)
    mins = VARIETY_MINIMUMS[grove["variety"]]
    result = (
        "PASS"
        if (
            ratio >= mins["min_ratio"]
            and D(brix) >= mins["min_brix"]
            and D(juice_pct) >= mins["min_juice"]
        )
        else "FAIL"
    )
    expires_at = sampled_at + timedelta(hours=MATURITY_VALIDITY_HOURS)

    prior = current_maturity_test(grove_id)
    t = new_entity()
    t.update(
        grove_id=grove_id,
        sampled_at=sampled_at,
        brix=brix,
        acid_pct=acid_pct,
        juice_pct=juice_pct,
        ratio=ratio,
        result=result,
        status="CURRENT",
        expires_at=expires_at,
    )
    DB["maturity_tests"][t["id"]] = t
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    touch(grove)
    return ok_object(ser_maturity_test(t), 201)


@bp.get("/packinghouse/groves/<rid>/maturity-tests")
def list_maturity_tests(rid):
    require_roles(ALL_READ)
    get_or_404("groves", rid, "Grove")
    items = [t for t in DB["maturity_tests"].values() if t["grove_id"] == rid]
    items = sort_desc(items)  # newest first (overrides default ascending sort)
    page, pag = paginate(items)
    return ok_list([ser_maturity_test(t) for t in page], pag)


@bp.get("/packinghouse/maturity-tests/<rid>")
def get_maturity_test(rid):
    require_roles(ALL_READ)
    t = get_or_404("maturity_tests", rid, "MaturityTest")
    return ok_object(ser_maturity_test(t))


# ---------------------------------------------------------------------------
# Harvest crews
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/crews")
def create_crew():
    require_roles(["PackinghouseAdmin"])
    b = body()
    code = as_str(req_field(b, "crew_code"), "crew_code")
    capacity = as_int(req_field(b, "daily_capacity_boxes"), "daily_capacity_boxes")
    if capacity <= 0:
        err(ERR_INVALID_REQUEST, 400, "daily_capacity_boxes must be > 0")
    for c in DB["crews"].values():
        if c["crew_code"] == code:
            err(ERR_DUPLICATE_ENTITY, 409, f"crew_code already exists: {code}")
    c = new_entity()
    c.update(crew_code=code, daily_capacity_boxes=capacity, status="ACTIVE")
    DB["crews"][c["id"]] = c
    return ok_object(ser_crew(c), 201)


@bp.get("/packinghouse/crews")
def list_crews():
    require_roles(ALL_READ)
    items = sort_asc(DB["crews"].values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, pag = paginate(items)
    return ok_list([ser_crew(c) for c in page], pag)


@bp.get("/packinghouse/crews/<rid>")
def get_crew(rid):
    require_roles(ALL_READ)
    c = get_or_404("crews", rid, "HarvestCrew")
    return ok_object(ser_crew(c))


@bp.post("/packinghouse/crews/<rid>/deactivate")
def deactivate_crew(rid):
    require_roles(["PackinghouseAdmin"])
    c = get_or_404("crews", rid, "HarvestCrew")
    if c["status"] != "ACTIVE":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Crew is already INACTIVE")
    for a in DB["assignments"].values():
        if a["crew_id"] == rid and a["status"] in {"SCHEDULED", "IN_PROGRESS"}:
            err(
                ERR_INVALID_STATE_TRANSITION,
                409,
                "Crew has assignments in SCHEDULED or IN_PROGRESS",
            )
    c["status"] = "INACTIVE"
    touch(c)
    return ok_object(ser_crew(c))


# ---------------------------------------------------------------------------
# Harvest assignments
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/harvest-assignments")
def create_assignment():
    require_roles(["FieldSupervisor"])
    b = body()
    crew_id = as_str(req_field(b, "crew_id"), "crew_id")
    crew = DB["crews"].get(crew_id)
    if crew is None:
        err(ERR_NOT_FOUND, 404, f"HarvestCrew not found: {crew_id}")
    grove_id = as_str(req_field(b, "grove_id"), "grove_id")
    grove = DB["groves"].get(grove_id)
    if grove is None:
        err(ERR_NOT_FOUND, 404, f"Grove not found: {grove_id}")
    ws = parse_dt(req_field(b, "window_start"), "window_start")
    we = parse_dt(req_field(b, "window_end"), "window_end")
    planned = as_int(req_field(b, "planned_boxes"), "planned_boxes")
    if planned <= 0:
        err(ERR_INVALID_REQUEST, 400, "planned_boxes must be > 0")
    if we <= ws:
        err(ERR_INVALID_REQUEST, 400, "window_end must be after window_start")
    # tier 7: regulatory/safety gates
    if grove_posture(grove) == "QUARANTINED":
        err(ERR_GROVE_QUARANTINED, 422, "Grove is quarantined")
    if grove["lifecycle_status"] != "PRODUCTIVE":
        err(ERR_GROVE_RETIRED, 409, "Grove is RETIRED")
    if crew["status"] != "ACTIVE":
        err(ERR_CREW_NOT_ACTIVE, 409, "Crew is INACTIVE")
    # tier 10: capacity then overlap
    window_days = math.ceil((we - ws).total_seconds() / 86400)
    if planned > crew["daily_capacity_boxes"] * window_days:
        err(ERR_CREW_CAPACITY_EXCEEDED, 422, "planned_boxes exceeds crew window capacity")
    for a in DB["assignments"].values():
        if a["crew_id"] != crew_id or a["status"] not in {"SCHEDULED", "IN_PROGRESS"}:
            continue
        if ws < a["window_end"] and a["window_start"] < we:
            err(ERR_CREW_WINDOW_OVERLAP, 409, "Crew window overlaps an existing assignment")
    a = new_entity()
    a.update(
        crew_id=crew_id,
        grove_id=grove_id,
        window_start=ws,
        window_end=we,
        planned_boxes=planned,
        actual_boxes=None,
        status="SCHEDULED",
    )
    DB["assignments"][a["id"]] = a
    return ok_object(ser_assignment(a), 201)


@bp.get("/packinghouse/harvest-assignments")
def list_assignments():
    require_roles(ALL_READ)
    items = sort_asc(DB["assignments"].values())
    for f in ("crew_id", "grove_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_assignment(a) for a in page], pag)


@bp.get("/packinghouse/harvest-assignments/<rid>")
def get_assignment(rid):
    require_roles(ALL_READ)
    a = get_or_404("assignments", rid, "HarvestAssignment")
    return ok_object(ser_assignment(a))


@bp.post("/packinghouse/harvest-assignments/<rid>/start")
def start_assignment(rid):
    require_roles(["FieldSupervisor"])
    a = get_or_404("assignments", rid, "HarvestAssignment")
    if a["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Assignment is not SCHEDULED")
    crew = DB["crews"][a["crew_id"]]
    grove = DB["groves"][a["grove_id"]]
    if grove_posture(grove) == "QUARANTINED":
        err(ERR_GROVE_QUARANTINED, 422, "Grove is quarantined")
    if grove["lifecycle_status"] != "PRODUCTIVE":
        err(ERR_GROVE_RETIRED, 409, "Grove is RETIRED")
    if crew["status"] != "ACTIVE":
        err(ERR_CREW_NOT_ACTIVE, 409, "Crew is INACTIVE")
    maturity_gate(
        grove, ERR_MATURITY_TEST_REQUIRED, ERR_MATURITY_NOT_PASSING, ERR_MATURITY_TEST_EXPIRED
    )
    if not (a["window_start"] <= now() < a["window_end"]):
        err(ERR_ASSIGNMENT_WINDOW_NOT_OPEN, 422, "Assignment window is not open")
    a["status"] = "IN_PROGRESS"
    touch(a)
    return ok_object(ser_assignment(a))


@bp.post("/packinghouse/harvest-assignments/<rid>/complete")
def complete_assignment(rid):
    require_roles(["FieldSupervisor"])
    a = get_or_404("assignments", rid, "HarvestAssignment")
    if a["status"] != "IN_PROGRESS":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Assignment is not IN_PROGRESS")
    b = body()
    actual = as_int(req_field(b, "actual_boxes"), "actual_boxes")
    max_allowed = (a["planned_boxes"] * 5 + 3) // 4  # ceil(planned * 1.25)
    if actual < 1 or actual > max_allowed:
        err(
            ERR_INVALID_REQUEST,
            400,
            f"actual_boxes must be between 1 and {max_allowed}",
        )
    a["actual_boxes"] = actual
    a["status"] = "COMPLETED"
    touch(a)
    return ok_object(ser_assignment(a))


@bp.post("/packinghouse/harvest-assignments/<rid>/cancel")
def cancel_assignment(rid):
    require_roles(["FieldSupervisor"])
    a = get_or_404("assignments", rid, "HarvestAssignment")
    if a["status"] == "SCHEDULED":
        pass
    elif a["status"] == "IN_PROGRESS":
        for d in DB["deliveries"].values():
            if d["assignment_id"] == rid:
                err(
                    ERR_INVALID_STATE_TRANSITION,
                    409,
                    "Assignment is referenced by a delivery",
                )
    else:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Assignment cannot be cancelled")
    a["status"] = "CANCELLED"
    touch(a)
    return ok_object(ser_assignment(a))
