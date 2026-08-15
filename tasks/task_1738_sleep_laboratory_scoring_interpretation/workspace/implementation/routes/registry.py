"""Lab resource registry: beds, technologists, scorers, physicians (PRD 3.3)."""
from flask import Blueprint

from errors import raise_error, ERR_SCORER_NOT_REMEDIATION
from middleware import authorized
from response import success_object
from routes.helpers import get_one, public
from services.core import new_record, touch
from validate import get_body, req_str, req_enum, opt_bool, require_path_resource

bp = Blueprint("registry", __name__)


@bp.post("/beds")
def create_bed():
    authorized(["LabDirector"])
    body = get_body()
    room_label = req_str(body, "room_label")
    titration_capable = opt_bool(body, "titration_capable", False)
    is_active = opt_bool(body, "is_active", True)
    rec = new_record("beds", {
        "room_label": room_label,
        "titration_capable": titration_capable,
        "is_active": is_active,
    })
    return success_object(public(rec), status=201)


@bp.post("/technologists")
def create_technologist():
    authorized(["LabDirector"])
    body = get_body()
    full_name = req_str(body, "full_name")
    credential = req_enum(body, "credential", {"RPSGT", "CPSGT"})
    is_active = opt_bool(body, "is_active", True)
    rec = new_record("technologists", {
        "full_name": full_name,
        "credential": credential,
        "is_active": is_active,
    })
    return success_object(public(rec), status=201)


@bp.post("/scorers")
def create_scorer():
    authorized(["LabDirector"])
    body = get_body()
    full_name = req_str(body, "full_name")
    credential = req_enum(body, "credential", {"RPSGT", "RST"})
    npi = req_str(body, "npi")
    reliability_pool = opt_bool(body, "reliability_pool", False)
    is_active = opt_bool(body, "is_active", True)
    rec = new_record("scorers", {
        "full_name": full_name,
        "credential": credential,
        "npi": npi,
        "reliability_pool": reliability_pool,
        "is_active": is_active,
        "consecutive_nonconcordant": 0,
        "rolling_agreement_index": None,
        "reliability_status": "PROVISIONAL",
    })
    return success_object(public(rec), status=201)


@bp.get("/scorers/<scorerId>")
def get_scorer(scorerId):
    return get_one("scorers", scorerId)


@bp.post("/scorers/<scorerId>/reinstate")
def reinstate_scorer(scorerId):
    authorized(["LabDirector"])
    scorer = require_path_resource("scorers", scorerId)
    if scorer["reliability_status"] != "REMEDIATION":
        raise_error(ERR_SCORER_NOT_REMEDIATION,
                    f"scorer reliability_status {scorer['reliability_status']} is not REMEDIATION")
    scorer["reliability_status"] = "PROVISIONAL"
    scorer["consecutive_nonconcordant"] = 0
    touch(scorer)
    return success_object(public(scorer))


@bp.post("/physicians")
def create_physician():
    authorized(["LabDirector"])
    body = get_body()
    full_name = req_str(body, "full_name")
    npi = req_str(body, "npi")
    board_certified = opt_bool(body, "board_certified", False)
    is_active = opt_bool(body, "is_active", True)
    rec = new_record("physicians", {
        "full_name": full_name,
        "npi": npi,
        "board_certified": board_certified,
        "is_active": is_active,
    })
    return success_object(public(rec), status=201)
