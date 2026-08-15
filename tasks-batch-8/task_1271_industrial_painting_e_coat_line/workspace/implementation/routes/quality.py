"""OvenCycles, QualityTests, ReworkOrders (PRD SS3.5-SS3.7)."""
from flask import g, request

from db import STORE
from errors import ApiError
from middleware import require_roles, ROLES
from response import success_object, success_list, paginate
from serializers import ser_oven_cycle, ser_quality_test, ser_rework_order
from services import (
    D, new_common, new_event, touch, lot_outstanding, spec_of,
    strip_cost_cents, repaint_per_part_cents, strip_voc_kg,
    covering_permit, post_emission, MAX_REWORK_COUNT,
)
from validators import get_body, req, as_str, as_int, as_num, as_dt

from . import bp

TEST_TYPES = ("ADHESION", "IMPACT")


def _get_or_404(table, rid):
    rec = STORE[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


# --- OvenCycle ---------------------------------------------------------------

@bp.post("/ecoat/oven-cycles")
@require_roles("QcInspector")
def create_oven_cycle():
    body = get_body()
    lot_id = as_str(req(body, "lot_id"), "lot_id")
    oven_id = as_str(req(body, "oven_id"), "oven_id")
    entered_raw = req(body, "entered_at")
    exited_raw = req(body, "exited_at")
    entered = as_dt(entered_raw, "entered_at")
    exited = as_dt(exited_raw, "exited_at")
    if exited <= entered:
        raise ApiError("ERR_INVALID_REQUEST", 400, "exited_at must be after entered_at")
    min_temp = as_num(req(body, "min_metal_temp_c"), "min_metal_temp_c")
    minutes = as_int(req(body, "minutes_at_or_above_temp"), "minutes_at_or_above_temp")
    recheck_of_id = body.get("recheck_of_id")

    lot = STORE["lots"].get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "lot_id does not exist")
    oven = STORE["cure_ovens"].get(oven_id)
    if oven is None:
        raise ApiError("ERR_NOT_FOUND", 404, "oven_id does not exist")
    parent = None
    if recheck_of_id is not None:
        if not isinstance(recheck_of_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "recheck_of_id must be a string id")
        parent = STORE["oven_cycles"].get(recheck_of_id)
        if parent is None:
            raise ApiError("ERR_NOT_FOUND", 404, "recheck_of_id does not exist")

    # State preconditions (rung 6).
    if parent is not None:
        # Recheck: parent must be FAIL and childless.
        if parent["verdict"] != "FAIL":
            raise ApiError("ERR_RECHECK_NOT_ALLOWED", 409,
                           "recheck_of_id references a PASS cycle")
        has_child = any(c["recheck_of_id"] == parent["id"]
                        for c in STORE["oven_cycles"].values())
        if has_child:
            raise ApiError("ERR_RECHECK_NOT_ALLOWED", 409,
                           "recheck_of_id references a cycle that already has a recheck child")
        if lot["status"] != "CURE_FAILED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A recheck cycle requires the lot to be CURE_FAILED")
    else:
        if lot["status"] != "CURING":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "An oven cycle requires the lot to be CURING")

    # Oven aggregate capacity (rung 8): closed-interval overlap counting.
    overlapping = sum(
        1 for c in STORE["oven_cycles"].values()
        if c["oven_id"] == oven_id
        and c["_entered"] <= exited and c["_exited"] >= entered
    )
    if overlapping + 1 > oven["max_loads"]:
        raise ApiError("ERR_OVEN_CAPACITY_FULL", 409,
                       "Overlapping oven cycles would exceed oven.max_loads")

    spec = spec_of(lot)
    verdict = ("PASS"
               if (min_temp >= D(spec["cure_metal_temp_c"])
                   and minutes >= spec["cure_minutes_at_temp"])
               else "FAIL")

    cycle = new_event()
    cycle.update({
        "lot_id": lot_id, "oven_id": oven_id, "recheck_of_id": recheck_of_id,
        "entered_at": entered_raw, "exited_at": exited_raw,
        "_entered": entered, "_exited": exited,
        "min_metal_temp_c": min_temp, "minutes_at_or_above_temp": minutes,
        "verdict": verdict,
    })
    STORE["oven_cycles"][cycle["id"]] = cycle

    # Advance the lot.
    if parent is None:
        lot["status"] = "QC_PENDING" if verdict == "PASS" else "CURE_FAILED"
        touch(lot)
    else:
        if verdict == "PASS":
            lot["status"] = "QC_PENDING"
            touch(lot)
        # FAIL recheck: the lot remains CURE_FAILED.
    return success_object(ser_oven_cycle(cycle), 201)


@bp.get("/ecoat/oven-cycles/<cid>")
@require_roles(*ROLES)
def get_oven_cycle(cid):
    return success_object(ser_oven_cycle(_get_or_404("oven_cycles", cid)))


@bp.get("/ecoat/oven-cycles")
@require_roles(*ROLES)
def list_oven_cycles():
    items = list(STORE["oven_cycles"].values())
    lot_id = request.args.get("lot_id")
    oven_id = request.args.get("oven_id")
    recheck_of_id = request.args.get("recheck_of_id")
    if lot_id is not None:
        items = [c for c in items if c["lot_id"] == lot_id]
    if oven_id is not None:
        items = [c for c in items if c["oven_id"] == oven_id]
    if recheck_of_id is not None:
        items = [c for c in items if c["recheck_of_id"] == recheck_of_id]
    page, meta = paginate(items, ser_oven_cycle)
    return success_list(page, meta)


