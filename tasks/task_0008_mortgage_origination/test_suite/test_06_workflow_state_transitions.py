"""Withdraw cascade, cross-entity state gates, and miscellaneous
invalid-state lockouts.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_income_verification_payload,
    create_title_search_payload,
    setup_applicant_and_loan_application_draft,
    setup_prequalified_loan_application,
    setup_prequalified_with_active_lock,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_withdraw_cancels_active_ratelock_depth2(api, lo_headers):
    """PRD §3.9: "A `LoanOfficer` may withdraw an application from `DRAFT`,
    `PREQUALIFIED`, or `UNDER_REVIEW`; the application transitions to the
    terminal `WITHDRAWN` state, any `ACTIVE` rate lock on the application is
    auto-transitioned to `CANCELLED` as a side effect, and the application's
    `version` is incremented by one."

    Design: Difficulty/transitive_cascade/withdraw_loan_application_cancels_active_ratelock_depth2
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "J",
            "email": "j.withdraw@test.com",
            "ssn_last4": "8888",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "property_address": "Withdraw Rd",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
        locked_rate_bps=687,
        lock_term_days=30,
        clock_iso="2026-06-01T00:00:00Z",
    )
    withdrawn = validate_success(api.withdraw_loan_application(app["id"], lo_headers), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    lock_after = validate_success(api.get_rate_lock(lock["id"], lo_headers), 200)
    assert lock_after["status"] == "CANCELLED"


def test_income_verification_accept_blocked_when_parent_loan_in_draft(api, lo_headers, underwriter_headers):
    """PRD §3.3: "An `Underwriter` reviews each verification while the parent
    loan application is in either `PREQUALIFIED` or `UNDER_REVIEW`. Accepting
    a verification transitions it from `PENDING` to `ACCEPTED` and increments
    its `version`."
    PRD §2.8: "then current-state legality (`ERR_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/income_verification_accept_requires_loan_application_non_terminal
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "P",
            "email": "p.iv@test.com",
            "ssn_last4": "9006",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
    )
    iv = validate_success(
        api.create_income_verification(
            create_income_verification_payload(
                app["id"], verified_annual_income_cents=7_800_000
            ),
            lo_headers,
        ),
        201,
    )
    res = api.accept_income_verification(iv["id"], underwriter_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    iv_after = validate_success(api.get_income_verification(iv["id"], lo_headers), 200)
    assert iv_after["status"] == "PENDING"

    app_after = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert app_after["status"] == "DRAFT"


def test_withdraw_application_status_is_terminal_withdrawn(api, lo_headers):
    """PRD §3.9: "A `LoanOfficer` may withdraw an application from `DRAFT`,
    `PREQUALIFIED`, or `UNDER_REVIEW`; the application transitions to the
    terminal `WITHDRAWN` state, any `ACTIVE` rate lock on the application is
    auto-transitioned to `CANCELLED` as a side effect, and the application's
    `version` is incremented by one."

    Companion to the cascade test — focuses on the application-side
    observable: status is exactly `WITHDRAWN` and version advanced.

    Design: Difficulty/transitive_cascade/withdraw_loan_application_cancels_active_ratelock_depth2
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "J2",
            "email": "j2.withdraw@test.com",
            "ssn_last4": "8889",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
        clock_iso="2026-06-01T00:00:00Z",
    )
    before = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    after = validate_success(api.withdraw_loan_application(app["id"], lo_headers), 200)
    assert after["status"] == "WITHDRAWN"
    assert after["version"] > before["version"]


def test_income_verification_accept_succeeds_when_parent_is_prequalified(
    api, lo_headers, underwriter_headers
):
    """PRD §3.3: "An `Underwriter` reviews each verification while the parent
    loan application is in either `PREQUALIFIED` or `UNDER_REVIEW`. Accepting
    a verification transitions it from `PENDING` to `ACCEPTED` and increments
    its `version`."

    Companion to the DRAFT-rejected test — positive path: when the parent is
    PREQUALIFIED, the accept transition succeeds and the verification ends in
    ACCEPTED.

    Design: Difficulty/cross_entity_state_dependency/income_verification_accept_requires_loan_application_non_terminal
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "P-OK",
            "email": "p.ok@test.com",
            "ssn_last4": "9007",
            "annual_income_cents": 7_726_104,
        },
    )
    assert app["status"] == "PREQUALIFIED"

    iv = validate_success(
        api.create_income_verification(
            create_income_verification_payload(app["id"], verified_annual_income_cents=7_800_000),
            lo_headers,
        ),
        201,
    )
    after = validate_success(api.accept_income_verification(iv["id"], underwriter_headers), 200)
    assert after["status"] == "ACCEPTED"


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_title_search_cure_from_clear_returns_invalid_state(api, lo_headers, title_agent_headers):
    """PRD §3.5: "Curing a previously raised exception transitions the title
    search from `EXCEPTIONS_FOUND` to `CURED`."
    PRD §2.8: "then current-state legality (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/title_search_cure_from_clear_returns_invalid_state
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "T2",
            "email": "t2.title@test.com",
            "ssn_last4": "8020",
            "annual_income_cents": 7_726_104,
        },
    )
    ts = get_success_data(
        api.create_title_search(create_title_search_payload(app["id"]), lo_headers)
    )
    validate_success(api.mark_clear_title_search(ts["id"], title_agent_headers), 200)

    res = api.cure_title_search(ts["id"], title_agent_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    final = validate_success(api.get_title_search(ts["id"], lo_headers), 200)
    assert final["status"] == "CLEAR"


def test_immediate_consistency_application_version_visible_after_write(api, lo_headers):
    """PRD §2.4: "Each such resource has an `id`, which is a server-minted UUID
    with no domain-specific prefix; a `created_at` timestamp recorded when the
    resource is first stored; an `updated_at` timestamp refreshed on every
    successful mutation; and a `version` integer that begins at 1 (or at
    whatever the implementation chooses for a freshly created resource) and
    increments by exactly one on every successful mutation of that resource."

    Design: Corner/consistency_model/immediate_consistency_application_version_visible_after_write
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "I",
            "email": "imm.i@test.com",
            "ssn_last4": "1500",
            "annual_income_cents": 7_726_104,
        },
    )
    after_prequal = validate_success(api.prequalify_loan_application(app["id"], lo_headers), 200)
    v_after_prequal = after_prequal["version"]

    read = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert read["version"] == v_after_prequal
    assert read["status"] == "PREQUALIFIED"
