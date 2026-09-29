"""Compliance sweep, annual spend analytics and the logical-clock endpoint."""
from flask import Blueprint, request

import constants as C
from auth import ALL_ROLES, endpoint
from clock import clock, parse_instant
from db import db, set_fields, sort_rows
from response import object_response
from services import compliance
from services.analytics import annual_spend
from services.determination import recompute_publisher_agreement_count
from util import parse_iso_date
from validation import filter_enum, get_body, invalid, req_str, resolve_filter

bp = Blueprint("ops", __name__)

SWEEPABLE_AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "EXHAUSTED")


@bp.post("/compliance-sweeps")
@endpoint(["ScholCommLibrarian"])
def run_compliance_sweep():
    today = clock.date()

    agreements_expired_count = 0
    for agreement in sort_rows(list(db.agreements.values())):
        if agreement["status"] not in SWEEPABLE_AGREEMENT_STATUSES:
            continue
        if parse_iso_date(agreement["effective_until"]) > today:
            continue
        set_fields(agreement, status="EXPIRED")
        recompute_publisher_agreement_count(agreement["publisher_id"])
        agreements_expired_count += 1

    grants_closed_count = 0
    for grant in sort_rows(list(db.grants.values())):
        if grant["status"] != "ACTIVE":
            continue
        if parse_iso_date(grant["award_until"]) >= today:
            continue
        set_fields(grant, status="CLOSED")
        grants_closed_count += 1

    articles_marked_non_compliant_count = 0
    for article in sort_rows(list(db.articles.values())):
        if article["compliance_status"] != "PENDING_DEPOSIT":
            continue
        deadline = parse_iso_date(article.get("deposit_deadline_on"))
        if deadline is None or deadline >= today:
            continue
        set_fields(article, compliance_status="NON_COMPLIANT")
        compliance.recompute_grant(article.get("grant_id"))
        articles_marked_non_compliant_count += 1

    articles_promoted_compliant_count = 0
    for article in sort_rows(list(db.articles.values())):
        if article["compliance_status"] != "EMBARGOED":
            continue
        embargo = parse_iso_date(article.get("embargo_until"))
        if embargo is None or embargo > today:
            continue
        set_fields(article, compliance_status="COMPLIANT")
        compliance.recompute_grant(article.get("grant_id"))
        articles_promoted_compliant_count += 1

    return object_response({
        "swept_at_utc": clock.now_iso(),
        "agreements_expired_count": agreements_expired_count,
        "grants_closed_count": grants_closed_count,
        "articles_marked_non_compliant_count": articles_marked_non_compliant_count,
        "articles_promoted_compliant_count": articles_promoted_compliant_count,
    })


@bp.get("/analytics/annual-spend")
@endpoint(["FundManager", "ScholCommLibrarian"])
def get_annual_spend():
    publisher_id = resolve_filter("publisher", "publisher_id")
    raw_year = request.args.get("fiscal_year")
    if raw_year is None or raw_year == "":
        invalid("fiscal_year is required")
    try:
        fiscal_year = int(str(raw_year).strip())
    except (TypeError, ValueError):
        invalid("fiscal_year must be an integer")
        fiscal_year = None
    basis = filter_enum("basis", C.ANALYTICS_BASES) or "ENCUMBRANCE"
    return object_response(annual_spend(fiscal_year, basis, publisher_id))


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc():
    body = get_body()
    raw = req_str(body, "to_iso8601")
    parsed = parse_instant(raw)
    if parsed is None:
        invalid("to_iso8601 must be an ISO 8601 instant")
    clock.set(parsed)
    return object_response({"current_utc": clock.now_iso()})
