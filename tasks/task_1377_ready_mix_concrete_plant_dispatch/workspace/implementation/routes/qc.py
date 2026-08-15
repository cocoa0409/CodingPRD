"""QC routes: cylinder set retrieval, breaks, certification."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from routes.catalog import get_or_404
from services import calc

bp = Blueprint("qc", __name__)

QCTECH = ["QCTech"]


@bp.get("/v1/cylinder-sets/<rid>")
def get_cylinder_set(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("cylinder_sets", rid))


@bp.post("/v1/cylinder-sets/<rid>/breaks")
def record_break(rid):
    user_id, _ = mw.require_auth(QCTECH)
    rec = get_or_404("cylinder_sets", rid)
    body = mw.get_json_body()
    break_type = mw.require_string(body, "break_type")
    if break_type not in ("SEVEN_DAY", "TWENTY_EIGHT_DAY"):
        raise errors.err_validation("break_type must be SEVEN_DAY or TWENTY_EIGHT_DAY")
    strength_psi = mw.require_int(body, "strength_psi")
    if rec["status"] in ("CERTIFIED", "FLAGGED"):
        raise errors.err_already_terminal()
    if break_type == "SEVEN_DAY":
        if rec["status"] != "CURING":
            raise errors.err_invalid_state()
        days = 7
    else:
        if rec["status"] != "SEVEN_DAY_RECORDED":
            raise errors.err_invalid_state()
        days = 28
    if not calc.break_age_ok(rec, days):
        raise errors.err_break_too_early()
    if user_id == rec["cast_by_user_id"]:
        raise errors.err_sod()
    if break_type == "SEVEN_DAY":
        rec["seven_day_strength_psi"] = strength_psi
        rec["seven_day_recorded_by"] = user_id
        rec["status"] = "SEVEN_DAY_RECORDED"
    else:
        rec["final_strength_psi"] = strength_psi
        rec["final_recorded_by"] = user_id
        rec["status"] = "FINAL_RECORDED"
    mw.touch(rec)
    return response.success_object(rec)


@bp.post("/v1/cylinder-sets/<rid>/certify")
def certify(rid):
    user_id, _ = mw.require_auth(QCTECH)
    rec = get_or_404("cylinder_sets", rid)
    if rec["status"] in ("CERTIFIED", "FLAGGED"):
        raise errors.err_already_terminal()
    if rec["status"] != "FINAL_RECORDED":
        raise errors.err_invalid_state()
    load = get_or_404("loads", rec["load_id"])
    if load["status"] != "COMPLETED":
        raise errors.err_invalid_state()
    if user_id == rec["cast_by_user_id"] or user_id == rec["final_recorded_by"]:
        raise errors.err_sod()
    passed = calc.acceptance_passed(rec)
    rec["acceptance_passed"] = passed
    rec["certified_by_user_id"] = user_id
    if passed:
        rec["status"] = "CERTIFIED"
    else:
        rec["status"] = "FLAGGED"
        if rec["acceptance_basis"] == "DESIGN_BASIS":
            load["strength_liability"] = "PLANT"
        else:
            additions = [w for w in stores["water_additions"].values()
                         if w["load_id"] == load["id"]]
            any_auth = any(w["customer_authorized"] for w in additions)
            load["strength_liability"] = "CUSTOMER" if any_auth else "PLANT"
        mw.touch(load)
    mw.touch(rec)
    return response.success_object(rec)
