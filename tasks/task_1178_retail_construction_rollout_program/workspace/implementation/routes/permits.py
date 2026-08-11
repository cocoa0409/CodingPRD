"""Permit endpoints (§3.3): fee schedule, filing rounds, refile loop, ledger."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import clock
from db import store
from errors import ApiError
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from routes.municipalities import profile_by_code
from services.forecast import recompute_commitment_for_site
from util import bump, iso_ms, new_entity, serialize
from validate import body_fk, get_or_404, json_body, req_enum, req_str

bp = Blueprint("permits", __name__)

TERMINAL = ("WITHDRAWN", "EXPIRED")
PERMIT_TYPES = ("BUILDING", "ELECTRICAL", "SIGNAGE", "HEALTH")
NON_TERMINAL_FOR_DUP = ("DRAFT", "FILED", "UNDER_REVIEW", "ISSUED")


def _base_fee(site, profile):
    """permit_fee_schedule: base + round_half_up(sqft * rate / 100); the
    per-permit fee is rounded to whole cents FIRST (rounding order pinned)."""
    sqft_term = (Decimal(site["square_footage"]) * Decimal(profile["fee_per_sqft_cents"])
                 / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return profile["fee_base_cents"] + int(sqft_term)


def _latest_approved_revision(program_id, jurisdiction_code):
    approved = [
        d for d in store.drawings.values()
        if d["program_id"] == program_id
        and d["jurisdiction_code"] == jurisdiction_code
        and d["status"] == "APPROVED"
    ]
    if not approved:
        return None
    return max(d["revision"] for d in approved)


def _is_latest_approved(drawing):
    if drawing["status"] != "APPROVED":
        return False
    latest = _latest_approved_revision(drawing["program_id"], drawing["jurisdiction_code"])
    return latest is not None and drawing["revision"] == latest


@bp.route("/rollout/permits", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def create_permit():
    body = json_body()
    site = body_fk(body, "site_id", store.sites)
    drawing = body_fk(body, "drawing_set_id", store.drawings)
    permit_type = body.get("permit_type")

    if site is not None:
        # Step 8 — municipality profile must exist for the site's municipality.
        profile = profile_by_code(site["municipality_code"])
        if profile is None:
            raise ApiError("ERR_MUNICIPALITY_PROFILE_MISSING", 422,
                           "no MunicipalityProfile for the site's municipality_code")
        # Step 10 — one non-terminal permit per (site, permit_type).
        if isinstance(permit_type, str):
            duplicate = any(
                p["site_id"] == site["id"]
                and p["permit_type"] == permit_type
                and p["status"] in NON_TERMINAL_FOR_DUP
                for p in store.permits.values()
            )
            if duplicate:
                raise ApiError("ERR_DUPLICATE_PERMIT_TYPE", 409,
                               "site already holds a non-terminal permit of this type")

    # Step 12 — request shape.
    if site is None:
        from errors import invalid_request
        invalid_request("field 'site_id' is required")
    permit_type = req_enum(body, "permit_type", PERMIT_TYPES)
    if drawing is None:
        from errors import invalid_request
        invalid_request("field 'drawing_set_id' is required")

    profile = profile_by_code(site["municipality_code"])
    permit = new_entity(store)
    permit.update({
        "site_id": site["id"],
        "drawing_set_id": drawing["id"],
        "permit_type": permit_type,
        "municipality_code": site["municipality_code"],
        "round_number": 1,
        "fee_cents": 0,
        "filed_at": None,
        "review_due_on": None,
        "issued_at": None,
        "expires_on": None,
        "rejection_reason": None,
        "status": "DRAFT",
        "_profile_id": profile["id"],
    })
    store.permits[permit["id"]] = permit
    return ok(serialize(permit), status=201)


@bp.route("/rollout/permits", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_permits():
    return list_response(store.permits, [
        ("site_id", "site_id", "str"),
        ("drawing_set_id", "drawing_set_id", "str"),
        ("status", "status", "str"),
        ("permit_type", "permit_type", "str"),
    ])


@bp.route("/rollout/permits/<permitId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_permit(permitId):
    return ok(serialize(get_or_404(store.permits, permitId, "permit")))


def _file_common(permit, site, profile, fee):
    permit["fee_cents"] = fee
    permit["filed_at"] = iso_ms(clock.now())
    due = clock.today() + timedelta(days=profile["statutory_review_days"])
    permit["review_due_on"] = due.isoformat()
    permit["status"] = "FILED"
    bump(permit)
    site["permit_fees_paid_cents"] += fee
    bump(site)


@bp.route("/rollout/permits/<permitId>/file", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def file_permit(permitId):
    permit = get_or_404(store.permits, permitId, "permit")
    require_state(permit, ("DRAFT",), TERMINAL)
    drawing = store.drawings.get(permit["drawing_set_id"])
    if drawing is None or not _is_latest_approved(drawing):
        raise ApiError("ERR_DRAWING_SUPERSEDED", 409,
                       "pinned drawing set is not the latest APPROVED revision")
    site = store.sites.get(permit["site_id"])
    profile = store.municipalities.get(permit["_profile_id"])
    fee = _base_fee(site, profile)
    _file_common(permit, site, profile, fee)
    recompute_commitment_for_site(site)  # permit filing triggers the forecast
    return ok(serialize(permit))


@bp.route("/rollout/permits/<permitId>/start-review", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def start_review(permitId):
    permit = get_or_404(store.permits, permitId, "permit")
    require_state(permit, ("FILED",), TERMINAL)
    permit["status"] = "UNDER_REVIEW"
    bump(permit)
    return ok(serialize(permit))


@bp.route("/rollout/permits/<permitId>/issue", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def issue_permit(permitId):
    permit = get_or_404(store.permits, permitId, "permit")
    require_state(permit, ("UNDER_REVIEW",), TERMINAL)
    profile = store.municipalities.get(permit["_profile_id"])
    permit["status"] = "ISSUED"
    permit["issued_at"] = iso_ms(clock.now())
    expires = clock.today() + timedelta(days=profile["permit_validity_days"])
    permit["expires_on"] = expires.isoformat()
    bump(permit)
    site = store.sites.get(permit["site_id"])
    if site is not None:
        recompute_commitment_for_site(site)  # permit issuance triggers the forecast
    return ok(serialize(permit))


@bp.route("/rollout/permits/<permitId>/reject", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def reject_permit(permitId):
    body = json_body()
    permit = get_or_404(store.permits, permitId, "permit")
    require_state(permit, ("UNDER_REVIEW",), TERMINAL)
    reason = req_str(body, "rejection_reason")
    permit["status"] = "REJECTED"
    permit["rejection_reason"] = reason
    bump(permit)
    return ok(serialize(permit))


@bp.route("/rollout/permits/<permitId>/refile", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def refile_permit(permitId):
    body = json_body()
    permit = get_or_404(store.permits, permitId, "permit")
    drawing = body_fk(body, "drawing_set_id", store.drawings)
    require_state(permit, ("REJECTED",), TERMINAL)
    if drawing is None:
        from errors import invalid_request
        invalid_request("field 'drawing_set_id' is required")
    site = store.sites.get(permit["site_id"])
    # The request set must be the latest APPROVED revision for the site's
    # program and municipality (§3.3 refile gate).
    if (drawing["status"] != "APPROVED"
            or drawing["program_id"] != site["program_id"]
            or drawing["jurisdiction_code"] != site["municipality_code"]
            or drawing["revision"] != _latest_approved_revision(
                site["program_id"], site["municipality_code"])):
        raise ApiError("ERR_DRAWING_SUPERSEDED", 409,
                       "drawing set is not the latest APPROVED revision for the site")
    profile = store.municipalities.get(permit["_profile_id"])
    base_fee = _base_fee(site, profile)
    fee = int((Decimal(base_fee) * Decimal("0.5")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    permit["round_number"] += 1
    permit["drawing_set_id"] = drawing["id"]
    _file_common(permit, site, profile, fee)
    return ok(serialize(permit))


@bp.route("/rollout/permits/<permitId>/withdraw", methods=["POST"], strict_slashes=False)
@authed(["PermitCoordinator"])
def withdraw_permit(permitId):
    permit = get_or_404(store.permits, permitId, "permit")
    require_state(permit, ("FILED", "UNDER_REVIEW"), TERMINAL)
    site = store.sites.get(permit["site_id"])
    permit["status"] = "WITHDRAWN"
    bump(permit)
    if site is not None:
        site["permit_fees_paid_cents"] -= permit["fee_cents"]
        bump(site)
    return ok(serialize(permit))
