"""Establishment endpoints: register, read, OCC-pinned profile update."""
import uuid

from flask import Blueprint

from db import STORE, now, next_seq
from errors import ApiError, ERR_STALE_VERSION
from middleware import auth, require_roles, forbid_unless, get_or_404
from response import success
from services.calculations import risk_classification, RISK_CLASSES
from services.posture import touch_establishment
from services.serializers import ser_establishment
from validation import body_json, v_str, v_int, v_bool, v_enum

bp = Blueprint("establishments", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact"]


@bp.post("/establishments")
def create_establishment():
    uid, role = auth()
    body = body_json()
    name = v_str(body, "name")
    street = v_str(body, "street_address")
    seats = v_int(body, "seating_capacity", min_val=0)
    fryers = v_int(body, "fryer_count", min_val=0)
    cuisine = v_enum(body, "cuisine_profile", RISK_CLASSES)
    charb = v_bool(body, "has_charbroiler", required=False, default=False)
    require_roles(role, ["ProgramAdmin"])
    current = now()
    score, rclass = risk_classification(seats, fryers, charb, cuisine)
    est = {
        "id": str(uuid.uuid4()),
        "name": name,
        "street_address": street,
        "seating_capacity": seats,
        "fryer_count": fryers,
        "has_charbroiler": charb,
        "cuisine_profile": cuisine,
        "risk_score": score,
        "risk_class": rclass,
        "compliance_status": "COMPLIANT",
        "last_verified_pump_at": None,
        "variance_override_frequency_days": None,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["establishments"][est["id"]] = est
    return success(ser_establishment(est), 201)


@bp.get("/establishments/<eid>")
def get_establishment(eid):
    uid, role = auth()
    require_roles(role, READERS)
    if role == "FseContact":
        forbid_unless(uid == eid)
    est = get_or_404("establishments", eid)
    return success(ser_establishment(est))


@bp.patch("/establishments/<eid>")
def patch_establishment(eid):
    uid, role = auth()
    body = body_json()
    expected = v_int(body, "expected_establishment_version")
    name = v_str(body, "name", required=False)
    street = v_str(body, "street_address", required=False)
    seats = v_int(body, "seating_capacity", required=False, min_val=0)
    fryers = v_int(body, "fryer_count", required=False, min_val=0)
    charb = v_bool(body, "has_charbroiler", required=False)
    cuisine = v_enum(body, "cuisine_profile", RISK_CLASSES, required=False)
    require_roles(role, ["ProgramAdmin"])
    est = get_or_404("establishments", eid)
    if expected != est["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_establishment_version does not match current version")
    current = now()
    if name is not None:
        est["name"] = name
    if street is not None:
        est["street_address"] = street
    if seats is not None:
        est["seating_capacity"] = seats
    if fryers is not None:
        est["fryer_count"] = fryers
    if charb is not None:
        est["has_charbroiler"] = charb
    if cuisine is not None:
        est["cuisine_profile"] = cuisine
    est["risk_score"], est["risk_class"] = risk_classification(
        est["seating_capacity"], est["fryer_count"], est["has_charbroiler"], est["cuisine_profile"]
    )
    # Single version advance for the whole update, posture recompute included.
    touch_establishment(est, current, bump=True)
    return success(ser_establishment(est))
