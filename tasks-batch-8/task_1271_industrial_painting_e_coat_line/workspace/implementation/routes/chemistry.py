"""PretreatmentStages, chemical adjustments, titration readings (PRD SS3.2)."""
from flask import g

from db import STORE
from errors import ApiError
from middleware import require_roles, ROLES
from response import success_object, success_list, paginate
from serializers import ser_stage, ser_titration
from services import new_common, new_event, touch, recompute_posture, D
from validators import get_body, req, as_str, as_int, as_num

from . import bp


def _get_or_404(table, rid):
    rec = STORE[table].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % rid)
    return rec


@bp.post("/ecoat/pretreatment-stages")
@require_roles("PlantAdmin")
def create_stage():
    body = get_body()
    paint_line_id = as_str(req(body, "paint_line_id"), "paint_line_id")
    stage_name = as_str(req(body, "stage_name"), "stage_name")
    sequence_no = as_int(req(body, "sequence_no"), "sequence_no")
    chemical_family = as_str(req(body, "chemical_family"), "chemical_family")
    conc_min = as_num(req(body, "conc_min_gpl"), "conc_min_gpl")
    conc_max = as_num(req(body, "conc_max_gpl"), "conc_max_gpl")
    if STORE["paint_lines"].get(paint_line_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, "paint_line_id does not exist")
    st = new_common()
    st.update({
        "paint_line_id": paint_line_id, "stage_name": stage_name,
        "sequence_no": sequence_no, "chemical_family": chemical_family,
        "conc_min_gpl": conc_min, "conc_max_gpl": conc_max,
        "status": "IN_RANGE",
    })
    STORE["pretreatment_stages"][st["id"]] = st
    return success_object(ser_stage(st), 201)


@bp.get("/ecoat/pretreatment-stages/<sid>")
@require_roles(*ROLES)
def get_stage(sid):
    return success_object(ser_stage(_get_or_404("pretreatment_stages", sid)))


@bp.post("/ecoat/pretreatment-stages/<sid>/adjustments")
@require_roles("ProcessChemist")
def record_adjustment(sid):
    body = get_body()
    as_num(req(body, "chemical_added_kg"), "chemical_added_kg")
    st = _get_or_404("pretreatment_stages", sid)
    if st["status"] != "OUT_OF_RANGE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Chemical adjustment requires the stage to be OUT_OF_RANGE")
    st["status"] = "ADJUSTING"
    touch(st)
    # Line remains on CHEM_HOLD throughout an adjustment.
    recompute_posture(STORE["paint_lines"][st["paint_line_id"]])
    return success_object(ser_stage(st))


@bp.post("/ecoat/titration-readings")
@require_roles("ProcessChemist")
def create_titration_reading():
    body = get_body()
    stage_id = as_str(req(body, "stage_id"), "stage_id")
    measured = as_num(req(body, "measured_conc_gpl"), "measured_conc_gpl")
    if measured < 0:
        raise ApiError("ERR_MEASUREMENT_INVALID", 422,
                       "measured_conc_gpl must be >= 0")
    st = STORE["pretreatment_stages"].get(stage_id)
    if st is None:
        raise ApiError("ERR_NOT_FOUND", 404, "stage_id does not exist")

    in_range = D(st["conc_min_gpl"]) <= measured <= D(st["conc_max_gpl"])
    reading = new_event()
    reading.update({
        "stage_id": stage_id,
        "measured_conc_gpl": measured,
        "recorded_by_user_id": g.user_id,
        "in_range": in_range,
    })
    STORE["titration_readings"][reading["id"]] = reading

    # Compliance loop (PRD SS3.2): the only cycle is
    # IN_RANGE -> OUT_OF_RANGE -> ADJUSTING -> IN_RANGE.
    prev = st["status"]
    if prev == "IN_RANGE" and not in_range:
        st["status"] = "OUT_OF_RANGE"
        touch(st)
    elif prev == "ADJUSTING":
        st["status"] = "IN_RANGE" if in_range else "OUT_OF_RANGE"
        touch(st)
    # OUT_OF_RANGE + any reading: unchanged (adjustment is mandatory).
    # IN_RANGE + in-range reading: unchanged.
    recompute_posture(STORE["paint_lines"][st["paint_line_id"]])
    return success_object(ser_titration(reading), 201)


@bp.get("/ecoat/pretreatment-stages/<sid>/titration-readings")
@require_roles(*ROLES)
def list_stage_readings(sid):
    _get_or_404("pretreatment_stages", sid)
    items = [r for r in STORE["titration_readings"].values() if r["stage_id"] == sid]
    page, meta = paginate(items, ser_titration)
    return success_list(page, meta)
