"""Charitable sales promotions (PRD 3.7) and disclosure materials (PRD 3.8)."""
from flask import Blueprint, g, request

import clock
import response
import validate
from auth import ALL_ROLES, endpoint, require_certifying_officer_of
from dates import add_days, fmt, parse_iso
from db import db, public, sorted_rows, stamp_new, touch_once
from errors import ApiError
from services import calc
from services.derive import (recompute_disclosures_for, resolve_disclosure)
from routes.fundraisers import has_active_registration

bp = Blueprint("promotions", __name__)

MATERIAL_TYPES = ("WEB", "PRINT", "PHONE_SCRIPT", "EMAIL")
# Promotions already SETTLED, DEFICIENT_REMITTANCE or HALTED are ignored by the
# window-separation check.
BUFFER_COMPETING = ("DRAFT", "FILED", "ACTIVE")


def _check_window_conflict(coventurer_id, state_codes, promo_start, promo_end):
    """Ladder rung 23 -- consecutive promotions of one co-venturer must be separated.

    The rejection fires when the new promo_start falls at or before the existing
    promo_end advanced by the buffer AND the existing promo_start falls at or
    before the new promo_end advanced by the buffer; when either half fails the
    windows are far enough apart.
    """
    wanted = set(state_codes)
    for other in db.coventure_promotions.values():
        if other["coventurer_id"] != coventurer_id:
            continue
        if other["status"] not in BUFFER_COMPETING:
            continue
        shared = wanted.intersection(other["state_codes"])
        if not shared:
            continue
        other_start = parse_iso(other["promo_start"])
        other_end = parse_iso(other["promo_end"])
        for state_code in sorted(shared):
            buffer_days = db.state_profiles[state_code]["coventure_buffer_days"]
            if (promo_start <= add_days(other_end, buffer_days)
                    and other_start <= add_days(promo_end, buffer_days)):
                raise ApiError("ERR_PROMOTION_WINDOW_CONFLICT")


@bp.post("/coventure-promotions")
@endpoint(["ComplianceOfficer"])
def create_promotion():
    """The promotion window is closed at both ends, unlike a coverage interval."""
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    coventurer_id = validate.req_string(body, "coventurer_id")
    state_codes = validate.req_array(body, "state_codes", non_empty=True)
    promo_start = validate.req_datetime(body, "promo_start")
    promo_end = validate.req_datetime(body, "promo_end")
    guaranteed_minimum_cents = validate.opt_int(body, "guaranteed_minimum_cents", 0, minimum=0)
    per_unit_cents = validate.opt_int(body, "per_unit_cents", 0, minimum=0)
    projected_units = validate.opt_int(body, "projected_units", 0, minimum=0)
    if promo_end < promo_start:
        raise ApiError("ERR_INVALID_REQUEST", "promo_end must be at or after promo_start.")

    organization = validate.find_organization(organization_id)
    profiles = validate.resolve_state_codes(state_codes)
    validate.find_fundraiser(coventurer_id)

    # Ladder rung 14.
    if organization["solicitation_posture"] == "HALTED":
        raise ApiError("ERR_SOLICITATION_HALTED")
    # Ladder rung 23.
    _check_window_conflict(coventurer_id, state_codes, promo_start, promo_end)

    promotion = {
        "organization_id": organization_id,
        "coventurer_id": coventurer_id,
        "state_codes": state_codes,
        "promo_start": fmt(promo_start),
        "promo_end": fmt(promo_end),
        "guaranteed_minimum_cents": guaranteed_minimum_cents,
        "per_unit_cents": per_unit_cents,
        "projected_units": projected_units,
        "status": "DRAFT",
        "projected_benefit_cents": 0,
        "actual_units": 0,
        "remitted_cents": 0,
        "final_benefit_cents": 0,
        "shortfall_cents": 0,
        "disclosure_clause_required": any(p["coventure_filing_required"] for p in profiles),
    }
    stamp_new(promotion)
    calc.recompute_projected_benefit(promotion)
    db.coventure_promotions[promotion["id"]] = promotion
    return response.created(public(promotion))


@bp.post("/coventure-promotions/<promotion_id>/file")
@endpoint(["ComplianceOfficer"])
def file_promotion(promotion_id):
    promotion = validate.find_promotion(promotion_id)

    # Ladder rung 12.
    if promotion["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PROMOTION_STATE")
    # Ladder rung 19 -- only states that require a co-venture filing impose it.
    for state_code in promotion["state_codes"]:
        profile = db.state_profiles[state_code]
        if not profile["coventure_filing_required"]:
            continue
        if not has_active_registration(promotion["coventurer_id"], state_code):
            raise ApiError("ERR_FUNDRAISER_NOT_REGISTERED_IN_STATE")
    # Ladder rung 26 -- a promotion already underway cannot be filed.
    if not (clock.now() < parse_iso(promotion["promo_start"])):
        raise ApiError("ERR_PROMOTION_WINDOW_NOT_OPEN")

    promotion["status"] = "FILED"
    calc.recompute_projected_benefit(promotion)
    touch_once(promotion, "coventure_promotion")
    recompute_disclosures_for(promotion["organization_id"], promotion["state_codes"])
    return response.ok(public(promotion))


