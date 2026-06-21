"""Extended-warranty endpoints (PRD §3.4, §3.9)."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_COVERAGE_OVERLAP,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_TIER_MISMATCH,
)
from middleware import require_roles
from response import ok_array, ok_object
from services import calc, common
from services.registration_svc import (
    active_extensions,
    bump,
    mint_common,
    public,
    reconcile,
)
from services.timeutil import add_months, parse_iso, whole_months_between

bp = Blueprint("extended_warranties", __name__)


def _ext_interval(effective_iso, extension_months):
    start = parse_iso(effective_iso)
    end = add_months(start, extension_months)
    return start, end


@bp.post("/extended-warranties")
def purchase_extension():
    require_roles(["Owner", "WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["registration_id", "coverage_tier_id", "amount_paid_cents"])
    registration_id = common.require_str(body, "registration_id")
    coverage_tier_id = common.require_str(body, "coverage_tier_id")
    amount_paid_cents = common.require_int(body, "amount_paid_cents", minimum=0)

    # existence (PRD §2.5)
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Registration not found")
    tier = db.coverage_tiers.get(coverage_tier_id)
    if tier is None:
        raise APIError(ERR_NOT_FOUND, 404, "CoverageTier not found")

    # tier-matching rule (ERR_TIER_MISMATCH, 422):
    # amount must equal tier price, tier ACTIVE, tier on registration's product
    if (amount_paid_cents != tier["price_cents"]
            or tier["status"] != "ACTIVE"
            or tier["product_id"] != reg["product_id"]):
        raise APIError(ERR_TIER_MISMATCH, 422,
                       "amount/price mismatch, retired tier, or wrong product")

    # coverage-overlap rule (ERR_COVERAGE_OVERLAP, 409): half-open interval check.
    # New extension takes effect now; spans tier.extension_months.
    effective_date = db.system_clock["current_utc"]
    new_start, new_end = _ext_interval(effective_date, tier["extension_months"])
    for ext in active_extensions(registration_id):
        ex_tier = db.coverage_tiers.get(ext["coverage_tier_id"])
        if ex_tier is None:
            continue
        ex_start, ex_end = _ext_interval(ext["effective_date"], ex_tier["extension_months"])
        # half-open overlap: start < ex_end AND ex_start < end
        if new_start < ex_end and ex_start < new_end:
            raise APIError(ERR_COVERAGE_OVERLAP, 409,
                           "Extension interval overlaps an existing active extension")

    ext = {
        "registration_id": registration_id,
        "coverage_tier_id": coverage_tier_id,
        "amount_paid_cents": amount_paid_cents,
        "effective_date": effective_date,
        "premium_refund_cents": 0,
        "status": "ACTIVE",
    }
    mint_common(ext)
    db.extended_warranties[ext["id"]] = ext

    # cascade onto registration
    reconcile(reg)
    bump(reg)
    return ok_object(public(ext), 201)


@bp.post("/extended-warranties/<eid>/cancel")
def cancel_extension(eid):
    require_roles(["Owner"])
    ext = db.extended_warranties.get(eid)
    if ext is None:
        raise APIError(ERR_NOT_FOUND, 404, "ExtendedWarranty not found")
    reg = db.registrations.get(ext["registration_id"])
    if reg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Registration not found")

    # state: extension must be ACTIVE
    if ext["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "ExtendedWarranty is not ACTIVE")
    # ownership: acting owner must be parent registration's owner
    if reg["owner_user_id"] != g.user_id:
        raise APIError(ERR_NOT_OWNER, 403, "Caller is not the registration owner")
    # parent registration must be REGISTERED or ACTIVE
    if reg["status"] not in ("REGISTERED", "ACTIVE"):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Parent registration must be REGISTERED or ACTIVE")

    tier = db.coverage_tiers.get(ext["coverage_tier_id"])
    now = parse_iso(db.system_clock["current_utc"])
    elapsed = whole_months_between(parse_iso(ext["effective_date"]), now)
    refund = calc.premium_refund(
        ext["amount_paid_cents"],
        tier["extension_months"] if tier is not None else 0,
        elapsed,
        tier["premium_refund_method"] if tier is not None else "PRO_RATA",
    )
    ext["premium_refund_cents"] = refund
    ext["status"] = "CANCELLED"
    bump(ext)

    # cascade: recompute active tier / end date / remaining coverage
    reconcile(reg)
    bump(reg)
    return ok_object(public(ext))


@bp.get("/extended-warranties/<eid>")
def get_extension(eid):
    require_roles(["WarrantyAdmin", "Owner"])
    ext = db.extended_warranties.get(eid)
    if ext is None:
        raise APIError(ERR_NOT_FOUND, 404, "ExtendedWarranty not found")
    return ok_object(public(ext))


@bp.get("/extended-warranties")
def list_extensions():
    require_roles(["WarrantyAdmin", "Owner"])
    limit, offset = common.parse_pagination()
    registration_id = request.args.get("registration_id")
    coverage_tier_id = request.args.get("coverage_tier_id")
    rows = list(db.extended_warranties.values())
    if registration_id is not None:
        rows = [e for e in rows if e["registration_id"] == registration_id]
    if coverage_tier_id is not None:
        rows = [e for e in rows if e["coverage_tier_id"] == coverage_tier_id]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(e) for e in page], limit, offset, total)
