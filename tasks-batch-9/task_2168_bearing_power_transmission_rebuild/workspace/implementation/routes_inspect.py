"""Vibration readings, inspections and metrology measurements."""

from flask import Blueprint

import calc
import ledger
import store
import validate as v
import views
from auth import (ALL_ROLES, INSPECTION_ACTIONS, authenticate,
                  require_action_role, require_roles)
from errors import fail
from response import created, listing, ok

bp = Blueprint("inspect", __name__)

CAUSE_CODES = {
    "OUTER_RACE_SPALL", "INNER_RACE_SPALL", "MISALIGNMENT", "LOOSE_FIT",
    "LUBRICATION_FAILURE", "NORMAL_WEAR", "WORKMANSHIP", "UNDETERMINED",
}
INSPECTION_ADVANCE = {"SUBMIT", "ACCEPT", "RETURN", "REOPEN"}


def path_inspection(iid):
    rec = store.get("inspections", iid)
    if rec is None:
        fail("ERR_INSPECTION_NOT_FOUND", "Inspection %s not found" % iid)
    return rec


# ---------------------------------------------------------------------------
# vibration readings
# ---------------------------------------------------------------------------
@bp.post("/shop/vibration-readings")
def create_reading():
    _, role = authenticate()
    require_roles(role, ["ReliabilityEngineer", "ShopAdmin"])
    body = v.body()
    asset_id = v.req_fk(body, "customer_asset_id")
    reading_at = v.req_ts(body, "reading_at")
    velocity = v.req_num(body, "overall_velocity_mm_s", minimum=0)
    bpfo = v.req_num(body, "bpfo_amplitude_g", minimum=0)
    bpfi = v.req_num(body, "bpfi_amplitude_g", minimum=0)
    baseline = v.req_num(body, "baseline_amplitude_g", exclusive_min=0)

    if store.get("assets", asset_id) is None:
        fail("ERR_ASSET_NOT_FOUND", "Asset %s not found" % asset_id)

    rec = store.base_record(with_version=False)
    rec.update({
        "customer_asset_id": asset_id,
        "reading_at": body["reading_at"],
        "overall_velocity_mm_s": velocity,
        "bpfo_amplitude_g": bpfo,
        "bpfi_amplitude_g": bpfi,
        "baseline_amplitude_g": baseline,
        "iso_zone": calc.vibration_zone(velocity),
        "defect_ratio_outer": calc.defect_ratio(bpfo, baseline),
        "defect_ratio_inner": calc.defect_ratio(bpfi, baseline),
        "_reading_at_dt": reading_at,
    })
    store.insert("readings", rec)
    return created(views.render("readings", rec))


@bp.get("/shop/assets/<aid>/vibration-readings")
def list_readings(aid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    asset = store.get("assets", aid)
    if asset is None:
        fail("ERR_ASSET_NOT_FOUND", "Asset %s not found" % aid)
    limit, offset = v.pagination()
    views.require_owner(role, uid, "assets", asset)
    rows = [r for r in store.all_rows("readings") if r["customer_asset_id"] == asset["id"]]
    zone = v.qparam("iso_zone")
    if zone is not None:
        rows = [r for r in rows if r["iso_zone"] == zone]
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("readings", page), limit, offset, total)


# ---------------------------------------------------------------------------
# inspections
# ---------------------------------------------------------------------------
@bp.post("/shop/inspections")
def create_inspection():
    _, role = authenticate()
    require_roles(role, ["Inspector", "ShopAdmin"])
    body = v.body()
    order_id = v.req_fk(body, "rebuild_order_id")
    reading_id = v.opt_fk(body, "linked_vibration_reading_id")
    note = v.opt_str(body, "inspector_note", None)
    override = v.opt_enum(body, "cause_code_override", CAUSE_CODES, None)

    order = store.get("orders", order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "Rebuild order %s not found" % order_id)
    reading = None
    if reading_id is not None:
        reading = store.get("readings", reading_id)
        if reading is None:
            fail("ERR_READING_NOT_FOUND", "Vibration reading %s not found" % reading_id)
        if reading["customer_asset_id"] != order["customer_asset_id"]:
            fail("ERR_VIBRATION_ASSET_MISMATCH",
                 "the reading was taken on a different machine")

    rec = store.base_record()
    rec.update({
        "rebuild_order_id": order_id,
        "linked_vibration_reading_id": reading_id,
        "status": "DRAFT",
        "inspector_note": note,
        "cause_code_override": override,
        "submitted_by_user_id": None,
        "accepted_by_user_id": None,
        "revision_count": 0,
        "life_score_variant": None,
        "remaining_life_score": None,
        "remaining_life_grade": None,
        "failure_cause_code": None,
        "cause_confidence": None,
        "return_reason": None,
    })
    store.insert("inspections", rec)

    core = store.get("core_units", order["core_unit_id"])
    if (core is not None and core["status"] == "RECEIVED"
            and order["work_status"] in ("DRAFT", "QUOTED")):
        core["status"] = "INSPECTING"
        store.touch(core)
    return created(views.render("inspections", rec))


