"""PurityAnalysis endpoints (PRD §3.4)."""
from flask import Blueprint

from constants import SUBJECT_TYPES
from db import store
from errors import (
    ERR_ANALYSIS_INVALID_STATE,
    ERR_SEGREGATION,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_enum, req_list, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import (
    analysis_out,
    base_record,
    fail_fill_lot,
    release_subject,
)
from util import dec, is_num, touch

bp = Blueprint("analyses", __name__)


def _compute_fill_lot_result(lot, readings):
    bands = []
    for entry in readings:
        if not isinstance(entry, dict):
            bad_request("readings entries must be objects")
        analyte = entry.get("analyte")
        ppm = entry.get("reading_ppm")
        if not isinstance(analyte, str) or not is_num(ppm):
            bad_request("each reading needs analyte and reading_ppm")
        band = calc.purity_band(lot["product_code"], analyte, ppm)
        if band is None:
            bad_request(f"unknown analyte '{analyte}' for grade {lot['product_code']}")
        bands.append(band)
    return calc.worst_band(bands)


def _compute_blend_result(blend, readings):
    for entry in readings:
        if not isinstance(entry, dict):
            bad_request("readings entries must be objects")
        if not isinstance(entry.get("product_code"), str) or not is_num(entry.get("actual_pct")):
            bad_request("each reading needs product_code and actual_pct")
    components = {c["product_code"]: c for c in blend["components"]}
    seen = set()
    bands = []
    for entry in readings:
        comp = components.get(entry["product_code"])
        if comp is None:
            bands.append("FAIL")
            continue
        seen.add(entry["product_code"])
        bands.append(calc.blend_component_band(comp, entry["actual_pct"]))
    for code in components:
        if code not in seen:
            bands.append("FAIL")
    return calc.worst_band(bands)


@bp.post("/api/purity-analyses")
@locked
def create_analysis():
    uid, _ = require_roles("LabAnalyst")
    body = get_body()
    subject_type = req_enum(body, "subject_type", SUBJECT_TYPES)
    fill_lot_id = body.get("fill_lot_id")
    blend_order_id = body.get("blend_order_id")
    if fill_lot_id is not None and not isinstance(fill_lot_id, str):
        bad_request("fill_lot_id must be a string")
    if blend_order_id is not None and not isinstance(blend_order_id, str):
        bad_request("blend_order_id must be a string")
    if subject_type == "FILL_LOT":
        if fill_lot_id is None or blend_order_id is not None:
            bad_request("subject_type FILL_LOT requires exactly fill_lot_id")
    else:
        if blend_order_id is None or fill_lot_id is not None:
            bad_request("subject_type BLEND_ORDER requires exactly blend_order_id")
    readings = req_list(body, "readings")

    if subject_type == "FILL_LOT":
        subject = store.fill_lots.get(fill_lot_id)
        if subject is None:
            not_found("fill lot not found")
        actor_anchor = subject["completed_by_user_id"]
    else:
        subject = store.blends.get(blend_order_id)
        if subject is None:
            not_found("blend order not found")
        actor_anchor = subject["blended_by_user_id"]

    if subject["status"] != "AWAITING_ANALYSIS":
        raise ApiError(ERR_ANALYSIS_INVALID_STATE, 409, "subject is not AWAITING_ANALYSIS")
    if actor_anchor is not None and uid == actor_anchor:
        raise ApiError(ERR_SEGREGATION, 403, "analyst must differ from the completing operator")

    if subject_type == "FILL_LOT":
        band = _compute_fill_lot_result(subject, readings)
    else:
        band = _compute_blend_result(subject, readings)
    # Band OK maps to the PASS analysis result; MARGINAL/FAIL carry through.
    result = "PASS" if band == "OK" else band

    a = base_record()
    a.update(
        {
            "subject_type": subject_type,
            "fill_lot_id": fill_lot_id,
            "blend_order_id": blend_order_id,
            "readings": readings,
            "result": result,
            "recorded_by_user_id": uid,
            "overridden_by_user_id": None,
            "status": "RECORDED",
        }
    )
    store.analyses[a["id"]] = a

    touched = {a["id"]}
    if result == "PASS":
        release_subject(a, touched)
    elif result == "FAIL":
        if subject_type == "FILL_LOT":
            fail_fill_lot(subject, touched)
        else:
            subject["status"] = "REWORK"
            touch(subject)
    # MARGINAL: subject stays AWAITING_ANALYSIS
    return success(analysis_out(a), status=201)


@bp.get("/api/purity-analyses")
@locked
def list_analyses():
    require_roles(*ANY_ROLE)
    return list_response(
        store.analyses.values(),
        analysis_out,
        [("fill_lot_id", "fill_lot_id"), ("blend_order_id", "blend_order_id"), ("result", "result")],
    )


@bp.get("/api/purity-analyses/<analysisId>")
@locked
def get_analysis(analysisId):
    require_roles(*ANY_ROLE)
    a = store.analyses.get(analysisId)
    if a is None:
        not_found("analysis not found")
    return success(analysis_out(a))


@bp.post("/api/purity-analyses/<analysisId>/override")
@locked
def override_analysis(analysisId):
    uid, _ = require_roles("QualityManager")
    get_body()
    a = store.analyses.get(analysisId)
    if a is None:
        not_found("analysis not found")
    if a["status"] != "RECORDED" or a["result"] != "MARGINAL":
        raise ApiError(ERR_ANALYSIS_INVALID_STATE, 409, "only a RECORDED MARGINAL analysis may be overridden")
    if uid == a["recorded_by_user_id"]:
        raise ApiError(ERR_SEGREGATION, 403, "override actor must differ from the recording analyst")
    a["status"] = "OVERRIDDEN"
    a["result"] = "PASS_OVERRIDE"
    a["overridden_by_user_id"] = uid
    touch(a)
    touched = {a["id"]}
    release_subject(a, touched)
    return success(analysis_out(a))
