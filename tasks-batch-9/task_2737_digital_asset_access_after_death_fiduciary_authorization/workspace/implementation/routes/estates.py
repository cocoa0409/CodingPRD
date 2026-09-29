"""Estate file, closure, authority resolution and the grant expiry sweep
(PRD sections 3.2, 3.3, 3.6, 3.10).
"""
from flask import Blueprint, request

from authz import (ALL_ROLES, COURT_REGISTRAR, ESTATE_ADMIN, FIDUCIARY,
                   READ_ROLES_NO_PLATFORM, authenticate,
                   require_fiduciary_estate, require_role)
from clock import CLOCK, add_months, format_date, parse_date, parse_datetime
from db import DB, bump, sorted_records, stamp_new
from errors import ApiError
from response import public, single
from routes.common import paged
from services import authority, lookup
from services import estate as estate_svc
from validation import (bad, parse_body, v_enum, v_state_code, v_str, validate)

bp = Blueprint("estates", __name__)

ASSET_CATEGORIES = ("FINANCIAL_ACCOUNT", "EMAIL", "CLOUD_STORAGE",
                    "SUBSCRIPTION", "LOYALTY_PROGRAM", "SOCIAL_PROFILE")
ALTERNATE_VALUATION_MONTHS = 6


@bp.route("/estates", methods=["POST"])
def create_estate():
    _, role = authenticate(request)
    require_role(role, (ESTATE_ADMIN,))
    body = validate(parse_body(request), required={
        "decedent_name": v_str(200),
        "date_of_death": v_str(10),
        "domicile_state": v_state_code(),
        "court_case_number": v_str(60),
    })
    try:
        dod = parse_date(body["date_of_death"])
    except ValueError:
        raise bad("date_of_death must be an ISO 8601 calendar date (YYYY-MM-DD).")
    if dod > CLOCK.today():
        raise ApiError("ERR_DATE_OF_DEATH_IN_FUTURE")

    estate = {
        "decedent_name": body["decedent_name"],
        "date_of_death": body["date_of_death"],
        "domicile_state": body["domicile_state"],
        "court_case_number": body["court_case_number"],
        "alternate_valuation_date": format_date(
            add_months(dod, ALTERNATE_VALUATION_MONTHS)),
        "administration_phase": "INTAKE",
        "inventory_total_count": 0,
        "disclosed_asset_count": 0,
        "assets_pending_disposition_count": 0,
        "assets_disposed_count": 0,
        "open_cancellation_count": 0,
        "cancelled_subscription_count": 0,
        "valuation_basis": None,
        "gross_digital_estate_cents": 0,
        "admin_deduction_cents": 0,
        "taxable_digital_estate_cents": 0,
        "undistributed_value_cents": 0,
        "refund_recovered_cents": 0,
        "closing_statement": None,
        "closed_at": None,
    }
    stamp_new(estate)
    DB.estates[estate["id"]] = estate
    return single(public(estate), 201)


@bp.route("/estates/<estate_id>", methods=["GET"])
def read_estate(estate_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_estate(estate_id)), 200)


@bp.route("/estates", methods=["GET"])
def list_estates():
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    return paged(DB.estates.values(), request.args, {
        "administration_phase": "administration_phase",
        "domicile_state": "domicile_state",
    })


@bp.route("/estates/<estate_id>/close", methods=["POST"])
def close_estate(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request),
                    required={"closing_statement": v_str(2000)})
    estate = lookup.get_estate(estate_id)
    require_fiduciary_estate(user_id, role, estate_id)
    estate_svc.require_open(estate)

    newest = estate_svc.newest_non_superseded_run(estate_id)
    if newest is None or newest["status"] != "FINALIZED":
        raise ApiError("ERR_VALUATION_NOT_FINALIZED")
    if estate["assets_pending_disposition_count"] > 0:
        raise ApiError("ERR_ASSETS_PENDING_DISPOSITION")
    if estate["open_cancellation_count"] > 0:
        raise ApiError("ERR_OPEN_CANCELLATIONS")
    for claim in lookup.estate_claims(estate_id):
        if claim["status"] in estate_svc.OPEN_CLAIM_STATUSES:
            raise ApiError("ERR_OPEN_REFUND_CLAIMS")

    estate["closed_at"] = CLOCK.iso()
    estate["closing_statement"] = body["closing_statement"]
    estate["administration_phase"] = "CLOSED"
    bump(estate)
    return single(public(estate), 200)


@bp.route("/estates/<estate_id>/authority-resolution", methods=["GET"])
def authority_resolution(estate_id):
    _, role = authenticate(request)
    require_role(role, READ_ROLES_NO_PLATFORM)
    args = request.args
    platform_id = args.get("platform_id")
    if not platform_id:
        raise bad("platform_id is required.")
    category = args.get("asset_category")
    if category is not None and category not in ASSET_CATEGORIES:
        raise bad("asset_category must be a known account category.")
    estate = lookup.get_estate(estate_id)
    platform = lookup.get_platform(platform_id)
    result = authority.resolve_authority(estate, platform, category)
    return single({
        "estate_id": estate_id,
        "platform_id": platform_id,
        "asset_category": category,
        "resolved_scope": result["resolved_scope"],
        "resolved_basis": result["resolved_basis"],
        "clamp_reason": result["clamp_reason"],
        "controlling_directive_id": result["controlling_directive_id"],
    }, 200)


@bp.route("/estates/<estate_id>/grant-expiry-sweeps", methods=["POST"])
def grant_expiry_sweep(estate_id):
    _, role = authenticate(request)
    require_role(role, (ESTATE_ADMIN,))
    estate = lookup.get_estate(estate_id)
    estate_svc.require_open(estate)

    swept_at = CLOCK.iso()
    now = CLOCK.instant()
    today = CLOCK.today()

    expired_grants = 0
    revoked_assets = 0
    for grant in sorted_records(lookup.estate_grants(estate_id)):
        if grant["status"] != "ACTIVE":
            continue
        if parse_datetime(grant["expires_at"]) > now:
            continue
        grant["status"] = "EXPIRED"
        grant["revocation_reason"] = "TERM_EXPIRED"
        bump(grant)
        expired_grants += 1
        covered = [a for a in lookup.estate_assets(estate_id)
                   if a["platform_id"] == grant["platform_id"]]
        revoked_assets += len(authority.revoke_asset_access(covered, False))

    lapsed_terms = 0
    for term in sorted_records(lookup.estate_terms(estate_id)):
        if term["state"] != "ACTIVE":
            continue
        if term["auto_renew"]:
            continue
        if parse_date(term["term_end_date"]) >= today:
            continue
        term["state"] = "LAPSED"
        bump(term)
        lapsed_terms += 1

    estate_svc.recompute(estate)
    return single({
        "swept_at": swept_at,
        "expired_grant_count": expired_grants,
        "revoked_asset_count": revoked_assets,
        "lapsed_term_count": lapsed_terms,
    }, 200)
