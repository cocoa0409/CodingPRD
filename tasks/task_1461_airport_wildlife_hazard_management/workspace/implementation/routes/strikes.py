"""Wildlife strike reports: CRUD + DRAFT/SUBMITTED/UNDER_REVIEW/CONFIRMED/REJECTED lifecycle."""
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, biologist_is_senior
from constants import (RUNWAY_RE, DAMAGE_CLASSES, PHASES_OF_FLIGHT, STRIKE_STATUSES)
from db import store
from services import hazard_is_critical, recompute_airport
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, now, parse_datetime)

bp = Blueprint("strikes", __name__, url_prefix="/wildlife")

READ_ROLES = ("AirportAdmin", "WildlifeBiologist", "RegulatorAgent")


def _get_strike(rid):
    return get_or_404(store.strike_reports, rid, "strike report")


def _species(report):
    return store.species.get(report["species_id"])


@bp.post("/strike-reports")
def create_strike():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("reporter_biologist_id", "str", True),
        ("strike_at", "datetime", True),
        ("runway_designator", "pattern", True, {"regex": RUNWAY_RE}),
        ("aircraft_registration", "str", True),
        ("species_id", "str", True),
        ("damage_class", "enum", True, {"values": DAMAGE_CLASSES}),
        ("phase_of_flight", "enum", True, {"values": PHASES_OF_FLIGHT}),
        ("altitude_ft_agl", "int", True, {"min": 0}),
        ("strike_count_animals", "int", True, {"min": 1}),
        ("carcass_present", "bool", True),
        ("confirmation_notes", "str", False),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    check_fk("reporter_biologist_id", data["reporter_biologist_id"], store.biologists, "biologist")
    check_fk("species_id", data["species_id"], store.species, "species")
    if data["reporter_biologist_id"] != uid:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         "reporter_biologist_id must equal the acting biologist", 403)
    rec = new_entity(store.strike_reports, {
        "airport_id": data["airport_id"],
        "reporter_biologist_id": data["reporter_biologist_id"],
        "strike_at": data["strike_at"],
        "runway_designator": data["runway_designator"],
        "aircraft_registration": data["aircraft_registration"],
        "species_id": data["species_id"],
        "status": "DRAFT",
        "damage_class": data["damage_class"],
        "phase_of_flight": data["phase_of_flight"],
        "altitude_ft_agl": data["altitude_ft_agl"],
        "strike_count_animals": data["strike_count_animals"],
        "carcass_present": data["carcass_present"],
        "confirmed_by_biologist_id": None,
        "confirmation_notes": data.get("confirmation_notes"),
    })
    return ok_object(serialize(rec), 201)


@bp.get("/strike-reports")
def list_strikes():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    damage = args.get("damage_class")
    if status is not None and status not in STRIKE_STATUSES:
        raise E.invalid_enum("status", status)
    if damage is not None and damage not in DAMAGE_CLASSES:
        raise E.invalid_enum("damage_class", damage)
    after = args.get("strike_after")
    before = args.get("strike_before")
    try:
        after_dt = parse_datetime(after) if after else None
        before_dt = parse_datetime(before) if before else None
    except Exception:
        raise E.invalid_request("strike_after / strike_before must be ISO8601 datetimes")
    rows = [s for s in store.strike_reports.values()
            if (args.get("airport_id") is None or s["airport_id"] == args.get("airport_id"))
            and (args.get("reporter_biologist_id") is None or s["reporter_biologist_id"] == args.get("reporter_biologist_id"))
            and (args.get("confirmed_by_biologist_id") is None or s.get("confirmed_by_biologist_id") == args.get("confirmed_by_biologist_id"))
            and (status is None or s["status"] == status)
            and (damage is None or s["damage_class"] == damage)
            and (args.get("species_id") is None or s["species_id"] == args.get("species_id"))
            and (after_dt is None or s["strike_at"] >= after_dt)
            and (before_dt is None or s["strike_at"] <= before_dt)]
    return list_response(rows)


@bp.get("/strike-reports/<rid>")
def get_strike(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_strike(rid)))


@bp.post("/strike-reports/<rid>/submit")
def submit_strike(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rep = _get_strike(rid)
    if rep["status"] != "DRAFT":
        raise E.invalid_state("strike report must be in DRAFT to submit")
    if hazard_is_critical(rep["airport_id"]):
        raise E.ApiError(E.ERR_HAZARD_CRITICAL_BLOCK,
                         "airport is at CRITICAL hazard level; submissions are blocked", 409)
    rep["status"] = "SUBMITTED"
    touch(rep)
    return ok_object(serialize(rep))


@bp.post("/strike-reports/<rid>/begin-review")
def begin_review(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rep = _get_strike(rid)
    if rep["status"] != "SUBMITTED":
        raise E.invalid_state("strike report must be in SUBMITTED to begin review")
    if uid == rep["reporter_biologist_id"]:
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         "reporter cannot review their own strike report", 403)
    rep["status"] = "UNDER_REVIEW"
    touch(rep)
    return ok_object(serialize(rep))


@bp.post("/strike-reports/<rid>/confirm")
def confirm_strike(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rep = _get_strike(rid)
    if rep["status"] != "UNDER_REVIEW":
        raise E.invalid_state("strike report must be in UNDER_REVIEW to confirm")
    if uid == rep["reporter_biologist_id"]:
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         "reporter cannot confirm their own strike report", 403)
    species = _species(rep)
    if not biologist_is_senior(uid) and (species is None or species["risk_tier"] not in ("LOW", "MEDIUM")):
        raise E.ApiError(E.ERR_SENIOR_REQUIRED,
                         "confirming a strike for a HIGH/CRITICAL risk-tier species requires a senior biologist", 403)
    notes = body().get("confirmation_notes")
    if not isinstance(notes, str) or notes == "":
        raise E.invalid_request("confirmation_notes is required and must be non-empty")
    rep["confirmation_notes"] = notes
    rep["confirmed_by_biologist_id"] = uid
    rep["status"] = "CONFIRMED"
    touch(rep)
    ap = store.airports.get(rep["airport_id"])
    if ap:
        recompute_airport(ap)
    # auto-create CarcassRecord when remains were recovered and none exists yet
    if rep["carcass_present"] and not any(c["strike_report_id"] == rep["id"] for c in store.carcass_records.values()):
        new_entity(store.carcass_records, {
            "strike_report_id": rep["id"],
            "species_id_at_collection": rep["species_id"],
            "species_id_final": None,
            "identification_method": None,
            "identification_status": "COLLECTED",
            "identified_by_biologist_id": None,
            "identified_at": None,
            "disposal_method": None,
        })
    return ok_object(serialize(rep))


@bp.post("/strike-reports/<rid>/reject")
def reject_strike(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rep = _get_strike(rid)
    if rep["status"] != "UNDER_REVIEW":
        raise E.invalid_state("strike report must be in UNDER_REVIEW to reject")
    if uid == rep["reporter_biologist_id"]:
        raise E.ApiError(E.ERR_SEGREGATION_OF_DUTIES,
                         "reporter cannot reject their own strike report", 403)
    rep["status"] = "REJECTED"
    touch(rep)
    return ok_object(serialize(rep))


@bp.post("/strike-reports/<rid>/return-to-draft")
def return_to_draft(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    rep = _get_strike(rid)
    if rep["status"] != "SUBMITTED":
        raise E.invalid_state("strike report must be in SUBMITTED to return to draft")
    if uid != rep["reporter_biologist_id"]:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         "only the original reporter may return the report to draft", 403)
    rep["status"] = "DRAFT"
    touch(rep)
    return ok_object(serialize(rep))
