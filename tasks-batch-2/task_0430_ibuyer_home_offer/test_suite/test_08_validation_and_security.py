"""Cross-cutting validation and security: authentication, RBAC denials, FK
integrity, not-found, the property-locked withdraw guard, validation-priority
pairs, ownership isolation, and list pagination.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_seller_headers,
    set_clock,
    create_seller,
    create_property,
    issue_offer,
    setup_property_under_offer,
    setup_finalized_assessment,
    setup_scheduled_transaction,
    accept_offer,
    get_assessment_for_offer,
)

_ANALYST = TEST_USERS["pricing_analyst_headers"]
_ADMIN = TEST_USERS["operations_admin_headers"]
_SELLER = TEST_USERS["seller_headers"]


# --- Authentication / RBAC --------------------------------------------------

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_seller({"email": "noauth@x.com", "full_name": "No Auth"}, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_seller_cannot_issue_offer_returns_forbidden(api):
    """PRD §2.1: "If the headers are well-formed but the role named in `X-User-Role`
    is not permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 (POST /properties/{id}/offers): authorized role is "PricingAnalyst".

    Design: Corner/rbac/seller_cannot_issue_offer_returns_forbidden
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(seller["id"])
    validate_error(
        api.issue_offer(prop["id"], {"service_fee_pct": 0.05}, make_seller_headers(seller["id"])),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_pricing_analyst_cannot_finalize_assessment_returns_forbidden(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4 (POST /assessments/{id}/finalize): authorized role is "OperationsAdmin".

    Design: Corner/rbac/pricing_analyst_cannot_finalize_assessment_returns_forbidden
    """
    seller, prop, offer = setup_property_under_offer()
    accept_offer(offer["id"], seller["id"])
    assessment = get_assessment_for_offer(offer["id"])
    validate_error(
        api.finalize_assessment(
            assessment["id"],
            {"roof_condition": "GOOD", "hvac_condition": "GOOD", "foundation_condition": "GOOD"},
            _ANALYST,
        ),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )


def test_non_owner_seller_cannot_schedule_close(api):
    """PRD §2.1: "whenever a `Seller` acts on a property, an offer, or a transaction,
    the underlying property's `seller_id` must equal `X-User-ID`; if it does not, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/non_owner_seller_cannot_schedule_close
    """
    seller, prop, offer, txn, assessment, _ = setup_finalized_assessment()
    intruder = create_seller(email="intruder@example.com")
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-15T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(intruder["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )


# --- Not found / FK integrity -----------------------------------------------

def test_get_property_not_found_returns_404(api):
    """PRD §2.7: "The outer resource is resolved first; if it does not exist, the
    request fails with `ERR_NOT_FOUND` (HTTP 404) before any inner segment or body
    reference is considered."

    Design: Corner/entities/get_property_not_found_returns_404
    """
    validate_error(
        api.get_property(NON_EXISTENT_UUID, _ANALYST), ApiErrorId.ERR_NOT_FOUND
    )


def test_create_property_invalid_seller_fk_returns_404(api):
    """PRD §2.7: "The same `ERR_NOT_FOUND` governs foreign-key references supplied in
    a request body that do not resolve to an existing record."

    Design: Corner/entities/create_property_invalid_seller_fk_returns_404
    """
    validate_error(
        api.create_property(
            {
                "seller_id": NON_EXISTENT_UUID,
                "address_line": "103 Oak",
                "zip_code": "90001",
                "bedrooms": 3,
                "living_area_sqft": 1800,
                "comp_median_value": 500000,
            },
            _ANALYST,
        ),
        ApiErrorId.ERR_NOT_FOUND,
    )


# --- Business-rule guards ---------------------------------------------------

def test_withdraw_locked_property_in_transaction_rejected(api):
    """PRD §3.3: "Withdrawal is blocked once a transaction has advanced past
    `PENDING_ASSESSMENT`; an attempt to withdraw while such a transaction is in flight
    is rejected with `ERR_PROPERTY_LOCKED`."

    Design: Corner/validations/withdraw_locked_property_in_transaction_returns_error
    """
    seller, prop, offer, txn, assessment, _ = setup_scheduled_transaction()
    # Transaction is SCHEDULED (past PENDING_ASSESSMENT).
    validate_error(
        api.withdraw_property(prop["id"], {}, make_seller_headers(seller["id"])),
        ApiErrorId.ERR_PROPERTY_LOCKED,
    )


# --- Validation-priority pairs ----------------------------------------------

def test_non_owner_accepting_expired_offer_is_rejected(api):
    """PRD §2.1: "whenever a `Seller` acts on a property, an offer, or a transaction,
    the underlying property's `seller_id` must equal `X-User-ID`; if it does not, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.3: "an accept attempted at or after `expires_at` is rejected with
    `ERR_OFFER_EXPIRED`."

    The PRD names both errors for this two-failure scenario but states no global
    precedence between the §2.1 ownership check and the §3.3 expiry check for the
    accept endpoint, so a faithful PRD-only implementer could report either; accept
    both outcomes (error-precedence Silence pattern).

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_beats_not_owner_state_vs_temporal
    """
    set_clock("2026-03-01T00:00:00Z")
    owner = create_seller(email="owner@example.com")
    other = create_seller(email="other@example.com")
    prop = create_property(owner["id"])
    offer = issue_offer(prop["id"])
    # Advance past expiry (offer expires 2026-03-06): both ownership AND expiry fail.
    set_clock("2026-03-10T00:00:00Z")
    validate_error_is_one_of(
        api.accept_offer(offer["id"], {}, make_seller_headers(other["id"])),
        [ApiErrorId.ERR_NOT_RESOURCE_OWNER, ApiErrorId.ERR_OFFER_EXPIRED],
    )


def test_non_owner_accepting_non_expired_offer_reports_owner(api):
    """PRD §2.1: "whenever a `Seller` acts on a property, an offer, or a transaction,
    the underlying property's `seller_id` must equal `X-User-ID`; if it does not, the
    request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Ownership isolated as the sole failing precondition (the offer is still live), so
    ERR_NOT_RESOURCE_OWNER is uniquely derivable.

    Design: Difficulty/priority_pair_validation_conflict/expired_offer_beats_not_owner_state_vs_temporal
    """
    set_clock("2026-03-01T00:00:00Z")
    owner = create_seller(email="owner2@example.com")
    other = create_seller(email="other2@example.com")
    prop = create_property(owner["id"])
    offer = issue_offer(prop["id"])
    # Clock still well before expiry: only the ownership precondition fails.
    validate_error(
        api.accept_offer(offer["id"], {}, make_seller_headers(other["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER,
    )


def test_schedule_close_draft_assessment_reports_finalized_first(api):
    """PRD §3.5: "Scheduling enforces a sequence of preconditions, which are evaluated
    in priority order so that the earliest applicable failure is the one reported."
    PRD §3.5: "When these checks share the endpoint, the assessment-finalized check is
    evaluated before the close-date window, which is evaluated before the lease-back
    bound, which is evaluated before the repair-credit cap."
    PRD §3.5: "The linked assessment must already be `FINALIZED`; if it is not, the
    request is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`."

    Design: Difficulty/priority_pair_validation_conflict/assessment_not_finalized_beats_close_window_referential_vs_temporal
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(seller["id"])
    offer = issue_offer(prop["id"])
    txn = accept_offer(offer["id"], seller["id"])
    # Assessment still DRAFT AND close_date 2026-03-02 is out of window (only 1 day out):
    # the assessment-finalized check (priority 7) is reported before the window check.
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-03-02T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED,
    )


def test_schedule_close_draft_beats_window_even_above_max(api):
    """PRD §3.5: "When these checks share the endpoint, the assessment-finalized check
    is evaluated before the close-date window, which is evaluated before the
    lease-back bound, which is evaluated before the repair-credit cap."
    PRD §3.5: "The linked assessment must already be `FINALIZED`; if it is not, the
    request is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`."

    Design: Difficulty/priority_pair_validation_conflict/assessment_not_finalized_beats_close_window_referential_vs_temporal
    """
    set_clock("2026-03-01T00:00:00Z")
    seller = create_seller()
    prop = create_property(seller["id"])
    offer = issue_offer(prop["id"])
    txn = accept_offer(offer["id"], seller["id"])
    # Assessment still DRAFT AND close_date 2026-09-01 is above now+90d: the
    # assessment-finalized check (priority 7) is reported before the window check (9).
    validate_error(
        api.schedule_close(
            txn["id"],
            {"close_date": "2026-09-01T00:00:00Z", "leaseback_days": 0, "final_concession": 0},
            make_seller_headers(seller["id"]),
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED,
    )


# --- Pagination -------------------------------------------------------------

def test_list_properties_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter defaults to 10 when omitted, with a minimum of
    1 and a maximum of 100"
    PRD §2.3: "the `meta` object carries the effective `limit` and `offset` alongside
    `total_count` (the total number of records matching the query before pagination)
    and `has_more` (true when records remain beyond the current page)."

    Design: Corner/endpoints/list_properties_pagination_envelope
    """
    seller = create_seller()
    create_property(seller["id"], address_line="120 Oak", comp_median_value=500000)
    create_property(
        seller["id"], address_line="121 Oak", bedrooms=2, living_area_sqft=1200,
        comp_median_value=300000,
    )
    data, meta = validate_paginated(
        api.list_properties(_ANALYST, params={"seller_id": seller["id"], "limit": 1, "offset": 0})
    )
    assert len(data) == 1, data
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