@bp.get("/shop/inspections/<iid>")
def read_inspection(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = path_inspection(iid)
    views.require_owner(role, uid, "inspections", rec)
    return ok(views.render("inspections", rec))


@bp.get("/shop/inspections")
def list_inspections():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = v.pagination()
    rows = store.all_rows("inspections")
    for key in ("rebuild_order_id", "linked_vibration_reading_id", "status"):
        value = v.qparam(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    rows = views.scope_rows(role, uid, "inspections", rows)
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("inspections", page), limit, offset, total)


# ---------------------------------------------------------------------------
# measurements
# ---------------------------------------------------------------------------
@bp.post("/shop/inspections/<iid>/measurements")
def create_measurement(iid):
    _, role = authenticate()
    require_roles(role, ["Inspector", "ShopAdmin"])
    inspection = path_inspection(iid)
    body = v.body()
    feature_code = v.req_str(body, "feature_code")
    measured_um = v.req_int(body, "measured_um")

    order = calc.order_of(inspection)
    standard = calc.standard_for_order(order)
    bands = calc.band_map(standard) if standard is not None else {}
    if feature_code not in bands:
        fail("ERR_INVALID_REQUEST", "feature_code is not part of the governing standard")

    if inspection["status"] != "DRAFT":
        fail("ERR_INSPECTION_INVALID_STATE", "inspection is not DRAFT")

    band_result, deviation, score = calc.clearance_band_evaluation(
        bands[feature_code], measured_um
    )
    sequence_no = len(calc.measurements_of(inspection["id"])) + 1

    rec = store.base_record(with_version=False)
    rec.update({
        "inspection_id": inspection["id"],
        "feature_code": feature_code,
        "measured_um": measured_um,
        "sequence_no": sequence_no,
        "band_result": band_result,
        "deviation_ratio": deviation,
        "feature_score": score,
    })
    store.insert("measurements", rec)
    return created(views.render("measurements", rec))


@bp.get("/shop/inspections/<iid>/measurements")
def list_measurements(iid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    inspection = path_inspection(iid)
    limit, offset = v.pagination()
    views.require_owner(role, uid, "inspections", inspection)
    rows = calc.measurements_of(inspection["id"])
    code = v.qparam("feature_code")
    if code is not None:
        rows = [r for r in rows if r["feature_code"] == code]
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("measurements", page), limit, offset, total)


# ---------------------------------------------------------------------------
# inspection lifecycle
# ---------------------------------------------------------------------------
@bp.post("/shop/inspections/<iid>/advance")
def advance_inspection(iid):
    uid, role = authenticate()
    require_roles(role, ["Inspector", "ReliabilityEngineer", "ShopAdmin"])
    raw = v.body()
    require_action_role(role, raw.get("action"), INSPECTION_ACTIONS)
    inspection = path_inspection(iid)
    action = v.req_enum(raw, "action", INSPECTION_ADVANCE)
    reading_id = v.opt_fk(raw, "linked_vibration_reading_id")
    return_reason = v.opt_str(raw, "return_reason", None)

    supplied_reading = None
    if reading_id is not None:
        supplied_reading = store.get("readings", reading_id)
        if supplied_reading is None:
            fail("ERR_READING_NOT_FOUND", "Vibration reading %s not found" % reading_id)

    order = calc.order_of(inspection)

    if action == "SUBMIT":
        if inspection["status"] != "DRAFT":
            fail("ERR_INSPECTION_INVALID_STATE", "inspection is not DRAFT")
        if supplied_reading is not None and order is not None:
            if supplied_reading["customer_asset_id"] != order["customer_asset_id"]:
                fail("ERR_VIBRATION_ASSET_MISMATCH",
                     "the reading was taken on a different machine")
        _submit(inspection, uid, reading_id, order)
    elif action == "ACCEPT":
        if inspection["status"] != "SUBMITTED":
            fail("ERR_INSPECTION_INVALID_STATE", "inspection is not SUBMITTED")
        if uid == inspection.get("submitted_by_user_id"):
            fail("ERR_SEGREGATION_OF_DUTIES", "an inspection may not be accepted by its submitter")
        for sibling in store.all_rows("inspections"):
            if (sibling["rebuild_order_id"] == inspection["rebuild_order_id"]
                    and sibling["id"] != inspection["id"]
                    and sibling["status"] == "ACCEPTED"):
                fail("ERR_INSPECTION_ALREADY_ACCEPTED",
                     "another inspection on this order is already accepted")
        if supplied_reading is not None and order is not None:
            if supplied_reading["customer_asset_id"] != order["customer_asset_id"]:
                fail("ERR_VIBRATION_ASSET_MISMATCH",
                     "the reading was taken on a different machine")
        _accept(inspection, uid, order)
    elif action == "RETURN":
        if inspection["status"] != "SUBMITTED":
            fail("ERR_INSPECTION_INVALID_STATE", "inspection is not SUBMITTED")
        inspection["status"] = "RETURNED"
        inspection["return_reason"] = return_reason
        store.touch(inspection)
    else:
        if inspection["status"] != "RETURNED":
            fail("ERR_INSPECTION_INVALID_STATE", "inspection is not RETURNED")
        inspection["status"] = "DRAFT"
        inspection["revision_count"] = int(inspection["revision_count"]) + 1
        inspection["submitted_by_user_id"] = None
        for field in ("remaining_life_score", "remaining_life_grade",
                      "life_score_variant", "failure_cause_code", "cause_confidence"):
            inspection[field] = None
        store.touch(inspection)

    return ok(views.render("inspections", inspection))


def _submit(inspection, uid, reading_id, order):
    effective_reading_id = reading_id or inspection.get("linked_vibration_reading_id")
    if not effective_reading_id:
        fail("ERR_VIBRATION_LINK_REQUIRED", "a linked vibration reading is required")

    standard = calc.standard_for_order(order)
    required = list(standard.get("required_feature_codes") or []) if standard else []
    measured_codes = {m["feature_code"] for m in calc.measurements_of(inspection["id"])}
    for code in required:
        if code not in measured_codes:
            fail("ERR_MEASUREMENTS_INCOMPLETE", "feature %s has no measurement" % code)

    inspection["linked_vibration_reading_id"] = effective_reading_id
    reading = store.get("readings", effective_reading_id)
    core = store.get("core_units", order["core_unit_id"]) if order else None
    asset = store.get("assets", order["customer_asset_id"]) if order else None

    variant, score, grade = calc.remaining_life(
        inspection, order, core, asset, standard, reading
    )
    inspection["life_score_variant"] = variant
    inspection["remaining_life_score"] = score
    inspection["remaining_life_grade"] = grade

    code, confidence = calc.failure_cause(inspection, reading, core)
    inspection["failure_cause_code"] = code
    inspection["cause_confidence"] = confidence

    inspection["submitted_by_user_id"] = uid
    inspection["status"] = "SUBMITTED"
    store.touch(inspection)


def _accept(inspection, uid, order):
    # hop 1
    inspection["status"] = "ACCEPTED"
    inspection["accepted_by_user_id"] = uid
    store.touch(inspection)

    core = store.get("core_units", order["core_unit_id"]) if order else None
    if core is None:
        return
    standard = store.get("standards", core["clearance_standard_id"])

    # hop 2
    governing = calc.governing_measurements(inspection["id"])
    bands = calc.band_map(standard) if standard else {}
    final_credit = calc.core_credit_valuation(
        standard["base_core_value_cents"] if standard else 0,
        inspection["remaining_life_grade"],
        core["rebuild_count"],
        governing,
        bands,
    )
    core["condition_grade"] = inspection["remaining_life_grade"]
    core["status"] = "GRADED"
    core["final_core_credit_cents"] = final_credit
    store.touch(core)

    # hop 3
    old = ledger.posted_core_note(core["id"])
    if old is not None:
        ledger.void_note(old, "superseded by bench grading")
    ledger.post_note(
        core["customer_id"], "CORE_EXCHANGE", final_credit,
        core_unit_id=core["id"], memo="final exchange-core credit",
    )

    # hops 4 and 5
    ledger.settle(store.get("customers", core["customer_id"]), reprice=True)
