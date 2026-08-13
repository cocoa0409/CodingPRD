"""Species registry."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, ALL_ROLES
from constants import GUILDS, RISK_TIERS
from db import store
from util import (body, validate_payload, get_or_404, list_response, ok_object,
                  new_entity, serialize)

bp = Blueprint("species", __name__, url_prefix="/wildlife")


@bp.post("/species")
def create_species():
    uid, role = authenticate()
    require_roles(role, ("AirportAdmin",))
    data = validate_payload(body(), [
        ("common_name", "str", True),
        ("scientific_name", "str", True),
        ("guild", "enum", True, {"values": GUILDS}),
        ("risk_tier", "enum", True, {"values": RISK_TIERS}),
        ("body_mass_g", "number", True, {"gt": 0}),
        ("is_protected_federally", "bool", False),
    ])
    for sp in store.species.values():
        if sp["common_name"] == data["common_name"]:
            raise E.invalid_request("common_name must be unique")
    rec = new_entity(store.species, {
        "common_name": data["common_name"],
        "scientific_name": data["scientific_name"],
        "guild": data["guild"],
        "risk_tier": data["risk_tier"],
        "body_mass_g": data["body_mass_g"],
        "is_protected_federally": data.get("is_protected_federally", False),
    })
    return ok_object(serialize(rec), 201)


@bp.get("/species")
def list_species():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    guild = request.args.get("guild")
    tier = request.args.get("risk_tier")
    if guild is not None and guild not in GUILDS:
        raise E.invalid_enum("guild", guild)
    if tier is not None and tier not in RISK_TIERS:
        raise E.invalid_enum("risk_tier", tier)
    rows = [s for s in store.species.values()
            if (guild is None or s["guild"] == guild)
            and (tier is None or s["risk_tier"] == tier)]
    return list_response(rows)


@bp.get("/species/<rid>")
def get_species(rid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    return ok_object(serialize(get_or_404(store.species, rid, "species")))
