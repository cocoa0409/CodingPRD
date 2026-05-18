"""Assessment endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from config import APPEAL_WINDOW_DAYS
from db import store
from errors import raise_error
from middleware import require_roles
from response import success
from routes._helpers import (
    bump,
    check_version,
    get_json_body,
    parse_number,
    require_assessment,
    require_field,
    require_property,
)
from services.calculations import compute_capped_value
from services.serializers import serialize_assessment
from utils import new_uuid, round_half_up

assessments_bp = Blueprint("assessments", __name__)


def _resolve_prior_assessment_id(property_id, roll_year):
    candidates = [
        a for a in store.assessments.values()
        if a["property_id"] == property_id and a["roll_year"] < roll_year
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a["roll_year"], reverse=True)
    return candidates[0]["id"]


@assessments_bp.post("/properties/<property_id>/assessments")
def create_assessment(property_id):
    require_roles({"Assessor"})
    require_property(property_id)
    body = get_json_body()
    roll_year = require_field(body, "roll_year")
    if not isinstance(roll_year, int) or isinstance(roll_year, bool):
        raise_error("ERR_VALIDATION_FAILED", "roll_year must be an integer")
    market_raw = require_field(body, "market_value_at_roll")
    market = parse_number(market_raw, "market_value_at_roll")
    if market < Decimal("0"):
        raise_error("ERR_VALIDATION_FAILED", "market_value_at_roll must be non-negative")
    market = round_half_up(market, 2)

    now = store.clock.now()
    prior_id = _resolve_prior_assessment_id(property_id, roll_year)
    prior_capped = Decimal("0")
    if prior_id:
        prior_capped = Decimal(str(store.assessments[prior_id].get("capped_value", 0) or 0))

    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": property_id,
        "roll_year": roll_year,
        "prior_assessment_id": prior_id,
        "prior_capped_value": prior_capped,
        "market_value_at_roll": market,
        "capped_value": None,
        "cap_reset_applied": None,
        "status": "DRAFT",
        "issued_at": None,
        "finalized_at": None,
        "appeal_window_closes_at": None,
        "issued_by_user_id": None,
    }
    with store.lock:
        store.assessments[rec["id"]] = rec
    return success(serialize_assessment(rec), status_code=201)


@assessments_bp.get("/properties/<property_id>/assessments/<assessment_id>")
def get_assessment(property_id, assessment_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_assessment(property_id, assessment_id)
    return success(serialize_assessment(rec))


@assessments_bp.post("/properties/<property_id>/assessments/<assessment_id>/issue")
def issue_assessment(property_id, assessment_id):
    require_roles({"Assessor"})
    rec = require_assessment(property_id, assessment_id)
    body = get_json_body()

    # State check
    if rec["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "assessment is not in DRAFT")

    # Duplicate roll year
    for other in store.assessments.values():
        if other["id"] == rec["id"]:
            continue
        if other["property_id"] != property_id:
            continue
        if other["roll_year"] != rec["roll_year"]:
            continue
        if other["status"] in ("ISSUED", "UNDER_APPEAL", "FINALIZED"):
            raise_error("ERR_DUPLICATE_ROLL_YEAR")

    check_version(rec, body)

    prop = store.properties[property_id]
    capped, reset, prior_capped = compute_capped_value(rec, prop)

    with store.lock:
        now = store.clock.now()
        rec["status"] = "ISSUED"
        rec["issued_at"] = now
        rec["appeal_window_closes_at"] = now + timedelta(days=APPEAL_WINDOW_DAYS)
        rec["capped_value"] = capped
        rec["cap_reset_applied"] = reset
        rec["prior_capped_value"] = prior_capped
        rec["issued_by_user_id"] = g.user_id
        bump(rec)
        # Side-effect: Property.current_assessment_year
        prop["current_assessment_year"] = rec["roll_year"]
        bump(prop)

    return success(serialize_assessment(rec))
