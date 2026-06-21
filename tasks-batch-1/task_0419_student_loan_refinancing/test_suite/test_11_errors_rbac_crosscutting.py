"""Remaining error triggers, RBAC forbidden-role denials, cross-cutting
complexity layers (OCC, cascading side effects, threshold triggers), and the
immediate-consistency model.

Corner queue B: sections errors, rbac, cross_cutting_complexity_layers,
consistency_model (non-stub instances only).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_borrower_headers,
    make_cosigner_headers,
    make_underwriter_headers,
    make_disbursement_officer_headers,
    make_servicing_agent_headers,
    setup_prequalified_application,
    setup_locked_application,
    setup_approved_application,
    setup_funded_loan,
    setup_loan_with_eligible_cosigner,
    create_borrower,
    create_application,
    invite_cosigner,
    schedule_disbursement,
    get_application,
    get_abs_pool,
    get_cosigner,
    list_offers,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BORROWER = TEST_USERS["borrower_headers"]


# ---------------------------------------------------------------------------
# Section: errors
# ---------------------------------------------------------------------------
def test_err_unauthenticated_missing_headers(api):
    """PRD 2.1: "If either header is missing, or if X-User-Role is not one of the
    known roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/err_unauthenticated_missing_headers
    """
    resp = api.approve_application("00000000-0000-4000-8000-0000000000dd", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_err_stale_application_version_on_lock(api):
    """PRD 2.8: "If the two do not match — for instance, because another writer has
    already locked a sibling offer on the same application, which legitimately
    supersedes the remaining presented offers and advances the application into
    UNDER_REVIEW, thereby advancing the application's version beyond what this
    client last read — the lock is rejected with ERR_STALE_APPLICATION_VERSION
    (HTTP 412)."

    Two PRESENTED offers; lock the first (advancing version), then lock the second
    with the now-stale observed version.

    ERROR PRECEDENCE: PRD 2.6 pins the order "target is in a legal source state
    (ERR_INVALID_STATE) ... then optimistic-concurrency staleness on offer lock
    (ERR_STALE_APPLICATION_VERSION)". Once the first lock advances the application
    from PREQUALIFIED to UNDER_REVIEW, a second lock attempt trips the state gate
    before the version check, so a PRD-faithful implementer may surface either
    ERR_INVALID_STATE or ERR_STALE_APPLICATION_VERSION. PRD 2.8 narrates this
    sibling-lock scenario as the canonical ERR_STALE_APPLICATION_VERSION case, so
    both members are accepted.

    Design: Corner/errors/err_stale_application_version_on_lock
    """
    from test_helpers import create_rate_grid_entry
    create_rate_grid_entry(rate_type="FIXED", term_months=120, min_fico_band="NEAR_PRIME",
                           base_apr_bps=650, index_apr_bps=0)
    create_rate_grid_entry(rate_type="FIXED", term_months=120, min_fico_band="SUBPRIME",
                           base_apr_bps=600, index_apr_bps=0)
    borrower = create_borrower(email="corner.b40@x.com", full_name="Corner B40",
                               annual_income_cents=30_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=5_000_000,
                                     requested_term_months=120, requested_rate_type="FIXED")
    from test_helpers import prequalify
    prequalified = prequalify(borrower, application)
    observed_version = prequalified["version"]
    offers = list_offers(borrower, application["id"])
    assert len(offers) >= 2, "two matching grid cells must mint two offers"

    headers = make_borrower_headers(borrower["id"])
    get_success_data(api.lock_offer(
        offers[0]["id"], {"expected_application_version": observed_version, "autopay_elected": False}, headers))
    resp = api.lock_offer(
        offers[1]["id"], {"expected_application_version": observed_version, "autopay_elected": False}, headers)
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_STALE_APPLICATION_VERSION.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


def test_err_segregation_of_duties_on_disbursement_send(api):
    """PRD 3.8: "the acting DisbursementOfficer's X-User-ID must differ from the
    approved_underwriter_id recorded on the parent application when it was
    approved; if the officer sending the payoff is the same principal who approved
    the application, the send is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP
    403)."

    Design: Corner/errors/err_segregation_of_duties_on_disbursement_send
    """
    shared_uw = "shared-uw"
    bundle = setup_funded_loan(
        underwriter_id=shared_uw,
        officer_id="do-corner-22",
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-SOD", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    disb = schedule_disbursement(loan, "do-corner-22", prior_servicer_name="Old Co",
                                 payoff_amount_cents=2_000_000)
    resp = api.send_disbursement(disb["id"], make_disbursement_officer_headers(shared_uw))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


# ---------------------------------------------------------------------------
# Section: rbac
# ---------------------------------------------------------------------------
def test_borrower_cannot_approve_application(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Approve is authorized for Underwriter only; a Borrower is forbidden.

    Design: Corner/rbac/borrower_cannot_approve_application
    """
    bundle = setup_locked_application(
        autopay_elected=False,
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    borrower = bundle["borrower"]
    resp = api.approve_application(bundle["application"]["id"], make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_underwriter_cannot_fund_application(api):
    """PRD 2.1: "If the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_FORBIDDEN_ROLE (HTTP 403)."

    Fund is authorized for DisbursementOfficer only; an Underwriter is forbidden.

    Design: Corner/rbac/underwriter_cannot_fund_application
    """
    from test_helpers import create_abs_pool
    create_abs_pool(pool_code="CORNER-POOL-RB1", max_principal_cents=20_000_000,
                    min_fico_band="SUBPRIME", allowed_rate_type="ANY")
    bundle = setup_approved_application(
        autopay_elected=False,
        underwriter_id="uw-corner-23",
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    resp = api.fund_application(bundle["application"]["id"], make_underwriter_headers("uw-corner-23"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_servicing_agent_cannot_create_abs_pool(api):
    """PRD 4 (endpoint table): POST /abs-pools is authorized for PlatformAdmin
    only; a ServicingAgent is forbidden.
    PRD 2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/servicing_agent_cannot_create_abs_pool
    """
    resp = api.create_abs_pool(
        {"pool_code": "CORNER-POOL-RB2", "max_principal_cents": 10_000_000, "min_fico_band": "SUBPRIME",
         "allowed_rate_type": "ANY"}, make_servicing_agent_headers("sa-corner-24"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_cosigner_cannot_lock_offer(api):
    """PRD 4 (endpoint table): POST /offers/{id}/lock is authorized for Borrower
    only; the Cosigner role is forbidden.
    PRD 2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/cosigner_cannot_lock_offer
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
        with_cosigner=True,
        cosigner_overrides={"cosigner_annual_income_cents": 6_000_000},
        cosigner_consents=False,
    )
    app = bundle["application"]
    offer = bundle["offers"][0]
    cosigner = bundle["cosigner"]
    resp = api.lock_offer(
        offer["id"], {"expected_application_version": app["version"], "autopay_elected": False},
        make_cosigner_headers(cosigner["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_disbursement_officer_cannot_start_forbearance(api):
    """PRD 4 (endpoint table): POST /loans/{id}/forbearance is authorized for
    ServicingAgent only; a DisbursementOfficer is forbidden.
    PRD 2.1: "the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/disbursement_officer_cannot_start_forbearance
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-RB3", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    resp = api.start_forbearance(loan["id"], {"reason_code": "MEDICAL", "months_requested": 3},
                                 make_disbursement_officer_headers("do-corner-25"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ---------------------------------------------------------------------------
# Section: cross_cutting_complexity_layers
# ---------------------------------------------------------------------------
def test_occ_correct_version_lock_succeeds_and_bumps_version(api):
    """PRD 3.4: "The application moves to UNDER_REVIEW and its version is
    incremented by 1 — this is precisely the increment that makes a concurrent
    lock against a stale expected_application_version fail."

    Locking with the matching version succeeds and bumps the version by 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_lock_succeeds_and_bumps_version
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    borrower = bundle["borrower"]
    app = bundle["application"]
    observed = app["version"]
    offer = bundle["offers"][0]
    locked = validate_success(api.lock_offer(
        offer["id"], {"expected_application_version": observed, "autopay_elected": False},
        make_borrower_headers(borrower["id"])), 200)
    assert locked["status"] == "LOCKED"
    app_after = get_application(app["id"])
    assert app_after["status"] == "UNDER_REVIEW"
    assert app_after["version"] == observed + 1, (
        f"version should bump from {observed} to {observed + 1}, got {app_after['version']}"
    )


def test_lock_supersedes_sibling_presented_offers(api):
    """PRD 3.4: "Every sibling offer on the same application still in PRESENTED is
    set to SUPERSEDED."

    Design: Corner/cross_cutting_complexity_layers/lock_supersedes_sibling_presented_offers
    """
    from test_helpers import create_rate_grid_entry, prequalify
    create_rate_grid_entry(rate_type="FIXED", term_months=120, min_fico_band="NEAR_PRIME",
                           base_apr_bps=650, index_apr_bps=0)
    create_rate_grid_entry(rate_type="FIXED", term_months=120, min_fico_band="SUBPRIME",
                           base_apr_bps=600, index_apr_bps=0)
    borrower = create_borrower(email="corner.b47@x.com", full_name="Corner B47",
                               annual_income_cents=30_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=5_000_000,
                                     requested_term_months=120, requested_rate_type="FIXED")
    prequalified = prequalify(borrower, application)
    observed = prequalified["version"]
    offers = list_offers(borrower, application["id"])
    assert len(offers) >= 2
    headers = make_borrower_headers(borrower["id"])
    validate_success(api.lock_offer(
        offers[0]["id"], {"expected_application_version": observed, "autopay_elected": False}, headers), 200)
    sibling = get_success_data(api.get_offer(offers[1]["id"], headers))
    assert sibling["status"] == "SUPERSEDED", (
        f"sibling PRESENTED offer should be SUPERSEDED, got {sibling['status']}"
    )


def test_withdraw_cascades_supersede_to_nonterminal_offers(api):
    """PRD 3.6: "Withdrawal moves the application to the terminal WITHDRAWN state,
    expires every non-terminal offer on the application by setting it to
    SUPERSEDED, and records an application audit event."

    Design: Corner/cross_cutting_complexity_layers/withdraw_cascades_supersede_to_nonterminal_offers
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    borrower = bundle["borrower"]
    app = bundle["application"]
    offer = bundle["offers"][0]
    headers = make_borrower_headers(borrower["id"])
    withdrawn = validate_success(api.withdraw_application(app["id"], headers), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    offer_after = get_success_data(api.get_offer(offer["id"], headers))
    assert offer_after["status"] == "SUPERSEDED", (
        f"non-terminal offer should be SUPERSEDED on withdraw, got {offer_after['status']}"
    )


def test_streak_threshold_crossing_makes_release_eligible(api):
    """PRD 3.10: "the cosigner's on_time_streak has reached at least the release
    threshold of 3 consecutive on-time payments, the release dimension advances
    from PENDING to ELIGIBLE and a loan audit event marking release eligibility is
    recorded."

    Three consecutive on-time payments take on_time_streak to 3 and flip
    cosigner_release_status PENDING -> ELIGIBLE on a CURRENT loan.

    Design: Corner/cross_cutting_complexity_layers/streak_threshold_crossing_makes_release_eligible
    """
    bundle = setup_loan_with_eligible_cosigner(
        base_clock="2026-06-01T00:00:00Z",
        payment_amount_cents=40_000,
        pool_overrides={"pool_code": "CORNER-POOL-THR", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
    )
    assert bundle["cosigner"]["on_time_streak"] == 3, (
        f"streak should reach 3, got {bundle['cosigner']['on_time_streak']}"
    )
    assert bundle["loan"]["cosigner_release_status"] == "ELIGIBLE", (
        f"release status should flip to ELIGIBLE, got {bundle['loan']['cosigner_release_status']}"
    )


# ---------------------------------------------------------------------------
# Section: consistency_model
# ---------------------------------------------------------------------------
def test_immediate_committed_principal_visible_after_funding(api):
    """PRD 3.7: "the chosen pool's committed_principal_cents is increased by that
    same original principal."

    Reading the pool right after funding shows committed_principal_cents already
    reflecting the funded loan's principal (immediate consistency, no lag).

    Design: Corner/consistency_model/immediate_committed_principal_visible_in_fund_response_chain
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-IMM", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    pool_after = get_abs_pool(bundle["pool"]["id"])
    assert pool_after["committed_principal_cents"] == 5_000_000, (
        f"committed_principal_cents should be 5,000,000 immediately, got {pool_after['committed_principal_cents']}"
    )
