"""Issuer CRUD + OCC-guarded update."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_STALE_VERSION, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    ISSUER_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate,
)
from services.calculations import recompute_holder

issuers_bp = Blueprint("issuers", __name__)


def _get_issuer_or_404(issuer_id):
    issuer = db.issuers.get(issuer_id)
    if not issuer:
        raise ApiError(ERR_NOT_FOUND, f"Issuer {issuer_id} not found.", 404)
    return issuer


@issuers_bp.route("/issuers", methods=["POST"])
def create_issuer():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}

    required = ["name", "ticker", "cik", "shares_outstanding", "fiscal_year_end_month", "edgar_ccc"]
    for f in required:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    shares = body["shares_outstanding"]
    if not isinstance(shares, int) or isinstance(shares, bool) or shares <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "shares_outstanding must be a positive integer.", 400)

    fy_month = body["fiscal_year_end_month"]
    if not isinstance(fy_month, int) or isinstance(fy_month, bool) or not (1 <= fy_month <= 12):
        raise ApiError(ERR_INVALID_REQUEST, "fiscal_year_end_month must be an integer 1..12.", 400)

    issuer = {
        "name": body["name"],
        "ticker": body["ticker"],
        "cik": body["cik"],
        "edgar_ccc": body["edgar_ccc"],
        "shares_outstanding": shares,
        "fiscal_year_end_month": fy_month,
        "holiday_dates": body.get("holiday_dates") or [],
        "next_earnings_filing_date": body.get("next_earnings_filing_date"),
    }
    stamp_created(issuer)
    db.issuers[issuer["id"]] = issuer
    return success_object(serialize(issuer, ISSUER_FIELDS), 201)


@issuers_bp.route("/issuers", methods=["GET"])
def list_issuers():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.issuers.values(), key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(i, ISSUER_FIELDS) for i in page], limit, offset, total)


@issuers_bp.route("/issuers/<issuerId>", methods=["GET"])
def get_issuer(issuerId):
    get_auth()
    issuer = _get_issuer_or_404(issuerId)
    return success_object(serialize(issuer, ISSUER_FIELDS))


@issuers_bp.route("/issuers/<issuerId>", methods=["PUT"])
def update_issuer(issuerId):
    user_id, role = require_role("ComplianceOfficer")
    issuer = _get_issuer_or_404(issuerId)
    body = request.get_json(force=True) or {}

    expected = body.get("expected_issuer_version")
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, "expected_issuer_version is required.", 400)
    if expected != issuer["version"]:
        raise ApiError(ERR_STALE_VERSION, "Issuer version mismatch.", 412)

    updatable = [
        "name", "ticker", "shares_outstanding", "fiscal_year_end_month",
        "edgar_ccc", "holiday_dates", "next_earnings_filing_date",
    ]
    shares_changed = False
    for f in updatable:
        if f in body:
            if f == "shares_outstanding":
                val = body[f]
                if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                    raise ApiError(ERR_INVALID_REQUEST, "shares_outstanding must be a positive integer.", 400)
                if val != issuer["shares_outstanding"]:
                    shares_changed = True
            if f == "fiscal_year_end_month":
                val = body[f]
                if not isinstance(val, int) or isinstance(val, bool) or not (1 <= val <= 12):
                    raise ApiError(ERR_INVALID_REQUEST, "fiscal_year_end_month must be an integer 1..12.", 400)
            issuer[f] = body[f]

    bump_version(issuer)

    if shares_changed:
        for holder in list(db.beneficial_holders.values()):
            if holder["issuer_id"] == issuer["id"]:
                recompute_holder(holder["id"])

    return success_object(serialize(issuer, ISSUER_FIELDS))
