"""Shared helpers for route modules."""
from __future__ import annotations

from flask import g, request

from config import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from db import store
from errors import (
    err_forbidden_for_role,
    err_invalid_request,
    err_invalid_state_transition,
    err_not_found,
)


# ── Body parsing ───────────────────────────────────────────────────────────


def get_json() -> dict:
    """Return the request JSON body (always a dict, tolerates empty bodies)."""
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        data = request.get_data(as_text=True)
        if not data.strip():
            return {}
        try:
            import json
            body = json.loads(data)
        except Exception:
            body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


# ── Pagination ─────────────────────────────────────────────────────────────


def parse_pagination():
    """Read limit/offset from query string, validate per PRD §2.3.

    Out-of-bounds values yield ERR_INVALID_REQUEST (400). Defaults apply if
    omitted (limit=10, offset=0). Min limit=1, max=100.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_request(
                f"limit must be in [{MIN_LIMIT},{MAX_LIMIT}]; got {limit}."
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer.")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> list:
    return items[offset:offset + limit]


def sort_for_list(items):
    """Default sort: created_at ASC, with id as deterministic tie-break."""
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))


# ── OCC ────────────────────────────────────────────────────────────────────


def parse_version(body: dict):
    if not isinstance(body, dict):
        return None
    if "version" not in body:
        return None
    v = body["version"]
    if v is None:
        return None
    if isinstance(v, bool):
        raise err_invalid_request("version must be a non-negative integer.")
    if isinstance(v, int):
        return v
    raise err_invalid_request("version must be a non-negative integer.")


def check_version(entity: dict, expected) -> None:
    """OCC check: a mismatch on the version raises ERR_INVALID_STATE_TRANSITION
    (per PRD §2.5)."""
    if expected is None:
        return
    if entity.get("version") != expected:
        raise err_invalid_state_transition("Optimistic concurrency: version mismatch.")


# ── Resource lookup (path resolution) ─────────────────────────────────────


def get_platform(platform_id: str) -> dict:
    p = store.platforms.get(platform_id)
    if p is None:
        raise err_not_found(f"Platform {platform_id} not found.")
    return p


def get_borrower(platform_id: str, borrower_id: str) -> dict:
    get_platform(platform_id)
    b = store.borrowers.get(borrower_id)
    if b is None or b["platform_id"] != platform_id:
        raise err_not_found(f"Borrower {borrower_id} not found.")
    return b


def get_investor(platform_id: str, investor_id: str) -> dict:
    get_platform(platform_id)
    i = store.investors.get(investor_id)
    if i is None or i["platform_id"] != platform_id:
        raise err_not_found(f"Investor {investor_id} not found.")
    return i


def get_listing(platform_id: str, listing_id: str) -> dict:
    get_platform(platform_id)
    l = store.loan_listings.get(listing_id)
    if l is None or l["platform_id"] != platform_id:
        raise err_not_found(f"Listing {listing_id} not found.")
    return l


def get_loan(platform_id: str, loan_id: str) -> dict:
    get_platform(platform_id)
    l = store.loans.get(loan_id)
    if l is None or l["platform_id"] != platform_id:
        raise err_not_found(f"Loan {loan_id} not found.")
    return l


def get_investment(platform_id: str, investment_id: str) -> dict:
    get_platform(platform_id)
    inv = store.investments.get(investment_id)
    if inv is None:
        raise err_not_found(f"Investment {investment_id} not found.")
    listing = store.loan_listings.get(inv["listing_id"])
    if listing is None or listing["platform_id"] != platform_id:
        raise err_not_found(f"Investment {investment_id} not found.")
    return inv


def get_payment(platform_id: str, payment_id: str) -> dict:
    get_platform(platform_id)
    p = store.payments.get(payment_id)
    if p is None:
        raise err_not_found(f"Payment {payment_id} not found.")
    loan = store.loans.get(p["loan_id"])
    if loan is None or loan["platform_id"] != platform_id:
        raise err_not_found(f"Payment {payment_id} not found.")
    return p


def get_disclosure(platform_id: str, disclosure_id: str) -> dict:
    get_platform(platform_id)
    d = store.disclosures.get(disclosure_id)
    if d is None or d["platform_id"] != platform_id:
        raise err_not_found(f"Disclosure {disclosure_id} not found.")
    return d


def get_compliance_officer(platform_id: str, officer_id: str) -> dict:
    get_platform(platform_id)
    o = store.compliance_officers.get(officer_id)
    if o is None or o["platform_id"] != platform_id:
        raise err_not_found(f"Compliance officer {officer_id} not found.")
    return o


# ── Ownership helpers (entity-backed roles) ────────────────────────────────


def enforce_borrower_ownership(borrower_id: str):
    """When role == Borrower, X-User-ID MUST match the borrower id."""
    if g.role == "Borrower" and g.user_id != borrower_id:
        raise err_forbidden_for_role("Borrower may only act on their own borrower id.")


def enforce_investor_ownership(investor_id: str):
    if g.role == "Investor" and g.user_id != investor_id:
        raise err_forbidden_for_role("Investor may only act on their own investor id.")


def enforce_compliance_officer_identity(platform_id: str):
    """When role == ComplianceOfficer, X-User-ID MUST resolve to a CO entity
    under this platform.

    Per PRD §2.1: ComplianceOfficer is entity-backed; X-User-ID is the id of
    the acting ComplianceOfficer record on the platform. A handle that does
    not resolve is rejected with ERR_FORBIDDEN_FOR_ROLE.
    """
    if g.role != "ComplianceOfficer":
        return
    officer = store.compliance_officers.get(g.user_id)
    if officer is None or officer.get("platform_id") != platform_id:
        raise err_forbidden_for_role(
            "ComplianceOfficer identity does not resolve on this platform."
        )


def enforce_borrower_role_resolves(platform_id: str, borrower_id: str | None = None):
    """When role == Borrower, X-User-ID must resolve to an actual Borrower row
    under this platform. If borrower_id is provided, X-User-ID must equal it.
    """
    if g.role != "Borrower":
        return
    b = store.borrowers.get(g.user_id)
    if b is None or b.get("platform_id") != platform_id:
        raise err_forbidden_for_role(
            "Borrower identity does not resolve on this platform."
        )
    if borrower_id is not None and g.user_id != borrower_id:
        raise err_forbidden_for_role(
            "Borrower may only act on their own borrower id."
        )


def enforce_investor_role_resolves(platform_id: str, investor_id: str | None = None):
    if g.role != "Investor":
        return
    inv = store.investors.get(g.user_id)
    if inv is None or inv.get("platform_id") != platform_id:
        raise err_forbidden_for_role(
            "Investor identity does not resolve on this platform."
        )
    if investor_id is not None and g.user_id != investor_id:
        raise err_forbidden_for_role(
            "Investor may only act on their own investor id."
        )
