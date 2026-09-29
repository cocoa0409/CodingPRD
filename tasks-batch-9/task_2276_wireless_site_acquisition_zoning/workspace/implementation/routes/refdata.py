"""Program reference data: landlords, jurisdictions and utility providers."""

from decimal import Decimal

from flask import Blueprint

import services
from db import db, new_record, serialize, touch
from response import created, ok
from routes.common import fetch
from validation import (ALL_ROLES, BOOLEAN, INTEGER, NUMBER, ROLE_AGENT,
                        ROLE_CONSTRUCTION, ROLE_DIRECTOR, ROLE_PLANNER, STRING,
                        authenticate, f, validate_body)

bp = Blueprint("refdata", __name__)

ENTITY_TYPES = ["INDIVIDUAL", "LLC", "REIT", "MUNICIPALITY", "TRIBAL_AUTHORITY"]
STANDINGS = ["ACTIVE", "SUSPENDED", "BLACKLISTED"]


# ---------------------------------------------------------------------------
# landlords
# ---------------------------------------------------------------------------

@bp.post("/landlords")
def create_landlord():
    authenticate([ROLE_AGENT])
    body = validate_body([
        f("legal_name", STRING),
        f("entity_type", STRING, enum=ENTITY_TYPES),
        f("contact_email", STRING),
        f("market_code", STRING),
        f("outreach_optout", BOOLEAN, required=False, default=False),
    ])
    landlord = new_record({
        "legal_name": body["legal_name"],
        "entity_type": body["entity_type"],
        "contact_email": body["contact_email"],
        "market_code": body["market_code"],
        "outreach_optout": body["outreach_optout"],
        "standing": "ACTIVE",
        "executed_lease_count": 0,
    })
    db.landlords[landlord["id"]] = landlord
    return created(serialize(landlord))


@bp.get("/landlords/<landlord_id>")
def read_landlord(landlord_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("landlords", landlord_id)))


@bp.post("/landlords/<landlord_id>/standing")
def set_standing(landlord_id):
    authenticate([ROLE_DIRECTOR])
    body = validate_body([
        f("standing", STRING, enum=STANDINGS),
        f("reason", STRING, required=False),
    ])
    landlord = fetch("landlords", landlord_id)

    standing = body["standing"]
    changed = landlord["standing"] != standing
    landlord["standing"] = standing
    if standing == "BLACKLISTED":
        services.blacklist_cascade(landlord)
    if services.refresh_landlord_lease_count(landlord, defer_touch=True):
        changed = True
    if changed:
        touch(landlord)
    return ok(serialize(landlord))


# ---------------------------------------------------------------------------
# jurisdictions
# ---------------------------------------------------------------------------

@bp.post("/jurisdictions")
def create_jurisdiction():
    authenticate([ROLE_PLANNER])
    body = validate_body([
        f("name", STRING),
        f("market_code", STRING),
        f("by_right_review_days", INTEGER, ge=1),
        f("conditional_use_review_days", INTEGER, ge=1),
        f("variance_review_days", INTEGER, ge=1),
        f("hearing_cadence_days", INTEGER, ge=1),
        f("requires_visual_simulation", BOOLEAN),
        f("min_visual_simulations", INTEGER, required=False, ge=0, default=2),
        f("max_continuances", INTEGER, ge=0),
        f("historic_district_flag", BOOLEAN),
        f("tribal_consultation_required", BOOLEAN),
        f("historical_delay_factor", NUMBER, ge=1),
        f("appeal_window_days", INTEGER, ge=0),
    ])
    jurisdiction = new_record({
        "name": body["name"],
        "market_code": body["market_code"],
        "by_right_review_days": body["by_right_review_days"],
        "conditional_use_review_days": body["conditional_use_review_days"],
        "variance_review_days": body["variance_review_days"],
        "hearing_cadence_days": body["hearing_cadence_days"],
        "requires_visual_simulation": body["requires_visual_simulation"],
        "min_visual_simulations": body["min_visual_simulations"],
        "max_continuances": body["max_continuances"],
        "historic_district_flag": body["historic_district_flag"],
        "tribal_consultation_required": body["tribal_consultation_required"],
        "historical_delay_factor": body["historical_delay_factor"],
        "appeal_window_days": body["appeal_window_days"],
    })
    db.jurisdictions[jurisdiction["id"]] = jurisdiction
    return created(serialize(jurisdiction))


@bp.get("/jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("jurisdictions", jurisdiction_id)))


# ---------------------------------------------------------------------------
# utility providers
# ---------------------------------------------------------------------------

@bp.post("/utility-providers")
def create_provider():
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([
        f("name", STRING),
        f("market_code", STRING),
        f("concurrent_crew_capacity", INTEGER, ge=1),
        f("quoted_interval_days", INTEGER, ge=0),
    ])
    provider = new_record({
        "name": body["name"],
        "market_code": body["market_code"],
        "concurrent_crew_capacity": body["concurrent_crew_capacity"],
        "quoted_interval_days": body["quoted_interval_days"],
        "committed_crew_days": 0,
    })
    db.utility_providers[provider["id"]] = provider
    return created(serialize(provider))


@bp.get("/utility-providers/<provider_id>")
def read_provider(provider_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("utility_providers", provider_id)))