# --- QualityTest -------------------------------------------------------------

@bp.post("/ecoat/quality-tests")
@require_roles("QcInspector")
def create_quality_test():
    body = get_body()
    lot_id = as_str(req(body, "lot_id"), "lot_id")
    test_type = req(body, "test_type")
    if test_type not in TEST_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "test_type must be one of %s" % (", ".join(TEST_TYPES)))
    measured = as_num(req(body, "measured_value"), "measured_value")
    lot = STORE["lots"].get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", 404, "lot_id does not exist")
    if lot["status"] != "QC_PENDING":
        raise ApiError("ERR_CURE_NOT_PASSED", 409,
                       "Quality test requires the lot in QC_PENDING (cure passed)")

    spec = spec_of(lot)
    if test_type == "ADHESION":
        verdict = "PASS" if measured >= D(spec["adhesion_class_min"]) else "FAIL"
    else:
        verdict = "PASS" if measured >= D(spec["impact_joules_min"]) else "FAIL"

    test = new_event()
    test.update({
        "lot_id": lot_id, "test_type": test_type, "measured_value": measured,
        "recorded_by_user_id": g.user_id, "verdict": verdict,
    })
    STORE["quality_tests"][test["id"]] = test

    if verdict == "FAIL":
        # Cascade: lot -> QC_HOLD; auto-create a DRAFT ReworkOrder snapshotting
        # the lot's outstanding quantity.
        lot["status"] = "QC_HOLD"
        touch(lot)
        ro = new_common()
        ro.update({
            "lot_id": lot["id"],
            "parts_to_rework": lot_outstanding(lot),
            "status": "DRAFT",
            "strip_cost_cents": 0,
            "repaint_charge_cents": 0,
            "scrapped_quantity": None,
            "total_charge_cents": 0,
        })
        STORE["rework_orders"][ro["id"]] = ro
    return success_object(ser_quality_test(test), 201)


@bp.get("/ecoat/lots/<lid>/quality-tests")
@require_roles(*ROLES)
def list_lot_quality_tests(lid):
    _get_or_404("lots", lid)
    items = [t for t in STORE["quality_tests"].values() if t["lot_id"] == lid]
    page, meta = paginate(items, ser_quality_test)
    return success_list(page, meta)


# --- ReworkOrder -------------------------------------------------------------

@bp.get("/ecoat/rework-orders/<rid>")
@require_roles(*ROLES)
def get_rework_order(rid):
    return success_object(ser_rework_order(_get_or_404("rework_orders", rid)))


@bp.get("/ecoat/lots/<lid>/rework-orders")
@require_roles(*ROLES)
def list_lot_rework_orders(lid):
    _get_or_404("lots", lid)
    items = [r for r in STORE["rework_orders"].values() if r["lot_id"] == lid]
    page, meta = paginate(items, ser_rework_order)
    return success_list(page, meta)


@bp.post("/ecoat/rework-orders/<rid>/approve")
@require_roles("QualityManager")
def approve_rework_order(rid):
    ro = _get_or_404("rework_orders", rid)
    if ro["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Rework-order approval requires status DRAFT")
    lot = STORE["lots"][ro["lot_id"]]
    if lot["rework_count"] >= MAX_REWORK_COUNT:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED", 422,
                       "lot.rework_count has reached MAX_REWORK_COUNT (2)")
    ro["strip_cost_cents"] = strip_cost_cents(ro["parts_to_rework"])
    ro["status"] = "APPROVED"
    touch(ro)
    lot["status"] = "STRIPPING"
    touch(lot)
    return success_object(ser_rework_order(ro))


@bp.post("/ecoat/rework-orders/<rid>/complete-strip")
@require_roles("QualityManager")
def complete_strip(rid):
    body = get_body()
    scrapped = as_int(req(body, "scrapped_quantity"), "scrapped_quantity")
    ro = _get_or_404("rework_orders", rid)
    if ro["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Strip completion requires status APPROVED")
    if not (0 <= scrapped <= ro["parts_to_rework"]):
        raise ApiError("ERR_PART_ACCOUNT_MISMATCH", 422,
                       "scrapped_quantity must lie in [0, parts_to_rework]")

    lot = STORE["lots"][ro["lot_id"]]
    spec = spec_of(lot)
    stripped = ro["parts_to_rework"] - scrapped

    # Pinned rounding: per-part repaint rounded to whole cents FIRST, then
    # multiplied by the repainted part count.
    ro["repaint_charge_cents"] = repaint_per_part_cents(spec["area_dm2_per_part"]) * stripped
    ro["total_charge_cents"] = ro["strip_cost_cents"] + ro["repaint_charge_cents"]
    ro["scrapped_quantity"] = scrapped
    ro["status"] = "COMPLETED"
    touch(ro)

    lot["scrapped_quantity"] += scrapped
    lot["rework_count"] += 1
    lot["rework_charge_cents"] += ro["total_charge_cents"]
    lot["status"] = "QUEUED" if scrapped < ro["parts_to_rework"] else "SCRAPPED"
    touch(lot)

    # STRIP_SOLVENT emission entry for the stripped part count.
    permit = covering_permit()
    if permit is not None:
        post_emission(permit, "STRIP_SOLVENT", strip_voc_kg(stripped), "METERED",
                      lot_id=lot["id"])
    return success_object(ser_rework_order(ro))
