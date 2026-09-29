"""Test bays and factory acceptance tests (PRD 3.5)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import BOOLEAN, DATETIME, INTEGER, NUMBER, STRING, f

bp = Blueprint("tests", __name__)

BAY_STATUSES = ["AVAILABLE", "MAINTENANCE", "DECOMMISSIONED"]


# --------------------------------------------------------------------------- #
# test bays
# --------------------------------------------------------------------------- #

@bp.route("/test-bays", methods=["POST"])
def create_bay():
    rbac.authenticate("POST /test-bays")
    payload = validation.body()
    data = validation.validate(payload, [
        f("bay_code", STRING, required=True),
        f("max_kv", NUMBER, required=True),
        f("changeover_buffer_hours", INTEGER, minimum=0, maximum=24, default=4),
        f("supports_impulse", BOOLEAN, default=False),
    ])
    if data["max_kv"] <= 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "max_kv must be greater than zero")
    for b in store.all_rows("bay"):
        if b.get("bay_code") == data["bay_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "bay_code already exists")
    bay = dict(data)
    bay["status"] = "AVAILABLE"
    bay["scheduled_hours_total"] = 0
    store.insert("bay", bay)
    return envelope.created(store.public(bay))


@bp.route("/test-bays", methods=["GET"])
def list_bays():
    rbac.authenticate("GET /test-bays")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("bay"), {
        "status": common.qstr("status"),
        "supports_impulse": common.qbool("supports_impulse"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/test-bays/<bid>", methods=["GET"])
def get_bay(bid):
    rbac.authenticate("GET /test-bays/{id}")
    return envelope.ok(store.public(common.resolve("bay", bid)))


@bp.route("/test-bays/<bid>", methods=["PATCH"])
def patch_bay(bid):
    rbac.authenticate("PATCH /test-bays/{id}")
    bay = common.resolve("bay", bid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("status", STRING, enum=BAY_STATUSES),
        f("max_kv", NUMBER),
        f("changeover_buffer_hours", INTEGER, minimum=0, maximum=24),
        f("supports_impulse", BOOLEAN),
    ])
    if "max_kv" in data and data["max_kv"] <= 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE", "max_kv must be greater than zero")
    for key in ("status", "max_kv", "changeover_buffer_hours", "supports_impulse"):
        if key in data:
            bay[key] = data[key]
    store.touch("bay", bay)
    return envelope.ok(store.public(bay))


@bp.route("/test-bays/<bid>/schedule", methods=["GET"])
def bay_schedule(bid):
    rbac.authenticate("GET /test-bays/{id}/schedule")
    common.resolve("bay", bid)
    limit, offset = envelope.pagination()
    rows = [t for t in store.where("fat", test_bay_id=bid)
            if t.get("status") in calc.OCCUPYING_STATES]
    return envelope.listing(store.public_list(rows), limit, offset)


# --------------------------------------------------------------------------- #
# factory acceptance tests
# --------------------------------------------------------------------------- #

@bp.route("/factory-acceptance-tests", methods=["POST"])
def create_fat():
    rbac.authenticate("POST /factory-acceptance-tests")
    payload = validation.body()
    order = common.resolve_body_ref("order", payload, "engineered_order_id")
    predecessor = None
    if payload.get("retest_of_fat_id") is not None:
        predecessor = common.resolve_body_ref("fat", payload, "retest_of_fat_id")
    data = validation.validate(payload, [
        f("engineered_order_id", STRING, required=True),
        f("test_duration_hours", INTEGER, required=True, minimum=1, maximum=120),
        f("witness_required", BOOLEAN, default=True),
        f("requires_impulse", BOOLEAN, default=False),
        f("retest_of_fat_id", STRING),
    ])
    common.check_order_not_cancelled(order)
    attempt = 1
    if predecessor is not None:
        if predecessor.get("status") != "FAILED" \
                or predecessor.get("engineered_order_id") != order["id"]:
            raise ApiError("ERR_RETEST_PREDECESSOR_NOT_FAILED",
                           "retest_of_fat_id must name a FAILED test on the same order")
        for other in store.where("fat", engineered_order_id=order["id"]):
            if other["id"] == predecessor["id"]:
                continue
            if other.get("status") not in ("PASSED", "ABANDONED"):
                raise ApiError("ERR_RETEST_PREDECESSOR_NOT_FAILED",
                               "another non-terminal test already exists on the order")
        attempt = (predecessor.get("attempt_number") or 1) + 1
    fat = {
        "engineered_order_id": order["id"],
        "test_bay_id": None,
        "retest_of_fat_id": predecessor["id"] if predecessor is not None else None,
        "attempt_number": attempt,
        "status": "REQUESTED",
        "window_start_at": None,
        "test_duration_hours": data["test_duration_hours"],
        "window_end_at": None,
        "witness_required": data["witness_required"],
        "confirmed_witness_count": 0,
        "requires_impulse": data["requires_impulse"],
        "run_by_user_id": None,
        "started_at": None,
        "concluded_at": None,
    }
    store.insert("fat", fat)
    if predecessor is not None:
        predecessor["status"] = "ABANDONED"
        store.touch("fat", predecessor)
        bay = store.get("bay", predecessor.get("test_bay_id"))
        if bay is not None:
            calc.refresh_bay_hours(bay)
            store.touch("bay", bay)
    posture.refresh(order)
    return envelope.created(store.public(fat))


@bp.route("/factory-acceptance-tests", methods=["GET"])
def list_fats():
    rbac.authenticate("GET /factory-acceptance-tests")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("fat"), {
        "engineered_order_id": common.qstr("engineered_order_id"),
        "test_bay_id": common.qstr("test_bay_id"),
        "retest_of_fat_id": common.qstr("retest_of_fat_id"),
        "status": common.qstr("status"),
        "witness_required": common.qbool("witness_required"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/factory-acceptance-tests/<fid>", methods=["GET"])
def get_fat(fid):
    rbac.authenticate("GET /factory-acceptance-tests/{id}")
    return envelope.ok(store.public(common.resolve("fat", fid)))


@bp.route("/factory-acceptance-tests/<fid>/schedule", methods=["POST"])
def schedule_fat(fid):
    rbac.authenticate("POST /factory-acceptance-tests/{id}/schedule")
    fat = common.resolve("fat", fid)
    order = common.resolve("order", fat.get("engineered_order_id"))
    payload = validation.body()
    bay = common.resolve_body_ref("bay", payload, "test_bay_id")
    data = validation.validate(payload, [
        f("test_bay_id", STRING, required=True),
        f("window_start_at", DATETIME, required=True),
    ])
    common.check_state("fat", fat, ("REQUESTED",))
    common.check_order_not_cancelled(order)
    common.check_order_fulfillment(order, ("IN_PRODUCTION", "FAT_COMPLETE"))
    if (order.get("rated_kv") or 0) > (bay.get("max_kv") or 0):
        raise ApiError("ERR_BAY_KV_INSUFFICIENT",
                       "the order's rated_kv exceeds the bay's max_kv")
    if fat.get("requires_impulse") and not bay.get("supports_impulse"):
        raise ApiError("ERR_BAY_IMPULSE_UNSUPPORTED", "the bay cannot run impulse tests")
    if bay.get("status") != "AVAILABLE":
        raise ApiError("ERR_BAY_UNAVAILABLE", "the bay is %s" % bay.get("status"))
    start = clock.sec(clock.parse(data["window_start_at"]))
    end = clock.sec(calc.window_end(start, fat.get("test_duration_hours"),
                                    bay.get("changeover_buffer_hours")))
    for other_start, other_end, other in calc.bay_windows(bay["id"], exclude_fat_id=fid):
        if calc.windows_conflict(start, end, other_start, other_end):
            raise ApiError("ERR_BAY_WINDOW_CONFLICT",
                           "the window overlaps test %s" % other["id"])
    if end <= start:
        raise ApiError("ERR_TEST_WINDOW_INVALID", "window_end_at must be after window_start_at")

    fat["test_bay_id"] = bay["id"]
    fat["window_start_at"] = data["window_start_at"]
    fat["window_end_at"] = clock.fmt(end)
    fat["status"] = "BAY_SCHEDULED"
    store.touch("fat", fat)
    calc.refresh_bay_hours(bay)
    store.touch("bay", bay)
    if (fat.get("attempt_number") or 1) > 1 and order.get("fulfillment_status") == "FAT_COMPLETE":
        order["fulfillment_status"] = "IN_PRODUCTION"
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(fat))


@bp.route("/factory-acceptance-tests/<fid>/start", methods=["POST"])
def start_fat(fid):
    rbac.authenticate("POST /factory-acceptance-tests/{id}/start")
    fat = common.resolve("fat", fid)
    order = common.resolve("order", fat.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("run_by_user_id", STRING, required=True)])
    common.check_state("fat", fat, ("BAY_SCHEDULED", "WITNESS_CONFIRMED"))
    common.check_order_not_cancelled(order)
    posture.check_posture_blocked(order)
    now = clock.sec(clock.now())
    for a in store.where("assignment", factory_acceptance_test_id=fid):
        if a.get("status") != "CONFIRMED":
            continue
        party = store.get("party", a.get("witness_party_id"))
        if party is None:
            continue
        expiry = clock.sec(clock.parse(party.get("credential_expires_at")))
        if expiry is None or expiry <= now:
            raise ApiError("ERR_WITNESS_CREDENTIAL_EXPIRED",
                           "witness party %s credential has lapsed" % party["id"])
    start = clock.sec(clock.parse(fat.get("window_start_at")))
    end = clock.sec(clock.parse(fat.get("window_end_at")))
    if start is None or end is None or now < start or now >= end:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the logical clock is outside the scheduled window")
    fat["status"] = "IN_PROGRESS"
    fat["started_at"] = clock.now_str()
    fat["run_by_user_id"] = data["run_by_user_id"]
    store.touch("fat", fat)
    posture.refresh(order)
    return envelope.ok(store.public(fat))


@bp.route("/factory-acceptance-tests/<fid>/conclude", methods=["POST"])
def conclude_fat(fid):
    rbac.authenticate("POST /factory-acceptance-tests/{id}/conclude")
    fat = common.resolve("fat", fid)
    order = common.resolve("order", fat.get("engineered_order_id"))
    payload = validation.body()
    data = validation.validate(payload, [f("result", STRING, required=True, enum=["PASS", "FAIL"])])
    common.check_state("fat", fat, ("IN_PROGRESS",))
    common.check_order_not_cancelled(order)
    reports = [r for r in store.where("report", factory_acceptance_test_id=fid)
               if r.get("status") == "ISSUED" and r.get("pass_result") == data["result"]]
    if not reports:
        raise ApiError("ERR_TEST_REPORT_NOT_ISSUED",
                       "an ISSUED test report with verdict %s is required" % data["result"])
    fat["concluded_at"] = clock.now_str()
    if data["result"] == "PASS":
        fat["status"] = "PASSED"
        store.touch("fat", fat)
        if order.get("fulfillment_status") == "IN_PRODUCTION":
            order["fulfillment_status"] = "FAT_COMPLETE"
        components = set()
        for a in store.where("allocation", engineered_order_id=order["id"]):
            if a.get("status") != "COMMITTED":
                continue
            comp = store.get("component", a.get("long_lead_component_id"))
            a["status"] = "CONSUMED"
            store.touch("allocation", a)
            if comp is not None:
                comp["quantity_on_hand"] = (comp.get("quantity_on_hand") or 0) - (a.get("quantity") or 0)
                components.add(comp["id"])
        for cid in components:
            comp = store.get("component", cid)
            calc.refresh_component_buckets(comp)
            store.touch("component", comp)
    else:
        fat["status"] = "FAILED"
        store.touch("fat", fat)
        for label in store.where("label", engineered_order_id=order["id"]):
            report = store.get("report", label.get("test_report_id"))
            if report is None or report.get("factory_acceptance_test_id") != fid:
                continue
            if label.get("status") in ("GENERATED", "VERIFIED", "ISSUED"):
                label["status"] = "VOIDED"
                label["void_reason"] = "FAT_FAILED"
                store.touch("label", label)
        if not common.order_has_issued_label(order):
            common.revert_cleared_releases(order)
    bay = store.get("bay", fat.get("test_bay_id"))
    if bay is not None:
        calc.refresh_bay_hours(bay)
        store.touch("bay", bay)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(fat))


@bp.route("/factory-acceptance-tests/<fid>/abandon", methods=["POST"])
def abandon_fat(fid):
    rbac.authenticate("POST /factory-acceptance-tests/{id}/abandon")
    fat = common.resolve("fat", fid)
    order = common.resolve("order", fat.get("engineered_order_id"))
    payload = validation.body()
    validation.validate(payload, [f("reason", STRING)])
    common.check_state("fat", fat,
                       ("REQUESTED", "BAY_SCHEDULED", "WITNESS_CONFIRMED", "IN_PROGRESS", "FAILED"))
    if fat.get("window_start_at") and fat.get("status") in ("BAY_SCHEDULED", "WITNESS_CONFIRMED"):
        start = clock.sec(clock.parse(fat.get("window_start_at")))
        if clock.sec(clock.now()) >= start:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "a claimed window may only be abandoned before it starts")
    fat["status"] = "ABANDONED"
    if isinstance(payload.get("reason"), str):
        fat["abandon_reason"] = payload["reason"]
    for a in store.where("assignment", factory_acceptance_test_id=fid):
        if a.get("status") in ("INVITED", "CONFIRMED"):
            a["status"] = "RELEASED"
            store.touch("assignment", a)
    fat["confirmed_witness_count"] = 0
    store.touch("fat", fat)
    bay = store.get("bay", fat.get("test_bay_id"))
    if bay is not None:
        calc.refresh_bay_hours(bay)
        store.touch("bay", bay)
    posture.refresh(order)
    return envelope.ok(store.public(fat))
