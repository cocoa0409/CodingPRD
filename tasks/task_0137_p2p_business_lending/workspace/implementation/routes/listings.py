"""LoanListing endpoints: create (under borrower), get, list, withdraw, originate, invest."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import ALLOWED_TERM_MONTHS, FUNDING_DEADLINE_DAYS
from db import store
from errors import (
    err_borrower_not_approved,
    err_borrower_not_listable,
    err_cross_platform_investment,
    err_diversification_cap_exceeded,
    err_forbidden_for_role,
    err_insufficient_cash,
    err_invalid_request,
    err_invalid_state_transition,
    err_investment_denomination,
    err_listing_integrity,
    err_listing_oversubscribed,
    err_segregation_violation,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_borrower_role_resolves,
    enforce_investor_role_resolves,
    get_borrower,
    get_json,
    get_listing,
    get_platform,
    paginate,
    parse_pagination,
    sort_for_list,
)
from services.calculations import (
    compute_interest_rate_bps,
    diversification_cap_cents,
)
from services.engine import (
    emit_disclosure,
    maybe_listing_funded,
    originate_loan_from_listing,
    stamp_create,
    stamp_update,
    withdraw_listing_cascade,
)
from services.serializers import (
    serialize_investment,
    serialize_listing,
    serialize_loan,
)
from utils import is_pos_int

bp = Blueprint("listings", __name__)


# ── POST /platforms/{platformId}/borrowers/{borrowerId}/listings ──────────


@bp.post("/platforms/<platform_id>/borrowers/<borrower_id>/listings")
@require_auth(["Borrower", "PlatformOperator"])
def create_listing(platform_id, borrower_id):
    platform = get_platform(platform_id)
    borrower = get_borrower(platform_id, borrower_id)
    enforce_borrower_role_resolves(platform_id, borrower_id)

    body = get_json()
    principal = body.get("principal_cents")
    term = body.get("term_months")
    if not is_pos_int(principal):
        raise err_invalid_request("principal_cents must be a positive integer.")
    if term not in ALLOWED_TERM_MONTHS:
        raise err_invalid_request(
            f"term_months must be one of {sorted(ALLOWED_TERM_MONTHS)}."
        )

    # Borrower must be APPROVED.
    if borrower["status"] != "APPROVED":
        raise err_borrower_not_listable(
            f"Borrower not APPROVED (status={borrower['status']})."
        )
    # No existing OPEN/FUNDED listing.
    for l in store.listings_for_borrower(borrower_id):
        if l["status"] in ("OPEN", "FUNDED"):
            raise err_borrower_not_listable(
                "Borrower already has an OPEN/FUNDED listing."
            )

    grade = borrower["final_grade"]
    if grade not in ("A", "B", "C", "D", "E"):
        raise err_borrower_not_listable("Borrower has no investable final_grade.")

    interest_rate_bps = compute_interest_rate_bps(grade, term)
    with store.lock:
        listing = {
            "borrower_id": borrower_id,
            "platform_id": platform_id,
            "principal_cents": principal,
            "term_months": term,
            "grade_at_listing": grade,
            "interest_rate_bps": interest_rate_bps,
            "pledged_cents": 0,
            "funding_deadline_day_index": platform["clock_day_index"] + FUNDING_DEADLINE_DAYS,
            "status": "OPEN",
        }
        stamp_create(listing)
        store.loan_listings[listing["id"]] = listing
        emit_disclosure(platform_id, "LISTING_OPENED", listing)
    return success(serialize_listing(listing), 201)


# ── GET /platforms/{platformId}/listings/{listingId} ──────────────────────


@bp.get("/platforms/<platform_id>/listings/<listing_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def get_listing_route(platform_id, listing_id):
    l = get_listing(platform_id, listing_id)
    # Scope reads for entity-backed roles. Borrower may only read their own
    # borrower's listings; Investor may read any listing on their platform.
    if g.role == "Borrower":
        if g.user_id != l["borrower_id"]:
            raise err_forbidden_for_role("Borrower may only read their own listings.")
    return success(serialize_listing(l))


# ── GET /platforms/{platformId}/listings ──────────────────────────────────


@bp.get("/platforms/<platform_id>/listings")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Borrower", "Investor"])
def list_listings(platform_id):
    get_platform(platform_id)
    limit, offset = parse_pagination()
    borrower_id = request.args.get("borrower_id")
    status_f = request.args.get("status")
    grade_f = request.args.get("grade")

    items = [l for l in store.loan_listings.values() if l["platform_id"] == platform_id]

    # Borrower role: only own.
    if g.role == "Borrower":
        items = [l for l in items if l["borrower_id"] == g.user_id]

    if borrower_id:
        items = [l for l in items if l["borrower_id"] == borrower_id]
    if status_f:
        items = [l for l in items if l["status"] == status_f]
    if grade_f:
        items = [l for l in items if l.get("grade_at_listing") == grade_f]

    items = sort_for_list(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success([serialize_listing(x) for x in page], limit, offset, total)


# ── POST /platforms/{platformId}/listings/{listingId}/withdraw ────────────


@bp.post("/platforms/<platform_id>/listings/<listing_id>/withdraw")
@require_auth(["Borrower", "PlatformOperator"])
def withdraw_route(platform_id, listing_id):
    listing = get_listing(platform_id, listing_id)
    # Borrower must own the listing.
    if g.role == "Borrower":
        enforce_borrower_role_resolves(platform_id, listing["borrower_id"])
    if listing["status"] != "OPEN":
        raise err_invalid_state_transition(
            f"Listing not OPEN (was {listing['status']})."
        )
    with store.lock:
        withdraw_listing_cascade(listing)
    return success(serialize_listing(listing))


# ── POST /platforms/{platformId}/listings/{listingId}/originate ───────────


@bp.post("/platforms/<platform_id>/listings/<listing_id>/originate")
@require_auth(["PlatformOperator", "ComplianceOfficer"])
def originate_route(platform_id, listing_id):
    platform = get_platform(platform_id)
    listing = get_listing(platform_id, listing_id)
    # PRD §3.4: "A FUNDED listing is originated by a PlatformOperator
    # (a ComplianceOfficer may not originate, per segregation of duties,
    # and an attempt by them returns ERR_SEGREGATION_VIOLATION)." The
    # role-list above admits ComplianceOfficer past the structural gate
    # so the segregation-of-duties rejection (ERR_SEGREGATION_VIOLATION)
    # is the one observed, per PRD §3.9.
    if g.role == "ComplianceOfficer":
        raise err_segregation_violation(
            "ComplianceOfficer may not originate (segregation of duties)."
        )
    if listing["status"] != "FUNDED":
        raise err_invalid_state_transition(
            f"Listing not FUNDED (was {listing['status']})."
        )

    borrower = store.borrowers.get(listing["borrower_id"])
    if borrower is None or borrower["status"] != "APPROVED":
        raise err_borrower_not_approved()

    # All investments on the listing must be COMMITTED.
    invs = store.investments_for_listing(listing_id)
    if not invs or any(i["status"] != "COMMITTED" for i in invs):
        raise err_listing_integrity()

    with store.lock:
        loan = originate_loan_from_listing(platform, listing)
    return success(serialize_loan(loan))


# ── POST /platforms/{platformId}/listings/{listingId}/investments ─────────


@bp.post("/platforms/<platform_id>/listings/<listing_id>/investments")
@require_auth(["Investor"])
def create_investment(platform_id, listing_id):
    platform = get_platform(platform_id)
    listing = get_listing(platform_id, listing_id)
    body = get_json()
    amount = body.get("amount_cents")

    # Resolve the calling Investor entity by X-User-ID (not yet bound to
    # the URL's platform — the cross-platform business validation below
    # is what enforces the platform match, per PRD §2.9 priority 6).
    investor = store.investors.get(g.user_id)
    if investor is None:
        # The identity doesn't map to any Investor — treat as forbidden.
        from errors import err_forbidden_for_role as _fr
        raise _fr("Investor identity does not resolve.")

    # Validation priority per PRD §2.9:
    #   state → segregation → cross-platform → diversification → cash → oversub → denomination

    # State: listing must be OPEN.
    if listing["status"] != "OPEN":
        raise err_invalid_state_transition(
            f"Listing not OPEN (was {listing['status']})."
        )

    # Segregation: Borrower cannot self-invest. When role == Investor, the
    # acting investor entity cannot be the borrower behind the listing.
    # Two interpretations: (a) X-User-ID equals listing.borrower_id, or
    # (b) the investor "represents" the same legal entity as the borrower.
    # We model the literal id-collision case (a) which is the only one
    # observable through the in-memory store.
    if g.user_id == listing["borrower_id"]:
        raise err_segregation_violation(
            "An investor may not pledge into a listing owned by the same id (self-investment)."
        )

    # Cross-platform: investor.platform_id must equal listing.platform_id.
    if investor["platform_id"] != listing["platform_id"]:
        raise err_cross_platform_investment()

    # Pre-compute basic type validity for amount (we'll do denomination last
    # but need a number to compute downstream checks). If amount is not even
    # a non-negative int, treat as denomination problem at the very end.
    valid_int_amount = (
        isinstance(amount, int) and not isinstance(amount, bool) and amount > 0
    )

    # Diversification cap.
    if valid_int_amount:
        cap = diversification_cap_cents(
            investor["committed_capital_cents"],
            platform["max_borrower_concentration_bps"],
        )
        # Existing exposure to this borrower (COMMITTED + CONVERTED).
        existing_exposure = 0
        for inv in store.investments.values():
            if inv["investor_id"] != g.user_id:
                continue
            if inv["status"] not in ("COMMITTED", "CONVERTED"):
                continue
            other_listing = store.loan_listings.get(inv["listing_id"])
            if other_listing is None:
                continue
            if other_listing["borrower_id"] == listing["borrower_id"]:
                existing_exposure += inv["amount_cents"]
        proposed_total = existing_exposure + amount
        if proposed_total > cap:
            raise err_diversification_cap_exceeded()

    # Cash sufficiency.
    if valid_int_amount and investor["cash_balance_cents"] < amount:
        raise err_insufficient_cash()

    # Oversubscription.
    if valid_int_amount and listing["pledged_cents"] + amount > listing["principal_cents"]:
        raise err_listing_oversubscribed()

    # Denomination (last).
    if not valid_int_amount:
        raise err_investment_denomination(
            "amount_cents must be a positive integer."
        )
    from config import INVESTMENT_MULTIPLE_CENTS, MIN_INVESTMENT_CENTS
    if amount < MIN_INVESTMENT_CENTS:
        raise err_investment_denomination()
    if amount % INVESTMENT_MULTIPLE_CENTS != 0:
        raise err_investment_denomination()

    with store.lock:
        # Re-check oversubscription inside lock (race protection).
        if listing["pledged_cents"] + amount > listing["principal_cents"]:
            raise err_listing_oversubscribed()
        investment = {
            "listing_id": listing_id,
            "investor_id": g.user_id,
            "amount_cents": amount,
            "status": "COMMITTED",
            "share_bps": 0,
        }
        stamp_create(investment)
        store.investments[investment["id"]] = investment

        # Side effects.
        investor["cash_balance_cents"] -= amount
        stamp_update(investor)

        listing["pledged_cents"] += amount
        stamp_update(listing)
        maybe_listing_funded(listing, platform)
    return success(serialize_investment(investment), 201)


# ── GET /platforms/{platformId}/investments/{investmentId} ────────────────


@bp.get("/platforms/<platform_id>/investments/<investment_id>")
@require_auth(["PlatformOperator", "ComplianceOfficer", "Investor"])
def get_investment_route(platform_id, investment_id):
    from routes._helpers import get_investment
    inv = get_investment(platform_id, investment_id)
    if g.role == "Investor":
        enforce_investor_role_resolves(platform_id, inv["investor_id"])
    return success(serialize_investment(inv))
