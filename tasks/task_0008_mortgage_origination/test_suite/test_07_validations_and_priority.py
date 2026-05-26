"""Validation rules: priority conflicts, UDAAP gates, SoD violation,
and UDAAPCheck-specific reasons-array validation.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_udaap_check_payload,
    create_income_verification_payload,
    create_asset_verification_payload,
    create_appraisal_payload,
    complete_appraisal_payload,
    create_title_search_payload,
    create_disclosure_payload,
    create_rate_lock_payload,
    create_applicant_payload,
    create_loan_application_payload,
    setup_applicant_and_loan_application_draft,
    setup_prequalified_loan_application,
    setup_prequalified_with_active_lock,
    set_clock,
    make_loan_officer_headers,
    make_underwriter_headers,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_invalid_state_wins_over_udaap_blocked_on_approve(api, lo_headers, underwriter_headers, compliance_headers):
    """PRD §2.8: "then current-state legality (`ERR_INVALID_STATE`), then
    optimistic concurrency on the parent's `version` (`ERR_STALE_VERSION`),
    and only after all of the above succeed does the server evaluate business
    safety, business constraints, business temporal checks, business referential
    checks, and finally request shape (`ERR_INVALID_REQUEST`, which is last so
    that more meaningful business rejections are surfaced before generic shape
    complaints)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_udaap_priority_on_approve
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "K",
            "email": "k.prio@test.com",
            "ssn_last4": "9001",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
    )
    # Record a FLAGGED UDAAP check — would block approval normally.
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(
                app["id"], review_outcome="FLAGGED", flagged_reasons=["HIDDEN_FEES"]
            ),
            compliance_headers,
        )
    )

    # App is still in DRAFT (never prequalified) → state check fires first.
    res = api.approve_loan_application(app["id"], underwriter_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    final = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert final["status"] == "DRAFT"


def test_invalid_state_fires_before_business_tier_on_approve_in_prequalified(
    api, lo_headers, underwriter_headers, compliance_headers
):
    """PRD §2.8: "Authentication is evaluated first (`ERR_UNAUTHENTICATED`),
    then role authorization (`ERR_UNAUTHORIZED`), then existence of the path's
    primary resource (`ERR_APPLICATION_NOT_FOUND`), then the sub-resource path
    id (`ERR_SUBRESOURCE_NOT_FOUND`), then foreign-key existence in the body
    (`ERR_APPLICANT_NOT_FOUND`), then current-state legality
    (`ERR_INVALID_STATE`), then optimistic concurrency on the parent's
    `version` (`ERR_STALE_VERSION`), and only after all of the above succeed
    does the server evaluate business safety, business constraints, business
    temporal checks, business referential checks, and finally request shape
    (`ERR_INVALID_REQUEST`, which is last so that more meaningful business
    rejections are surfaced before generic shape complaints)."

    Companion to the DRAFT-state test — confirms the same precedence holds
    from a different pre-state (PREQUALIFIED, where the approve transition is
    still illegal because UNDER_REVIEW is required).

    Design: Difficulty/priority_pair_validation_conflict/state_vs_udaap_priority_on_approve
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "K2",
            "email": "k2.prio@test.com",
            "ssn_last4": "9002",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
    )
    # Record FLAGGED UDAAP — would have triggered UDAAP_BLOCKED if state was UNDER_REVIEW
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(
                app["id"], review_outcome="FLAGGED", flagged_reasons=["STEERING"]
            ),
            compliance_headers,
        )
    )
    # App is still in PREQUALIFIED — approve requires UNDER_REVIEW per PRD §3.9.
    res = api.approve_loan_application(app["id"], underwriter_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    final = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert final["status"] == "PREQUALIFIED"


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_udaap_check_flagged_without_reasons_rejected(api, compliance_headers):
    """PRD §3.8: "The two halves of this rule are symmetric: `flagged_reasons`
    must be present and non-empty when the outcome is `FLAGGED`, and must be
    omitted or empty when the outcome is `CLEARED`; either deviation is
    rejected with `ERR_UDAAP_REASONS_INVALID`."

    Design: Corner/validations/udaap_check_flagged_without_reasons_rejected
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "U2",
            "email": "u2.udaap@test.com",
            "ssn_last4": "1130",
            "annual_income_cents": 7_726_104,
        },
    )
    res = api.create_udaap_check(
        {"application_id": app["id"], "review_outcome": "FLAGGED"},
        compliance_headers,
    )
    validate_error(res, ApiErrorId.ERR_UDAAP_REASONS_INVALID.value)


def test_udaap_check_cleared_with_reasons_rejected(api, compliance_headers):
    """PRD §3.8: "The two halves of this rule are symmetric: `flagged_reasons`
    must be present and non-empty when the outcome is `FLAGGED`, and must be
    omitted or empty when the outcome is `CLEARED`; either deviation is
    rejected with `ERR_UDAAP_REASONS_INVALID`."

    Design: Corner/validations/udaap_check_cleared_with_reasons_rejected
    """
    applicant, app = setup_applicant_and_loan_application_draft(
        applicant_overrides={
            "full_name": "U3",
            "email": "u3.udaap@test.com",
            "ssn_last4": "1140",
            "annual_income_cents": 7_726_104,
        },
    )
    res = api.create_udaap_check(
        {"application_id": app["id"], "review_outcome": "CLEARED", "flagged_reasons": ["HIDDEN_FEES"]},
        compliance_headers,
    )
    validate_error(res, ApiErrorId.ERR_UDAAP_REASONS_INVALID.value)


