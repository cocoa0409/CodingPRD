"""Dwellings and the self-attested retrofit (PRD 3.2)."""

from flask import Blueprint

import envelope
import guards
import store
from errors import ApiError

bp = Blueprint("dwellings", __name__)

DWELLING_LIMIT_MIN_CENTS = 5000000
DWELLING_LIMIT_MAX_CENTS = 300000000
YEAR_BUILT_MIN = 1850
YEAR_BUILT_MAX = 2026


@bp.post("/dwellings")
def create_dwelling():
    role = guards.auth(("ProgramAdmin", "Policyholder"))
    body = guards.body()
    fks = guards.body_fks(body, ("policyholder_id",))
    owner = fks.get("policyholder_id")
    if role == "Policyholder" and owner is not None:
        guards.owner_must_be(owner["id"])
    guards.required(body, ("policyholder_id", "street_address", "county_hazard_tier",
                           "soil_class", "structure_type", "year_built",
                           "dwelling_limit_cents"))
    if not isinstance(body["street_address"], str):
        raise ApiError("ERR_INVALID_REQUEST")
    tier = guards.enum(body, "county_hazard_tier", "county_hazard_tier")
    soil = guards.enum(body, "soil_class", "soil_class")
    structure = guards.enum(body, "structure_type", "structure_type")
    year_built = guards.integer(body, "year_built", minimum=YEAR_BUILT_MIN,
                               maximum=YEAR_BUILT_MAX)
    limit = guards.integer(body, "dwelling_limit_cents",
                           minimum=DWELLING_LIMIT_MIN_CENTS,
                           maximum=DWELLING_LIMIT_MAX_CENTS)
    row = store.insert("dwellings", {
        "policyholder_id": owner["id"],
        "street_address": body["street_address"],
        "county_hazard_tier": tier,
        "soil_class": soil,
        "structure_type": structure,
        "year_built": year_built,
        "dwelling_limit_cents": limit,
        "retrofit_status": "NONE",
        "verified_retrofit_scope": "NONE",
        "grant_lifetime_count": 0,
    })
    return envelope.created(store.public(row))


@bp.get("/dwellings/<row_id>")
def read_dwelling(row_id):
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder",
                        "GrantReviewer", "FieldInspector"))
    row = guards.path_row("dwellings", row_id)
    if role == "Policyholder":
        guards.owner_must_be(row["policyholder_id"])
    return envelope.object_response(store.public(row))


@bp.get("/dwellings")
def list_dwellings():
    role = guards.auth(("ProgramAdmin", "ParticipatingInsurer", "Policyholder"))
    rows = store.all_rows("dwellings")
    if role == "Policyholder":
        acting = guards.acting_id()
        rows = [row for row in rows if row["policyholder_id"] == acting]
    rows = guards.filtered(rows, (("policyholder_id", "policyholder_id"),
                                  ("structure_type", "structure_type"),
                                  ("retrofit_status", "retrofit_status")))
    return envelope.list_response(rows)


@bp.post("/dwellings/<row_id>/declare-retrofit")
def declare_retrofit(row_id):
    guards.auth(("Policyholder",))
    dwelling = guards.path_row("dwellings", row_id)
    guards.owner_must_be(dwelling["policyholder_id"])
    body = guards.body()
    guards.required(body, ("declared_scope",))
    scope = guards.enum(body, "declared_scope", "scope")
    # Rung 76: a physical inspection outranks the owner's word.
    if dwelling["retrofit_status"] == "VERIFIED":
        raise ApiError("ERR_RETROFIT_ALREADY_VERIFIED")
    dwelling["retrofit_status"] = "SELF_DECLARED"
    dwelling["verified_retrofit_scope"] = scope
    store.touch(dwelling)
    return envelope.object_response(store.public(dwelling))
