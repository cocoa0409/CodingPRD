"""PFCApplication: single-resource read and director decision."""
from flask import Blueprint

import errors
import helpers
from db import store
from helpers import (authenticate, get_path, json_body, req_string, opt_string,
                     READ_ROLES, PFC_DECISIONS_ACCEPT, PFC_DECISIONS_REJECT)
from response import success_object
from services import ser_pfc, touch, check_fy_open_guard

bp = Blueprint("pfc", __name__)


def _get_pfc(pfc_id):
    return get_path(store.pfc_applications, pfc_id, "PFCApplication")


@bp.get("/airport/pfc_applications/<pfc_id>")
def get_pfc(pfc_id):
    authenticate(READ_ROLES)
    app = _get_pfc(pfc_id)
    return success_object(ser_pfc(app))


@bp.post("/airport/pfc_applications/<pfc_id>/decide")
def decide_pfc(pfc_id):
    authenticate(("AirportDirector",))
    app = _get_pfc(pfc_id)
    body = json_body()
    decision = req_string(body, "decision")
    if decision in PFC_DECISIONS_ACCEPT:
        verdict = "ACCEPTED"
    elif decision in PFC_DECISIONS_REJECT:
        verdict = "REJECTED"
    else:
        raise errors.invalid_request(
            "Field 'decision' must be one of ['ACCEPT', 'REJECT']")
    rejection_reason = opt_string(body, "rejection_reason")
    if app["status"] != "SUBMITTED":
        raise errors.invalid_state("Only a SUBMITTED application can be decided")
    fy = store.fiscal_years[app["fiscal_year_id"]]
    check_fy_open_guard(fy)
    app["status"] = verdict
    app["rejection_reason"] = rejection_reason if verdict == "REJECTED" else None
    touch(app)
    return success_object(ser_pfc(app))
