"""RatingCriteriaConfig endpoints (PRD 3.2): band validation and the
exactly-one-ACTIVE invariant with supersession."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_CONFIG_BANDS_INVALID,
    ERR_RATING_CONFIG_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.calculations import config_bands_valid
from services.core import new_record, public, touch
from util import CLOCK
from validate import check_unknown_fields, get_body, opt_int, req_str, require_path

bp = Blueprint("rating_criteria_configs", __name__)

CREATE_FIELDS = {"name", "critical_min", "high_min", "moderate_min"}


def _check_bands(cfg_or_vals):
    if isinstance(cfg_or_vals, dict):
        moderate_min = cfg_or_vals["moderate_min"]
        high_min = cfg_or_vals["high_min"]
        critical_min = cfg_or_vals["critical_min"]
    else:
        moderate_min, high_min, critical_min = cfg_or_vals
    if not config_bands_valid(moderate_min, high_min, critical_min):
        raise_error(ERR_CONFIG_BANDS_INVALID,
                    "bands must satisfy 1 <= moderate_min < high_min < critical_min <= 25")


@bp.post("/audit/rating-criteria-configs")
def create_config():
    authorized(["AuditAdmin"])
    body = get_body()
    check_unknown_fields(body, CREATE_FIELDS)
    name = req_str(body, "name")
    critical_min = opt_int(body, "critical_min", 20)
    high_min = opt_int(body, "high_min", 12)
    moderate_min = opt_int(body, "moderate_min", 6)
    _check_bands((moderate_min, high_min, critical_min))
    rec = new_record("rating_criteria_configs", {
        "name": name,
        "critical_min": critical_min,
        "high_min": high_min,
        "moderate_min": moderate_min,
        "status": "DRAFT",
        "activated_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/rating-criteria-configs/<rid>")
def get_config(rid):
    return get_one("rating_criteria_configs", rid)


@bp.post("/audit/rating-criteria-configs/<rid>/activate")
def activate_config(rid):
    authorized(["AuditAdmin"])
    cfg = require_path("rating_criteria_configs", rid)
    # Stage 7: must be DRAFT
    if cfg["status"] != "DRAFT":
        raise_error(ERR_RATING_CONFIG_INVALID_STATE, "config is not DRAFT")
    # Stage 9: bands re-validated at activation
    _check_bands(cfg)
    # Exactly-one-ACTIVE invariant: supersede the incumbent
    for other in db["rating_criteria_configs"].values():
        if other["id"] != cfg["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)
    cfg["status"] = "ACTIVE"
    cfg["activated_at"] = CLOCK.now_iso()
    touch(cfg)
    return success_object(public(cfg))
