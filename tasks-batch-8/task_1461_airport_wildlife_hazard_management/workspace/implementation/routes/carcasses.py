"""Carcass records: creation (manual), listing, and the identification lifecycle."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, biologist_is_senior
from constants import ID_METHODS, DISPOSAL_METHODS, CARCASS_STATUSES
from db import store
from services import recompute_airport
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, now)

bp = Blueprint("carcasses", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent")


def _get_carcass(rid):
    return get_or_404(store.carcass_records, rid, "carcass record")


def _parent_strike(carcass):
    return store.strike_reports.get(carcass["strike_report_id"])


def _cascade_amend(carcass):
    """If final species differs from the parent strike's species, cascade the
    parent WildlifeStrikeReport to AMENDED and refresh the airport rollups."""
    strike = _parent_strike(carcass)
    if strike is None:
        return
    if carcass["species_id_final"] and carcass["species_id_final"] != strike["species_id"]:
        strike["species_id"] = carcass["species_id_final"]
        if strike["status"] != "AMENDED":
            strike["status"] = "AMENDED"
        touch(strike)
        ap = store.airports.get(strike["airport_id"])
        if ap:
            recompute_airport(ap)


def _senior_or_lowmed_species(uid, carcass):
    strike = _parent_strike(carcass)
    species = store.species.get(strike["species_id"]) if strike else None
    if biologist_is_senior(uid):
        return
    if species is not None and species["risk_tier"] in ("LOW", "MEDIUM"):
        return
    raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                     "carcass identification requires a senior biologist for HIGH/CRITICAL risk-tier species", 403)


@bp.post("/strike-reports/<rid>/carcass-records")
def create_carcass(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    strike = get_or_404(store.strike_reports, rid, "strike report")
    data = validate_payload(body(), [
        ("species_id_at_collection", "str", True),
        ("identification_method", "enum", True, {"values": ID_METHODS}),
        ("disposal_method", "enum", True, {"values": DISPOSAL_METHODS}),
    ])
    check_fk("species_id_at_collection", data["species_id_at_collection"], store.species, "species")
    rec = new_entity(store.carcass_records, {
        "strike_report_id": strike["id"],
        "species_id_at_collection": data["species_id_at_collection"],
        "species_id_final": None,
        "identification_method": data["identification_method"],
        "identification_status": "COLLECTED",
        "identified_by_biologist_id": None,
        "identified_at": None,
        "disposal_method": data["disposal_method"],
    })
    return ok_object(serialize(rec), 201)


@bp.get("/strike-reports/<rid>/carcass-records")
def list_carcasses_for_strike(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    strike = get_or_404(store.strike_reports, rid, "strike report")
    rows = [c for c in store.carcass_records.values() if c["strike_report_id"] == strike["id"]]
    return list_response(rows)


@bp.get("/carcass-records")
def list_carcasses():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("identification_status")
    if status is not None and status not in CARCASS_STATUSES:
        raise E.invalid_enum("identification_status", status)
    rows = [c for c in store.carcass_records.values()
            if (args.get("strike_report_id") is None or c["strike_report_id"] == args.get("strike_report_id"))
            and (status is None or c["identification_status"] == status)
            and (args.get("species_id_at_collection") is None or c["species_id_at_collection"] == args.get("species_id_at_collection"))
            and (args.get("species_id_final") is None or c.get("species_id_final") == args.get("species_id_final"))
            and (args.get("identified_by_biologist_id") is None or c.get("identified_by_biologist_id") == args.get("identified_by_biologist_id"))]
    return list_response(rows)


@bp.get("/carcass-records/<rid>")
def get_carcass(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_carcass(rid)))


@bp.post("/carcass-records/<rid>/send-to-lab")
def send_to_lab(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rec = _get_carcass(rid)
    if rec["identification_status"] != "COLLECTED":
        raise E.invalid_state("carcass record must be in COLLECTED to send to lab")
    if rec["identification_method"] == "PENDING":
        raise E.invalid_state("cannot send to lab while identification_method is PENDING")
    rec["identification_status"] = "PENDING_ID"
    touch(rec)
    return ok_object(serialize(rec))


@bp.post("/carcass-records/<rid>/identify")
def identify(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rec = _get_carcass(rid)
    data = body()
    final = data.get("species_id_final")
    if final is None:
        raise E.invalid_request("missing required field: 'species_id_final'")
    if not isinstance(final, str):
        raise E.invalid_request("field 'species_id_final' must be a string")
    method = data.get("identification_method")
    if method is not None and method not in ID_METHODS:
        raise E.invalid_enum("identification_method", method)
    check_fk("species_id_final", final, store.species, "species")
    if rec["identification_status"] not in ("COLLECTED", "PENDING_ID"):
        raise E.invalid_state("carcass record must be in COLLECTED or PENDING_ID to identify")
    _senior_or_lowmed_species(uid, rec)
    # ERR_ID_METHOD_PENDING: cannot identify while the method is PENDING —
    # neither a record still carrying PENDING nor a payload declaring PENDING.
    if rec["identification_status"] == "COLLECTED" and rec["identification_method"] == "PENDING":
        raise E.ApiError(E.ERR_ID_METHOD_PENDING,
                         "cannot identify while identification_method is PENDING", 422)
    if method == "PENDING":
        raise E.ApiError(E.ERR_ID_METHOD_PENDING,
                         "cannot identify while identification_method is PENDING", 422)
    rec["species_id_final"] = final
    rec["identified_by_biologist_id"] = uid
    rec["identified_at"] = now()
    if method is not None:
        rec["identification_method"] = method
    rec["identification_status"] = "IDENTIFIED"
    touch(rec)
    _cascade_amend(rec)
    return ok_object(serialize(rec))


@bp.post("/carcass-records/<rid>/dispute")
def dispute(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rec = _get_carcass(rid)
    if rec["identification_status"] != "IDENTIFIED":
        raise E.invalid_state("carcass record must be in IDENTIFIED to dispute")
    if uid == rec.get("identified_by_biologist_id"):
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         "the identifying biologist cannot dispute their own identification", 403)
    if not biologist_is_senior(uid):
        raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                         "disputing a carcass identification requires a senior biologist", 403)
    rec["identification_status"] = "DISPUTED"
    touch(rec)
    return ok_object(serialize(rec))


@bp.post("/carcass-records/<rid>/resolve")
def resolve(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rec = _get_carcass(rid)
    data = body()
    final = data.get("species_id_final")
    if final is None:
        raise E.invalid_request("missing required field: 'species_id_final'")
    if not isinstance(final, str):
        raise E.invalid_request("field 'species_id_final' must be a string")
    check_fk("species_id_final", final, store.species, "species")
    if rec["identification_status"] != "DISPUTED":
        raise E.invalid_state("carcass record must be in DISPUTED to resolve")
    if uid == rec.get("identified_by_biologist_id"):
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         "the identifying biologist cannot resolve their own disputed identification", 403)
    if not biologist_is_senior(uid):
        raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                         "resolving a carcass identification requires a senior biologist", 403)
    rec["species_id_final"] = final
    rec["identification_status"] = "RESOLVED"
    touch(rec)
    _cascade_amend(rec)
    return ok_object(serialize(rec))