def test_udaap_check_flagged_blocks_approve(api, lo_headers, underwriter_headers, compliance_headers):
    """PRD §3.8: "A UDAAP check governs approval via a "last-entry-wins" rule.
    When a `LoanOfficer` submits a loan application for review and an
    `Underwriter` later approves it, the system inspects the most recent
    UDAAPCheck for the application (ordered by `created_at` ascending, last
    entry wins). Approval requires that most-recent UDAAPCheck's
    `review_outcome` to be `CLEARED`; a `FLAGGED` most-recent UDAAPCheck blocks
    approval with `ERR_UDAAP_BLOCKED`."

    Design: Corner/validations/udaap_check_blocks_approve
    """
    set_clock("2026-06-01T00:00:00Z", role_headers=lo_headers)
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "UB",
            "email": "ub.udaap@test.com",
            "ssn_last4": "1150",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "property_address": "X",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=687,
        lock_term_days=60,
    )
    v2 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", v2),
            lo_headers,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_headers), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_headers), 200)

    iv = get_success_data(
        api.create_income_verification(
            create_income_verification_payload(app["id"], verified_annual_income_cents=9_000_000),
            lo_headers,
        )
    )
    validate_success(api.accept_income_verification(iv["id"], underwriter_headers), 200)
    av = get_success_data(
        api.create_asset_verification(create_asset_verification_payload(app["id"]), lo_headers)
    )
    validate_success(api.accept_asset_verification(av["id"], underwriter_headers), 200)
    appr = get_success_data(api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers))
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(35_000_000), TEST_USERS["appraiser_headers"]
        ),
        200,
    )
    ts = get_success_data(api.create_title_search(create_title_search_payload(app["id"]), lo_headers))
    validate_success(api.mark_clear_title_search(ts["id"], TEST_USERS["title_agent_headers"]), 200)
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(
                app["id"], review_outcome="FLAGGED", flagged_reasons=["HIDDEN_FEES"]
            ),
            compliance_headers,
        )
    )
    res = api.approve_loan_application(app["id"], underwriter_headers)
    validate_error(res, ApiErrorId.ERR_UDAAP_BLOCKED.value)

    final = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert final["status"] == "UNDER_REVIEW"


def test_sod_violation_underwriter_same_as_loan_officer(api, compliance_headers):
    """PRD §3.9: "the underwriter approving the application must not be the
    same person who originated it. The system recorded the originating
    `LoanOfficer`'s `X-User-ID` against the application at creation time; an
    approval attempt whose `X-User-ID` matches that recorded value is rejected
    with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/validations/sod_violation_underwriter_same_as_loan_officer
    """
    shared = "lo-shared"
    lo_h = make_loan_officer_headers(shared)
    uw_h_shared = make_underwriter_headers(shared)
    uw_h_other = make_underwriter_headers("uw-other")
    appr_h = TEST_USERS["appraiser_headers"]
    ta_h = TEST_USERS["title_agent_headers"]

    set_clock("2026-06-01T00:00:00Z", role_headers=lo_h)
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="S",
                email="s.sod@test.com",
                ssn_last4="1160",
                annual_income_cents=9_000_000,
            ),
            lo_h,
        ),
        201,
    )
    app = validate_success(
        api.create_loan_application(
            create_loan_application_payload(
                applicant["id"],
                property_address="X",
                requested_loan_amount_cents=30_000_000,
                property_value_cents=35_000_000,
                loan_term_months=360,
            ),
            lo_h,
        ),
        201,
    )
    prequal = validate_success(api.prequalify_loan_application(app["id"], lo_h), 200)
    validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], prequal["version"], locked_rate_bps=687, lock_term_days=60
            ),
            lo_h,
        ),
        201,
    )
    v2 = validate_success(api.get_loan_application(app["id"], lo_h), 200)["version"]
    le = validate_success(
        api.create_disclosure(
            create_disclosure_payload(app["id"], "LOAN_ESTIMATE", v2),
            lo_h,
        ),
        201,
    )
    validate_success(api.deliver_disclosure(le["id"], lo_h), 200)
    validate_success(api.submit_for_review_loan_application(app["id"], lo_h), 200)

    iv = get_success_data(
        api.create_income_verification(
            create_income_verification_payload(app["id"], verified_annual_income_cents=9_000_000),
            lo_h,
        )
    )
    validate_success(api.accept_income_verification(iv["id"], uw_h_other), 200)
    av = get_success_data(
        api.create_asset_verification(create_asset_verification_payload(app["id"]), lo_h)
    )
    validate_success(api.accept_asset_verification(av["id"], uw_h_other), 200)
    appr = get_success_data(api.create_appraisal(create_appraisal_payload(app["id"]), lo_h))
    validate_success(
        api.complete_appraisal(appr["id"], complete_appraisal_payload(35_000_000), appr_h), 200
    )
    ts = get_success_data(api.create_title_search(create_title_search_payload(app["id"]), lo_h))
    validate_success(api.mark_clear_title_search(ts["id"], ta_h), 200)
    get_success_data(
        api.create_udaap_check(
            create_udaap_check_payload(app["id"], review_outcome="CLEARED"),
            compliance_headers,
        )
    )

    res = api.approve_loan_application(app["id"], uw_h_shared)
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION.value)

    final = validate_success(api.get_loan_application(app["id"], lo_h), 200)
    assert final["status"] == "UNDER_REVIEW"
