"""Dispersal activities: logging, review, close; take-permit accounting hooks."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, biologist_is_senior
from constants import DISPERSAL_METHODS, DISPERSAL_STATUSES
from db import store
from services import recompute_permit_take
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, parse_datetime, parse_date)

bp = Blueprint("dispersals", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent")


def _get_dispersal(rid):
    return get_or_404(store.dispersal_activities, rid, "dispersal activity")


def _permit_of(d):
    pid = d.get("take_permit_id")
    return store.take_permits.get(pid) if pid else None


@bp.post("/dispersal-activities")
def create_dispersal():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("performed_by_biologist_id", "str", True),
        ("performed_at", "datetime", True),
        ("method", "enum", True, {"values": DISPERSAL_METHODS}),
        ("species_id", "str", True),
        ("animals_dispersed", "int", True, {"min": 0}),
        ("animals_taken_lethal", "int", True, {"min": 0}),
        ("take_permit_id", "str", False),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    check_fk("performed_by_biologist_id", data["performed_by_biologist_id"], store.biologists, "biologist")
    species = check_fk("species_id", data["species_id"], store.species, "species")
    permit = None
    if data.get("take_permit_id") is not None:
        permit = check_fk("take_permit_id", data["take_permit_id"], store.take_permits, "take permit")

    lethal = data["animals_taken_lethal"] > 0 or data["method"] == "LETHAL_AMMO"
    if lethal:
        # priority 11: permit presence + ACTIVE + same airport/species + budget headroom
        if permit is None:
            raise E.ApiError(E.ERR_TAKE_PERMIT_REQUIRED,
                             "a take_permit_id is required when animals_taken_lethal > 0 or method is LETHAL_AMMO", 422)
        if (permit["status"] != "ACTIVE"
                or permit["airport_id"] != data["airport_id"]
                or permit["species_id"] != data["species_id"]
                or permit["take_consumed"] + data["animals_taken_lethal"] > permit["authorized_take_total"]):
            raise E.ApiError(E.ERR_TAKE_PERMIT_REQUIRED,
                             "referenced take permit is not ACTIVE for this airport and species "
                             "or lacks sufficient remaining authorized take", 422)
    # priority 14: federal permit requirement for lethal take of protected species
    if data["method"] == "LETHAL_AMMO" and species["is_protected_federally"]:
        issuer = store.regulators.get(permit["issued_by_regulator_id"]) if permit else None
        if issuer is None or issuer["agency"] != "USFWS":
            raise E.ApiError(E.ERR_FEDERAL_PERMIT_REQUIRED,
                             "lethal take of a federally protected species requires a USFWS-issued permit", 422)
    # priority 18: performed_at within [valid_from, valid_to] inclusive
    if permit is not None:
        perf_date = data["performed_at"].date()
        if not (parse_date(permit["valid_from"]) <= perf_date <= parse_date(permit["valid_to"])):
            raise E.ApiError(E.ERR_PERMIT_OUTSIDE_WINDOW,
                             "dispersal performed_at is outside the permit validity window", 422)

    rec = new_entity(store.dispersal_activities, {
        "airport_id": data["airport_id"],
        "performed_by_biologist_id": data["performed_by_biologist_id"],
        "performed_at": data["performed_at"],
        "method": data["method"],
        "species_id": data["species_id"],
        "animals_dispersed": data["animals_dispersed"],
        "animals_taken_lethal": data["animals_taken_lethal"],
        "take_permit_id": data.get("take_permit_id"),
        "status": "LOGGED",
    })
    return ok_object(serialize(rec), 201)


@bp.get("/dispersal-activities")
def list_dispersals():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    method = args.get("method")
    if status is not None and status not in DISPERSAL_STATUSES:
        raise E.invalid_enum("status", status)
    if method is not None and method not in DISPERSAL_METHODS:
        raise E.invalid_enum("method", method)
    after = args.get("performed_after")
    before = args.get("performed_before")
    try:
        after_dt = parse_datetime(after) if after else None
        before_dt = parse_datetime(before) if before else None
    except Exception:
        raise E.invalid_request("performed_after / performed_before must be ISO8601 datetimes")
    rows = [d for d in store.dispersal_activities.values()
            if (args.get("airport_id") is None or d["airport_id"] == args.get("airport_id"))
            and (args.get("performed_by_biologist_id") is None or d["performed_by_biologist_id"] == args.get("performed_by_biologist_id"))
            and (status is None or d["status"] == status)
            and (method is None or d["method"] == method)
            and (args.get("species_id") is None or d["species_id"] == args.get("species_id"))
            and (args.get("take_permit_id") is None or d.get("take_permit_id") == args.get("take_permit_id"))
            and (after_dt is None or d["performed_at"] >= after_dt)
            and (before_dt is None or d["performed_at"] <= before_dt)]
    return list_response(rows)


@bp.get("/dispersal-activities/<rid>")
def get_dispersal(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_dispersal(rid)))


@bp.post("/dispersal-activities/<rid>/review")
def review_dispersal(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    d = _get_dispersal(rid)
    if d["status"] != "LOGGED":
        raise E.invalid_state("dispersal activity must be in LOGGED to review")
    if uid == d["performed_by_biologist_id"]:
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         "the performer cannot review their own dispersal activity", 403)
    d["status"] = "REVIEWED"
    touch(d)
    return ok_object(serialize(d))


@bp.post("/dispersal-activities/<rid>/close")
def close_dispersal(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    d = _get_dispersal(rid)
    if d["status"] not in ("REVIEWED", "FLAGGED"):
        raise E.invalid_state("dispersal activity must be in REVIEWED or FLAGGED to close")
    if not biologist_is_senior(uid):
        raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                         "closing a dispersal activity requires a senior biologist", 403)
    if d["status"] == "REVIEWED" and d["animals_taken_lethal"] > 0:
        permit = _permit_of(d)
        # priority 11: permit still ACTIVE
        if permit is None or permit["status"] != "ACTIVE":
            raise E.ApiError(E.ERR_TAKE_PERMIT_REQUIRED,
                             "referenced take permit must be in ACTIVE status to close with lethal take", 422)
        # priority 13: budget overrun
        if permit["take_consumed"] + d["animals_taken_lethal"] > permit["authorized_take_total"]:
            raise E.ApiError(E.ERR_TAKE_BUDGET_EXCEEDED,
                             "take_consumed + animals_taken_lethal would exceed authorized_take_total", 422)
    if d["status"] == "FLAGGED" and d["animals_taken_lethal"] > 0:
        permit = _permit_of(d)
        if permit is not None and permit["status"] != "REVOKED":
            raise E.ApiError(E.ERR_TAKE_PERMIT_REQUIRED,
                             "a FLAGGED dispersal may only close after its permit is REVOKED", 422)
    was_reviewed = d["status"] == "REVIEWED"
    d["status"] = "CLOSED"
    touch(d)
    # authoritative take reconciliation on closure with lethal take
    if was_reviewed and d["animals_taken_lethal"] > 0:
        permit = _permit_of(d)
        if permit is not None:
            recompute_permit_take(permit)
    return ok_object(serialize(d))
