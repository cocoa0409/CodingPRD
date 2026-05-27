"""Claimant endpoints."""
import re

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE_CODE,
    invalid_request,
    not_found,
)
from middleware import require_roles
from response import created, ok, paginated
from services.utils import (
    USPS_STATES,
    opt_int,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_body,
    require_field,
    require_str,
)

bp = Blueprint("claimants", __name__)


@bp.route("/ssdi/claimants", methods=["POST"])
@require_roles("Claimant", "SSAAdmin")
def create_claimant(user_id, role):
    body = require_body()
    ssn_last4 = require_str(body, "ssn_last4")
    if not re.fullmatch(r"[0-9]{4}", ssn_last4):
        raise invalid_request("ssn_last4 must be 4 digits")
    full_name = require_str(body, "full_name")
    dob_raw = require_str(body, "date_of_birth")
    parse_iso8601(dob_raw, "date_of_birth")  # validate

    filing_state = require_str(body, "filing_state")
    if not re.fullmatch(r"[A-Z]{2}", filing_state):
        raise APIError(ERR_INVALID_STATE_CODE, 422, "filing_state must be 2 uppercase letters")
    if filing_state not in USPS_STATES:
        raise APIError(ERR_INVALID_STATE_CODE, 422, f"unknown USPS state code: {filing_state}")

    monthly_income = opt_int(body, "monthly_income_cents", 0)
    countable_resources = opt_int(body, "countable_resources_cents", 0)

    rec = {
        "ssn_last4": ssn_last4,
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "filing_state": filing_state,
        "monthly_income_cents": monthly_income,
        "countable_resources_cents": countable_resources,
    }
    # For Claimant role self-registration, id := X-User-ID so subsequent calls match.
    if role == "Claimant":
        rec["id"] = user_id
    db.stamp_create(rec)
    db.claimants[rec["id"]] = rec
    return created(rec)


@bp.route("/ssdi/claimants/<cid>", methods=["GET"])
@require_roles("Claimant", "SSAAdmin", "DDSExaminer", "ALJ", "BenefitsAdmin")
def get_claimant(cid, user_id, role):
    rec = db.claimants.get(cid)
    if rec is None:
        raise not_found(f"claimant {cid} not found")
    return ok(rec)


@bp.route("/ssdi/claimants", methods=["GET"])
@require_roles("SSAAdmin")
def list_claimants(user_id, role):
    limit, offset = parse_pagination(request.args)
    items, total = paginate(list(db.claimants.values()), limit, offset)
    return paginated(items, total, limit, offset)
