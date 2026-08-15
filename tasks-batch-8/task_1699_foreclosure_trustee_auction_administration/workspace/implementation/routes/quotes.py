"""Quote routes: issuance (OCC on the case version), list, acceptance.

Issuance order (PRD §3.6): schema -> case non-terminal -> staleness.
Acceptance order (PRD §3.6): schema -> case state permits -> quote stored
ISSUED -> not expired -> reinstatement cutoff (when a sale is pending) ->
tender equality.
"""
from flask import Blueprint, request

import db
from db import stamp_new, touch, now_iso
from errors import (err_invalid_request, err_invalid_case_state,
                    err_stale_case_version, err_invalid_quote_state,
                    err_quote_expired, err_reinstatement_cutoff,
                    err_payment_shortfall)
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services import calc
from services.domain import (get_case, get_quote, view, quote_view,
                             quote_derived_status, case_quotes, recorded_nod,
                             total_approved_costs_cents, reinstatement_cutoff,
                             TERMINAL_CASE_STATES)
from services.validate import get_body, check_unknown, req_enum, req_date, req_int
from services.workflow import apply_quote_acceptance
from util import format_date, parse_date_strict

bp = Blueprint("quotes", __name__)

QUOTE_TYPES = ("REINSTATEMENT", "PAYOFF")
REINSTATEMENT_FROM = ("NOD_RECORDED", "NOTS_RECORDED", "SALE_SCHEDULED")
PAYOFF_FROM = ("REFERRED", "NOD_RECORDED", "NOTS_RECORDED", "SALE_SCHEDULED")


@bp.route("/api/foreclosure-cases/<case_id>/quotes", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def issue_quote(user_id, role, case_id):
    case = get_case(case_id)
    body = get_body()
    check_unknown(body, {"quote_type", "good_through_date",
                         "expected_foreclosure_case_version"})
    quote_type = req_enum(body, "quote_type", QUOTE_TYPES)
    good_through = req_date(body, "good_through_date")
    expected = req_int(body, "expected_foreclosure_case_version")
    # clock consistency (§2.5): good_through on or after the clock date
    if good_through < db.CLOCK.now_date():
        raise err_invalid_request("good_through_date must be on or after the current clock date")
    # case-state check first, then staleness (PRD §3.6)
    if case["lifecycle_status"] in TERMINAL_CASE_STATES:
        raise err_invalid_case_state("quote issuance requires a non-terminal case")
    if expected != case["version"]:
        raise err_stale_case_version()
    # supersede the prior ISSUED quote of the same type
    for q in case_quotes(case["id"]):
        if q["status"] == "ISSUED" and q["quote_type"] == quote_type:
            q["status"] = "SUPERSEDED"
            touch(q)
    nod = recorded_nod(case["id"])
    nod_date = parse_date_strict(nod["recording_date"]) if nod else None
    amounts = calc.quote_amounts(case, quote_type, good_through,
                                 total_approved_costs_cents(case["id"]), nod_date)
    quote = {
        "foreclosure_case_id": case["id"],
        "quote_type": quote_type,
        "good_through_date": format_date(good_through),
        "status": "ISSUED",
        "accepted_at": None,
    }
    quote.update(amounts)
    stamp_new(quote)
    db.quotes[quote["id"]] = quote
    touch(case)
    return success_object(quote_view(quote), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/quotes", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Beneficiary")
def list_quotes(user_id, role, case_id):
    get_case(case_id)
    items = case_quotes(case_id)
    quote_type = request.args.get("quote_type")
    status = request.args.get("status")
    if quote_type is not None:
        items = [q for q in items if q["quote_type"] == quote_type]
    if status is not None:
        # filters match the surfaced (derived) status
        items = [q for q in items if quote_derived_status(q) == status]
    limit, offset = parse_pagination(request.args)
    page = [quote_view(q) for q in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/quotes/<quote_id>/accept", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def accept_quote(user_id, role, quote_id):
    quote = get_quote(quote_id)
    body = get_body()
    check_unknown(body, {"tendered_amount_cents"})
    tendered = req_int(body, "tendered_amount_cents")
    case = get_case(quote["foreclosure_case_id"])
    # five checks in order (PRD §3.6)
    allowed_from = REINSTATEMENT_FROM if quote["quote_type"] == "REINSTATEMENT" else PAYOFF_FROM
    if case["lifecycle_status"] not in allowed_from:
        raise err_invalid_case_state("case status does not permit accepting this quote type")
    if quote["status"] != "ISSUED":
        # stored-terminal statuses only; expiry is temporal, not a state error
        raise err_invalid_quote_state("quote status is not ISSUED")
    if db.CLOCK.now_date() > parse_date_strict(quote["good_through_date"]):
        raise err_quote_expired()
    if quote["quote_type"] == "REINSTATEMENT":
        cutoff = reinstatement_cutoff(case)
        if cutoff is not None and db.CLOCK.now_date() > cutoff:
            # acceptance on the cutoff day itself is allowed
            raise err_reinstatement_cutoff()
    if tendered != quote["total_cents"]:
        # exact match; short or over both rejected
        raise err_payment_shortfall()
    quote["status"] = "ACCEPTED"
    quote["accepted_at"] = now_iso()
    touch(quote)
    apply_quote_acceptance(case, quote)
    return success_object(quote_view(quote))
