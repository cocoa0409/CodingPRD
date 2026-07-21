import re
from flask import Blueprint
from db import db, new_common_fields, now, fmt_ts, touch
from errors import err
from middleware import get_caller, require_role, require_ownership
from response import object_response
from validate import body, require_str, require_int, require_enum
import lookups

properties_bp = Blueprint("properties", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
PROPERTY_TYPES = {"SINGLE_FAMILY", "MULTI_FAMILY", "CONDO"}
DEFAULT_COOLING_OFF_DAYS = 30


@properties_bp.post("/properties")
def create_property():
    caller = get_caller()
    require_role(caller, {"Landlord"})
    b = body()
    landlord_id = require_str(b, "landlord_id")
    address_line1 = require_str(b, "address_line1")
    city = require_str(b, "city")
    state_code = require_str(b, "state_code")
    monthly_rent_cents = require_int(b, "monthly_rent_cents", positive=True)
    property_type = require_enum(b, "property_type", PROPERTY_TYPES)

    if not STATE_CODE_RE.match(state_code):
        raise err("ERR_VALIDATION", "state_code must be a 2-letter uppercase code.")

    landlord = lookups.get_landlord(landlord_id)
    require_ownership(caller, landlord["id"], "Landlord")

    prop = {
        **new_common_fields(),
        "landlord_id": landlord_id,
        "address_line1": address_line1,
        "city": city,
        "state_code": state_code,
        "monthly_rent_cents": monthly_rent_cents,
        "property_type": property_type,
        "program_status": "PENDING_REVIEW",
        "terminated_at": None,
        "total_paid_claims_cents": 0,
    }
    db.properties[prop["id"]] = prop
    return object_response(prop, 201)


@properties_bp.get("/properties/<property_id>")
def get_property(property_id):
    caller = get_caller()
    require_role(caller, {"Landlord", "UnderwritingAgent", "ClaimsAdjuster", "ComplianceOfficer", "PlatformAdmin"})
    prop = lookups.get_property(property_id)
    require_ownership(caller, prop["landlord_id"], "Landlord")
    return object_response(prop)


@properties_bp.post("/properties/<property_id>/program-status")
def property_program_status(property_id):
    caller = get_caller()
    require_role(caller, {"ComplianceOfficer"})
    b = body()
    action = require_enum(b, "action", {"ACTIVATE", "TERMINATE"})

    prop = lookups.get_property(property_id)

    if action == "ACTIVATE":
        if prop["program_status"] not in ("PENDING_REVIEW", "TERMINATED"):
            raise err("ERR_INVALID_STATE", "Property cannot be activated from its current state.")
        if prop["program_status"] == "TERMINATED":
            rule = db.state_compliance_rules.get(prop["state_code"])
            cooling_off_days = rule["cooling_off_buffer_days"] if rule else DEFAULT_COOLING_OFF_DAYS
            from datetime import timedelta
            from db import parse_ts
            terminated_at = parse_ts(prop["terminated_at"])
            earliest_reactivation = terminated_at + timedelta(days=cooling_off_days)
            if now() < earliest_reactivation:
                raise err("ERR_REENROLLMENT_COOLDOWN_ACTIVE", "Cooling-off buffer has not elapsed yet.")
        prop["program_status"] = "ACTIVE"
        prop["terminated_at"] = None
        touch(prop)
    else:  # TERMINATE
        if prop["program_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Property cannot be terminated from its current state.")
        prop["program_status"] = "TERMINATED"
        prop["terminated_at"] = fmt_ts(now())
        touch(prop)

    return object_response(prop)
