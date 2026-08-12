"""Formula endpoints: create/list/get/lines, supersede (OCC), activate, deprecate."""
from flask import Blueprint, request

from .domain import (
    deprecate_formula_cascade,
    lines_of_formula,
    ser_formula,
    ser_formula_line,
)
from .errors import ApiError, bad_request, conflict, invalid_state, not_found
from .store import now, store
from .util import (
    auth,
    body,
    list_response,
    new_light_record,
    new_record,
    success,
    touch,
    v_arr,
    v_bool,
    v_int,
    v_num,
    v_str,
)

bp = Blueprint("formulas", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


def _validate_lines(raw_lines):
    """Gate 3 schema for formula lines; returns list of (colorant_id, shots, sequence)."""
    if not isinstance(raw_lines, list):
        raise bad_request("lines must be an array")
    parsed = []
    for i, entry in enumerate(raw_lines):
        if not isinstance(entry, dict):
            raise bad_request("lines[%d] must be an object" % i)
        colorant_id = v_str(entry, "colorant_id")
        shots = v_num(entry, "shots_per_gallon", gt=0)
        seq = v_int(entry, "sequence")
        parsed.append((colorant_id, shots, seq))
    return parsed


def _check_colorants_exist(parsed):
    for colorant_id, _shots, _seq in parsed:
        if colorant_id not in store.colorants:
            raise not_found()


def _create_lines(formula_id, parsed):
    for colorant_id, shots, seq in parsed:
        line = new_light_record()
        line.update({
            "formula_id": formula_id,
            "colorant_id": colorant_id,
            "shots_per_gallon": shots,
            "sequence": seq,
        })
        store.formula_lines[line["id"]] = line


@bp.post("/coatings/formulas")
def create_formula():
    auth(("LabTechnician",))
    b = body()
    formula_code = v_str(b, "formula_code")
    color_name = v_str(b, "color_name")
    tint_base_id = v_str(b, "tint_base_id")
    is_custom = v_bool(b, "is_custom")
    target_delta_e = v_num(b, "target_delta_e", minv=0)
    parsed = _validate_lines(v_arr(b, "lines"))
    # gate 4: existence
    if tint_base_id not in store.tint_bases:
        raise not_found()
    _check_colorants_exist(parsed)
    # gate 10: unique formula_code among non-DEPRECATED
    for f in store.formulas.values():
        if f["formula_code"] == formula_code and f["status"] != "DEPRECATED":
            raise conflict("ERR_DUPLICATE_CODE", "formula_code already exists among non-DEPRECATED formulas")
    rec = new_record()
    rec.update({
        "formula_code": formula_code,
        "color_name": color_name,
        "tint_base_id": tint_base_id,
        "is_custom": is_custom,
        "target_delta_e": target_delta_e,
        "min_batch_gallons": 50 if is_custom else 1,
        "formula_version_no": 1,
        "predecessor_formula_id": None,
        "status": "DRAFT",
        "activated_at": None,
    })
    store.formulas[rec["id"]] = rec
    _create_lines(rec["id"], parsed)
    return success(ser_formula(rec), 201)


@bp.get("/coatings/formulas/<fid>")
def get_formula(fid):
    auth(ALL)
    rec = store.formulas.get(fid)
    if rec is None:
        raise not_found()
    return success(ser_formula(rec), 200)


@bp.get("/coatings/formulas")
def list_formulas():
    auth(ALL)
    recs = list(store.formulas.values())
    tb = request.args.get("tint_base_id")
    if tb is not None:
        recs = [f for f in recs if f["tint_base_id"] == tb]
    pred = request.args.get("predecessor_formula_id")
    if pred is not None:
        recs = [f for f in recs if f["predecessor_formula_id"] == pred]
    st = request.args.get("status")
    if st is not None:
        recs = [f for f in recs if f["status"] == st]
    return list_response(recs, ser_formula)


@bp.get("/coatings/formulas/<fid>/lines")
def get_formula_lines(fid):
    auth(ALL)
    if fid not in store.formulas:
        raise not_found()
    return list_response(lines_of_formula(fid), ser_formula_line)


@bp.post("/coatings/formulas/<fid>/supersede")
def supersede_formula(fid):
    auth(("LabTechnician",))
    b = body()
    formula_code = v_str(b, "formula_code")
    color_name = v_str(b, "color_name")
    target_delta_e = v_num(b, "target_delta_e", minv=0)
    parsed = _validate_lines(v_arr(b, "lines"))
    expected = v_int(b, "expected_formula_version")
    # gate 4: path id, then body ids (left to right)
    pred = store.formulas.get(fid)
    if pred is None:
        raise not_found()
    _check_colorants_exist(parsed)
    # gate 5: optimistic concurrency against predecessor version
    if expected != pred["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "expected_formula_version does not match the current formula version")
    # gate 6: predecessor must be ACTIVE
    if pred["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE formula can be superseded")
    rec = new_record()
    rec.update({
        "formula_code": formula_code,
        "color_name": color_name,
        "tint_base_id": pred["tint_base_id"],
        "is_custom": pred["is_custom"],
        "target_delta_e": target_delta_e,
        "min_batch_gallons": 50 if pred["is_custom"] else 1,
        "formula_version_no": pred["formula_version_no"] + 1,
        "predecessor_formula_id": pred["id"],
        "status": "DRAFT",
        "activated_at": None,
    })
    store.formulas[rec["id"]] = rec
    _create_lines(rec["id"], parsed)
    # superseding advances the predecessor's version (what makes a stale retry fail)
    touch(pred)
    return success(ser_formula(rec), 201)


@bp.post("/coatings/formulas/<fid>/activate")
def activate_formula(fid):
    auth(("LabTechnician",))
    rec = store.formulas.get(fid)
    if rec is None:
        raise not_found()
    if rec["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT formula can be activated")
    lines = lines_of_formula(fid)
    if len(lines) == 0:
        raise invalid_state("Formula has no colorant lines")
    for line in lines:
        if line["colorant_id"] not in store.colorants:
            raise not_found()
    for f in store.formulas.values():
        if f["id"] != fid and f["formula_code"] == rec["formula_code"] and f["status"] != "DEPRECATED":
            raise conflict("ERR_DUPLICATE_CODE", "Another non-DEPRECATED formula carries the same formula_code")
    rec["status"] = "ACTIVE"
    rec["activated_at"] = now()
    touch(rec)
    pred_id = rec["predecessor_formula_id"]
    if pred_id:
        pred = store.formulas.get(pred_id)
        if pred is not None and pred["status"] == "ACTIVE":
            deprecate_formula_cascade(pred)
    return success(ser_formula(rec), 200)


@bp.post("/coatings/formulas/<fid>/deprecate")
def deprecate_formula(fid):
    auth(("LabTechnician",))
    rec = store.formulas.get(fid)
    if rec is None:
        raise not_found()
    if rec["status"] not in ("ACTIVE", "DRAFT"):
        raise invalid_state("Formula is already DEPRECATED")
    if rec["status"] == "ACTIVE":
        deprecate_formula_cascade(rec)
    else:
        rec["status"] = "DEPRECATED"
        touch(rec)
    return success(ser_formula(rec), 200)
