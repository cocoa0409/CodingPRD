"""Client endpoints: intake, read and consent changes."""

from flask import Blueprint

from db import db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
                        ROLE_LEGAL_ADVOCATE, ROLE_PRIVACY_OFFICER, ROLE_SHELTER_MANAGER,
                        auth)
from response import created, ok
from routes.common import get_client, insert
from validation import bad, get_body, opt_bool, opt_enum, opt_int, req_enum, req_int, req_str

bp = Blueprint("clients", __name__)

CONSENT_VALUES = ("GRANTED", "DENIED", "REVOKED")
INTAKE_CONSENT_VALUES = ("GRANTED", "DENIED")

READ_ALL = (ROLE_HOTLINE_ADVOCATE, ROLE_SHELTER_MANAGER, ROLE_LEGAL_ADVOCATE,
            ROLE_HOUSING_SPECIALIST, ROLE_PRIVACY_OFFICER, ROLE_AGENCY_ADMIN)


@bp.post("/clients")
def create_client():
    auth((ROLE_HOTLINE_ADVOCATE, ROLE_AGENCY_ADMIN))
    body = get_body()
    client_code = req_str(body, "client_code", 3, 40)
    legal_name = req_str(body, "legal_name", 1, 120)
    household_size = req_int(body, "household_size", 1, 12)
    minor_children_count = opt_int(body, "minor_children_count", 0, 0, 10)
    if minor_children_count > household_size - 1:
        raise bad("minor_children_count may not exceed household_size - 1")
    accessibility_required = opt_bool(body, "accessibility_required", False)
    location_confidential = opt_bool(body, "location_confidential", True)
    consent = opt_enum(body, "hmis_disclosure_consent", INTAKE_CONSENT_VALUES, "DENIED")

    for existing in db.clients.values():
        if existing["client_code"] == client_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "client_code is already in use")

    client = insert("clients", {
        "client_code": client_code,
        "legal_name": legal_name,
        "household_size": household_size,
        "minor_children_count": minor_children_count,
        "accessibility_required": accessibility_required,
        "location_confidential": location_confidential,
        "hmis_disclosure_consent": consent,
        "status": "INTAKE",
        "confidentiality_posture": "NORMAL",
        "current_danger_score": None,
        "current_risk_band": None,
        "protective_order_active": False,
        "resource_referral_count": 0,
    })
    return created(public(client))


@bp.get("/clients/<client_id>")
def read_client(client_id):
    auth(READ_ALL)
    return ok(public(get_client(client_id)))


@bp.post("/clients/<client_id>/consent")
def change_consent(client_id):
    auth((ROLE_PRIVACY_OFFICER, ROLE_AGENCY_ADMIN))
    body = get_body()
    consent = req_enum(body, "hmis_disclosure_consent", CONSENT_VALUES)
    client = get_client(client_id)
    client["hmis_disclosure_consent"] = consent
    touch(client)
    return ok(public(client))
