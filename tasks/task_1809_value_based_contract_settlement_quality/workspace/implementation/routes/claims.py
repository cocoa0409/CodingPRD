"""ClaimRecord endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CLAIM_OUTSIDE_PERIOD,
    ERR_DUPLICATE_CLAIM_REF,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_YEAR_LOCKED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_date,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("claims", __name__)

# Year statuses strictly past MEASURING: a mark-paid/void here recomputes the
# year's cost rollups, stales PUBLISHED interim reports, and flags the
# year's settlement (PRD §3.7 / §2.10).
PAST_MEASURING = {"RECONCILING", "SETTLED", "CLOSED"}


def _get_claim_or_404(claim_id: str) -> dict:
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_NOT_FOUND, "ClaimRecord id does not exist")
    return claim


@bp.route("/vbc/claims", methods=["POST"])
@require_roles("ClaimsProcessor")
def create_claim(_user_id: str, _role: str):
    body = get_json_body()
    # Priority 3: body FK existence.
    raw_year = body.get("performance_year_id")
    if isinstance(raw_year, str) and raw_year != "" and raw_year not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")
    raw_member = body.get("member_id")
    if isinstance(raw_member, str) and raw_member != "" and raw_member not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")
    # Priority 5: shape.
    reject_unknown_fields(
        body, {"performance_year_id", "member_id", "claim_ref", "service_date", "paid_amount_cents"}
    )
    performance_year_id = require_string(body, "performance_year_id")
    member_id = require_string(body, "member_id")
    claim_ref = require_string(body, "claim_ref")
    service_date = require_date(body, "service_date")
    paid_amount_cents = require_int(body, "paid_amount_cents")
    if performance_year_id not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")
    if member_id not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")

    year = db.performance_years[performance_year_id]
    # Priority 8 (temporal): service_date inside the half-open year window.
    sd = db.parse_date(service_date)
    if not (db.parse_date(year["period_start"]) <= sd < db.parse_date(year["period_end"])):
        raise_err(ERR_CLAIM_OUTSIDE_PERIOD, "service_date outside [period_start, period_end)")
    # Priority 11: claim_ref unique within the year.
    for claim in db.claims.values():
        if claim["performance_year_id"] == performance_year_id and claim["claim_ref"] == claim_ref:
            raise_err(ERR_DUPLICATE_CLAIM_REF, "claim_ref already exists in the performance year")
    # Priority 12 (fiscal): amount strictly positive.
    if paid_amount_cents <= 0:
        raise_err(ERR_INVALID_AMOUNT, "paid_amount_cents must be > 0")

    claim = {
        "performance_year_id": performance_year_id,
        "member_id": member_id,
        "claim_ref": claim_ref,
        "service_date": service_date,
        "paid_amount_cents": paid_amount_cents,
        "claim_status": "RECEIVED",
        "paid_on": None,
    }
    db.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return success_object(claim, 201)


@bp.route("/vbc/claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_claims(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.claims.values()))
    items = apply_filters(items, ["performance_year_id", "member_id", "claim_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/claims/<claim_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_claim(claim_id: str, _user_id: str, _role: str):
    return success_object(_get_claim_or_404(claim_id))


@bp.route("/vbc/claims/<claim_id>/mark-paid", methods=["POST"])
@require_roles("ClaimsProcessor")
def mark_paid(claim_id: str, _user_id: str, _role: str):
    claim = _get_claim_or_404(claim_id)
    if claim["claim_status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a RECEIVED claim can be marked paid")
    claim["claim_status"] = "PAID"
    claim["paid_on"] = db.clock_date_iso()
    db.touch(claim)
    # Cascade only when the year is past MEASURING (RECONCILING or later).
    year = db.performance_years.get(claim["performance_year_id"])
    if year is not None and year["year_status"] in PAST_MEASURING:
        engine.after_cost_mutation(year)
    return success_object(claim)


@bp.route("/vbc/claims/<claim_id>/deny", methods=["POST"])
@require_roles("ClaimsProcessor")
def deny_claim(claim_id: str, _user_id: str, _role: str):
    claim = _get_claim_or_404(claim_id)
    if claim["claim_status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a RECEIVED claim can be denied")
    claim["claim_status"] = "DENIED"
    db.touch(claim)
    return success_object(claim)


@bp.route("/vbc/claims/<claim_id>/void", methods=["POST"])
@require_roles("ClaimsProcessor")
def void_claim(claim_id: str, _user_id: str, _role: str):
    claim = _get_claim_or_404(claim_id)
    if claim["claim_status"] != "PAID":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PAID claim can be voided")
    year = db.performance_years.get(claim["performance_year_id"])
    if year is not None and year["year_status"] in ("SETTLED", "CLOSED"):
        raise_err(ERR_YEAR_LOCKED, "Year is locked for data mutations")
    claim["claim_status"] = "VOIDED"
    db.touch(claim)
    # Cascade (unconditional per the PAID -> VOIDED transition's side effects):
    # recompute the year's cost rollups without this claim, stale every
    # PUBLISHED interim report, flag the settlement when PROVISIONAL/FINALIZED.
    if year is not None:
        engine.after_cost_mutation(year)
    return success_object(claim)