@bp.post("/coventure-promotions/<promotion_id>/activate")
@endpoint(["ComplianceOfficer"])
def activate_promotion(promotion_id):
    """The strictest gate in the system on solicitation posture."""
    promotion = validate.find_promotion(promotion_id)

    # Ladder rung 12.
    if promotion["status"] != "FILED":
        raise ApiError("ERR_INVALID_PROMOTION_STATE")
    # Ladder rung 15 -- exactly CLEAR; a single non-domicile cease order blocks this.
    organization = db.organizations[promotion["organization_id"]]
    if organization["solicitation_posture"] != "CLEAR":
        raise ApiError("ERR_SOLICITATION_RESTRICTED")
    # Ladder rung 26 -- the clock must lie inside the closed window.
    now = clock.now()
    if not (parse_iso(promotion["promo_start"]) <= now <= parse_iso(promotion["promo_end"])):
        raise ApiError("ERR_PROMOTION_WINDOW_NOT_OPEN")

    promotion["status"] = "ACTIVE"
    touch_once(promotion, "coventure_promotion")
    return response.ok(public(promotion))


@bp.post("/coventure-promotions/<promotion_id>/settle")
@endpoint(["CertifyingOfficer"])
def settle_promotion(promotion_id):
    """A shortfall is a state, not an error: there is no under-remittance code."""
    body = validate.json_body()
    if "actual_units" not in body or body["actual_units"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "actual_units is required.")
    if "remitted_cents" not in body or body["remitted_cents"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "remitted_cents is required.")
    actual_units = validate.req_int(body, "actual_units")
    remitted_cents = validate.req_int(body, "remitted_cents")

    promotion = validate.find_promotion(promotion_id)

    # Ladder rung 6 -- a certifying officer of the benefiting charity.
    officer = require_certifying_officer_of(promotion["organization_id"])
    # Ladder rung 12.
    if promotion["status"] not in ("ACTIVE", "DEFICIENT_REMITTANCE"):
        raise ApiError("ERR_INVALID_PROMOTION_STATE")
    # Ladder rung 16 -- the settling officer may not have certified the client
    # filing for the state in question.
    for registration in db.state_registrations.values():
        if registration["organization_id"] != promotion["organization_id"]:
            continue
        if registration["state_code"] not in promotion["state_codes"]:
            continue
        if registration["certified_by_officer_id"] == officer["id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Ladder rung 26 -- the first settlement requires a closed window; the cure
    # path from DEFICIENT_REMITTANCE is not gated, since the window has closed.
    if promotion["status"] == "ACTIVE":
        if not (clock.now() > parse_iso(promotion["promo_end"])):
            raise ApiError("ERR_PROMOTION_WINDOW_NOT_OPEN")
    # Ladder rung 35 -- the last rung on the ladder.
    if actual_units < 0 or remitted_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "actual_units and remitted_cents may not be negative.")

    final_benefit = calc.coventure_benefit(promotion, actual_units)
    promotion["actual_units"] = actual_units
    promotion["remitted_cents"] = remitted_cents
    promotion["final_benefit_cents"] = final_benefit
    if remitted_cents >= final_benefit:
        promotion["status"] = "SETTLED"
        promotion["shortfall_cents"] = 0
    else:
        promotion["status"] = "DEFICIENT_REMITTANCE"
        promotion["shortfall_cents"] = final_benefit - remitted_cents
    touch_once(promotion, "coventure_promotion")
    return response.ok(public(promotion))


@bp.get("/coventure-promotions")
@endpoint(ALL_ROLES)
def list_promotions():
    rows = list(db.coventure_promotions.values())
    for field in ("organization_id", "coventurer_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if state_code in r["state_codes"]]
    page, limit, offset, total = response.paginate(sorted_rows(rows))
    return response.listing([public(r) for r in page], limit, offset, total)


@bp.get("/coventure-promotions/<promotion_id>")
@endpoint(ALL_ROLES)
def read_promotion(promotion_id):
    return response.ok(public(validate.find_promotion(promotion_id)))


@bp.post("/disclosure-statements")
@endpoint(["ComplianceOfficer"])
def create_disclosure_statement():
    body = validate.json_body()
    organization_id = validate.req_string(body, "organization_id")
    state_code = validate.req_state_code(body, "state_code")
    material_type = validate.req_enum(body, "material_type", MATERIAL_TYPES)
    included_clauses = validate.opt_array(body, "included_clauses",
                                          allowed=validate.CANONICAL_CLAUSE_ORDER, default=[])

    validate.find_organization(organization_id)
    validate.find_state_profile(state_code)

    statement = {
        "organization_id": organization_id,
        "state_code": state_code,
        "material_type": material_type,
        "included_clauses": included_clauses,
        "required_clauses": [],
        "missing_clauses": [],
        "compliance_status": "COMPLIANT",
    }
    stamp_new(statement)
    resolve_disclosure(statement)
    db.disclosure_statements[statement["id"]] = statement
    return response.created(public(statement))
