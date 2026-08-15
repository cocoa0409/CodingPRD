"""Routes: deliveries, degreening rooms/sessions, sort runs, allocation channels."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    DB, D, rhu, f2, cents, now, err, ok_object, ok_list, require_roles, body,
    req_field, as_int, as_num, as_str, as_enum, opt_bool, parse_dt, parse_date,
    paginate, new_entity, touch, get_or_404, sort_asc, STAFF_ROLES,
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_DUPLICATE_ENTITY,
    ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION, ERR_GROVE_QUARANTINED,
    ERR_GROVE_RETIRED, ERR_GROWER_NOT_ACTIVE, ERR_DELIVERY_REGULATORY_HOLD,
    ERR_SEGREGATION_OF_DUTIES, ERR_MATURITY_TEST_REQUIRED,
    ERR_MATURITY_NOT_PASSING, ERR_MATURITY_TEST_EXPIRED,
    ERR_ROOM_CAPACITY_EXCEEDED, ERR_ROOM_NOT_AVAILABLE,
    ERR_DEGREENING_DURATION_OUT_OF_BOUNDS, ERR_DEGREENING_REQUIRED,
    ERR_SORT_BOX_MISMATCH, ERR_SORT_RUN_ALREADY_ACTIVE, ERR_POOL_NOT_ACCEPTING,
    ERR_NO_JUICE_CHANNEL, ERR_ASSIGNMENT_NOT_ACTIVE,
)
from domain import (
    VARIETIES, GRADES, REQUIRES_DEGREENING, GE_WEIGHTS, FRESH_COLOR_MIN,
    FRESH_DEFECT_MAX, CHANNEL_TYPES, DESTINATION_MARKETS, EXPORT_MARKETS,
    grove_posture, maturity_gate, find_open_pool, find_juice_channel,
    recompute_provisional, ser_delivery, ser_room, ser_session, ser_sort_run,
    ser_channel,
)

bp = Blueprint("line", __name__)
ALL_READ = STAFF_ROLES


def _check_delivery_sortable_regulatory(d):
    if d["regulatory_status"] not in {"CLEAR", "RELEASED"}:
        err(
            ERR_DELIVERY_REGULATORY_HOLD,
            422,
            f"Delivery regulatory_status is {d['regulatory_status']}",
        )


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/deliveries")
def create_delivery():
    require_roles(["FieldSupervisor"])
    b = body()
    grove_id = as_str(req_field(b, "grove_id"), "grove_id")
    grove = DB["groves"].get(grove_id)
    if grove is None:
        err(ERR_NOT_FOUND, 404, f"Grove not found: {grove_id}")
    assignment_id = as_str(req_field(b, "assignment_id"), "assignment_id")
    assignment = DB["assignments"].get(assignment_id)
    if assignment is None:
        err(ERR_NOT_FOUND, 404, f"HarvestAssignment not found: {assignment_id}")
    gross = as_int(req_field(b, "gross_boxes"), "gross_boxes")
    tare = as_int(req_field(b, "tare_boxes"), "tare_boxes")
    if gross <= 0:
        err(ERR_INVALID_REQUEST, 400, "gross_boxes must be > 0")
    if tare < 0 or tare >= gross:
        err(ERR_INVALID_REQUEST, 400, "tare_boxes must be >= 0 and < gross_boxes")
    grower = DB["growers"][grove["grower_id"]]
    # tier 7
    if grove_posture(grove) == "QUARANTINED":
        err(ERR_GROVE_QUARANTINED, 422, "Grove is quarantined")
    if grove["lifecycle_status"] != "PRODUCTIVE":
        err(ERR_GROVE_RETIRED, 409, "Grove is RETIRED")
    # tier 8 then 11
    maturity_gate(
        grove, ERR_MATURITY_TEST_REQUIRED, ERR_MATURITY_NOT_PASSING, ERR_MATURITY_TEST_EXPIRED
    )
    # tier 12
    if grower["status"] != "ACTIVE":
        err(ERR_GROWER_NOT_ACTIVE, 409, "Grower is not ACTIVE")
    # tier 13
    if assignment["status"] != "IN_PROGRESS" or assignment["grove_id"] != grove_id:
        err(ERR_ASSIGNMENT_NOT_ACTIVE, 409, "Assignment is not IN_PROGRESS for this grove")
    received_at = now()
    pool = find_open_pool(grove["variety"], received_at)
    if pool is None:
        err(ERR_POOL_NOT_ACCEPTING, 409, "No OPEN pool accepts this delivery")
    d = new_entity()
    d.update(
        grove_id=grove_id,
        assignment_id=assignment_id,
        received_at=received_at,
        variety=grove["variety"],
        gross_boxes=gross,
        tare_boxes=tare,
        net_boxes=gross - tare,
        processing_status="RECEIVED",
        regulatory_status="CLEAR",
        pool_id=pool["id"],
        requires_degreening=grove["variety"] in REQUIRES_DEGREENING,
        hold_cause=None,
    )
    DB["deliveries"][d["id"]] = d
    return ok_object(ser_delivery(d), 201)


@bp.get("/packinghouse/deliveries")
def list_deliveries():
    require_roles(ALL_READ)
    items = sort_asc(DB["deliveries"].values())
    for f in ("grove_id", "assignment_id", "pool_id", "processing_status", "regulatory_status"):
        v = request.args.get(f)
        if v is not None:
            items = [d for d in items if d[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_delivery(d) for d in page], pag)


@bp.get("/packinghouse/deliveries/<rid>")
def get_delivery(rid):
    require_roles(ALL_READ)
    d = get_or_404("deliveries", rid, "Delivery")
    return ok_object(ser_delivery(d))


def _delivery_reg_action(rid, allowed_from, target):
    require_roles(["ComplianceOfficer"])
    d = get_or_404("deliveries", rid, "Delivery")
    if d["regulatory_status"] not in allowed_from:
        err(
            ERR_INVALID_STATE_TRANSITION,
            409,
            f"Delivery regulatory_status {d['regulatory_status']} cannot move to {target}",
        )
    return d


@bp.post("/packinghouse/deliveries/<rid>/hold")
def hold_delivery(rid):
    d = _delivery_reg_action(rid, {"CLEAR"}, "HELD")
    d["regulatory_status"] = "HELD"
    d["hold_cause"] = "manual"
    touch(d)
    return ok_object(ser_delivery(d))


@bp.post("/packinghouse/deliveries/<rid>/release")
def release_delivery(rid):
    d = _delivery_reg_action(rid, {"HELD"}, "RELEASED")
    d["regulatory_status"] = "RELEASED"
    d["hold_cause"] = None
    touch(d)
    return ok_object(ser_delivery(d))


@bp.post("/packinghouse/deliveries/<rid>/condemn")
def condemn_delivery(rid):
    d = _delivery_reg_action(rid, {"HELD"}, "CONDEMNED")
    if d["processing_status"] in {"SORTED", "CLOSED"}:
        err(
            ERR_INVALID_STATE_TRANSITION,
            409,
            "Delivery already SORTED/CLOSED cannot be condemned",
        )
    d["regulatory_status"] = "CONDEMNED"
    d["hold_cause"] = None
    touch(d)
    # auto-void OPEN/VERIFIED sort runs (no pool impact; only POSTED contribute)
    for r in DB["sort_runs"].values():
        if r["delivery_id"] == rid and r["status"] in {"OPEN", "VERIFIED"}:
            r["status"] = "VOIDED"
            touch(r)
    return ok_object(ser_delivery(d))


@bp.post("/packinghouse/deliveries/<rid>/close")
def close_delivery(rid):
    require_roles(["LineOperator"])
    d = get_or_404("deliveries", rid, "Delivery")
    if d["processing_status"] != "SORTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Delivery is not SORTED")
    pool = DB["pools"].get(d["pool_id"])
    if pool is None or pool["status"] not in {"PRICED", "SETTLED"}:
        err(ERR_POOL_NOT_ACCEPTING, 409, "Delivery's pool is not priced yet")
    d["processing_status"] = "CLOSED"
    touch(d)
    return ok_object(ser_delivery(d))


# ---------------------------------------------------------------------------
# Degreening rooms
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/degreening-rooms")
def create_room():
    require_roles(["PackinghouseAdmin"])
    b = body()
    code = as_str(req_field(b, "room_code"), "room_code")
    capacity = as_int(req_field(b, "capacity_boxes"), "capacity_boxes")
    if capacity <= 0:
        err(ERR_INVALID_REQUEST, 400, "capacity_boxes must be > 0")
    min_hours = b.get("min_hours")
    max_hours = b.get("max_hours")
    min_hours = 12 if min_hours is None else as_int(min_hours, "min_hours")
    max_hours = 72 if max_hours is None else as_int(max_hours, "max_hours")
    if min_hours < 0 or max_hours < 0:
        err(ERR_INVALID_REQUEST, 400, "min_hours/max_hours must be >= 0")
    for r in DB["rooms"].values():
        if r["room_code"] == code:
            err(ERR_DUPLICATE_ENTITY, 409, f"room_code already exists: {code}")
    r = new_entity()
    r.update(
        room_code=code,
        capacity_boxes=capacity,
        min_hours=min_hours,
        max_hours=max_hours,
        status="AVAILABLE",
    )
    DB["rooms"][r["id"]] = r
    return ok_object(ser_room(r), 201)


@bp.get("/packinghouse/degreening-rooms")
def list_rooms():
    require_roles(ALL_READ)
    items = sort_asc(DB["rooms"].values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pag = paginate(items)
    return ok_list([ser_room(r) for r in page], pag)


@bp.get("/packinghouse/degreening-rooms/<rid>")
def get_room(rid):
    require_roles(ALL_READ)
    r = get_or_404("rooms", rid, "DegreeningRoom")
    return ok_object(ser_room(r))


@bp.post("/packinghouse/degreening-rooms/<rid>/enter-maintenance")
def enter_maintenance(rid):
    require_roles(["PackinghouseAdmin"])
    r = get_or_404("rooms", rid, "DegreeningRoom")
    if r["status"] != "AVAILABLE":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Room is not AVAILABLE")
    for s in DB["sessions"].values():
        if s["room_id"] == rid and s["status"] == "CONDITIONING":
            err(ERR_ROOM_NOT_AVAILABLE, 409, "Room has CONDITIONING sessions")
    r["status"] = "MAINTENANCE"
    touch(r)
    return ok_object(ser_room(r))


@bp.post("/packinghouse/degreening-rooms/<rid>/exit-maintenance")
def exit_maintenance(rid):
    require_roles(["PackinghouseAdmin"])
    r = get_or_404("rooms", rid, "DegreeningRoom")
    if r["status"] != "MAINTENANCE":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Room is not in MAINTENANCE")
    r["status"] = "AVAILABLE"
    touch(r)
    return ok_object(ser_room(r))


# ---------------------------------------------------------------------------
# Degreening sessions
# ---------------------------------------------------------------------------
def _delivery_sessions(delivery_id):
    return [s for s in DB["sessions"].values() if s["delivery_id"] == delivery_id]


def _maybe_advance_delivery(d):
    """IN_DEGREENING -> READY_TO_SORT when released+aborted boxes reach net."""
    if d["processing_status"] != "IN_DEGREENING":
        return
    done = sum(
        s["boxes"]
        for s in _delivery_sessions(d["id"])
        if s["status"] in {"RELEASED", "ABORTED"}
    )
    if done >= d["net_boxes"]:
        d["processing_status"] = "READY_TO_SORT"
        touch(d)


@bp.post("/packinghouse/degreening-sessions")
def create_session():
    require_roles(["LineOperator"])
    b = body()
    room_id = as_str(req_field(b, "room_id"), "room_id")
    room = DB["rooms"].get(room_id)
    if room is None:
        err(ERR_NOT_FOUND, 404, f"DegreeningRoom not found: {room_id}")
    delivery_id = as_str(req_field(b, "delivery_id"), "delivery_id")
    delivery = DB["deliveries"].get(delivery_id)
    if delivery is None:
        err(ERR_NOT_FOUND, 404, f"Delivery not found: {delivery_id}")
    boxes = as_int(req_field(b, "boxes"), "boxes")
    planned_hours = as_int(req_field(b, "planned_hours"), "planned_hours")
    color_add = opt_bool(b, "color_add_applied", True)
    if boxes <= 0:
        err(ERR_INVALID_REQUEST, 400, "boxes must be > 0")
    if planned_hours <= 0:
        err(ERR_INVALID_REQUEST, 400, "planned_hours must be > 0")
    if room["status"] != "AVAILABLE":
        err(ERR_ROOM_NOT_AVAILABLE, 409, "Room is in MAINTENANCE")
    _check_delivery_sortable_regulatory(delivery)
    # quantity rule: boxes across all of the delivery's sessions <= net_boxes
    existing_total = sum(s["boxes"] for s in _delivery_sessions(delivery_id))
    if existing_total + boxes > delivery["net_boxes"]:
        err(
            ERR_INVALID_REQUEST,
            400,
            "Sum of session boxes would exceed delivery.net_boxes",
        )
    # aggregate-capacity overlap semantics
    start = now()
    end = start + timedelta(hours=planned_hours)
    conditioning = [
        s for s in DB["sessions"].values()
        if s["room_id"] == room_id and s["status"] == "CONDITIONING"
    ]
    candidates = {start}
    for s in conditioning:
        if start < s["started_at"] < end:
            candidates.add(s["started_at"])
    for t in candidates:
        occ = sum(
            s["boxes"]
            for s in conditioning
            if s["started_at"] <= t < s["started_at"] + timedelta(hours=s["planned_hours"])
        )
        if occ + boxes > room["capacity_boxes"]:
            err(ERR_ROOM_CAPACITY_EXCEEDED, 422, "Room aggregate capacity exceeded")
    s = new_entity()
    s.update(
        room_id=room_id,
        delivery_id=delivery_id,
        boxes=boxes,
        planned_hours=planned_hours,
        color_add_applied=color_add,
        started_at=start,
        released_at=None,
        duration_hours=None,
        status="CONDITIONING",
    )
    DB["sessions"][s["id"]] = s
    # first session moves delivery RECEIVED -> IN_DEGREENING
    if delivery["processing_status"] == "RECEIVED":
        delivery["processing_status"] = "IN_DEGREENING"
        touch(delivery)
    return ok_object(ser_session(s), 201)


@bp.get("/packinghouse/degreening-sessions")
def list_sessions():
    require_roles(ALL_READ)
    items = sort_asc(DB["sessions"].values())
    for f in ("room_id", "delivery_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_session(s) for s in page], pag)


@bp.get("/packinghouse/degreening-sessions/<rid>")
def get_session(rid):
    require_roles(ALL_READ)
    s = get_or_404("sessions", rid, "DegreeningSession")
    return ok_object(ser_session(s))


def _elapsed_hours(start, end):
    delta = end - start
    secs = D(delta.days * 86400 + delta.seconds) + D(delta.microseconds) / D(10 ** 6)
    return secs / D(3600)


@bp.post("/packinghouse/degreening-sessions/<rid>/release")
def release_session(rid):
    uid, role = require_roles(["LineOperator", "QualityInspector"])
    s = get_or_404("sessions", rid, "DegreeningSession")
    if s["status"] != "CONDITIONING":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Session is not CONDITIONING")
    delivery = DB["deliveries"][s["delivery_id"]]
    _check_delivery_sortable_regulatory(delivery)
    b = body()
    override = opt_bool(b, "override_approved", False)
    room = DB["rooms"][s["room_id"]]
    released_at = now()
    duration = rhu(_elapsed_hours(s["started_at"], released_at), 2)
    effective_override = role == "QualityInspector" and override
    if not effective_override:
        if duration < D(room["min_hours"]) or duration > D(room["max_hours"]):
            err(
                ERR_DEGREENING_DURATION_OUT_OF_BOUNDS,
                422,
                f"Duration {duration}h outside [{room['min_hours']}, {room['max_hours']}]",
            )
    s["released_at"] = released_at
    s["duration_hours"] = duration
    s["status"] = "RELEASED"
    touch(s)
    _maybe_advance_delivery(delivery)
    return ok_object(ser_session(s))


@bp.post("/packinghouse/degreening-sessions/<rid>/abort")
def abort_session(rid):
    require_roles(["LineOperator"])
    s = get_or_404("sessions", rid, "DegreeningSession")
    if s["status"] != "CONDITIONING":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Session is not CONDITIONING")
    s["status"] = "ABORTED"
    touch(s)
    delivery = DB["deliveries"][s["delivery_id"]]
    _maybe_advance_delivery(delivery)
    return ok_object(ser_session(s))


# ---------------------------------------------------------------------------
# Sort runs
# ---------------------------------------------------------------------------
def compute_ge_boxes(fancy, choice, standard, juice):
    return rhu(
        D(fancy) * GE_WEIGHTS["FANCY"]
        + D(choice) * GE_WEIGHTS["CHOICE"]
        + D(standard) * GE_WEIGHTS["STANDARD"]
        + D(juice) * GE_WEIGHTS["JUICE"],
        2,
    )


@bp.post("/packinghouse/sort-runs")
def create_sort_run():
    uid, _role = require_roles(["LineOperator"])
    b = body()
    delivery_id = as_str(req_field(b, "delivery_id"), "delivery_id")
    delivery = DB["deliveries"].get(delivery_id)
    if delivery is None:
        err(ERR_NOT_FOUND, 404, f"Delivery not found: {delivery_id}")
    grades = {}
    for name in ("fancy_boxes", "choice_boxes", "standard_boxes", "juice_boxes", "cull_boxes"):
        v = as_int(req_field(b, name), name)
        if v < 0:
            err(ERR_INVALID_REQUEST, 400, f"{name} must be >= 0")
        grades[name] = v
    color_score = as_int(req_field(b, "color_score"), "color_score")
    if color_score < 1 or color_score > 10:
        err(ERR_INVALID_REQUEST, 400, "color_score must be in 1..10")
    defect_pct = as_num(req_field(b, "defect_pct"), "defect_pct")
    if D(defect_pct) < 0 or D(defect_pct) > 100:
        err(ERR_INVALID_REQUEST, 400, "defect_pct must be in 0..100")
    expected = as_int(req_field(b, "expected_delivery_version"), "expected_delivery_version")
    # tier 6: state legality, then OCC
    if delivery["processing_status"] not in {"RECEIVED", "READY_TO_SORT"}:
        err(
            ERR_INVALID_STATE_TRANSITION,
            409,
            f"Delivery processing_status {delivery['processing_status']} does not accept sort runs",
        )
    if expected != delivery["version"]:
        err(ERR_STALE_VERSION, 412, "expected_delivery_version is stale")
    # tier 7
    _check_delivery_sortable_regulatory(delivery)
    # tier 9: at most one non-VOIDED run per delivery
    for r in DB["sort_runs"].values():
        if r["delivery_id"] == delivery_id and r["status"] != "VOIDED":
            err(ERR_SORT_RUN_ALREADY_ACTIVE, 409, "Delivery already has a non-VOIDED sort run")
    # tier 10
    total = sum(grades.values())
    if total != delivery["net_boxes"]:
        err(
            ERR_SORT_BOX_MISMATCH,
            422,
            f"Grade boxes sum {total} != delivery.net_boxes {delivery['net_boxes']}",
        )
    # tier 13
    if delivery["requires_degreening"] and delivery["processing_status"] == "RECEIVED":
        err(ERR_DEGREENING_REQUIRED, 422, "Delivery requires degreening before sorting")
    fresh_eligible = (
        color_score >= FRESH_COLOR_MIN
        and D(defect_pct) <= D(FRESH_DEFECT_MAX)
        and delivery["regulatory_status"] in {"CLEAR", "RELEASED"}
    )
    ge = compute_ge_boxes(
        grades["fancy_boxes"], grades["choice_boxes"], grades["standard_boxes"], grades["juice_boxes"]
    )
    r = new_entity()
    r.update(
        delivery_id=delivery_id,
        fancy_boxes=grades["fancy_boxes"],
        choice_boxes=grades["choice_boxes"],
        standard_boxes=grades["standard_boxes"],
        juice_boxes=grades["juice_boxes"],
        cull_boxes=grades["cull_boxes"],
        color_score=color_score,
        defect_pct=defect_pct,
        fresh_eligible=fresh_eligible,
        ge_boxes=ge,
        proceeds_cents=None,
        allocation=None,
        created_by=uid,
        verified_by=None,
        status="OPEN",
    )
    DB["sort_runs"][r["id"]] = r
    # non-degreening variety: RECEIVED -> READY_TO_SORT on run creation
    if not delivery["requires_degreening"] and delivery["processing_status"] == "RECEIVED":
        delivery["processing_status"] = "READY_TO_SORT"
    touch(delivery)  # create-with-supersede bumps the parent's version
    return ok_object(ser_sort_run(r), 201)


@bp.get("/packinghouse/sort-runs")
def list_sort_runs():
    require_roles(ALL_READ)
    items = sort_asc(DB["sort_runs"].values())
    for f in ("delivery_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_sort_run(r) for r in page], pag)


@bp.get("/packinghouse/sort-runs/<rid>")
def get_sort_run(rid):
    require_roles(ALL_READ)
    r = get_or_404("sort_runs", rid, "SortRun")
    return ok_object(ser_sort_run(r))


@bp.post("/packinghouse/sort-runs/<rid>/verify")
def verify_sort_run(rid):
    uid, _role = require_roles(["QualityInspector"])
    r = get_or_404("sort_runs", rid, "SortRun")
    if r["status"] != "OPEN":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Sort run is not OPEN")
    delivery = DB["deliveries"][r["delivery_id"]]
    _check_delivery_sortable_regulatory(delivery)
    if uid == r["created_by"]:
        err(ERR_SEGREGATION_OF_DUTIES, 403, "Verifier must differ from the run's creator")
    r["verified_by"] = uid
    r["status"] = "VERIFIED"
    touch(r)
    return ok_object(ser_sort_run(r))


@bp.post("/packinghouse/sort-runs/<rid>/post")
def post_sort_run(rid):
    require_roles(["LineOperator"])
    r = get_or_404("sort_runs", rid, "SortRun")
    if r["status"] != "VERIFIED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Sort run is not VERIFIED")
    delivery = DB["deliveries"][r["delivery_id"]]
    pool = DB["pools"].get(delivery["pool_id"])
    if delivery["processing_status"] != "READY_TO_SORT":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Delivery is not READY_TO_SORT")
    _check_delivery_sortable_regulatory(delivery)
    if pool is None or pool["status"] != "OPEN":
        err(ERR_POOL_NOT_ACCEPTING, 409, "Delivery's pool is not OPEN")

    # packout_allocation (computed BEFORE any mutation for atomicity)
    alloc_lines = []
    touched_channels = []  # (channel, take_total)
    overflow_fresh = 0
    if r["fresh_eligible"]:
        channels = [
            c
            for c in DB["channels"].values()
            if c["variety"] == delivery["variety"]
            and c["week_start"] == pool["week_start"]
            and c["channel_type"] != "JUICE"
        ]
        channels.sort(key=lambda c: (c["priority_rank"], c["created_at"], c["_seq"]))
        remaining = {
            "FANCY": r["fancy_boxes"],
            "CHOICE": r["choice_boxes"],
            "STANDARD": r["standard_boxes"],
        }
        for ch in channels:
            rem = ch["remaining_boxes"]
            taken_total = 0
            for g in ("FANCY", "CHOICE", "STANDARD"):
                if g in ch["accepts_grades"] and rem > 0 and remaining[g] > 0:
                    take = min(remaining[g], rem)
                    alloc_lines.append({"channel_id": ch["id"], "grade": g, "boxes": take})
                    remaining[g] -= take
                    rem -= take
                    taken_total += take
            if taken_total > 0:
                touched_channels.append((ch, taken_total))
        overflow_fresh = remaining["FANCY"] + remaining["CHOICE"] + remaining["STANDARD"]
    else:
        # juice_forced variant: entire fresh volume diverted at juice price
        overflow_fresh = r["fancy_boxes"] + r["choice_boxes"] + r["standard_boxes"]
    juice_channel = find_juice_channel(delivery["variety"], pool["week_start"])
    if juice_channel is None:
        err(ERR_NO_JUICE_CHANNEL, 422, "No JUICE channel for variety + week")
    juice_total = overflow_fresh + r["juice_boxes"]
    if juice_total > 0:
        alloc_lines.append(
            {"channel_id": juice_channel["id"], "grade": "JUICE", "boxes": juice_total}
        )
    proceeds = 0
    for line in alloc_lines:
        ch = DB["channels"][line["channel_id"]]
        proceeds += line["boxes"] * ch["price_cents_per_box"]
    ge = compute_ge_boxes(r["fancy_boxes"], r["choice_boxes"], r["standard_boxes"], r["juice_boxes"])

    # commit
    r["allocation"] = alloc_lines
    r["ge_boxes"] = ge
    r["proceeds_cents"] = proceeds
    r["status"] = "POSTED"
    touch(r)
    for ch, take in touched_channels:
        ch["remaining_boxes"] -= take
        touch(ch)
    delivery["processing_status"] = "SORTED"
    touch(delivery)
    pool["posted_ge_boxes"] = pool["posted_ge_boxes"] + ge
    pool["posted_proceeds_cents"] += proceeds
    pool["sorted_field_boxes"] += delivery["net_boxes"]
    recompute_provisional(pool)
    touch(pool)
    return ok_object(ser_sort_run(r))


@bp.post("/packinghouse/sort-runs/<rid>/void")
def void_sort_run(rid):
    require_roles(["LineOperator"])
    r = get_or_404("sort_runs", rid, "SortRun")
    if r["status"] not in {"OPEN", "VERIFIED"}:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Only OPEN or VERIFIED runs can be voided")
    r["status"] = "VOIDED"
    touch(r)
    return ok_object(ser_sort_run(r))


@bp.post("/packinghouse/sort-runs/<rid>/reverse")
def reverse_sort_run(rid):
    require_roles(["PoolAccountant"])
    r = get_or_404("sort_runs", rid, "SortRun")
    if r["status"] != "POSTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Only POSTED runs can be reversed")
    delivery = DB["deliveries"][r["delivery_id"]]
    pool = DB["pools"].get(delivery["pool_id"])
    if pool is None or pool["status"] not in {"OPEN", "INTAKE_CLOSED"}:
        err(ERR_POOL_NOT_ACCEPTING, 409, "Pool no longer accepts reversals")
    # exact compensation
    for line in r["allocation"] or []:
        ch = DB["channels"][line["channel_id"]]
        if ch["channel_type"] != "JUICE":
            ch["remaining_boxes"] += line["boxes"]
            touch(ch)
    pool["posted_ge_boxes"] = pool["posted_ge_boxes"] - D(str(r["ge_boxes"]))
    pool["posted_proceeds_cents"] -= r["proceeds_cents"]
    pool["sorted_field_boxes"] -= delivery["net_boxes"]
    recompute_provisional(pool)
    touch(pool)
    delivery["processing_status"] = "READY_TO_SORT"
    touch(delivery)
    r["status"] = "VOIDED"
    touch(r)
    return ok_object(ser_sort_run(r))


# ---------------------------------------------------------------------------
# Allocation channels
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/allocation-channels")
def create_channel():
    require_roles(["PackinghouseAdmin"])
    b = body()
    code = as_str(req_field(b, "channel_code"), "channel_code")
    channel_type = as_enum(req_field(b, "channel_type"), "channel_type", CHANNEL_TYPES)
    dest = as_enum(req_field(b, "destination_market"), "destination_market", DESTINATION_MARKETS)
    variety = as_enum(req_field(b, "variety"), "variety", VARIETIES)
    week_start = parse_date(req_field(b, "week_start"), "week_start")
    allocation_boxes = as_int(req_field(b, "allocation_boxes"), "allocation_boxes")
    if allocation_boxes < 0:
        err(ERR_INVALID_REQUEST, 400, "allocation_boxes must be >= 0")
    price = as_int(req_field(b, "price_cents_per_box"), "price_cents_per_box")
    if price <= 0:
        err(ERR_INVALID_REQUEST, 400, "price_cents_per_box must be > 0")
    priority_rank = as_int(req_field(b, "priority_rank"), "priority_rank")
    accepts = req_field(b, "accepts_grades")
    if not isinstance(accepts, list) or any(
        not isinstance(g, str) or g not in GRADES for g in accepts
    ):
        err(ERR_INVALID_REQUEST, 400, "accepts_grades must be a subset of FANCY/CHOICE/STANDARD/JUICE")
    if len(set(accepts)) != len(accepts):
        err(ERR_INVALID_REQUEST, 400, "accepts_grades contains duplicates")
    # channel_type / destination_market consistency
    if channel_type == "EXPORT" and dest not in EXPORT_MARKETS:
        err(ERR_INVALID_REQUEST, 400, "EXPORT channels require destination_market JAPAN/EU/KOREA")
    if channel_type == "DOMESTIC_FRESH" and dest != "DOMESTIC":
        err(ERR_INVALID_REQUEST, 400, "DOMESTIC_FRESH channels require destination_market DOMESTIC")
    if channel_type == "JUICE" and dest != "NONE":
        err(ERR_INVALID_REQUEST, 400, "JUICE channels require destination_market NONE")
    for c in DB["channels"].values():
        if c["channel_code"] == code:
            err(ERR_DUPLICATE_ENTITY, 409, f"channel_code already exists: {code}")
    c = new_entity()
    c.update(
        channel_code=code,
        channel_type=channel_type,
        destination_market=dest,
        variety=variety,
        week_start=week_start.isoformat(),
        allocation_boxes=allocation_boxes,
        price_cents_per_box=price,
        priority_rank=priority_rank,
        accepts_grades=list(accepts),
        remaining_boxes=None if channel_type == "JUICE" else allocation_boxes,
    )
    DB["channels"][c["id"]] = c
    return ok_object(ser_channel(c), 201)


@bp.get("/packinghouse/allocation-channels")
def list_channels():
    require_roles(ALL_READ)
    items = sort_asc(DB["channels"].values())
    for f in ("variety", "week_start", "channel_type"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_channel(c) for c in page], pag)


@bp.get("/packinghouse/allocation-channels/<rid>")
def get_channel(rid):
    require_roles(ALL_READ)
    c = get_or_404("channels", rid, "AllocationChannel")
    return ok_object(ser_channel(c))
