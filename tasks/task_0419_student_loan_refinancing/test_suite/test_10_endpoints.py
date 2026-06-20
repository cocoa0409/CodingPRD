"""Endpoint behaviors: FK reverse-reachability list filters, conditional
actions (pool close), clock-driven offer expiry sweep, payment side effects.

Corner queue B: section endpoints.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_borrower_headers,
    make_disbursement_officer_headers,
    make_servicing_agent_headers,
    setup_prequalified_application,
    setup_approved_application,
    setup_funded_loan,
    create_borrower,
    create_application,
    prequalify,
    invite_cosigner,
    set_clock,
    schedule_disbursement,
    post_payment,
    start_forbearance,
    get_cosigner,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_list_offers_filtered_by_application_id(api):
    """PRD 2.5: "offers can be listed by application_id"

    Design: Corner/endpoints/list_offers_filtered_by_application_id
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
    # A second unrelated application also prequalified.
    app_b = create_application(borrower, requested_principal_cents=4_000_000,
                               requested_term_months=60, requested_rate_type="FIXED")
    prequalify(borrower, app_b)

    resp = api.list_offers(make_borrower_headers(borrower["id"]), params={"application_id": app["id"]})
    data, meta = validate_paginated(resp)
    assert all(o["application_id"] == app["id"] for o in data), "every offer must belong to the app"
    assert meta["total_count"] == 1, f"total_count should be 1, got {meta['total_count']}"


def test_list_loans_filtered_by_abs_pool_id(api):
    """PRD 2.5: "loans by application_id and by abs_pool_id"

    Design: Corner/endpoints/list_loans_filtered_by_abs_pool_id
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-LIST", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    pool = bundle["pool"]
    resp = api.list_loans(make_servicing_agent_headers("sa-corner-16"), params={"abs_pool_id": pool["id"]})
    data, meta = validate_paginated(resp)
    assert all(loan["abs_pool_id"] == pool["id"] for loan in data)
    assert meta["total_count"] == 1


def test_list_payments_reverse_reachability_for_loan(api):
    """PRD 2.5: "payments and forbearance plans and disbursements by their
    loan_id"

    Design: Corner/endpoints/list_payments_reverse_reachability_for_loan
    """
    bundle = setup_funded_loan(
        clock_at="2026-06-01T00:00:00Z",
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-PAY", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    post_payment(loan, 100_000, "2026-06-01T00:00:00Z", paid_at="2026-06-01T00:00:00Z",
                 servicing_agent_id="sa-corner-17")
    resp = api.list_payments(loan["id"], make_servicing_agent_headers("sa-corner-17"),
                             params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(p["loan_id"] == loan["id"] for p in data)


def test_list_forbearance_plans_filtered_by_loan_id(api):
    """PRD 2.5: "payments and forbearance plans and disbursements by their
    loan_id"

    Design: Corner/endpoints/list_forbearance_plans_filtered_by_loan_id
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-FBL", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    start_forbearance(loan, servicing_agent_id="sa-corner-18", reason_code="JOB_LOSS", months_requested=4)
    resp = api.list_forbearance_plans(make_servicing_agent_headers("sa-corner-18"),
                                      params={"loan_id": loan["id"]})
    data, meta = validate_paginated(resp)
    assert all(p["loan_id"] == loan["id"] for p in data)
    assert meta["total_count"] == 1


