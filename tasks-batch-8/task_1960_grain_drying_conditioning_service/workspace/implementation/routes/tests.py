"""Moisture tests: create (OCC on lot), certify (rebaseline), dispute (PRD §3.2)."""

from flask import Blueprint, request

from db import logical_now_iso, public, sort_by_creation, stamp_new, store, touch
from errors import raise_err
from middleware import get_ctx, require_roles
from response import success
from routes.helpers import check_grower_on_test, get_lot, get_test, scope_by_lot_for_grower
from services.calculations import provisional_shrink_estimate
from validation import get_body, opt_enum, opt_str, paginate, req_int, req_num

bp = Blueprint("tests", __name__)

METHODS = {"PROBE", "OVEN_REFERENCE"}
READ_ROLES = {"ElevatorManager", "Grower", "IntakeTechnician", "DryerOperator", "ClaimsAdjuster"}


@bp.post("/moisture-tests")
def create_test():
    ctx = get_ctx()
    require_roles(ctx, {"IntakeTechnician"})
    body = get_body()
    # priority 4: body FK existence (lot_id, then supersedes_test_id)
    lot = None
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    supersedes = body.get("supersedes_test_id")
    if supersedes is not None:
        get_test(supersedes)
    # priority 5: request shape
    lot_id = body.get("lot_id")
    if not isinstance(lot_id, str) or not lot_id:
        raise_err("ERR_INVALID_REQUEST", "Field lot_id is required")
    sample = req_num(body, "sample_moisture_pct", minimum=0, maximum=60, exclusive_min=True, exclusive_max=True)
    expected_version = req_int(body, "expected_grain_lot_version")
    method = opt_enum(body, "method", METHODS, default="PROBE")
    supersedes = opt_str(body, "supersedes_test_id", default=None)
    # priority 7: OCC on the parent lot's version
    if lot["version"] != expected_version:
        raise_err("ERR_STALE_LOT_VERSION", "expected_grain_lot_version does not match current GrainLot.version")
    rec = stamp_new(
        {
            "lot_id": lot["id"],
            "sample_moisture_pct": sample,
            "method": method,
            "supersedes_test_id": supersedes,
            "status": "PRELIMINARY",
            "tested_by_user_id": ctx["user_id"],
            "certified_by_user_id": None,
            "certified_at": None,
        }
    )
    store.tests[rec["id"]] = rec
    # creating a test advances the lot's version (§2.7)
    touch(lot)
    return success(public(rec), code=201)


@bp.get("/moisture-tests")
def list_tests():
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    records = scope_by_lot_for_grower(ctx, list(store.tests.values()), "lot_id")
    for field in ("lot_id", "supersedes_test_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/moisture-tests/<tid>")
def get_one_test(tid):
    ctx = get_ctx()
    require_roles(ctx, READ_ROLES)
    rec = get_test(tid)
    check_grower_on_test(ctx, rec)
    return success(public(rec))


@bp.post("/moisture-tests/<tid>/certify")
def certify_test(tid):
    ctx = get_ctx()
    require_roles(ctx, {"IntakeTechnician"})
    rec = get_test(tid)
    lot = store.lots.get(rec["lot_id"])
    # priority 6: state permission
    if rec["status"] == "SUPERSEDED":
        raise_err("ERR_ALREADY_TERMINAL", "Moisture test is in a terminal state")
    if rec["status"] != "PRELIMINARY":
        raise_err("ERR_INVALID_STATE", "Only a PRELIMINARY test may be certified")
    if lot is None or lot["status"] not in ("RECEIVED", "TESTED"):
        raise_err("ERR_INVALID_STATE", "Lot state does not permit certification")
    # priority 8: retest segregation of duties (§2.8)
    current = store.tests.get(lot["certified_test_id"]) if lot["certified_test_id"] else None
    if (
        current is not None
        and current["status"] == "DISPUTED"
        and current["certified_by_user_id"] == ctx["user_id"]
    ):
        raise_err("ERR_RETEST_SO_DUTY_VIOLATION", "Dispute-retest certifier must differ from the disputed test's certifier")
    # side effects: prior CERTIFIED or DISPUTED test of this lot -> SUPERSEDED
    for other in store.tests.values():
        if other["lot_id"] == lot["id"] and other["id"] != rec["id"] and other["status"] in ("CERTIFIED", "DISPUTED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    rec["status"] = "CERTIFIED"
    rec["certified_by_user_id"] = ctx["user_id"]
    rec["certified_at"] = logical_now_iso()
    touch(rec)
    # rebaseline the lot + provisional shrink estimate
    lot["intake_moisture_pct"] = rec["sample_moisture_pct"]
    lot["current_moisture_pct"] = rec["sample_moisture_pct"]
    lot["certified_test_id"] = rec["id"]
    shrink, dry = provisional_shrink_estimate(lot)
    lot["provisional_shrink_pct"] = shrink
    lot["provisional_dry_weight_lbs"] = dry
    lot["status"] = "TESTED"
    touch(lot)
    return success(public(rec))


@bp.post("/moisture-tests/<tid>/dispute")
def dispute_test(tid):
    ctx = get_ctx()
    require_roles(ctx, {"Grower"})
    rec = get_test(tid)
    lot = store.lots.get(rec["lot_id"])
    # priority 3: only the lot's current owner may dispute
    owner = lot["current_owner_id"] if lot is not None else None
    if ctx["user_id"] != owner:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Only the lot's current owner may dispute a test")
    # priority 6: state
    if rec["status"] == "SUPERSEDED":
        raise_err("ERR_ALREADY_TERMINAL", "Moisture test is in a terminal state")
    if rec["status"] != "CERTIFIED":
        raise_err("ERR_INVALID_STATE", "Only a CERTIFIED test may be disputed")
    rec["status"] = "DISPUTED"
    touch(rec)
    return success(public(rec))