def test_list_disbursements_filtered_by_loan_id(api):
    """PRD 2.5: "payments and forbearance plans and disbursements by their
    loan_id"

    Design: Corner/endpoints/list_disbursements_filtered_by_loan_id
    """
    bundle = setup_funded_loan(
        officer_id="do-corner-19",
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-DBL", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    schedule_disbursement(loan, "do-corner-19", prior_servicer_name="Old Co", payoff_amount_cents=2_500_000)
    resp = api.list_disbursements(make_disbursement_officer_headers("do-corner-19"),
                                  params={"loan_id": loan["id"]})
    data, meta = validate_paginated(resp)
    assert all(d["loan_id"] == loan["id"] for d in data)
    assert meta["total_count"] == 1


def test_list_cosigners_filtered_by_application_id(api):
    """PRD 2.5: "cosigners by application_id"

    Design: Corner/endpoints/list_cosigners_filtered_by_application_id
    """
    borrower = create_borrower(email="corner.b35@x.com", full_name="Corner B35",
                               annual_income_cents=30_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=4_000_000,
                                     requested_term_months=60, requested_rate_type="FIXED")
    invite_cosigner(borrower, application, cosigner_email="corner.c35@x.com",
                    cosigner_annual_income_cents=2_000_000)
    resp = api.list_cosigners(make_borrower_headers(borrower["id"]),
                              params={"application_id": application["id"]})
    data, meta = validate_paginated(resp)
    assert all(c["application_id"] == application["id"] for c in data)
    assert meta["total_count"] == 1


def test_list_audit_events_filtered_by_subject_polymorphic(api):
    """PRD 2.5: "and audit events by subject_type and subject_id"
    PRD 3.12: "Audit events are append-only and are read back filtered by
    subject_type and subject_id."

    Design: Corner/endpoints/list_audit_events_filtered_by_subject_polymorphic
    """
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    app = bundle["application"]
    resp = api.list_audit_events(ADMIN, params={"subject_type": "APPLICATION", "subject_id": app["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) >= 1, "prequalify must have appended an APPLICATION audit event"
    assert all(e["subject_id"] == app["id"] for e in data)
    assert all(e["subject_type"] == "APPLICATION" for e in data)


def test_close_pool_excludes_from_funding_candidate_set(api):
    """PRD 3.1: "A pool may be closed to new loans, which sets its status to
    CLOSED; only OPEN pools are candidates at funding time."
    PRD 3.7: "If that candidate set is empty, funding is rejected with
    ERR_NO_ELIGIBLE_POOL (HTTP 422) and no loan is created."

    Design: Corner/endpoints/close_pool_excludes_from_funding_candidate_set
    """
    from test_helpers import create_abs_pool
    pool = create_abs_pool(pool_code="CORNER-POOL-CLOSE", max_principal_cents=20_000_000,
                           min_fico_band="SUBPRIME", allowed_rate_type="ANY")
    bundle = setup_approved_application(
        autopay_elected=False,
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    closed = validate_success(api.close_abs_pool(pool["id"], ADMIN), 200)
    assert closed["status"] == "CLOSED"
    resp = api.fund_application(bundle["application"]["id"], make_disbursement_officer_headers("do-corner-20"))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_POOL.value, 422)


def test_clock_set_governs_offer_expiry_sweep(api):
    """PRD 3.6: "The sweep is defined only when the application is in PREQUALIFIED
    and only when every offer on the application has an expires_at at or before the
    current clock. When both hold, every offer still in PRESENTED is set to
    EXPIRED, the application moves to the terminal EXPIRED state"

    Design: Corner/endpoints/clock_set_governs_offer_expiry_sweep
    """
    set_clock("2026-06-01T00:00:00Z")
    bundle = setup_prequalified_application(
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 4_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    app = bundle["application"]
    offer = bundle["offers"][0]
    set_clock("2026-12-01T00:00:00Z")
    expired_app = validate_success(api.expire_offers(app["id"], ADMIN), 200)
    assert expired_app["status"] == "EXPIRED"
    offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
    assert offer_after["status"] == "EXPIRED", f"offer should be EXPIRED, got {offer_after['status']}"


def test_payment_side_effect_streak_increment_on_time(api):
    """PRD 3.9: "When the payment is on time and the loan's repayment_status is
    CURRENT, and a CONSENTED cosigner exists, that cosigner's on_time_streak is
    incremented by 1."

    Design: Corner/endpoints/payment_side_effect_streak_increment_on_time
    """
    set_clock("2026-07-01T00:00:00Z")
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-STRK", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
        with_cosigner=True,
    )
    loan = bundle["loan"]
    cosigner = bundle["cosigner"]
    payment = post_payment(loan, 50_000, "2026-07-01T00:00:00Z", paid_at="2026-07-01T00:00:00Z",
                           servicing_agent_id="sa-corner-21")
    assert payment["on_time"] is True
    assert get_cosigner(cosigner["id"])["on_time_streak"] == 1
