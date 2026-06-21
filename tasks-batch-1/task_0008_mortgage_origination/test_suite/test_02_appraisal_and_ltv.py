"""Appraisal lifecycle, LTV recomputation, and the appraisal-LTV cascade.

The cascade is two hops deep when LTV stays at-or-below 0.95, and three hops
deep when the recomputed LTV breaches the conforming ceiling (Appraisal →
LoanApplication → RateLock).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    complete_appraisal_payload,
    reconsider_appraisal_payload,
    create_appraisal_payload,
    setup_prequalified_loan_application,
    setup_prequalified_with_active_lock,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_appraisal_cyclic_completed_reconsidered_completed_loop(api, lo_headers, appraiser_headers):
    """PRD §3.4: "The Appraiser may then confirm the reconsidered value,
    returning the appraisal from `RECONSIDERED` to `COMPLETED`. This
    `COMPLETED → RECONSIDERED → COMPLETED` loop may repeat any number of
    times while the parent loan application is non-terminal."

    Design: Difficulty/non_linear_state_machine/appraisal_cyclic_completed_reconsidered_completed_loop
    """
    # Use a property_value high enough that all appraised values keep LTV ≤ 0.95
    # (PRD §3.4: LTV > 0.95 triggers auto-DENY cascade and ends the loop early).
    applicant, app = setup_prequalified_loan_application(
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 50_000_000,
        },
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    # appraised 40M → min(50M, 40M)=40M → LTV=30M/40M=0.75 ≤ 0.95
    completed = validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(40_000_000), appraiser_headers
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"

    # First reconsider → COMPLETED → RECONSIDERED
    # appraised 45M → LTV=30M/45M=0.6667 ≤ 0.95
    reconsidered = validate_success(
        api.reconsider_appraisal(
            appr["id"],
            reconsider_appraisal_payload(
                new_appraised_value_cents=45_000_000,
                reconsideration_note="Comparables suggest higher.",
            ),
            lo_headers,
        ),
        200,
    )
    assert reconsidered["status"] == "RECONSIDERED"
    assert reconsidered["appraised_value_cents"] == 45_000_000

    confirmed = validate_success(
        api.confirm_reconsideration_appraisal(appr["id"], appraiser_headers), 200
    )
    assert confirmed["status"] == "COMPLETED"
    assert confirmed["appraised_value_cents"] == 45_000_000
    assert confirmed["reconsideration_note"] == "Comparables suggest higher."


def test_appraisal_complete_cascades_ltv_breach_into_denial_and_lock_cancel(
    api, lo_headers, appraiser_headers
):
    """PRD §3.4: "If that recomputed `ltv_ratio` exceeds 0.95, a second cascade
    hop fires automatically: the loan application is auto-transitioned to
    `DENIED` from whichever non-terminal state it currently inhabits (either
    `PREQUALIFIED` or `UNDER_REVIEW`, symmetrically). The auto-denial is the
    second hop. The third hop follows immediately on the rate lock: if the
    application had an `ACTIVE` rate lock, that lock is transitioned to
    `CANCELLED` as a side effect of the auto-denial."

    Design: Difficulty/transitive_cascade/appraisal_complete_ltv_denial_ratelock_cancel_depth3
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "I",
            "email": "cascade.i@test.com",
            "ssn_last4": "7777",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "property_address": "Cascade Ln",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
            "loan_term_months": 360,
        },
        locked_rate_bps=687,
        lock_term_days=30,
        clock_iso="2026-06-01T00:00:00Z",
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    completed = validate_success(
        api.complete_appraisal(
            appr["id"],
            complete_appraisal_payload(30_000_000),
            appraiser_headers,
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["appraised_value_cents"] == 30_000_000

    app_after = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    assert app_after["ltv_ratio"] == pytest.approx(1.0, abs=1e-4)
    assert app_after["status"] == "DENIED"

    lock_after = validate_success(api.get_rate_lock(lock["id"], lo_headers), 200)
    assert lock_after["status"] == "CANCELLED"


def test_appraisal_reconsider_roundtrip_preserves_ltv(
    api, lo_headers, appraiser_headers
):
    """PRD §3.4: "On every `ORDERED → COMPLETED` and `COMPLETED → RECONSIDERED`
    transition, the system recomputes `ltv_ratio` for the loan application
    using the **lesser** of the applicant-stated `property_value_cents` and the
    appraisal's `appraised_value_cents` in the denominator — the requested loan
    amount divided by that minimum, rounded half-up to four decimal places."

    Design: Difficulty/compensating_invariant/appraisal_reconsider_roundtrip_preserves_ltv_ratio
    """
    # Use a property_value high enough that the chosen appraised values keep
    # LTV ≤ 0.95 throughout the round-trip (PRD §3.4 auto-DENY at LTV > 0.95).
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "T",
            "email": "round.t@test.com",
            "ssn_last4": "9010",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 50_000_000,
            "loan_term_months": 360,
        },
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    # appraised 32M → min(50M, 32M)=32M → LTV=30M/32M=0.9375 ≤ 0.95
    get_success_data(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(32_000_000), appraiser_headers
        )
    )
    # Reconsider up to 40M → LTV = 30M/40M = 0.75
    get_success_data(
        api.reconsider_appraisal(
            appr["id"],
            reconsider_appraisal_payload(
                new_appraised_value_cents=40_000_000,
                reconsideration_note="Comparable A",
            ),
            lo_headers,
        )
    )
    get_success_data(
        api.confirm_reconsideration_appraisal(appr["id"], appraiser_headers)
    )

    # Reconsider back down to 32M → LTV = 30M/32M = 0.9375 again
    get_success_data(
        api.reconsider_appraisal(
            appr["id"],
            reconsider_appraisal_payload(
                new_appraised_value_cents=32_000_000,
                reconsideration_note="Revert to original value",
            ),
            lo_headers,
        )
    )
    final_appr = validate_success(
        api.confirm_reconsideration_appraisal(appr["id"], appraiser_headers),
        200,
    )
    assert final_appr["status"] == "COMPLETED"
    assert final_appr["appraised_value_cents"] == 32_000_000

    app_after = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    # 30M / min(50M, 32M) = 30M / 32M = 0.9375
    assert app_after["ltv_ratio"] == pytest.approx(0.9375, abs=1e-4)


def test_appraisal_cyclic_two_full_revisions(api, lo_headers, appraiser_headers):
    """PRD §3.4: "This `COMPLETED → RECONSIDERED → COMPLETED` loop may repeat
    any number of times while the parent loan application is non-terminal."

    Companion to the single-cycle test in the same Difficulty instance —
    drives two full revision cycles to confirm the loop has no transition-count
    cap.

    Design: Difficulty/non_linear_state_machine/appraisal_cyclic_completed_reconsidered_completed_loop
    """
    # Use a property_value high enough that all chosen appraised values keep
    # LTV ≤ 0.95 throughout the loop (PRD §3.4 auto-DENY at LTV > 0.95).
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "F2",
            "email": "f2.cycle@test.com",
            "ssn_last4": "4445",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 50_000_000,
        },
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    # appraised 40M → LTV = 30M/40M = 0.75
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(40_000_000), appraiser_headers
        ),
        200,
    )
    # Cycle 1: complete → reconsider → confirm (appraised 42M → LTV 0.7143)
    validate_success(
        api.reconsider_appraisal(
            appr["id"],
            reconsider_appraisal_payload(
                new_appraised_value_cents=42_000_000, reconsideration_note="A"
            ),
            lo_headers,
        ),
        200,
    )
    validate_success(api.confirm_reconsideration_appraisal(appr["id"], appraiser_headers), 200)
    # Cycle 2: another reconsider → confirm (appraised 43M → LTV 0.6977)
    validate_success(
        api.reconsider_appraisal(
            appr["id"],
            reconsider_appraisal_payload(
                new_appraised_value_cents=43_000_000, reconsideration_note="B"
            ),
            lo_headers,
        ),
        200,
    )
    final = validate_success(
        api.confirm_reconsideration_appraisal(appr["id"], appraiser_headers), 200
    )
    assert final["status"] == "COMPLETED"
    assert final["appraised_value_cents"] == 43_000_000


def test_appraisal_cascade_increments_loan_application_version_at_least_twice(
    api, lo_headers, appraiser_headers
):
    """PRD §3.4: "The original appraiser action thus mutates three entities —
    the appraisal itself, the loan application, and the active rate lock —
    and increments three `version` counters; if the auto-deny hop fires, the
    loan application receives an additional `version` increment on top of the
    one from the recomputation."

    Companion to the cascade test — focuses on the version-increment side
    effect on the LoanApplication (and on the RateLock terminal-status).

    Design: Difficulty/transitive_cascade/appraisal_complete_ltv_denial_ratelock_cancel_depth3
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "I2",
            "email": "i2.cascade@test.com",
            "ssn_last4": "7778",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
        locked_rate_bps=687,
        lock_term_days=30,
        clock_iso="2026-06-01T00:00:00Z",
    )
    app_before = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    lock_before = validate_success(api.get_rate_lock(lock["id"], lo_headers), 200)

    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(30_000_000), appraiser_headers
        ),
        200,
    )
    app_after = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    lock_after = validate_success(api.get_rate_lock(lock["id"], lo_headers), 200)

    # PRD: LTV recompute bumps app version by 1, and auto-deny hop adds +1 more.
    assert app_after["version"] > app_before["version"] + 1
    # RateLock auto-CANCELLED → its version also bumped.
    assert lock_after["version"] > lock_before["version"]
    assert lock_after["status"] == "CANCELLED"


def test_appraisal_reconsider_first_recompute_changes_ltv(api, lo_headers, appraiser_headers):
    """PRD §3.4: "On every `ORDERED → COMPLETED` and
    `COMPLETED → RECONSIDERED` transition, the system recomputes `ltv_ratio`
    for the loan application using the **lesser** of the applicant-stated
    `property_value_cents` and the appraisal's `appraised_value_cents` in the
    denominator — the requested loan amount divided by that minimum, rounded
    half-up to four decimal places."

    Companion to the roundtrip-preservation test — confirms the LTV value
    actually moves between the boundary value at COMPLETED(31M) and the
    after-reconsider value (32M).

    Design: Difficulty/compensating_invariant/appraisal_reconsider_roundtrip_preserves_ltv_ratio
    """
    # Use property_value=50M so both appraised values fall below property_value,
    # changing the denominator and thus LTV — while keeping LTV ≤ 0.95 (PRD §3.4
    # auto-DENY at LTV > 0.95).
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "T2",
            "email": "t2.roundtrip@test.com",
            "ssn_last4": "9011",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 50_000_000,
        },
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    # appraised 35M → min(50M, 35M)=35M → LTV=30M/35M=0.8571 ≤ 0.95
    validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(35_000_000), appraiser_headers
        ),
        200,
    )
    after_complete = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    ltv_at_35m = after_complete["ltv_ratio"]
    assert ltv_at_35m == pytest.approx(0.8571, abs=1e-4)

    # Reconsider to 40M — min(50M, 40M)=40M → LTV=30M/40M=0.75 (different).
    validate_success(
        api.reconsider_appraisal(
            appr["id"],
            reconsider_appraisal_payload(
                new_appraised_value_cents=40_000_000, reconsideration_note="Higher"
            ),
            lo_headers,
        ),
        200,
    )
    after_reconsider = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    # 30M / 40M = 0.75
    assert after_reconsider["ltv_ratio"] == pytest.approx(0.75, abs=1e-4)
    assert after_reconsider["ltv_ratio"] != ltv_at_35m


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_appraisal_complete_from_completed_returns_invalid_state(
    api, lo_headers, appraiser_headers
):
    """PRD §3.4: "An Appraiser reports completion by supplying a strictly
    positive `appraised_value_cents`, transitioning the appraisal from
    `ORDERED` to `COMPLETED`."
    PRD §2.8: "then current-state legality (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/appraisal_complete_from_completed_returns_invalid_state
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "P2",
            "email": "p2.appr@test.com",
            "ssn_last4": "6020",
            "annual_income_cents": 7_726_104,
        },
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    first = validate_success(
        api.complete_appraisal(
            appr["id"], complete_appraisal_payload(31_000_000), appraiser_headers
        ),
        200,
    )
    assert first["status"] == "COMPLETED"

    second = api.complete_appraisal(
        appr["id"], complete_appraisal_payload(32_000_000), appraiser_headers
    )
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value)

    final = validate_success(api.get_appraisal(appr["id"], lo_headers), 200)
    assert final["status"] == "COMPLETED"
    assert final["appraised_value_cents"] == 31_000_000


def test_appraisal_complete_missing_appraised_value_rejected(api, lo_headers, appraiser_headers):
    """PRD §3.4: "An Appraiser reports completion by supplying a strictly
    positive `appraised_value_cents`, transitioning the appraisal from
    `ORDERED` to `COMPLETED`."
    PRD §2.7: "Body-shape problems unrelated to existence (a missing required
    field, an enum value outside its declared set, an integer outside its
    declared range) are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/appraisal_complete_missing_appraised_value_rejected
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "AC",
            "email": "ac.appr@test.com",
            "ssn_last4": "1180",
            "annual_income_cents": 7_726_104,
        },
    )
    appr = get_success_data(
        api.create_appraisal(create_appraisal_payload(app["id"]), lo_headers)
    )
    # Use raw _request to omit body field; complete_appraisal expects a payload dict.
    res = api.complete_appraisal(appr["id"], {}, appraiser_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    final = validate_success(api.get_appraisal(appr["id"], lo_headers), 200)
    assert final["status"] == "ORDERED"


def test_error_subresource_not_found_on_appraisal(api, appraiser_headers):
    """PRD §2.7: "If a sub-resource segment — referring to an income
    verification, asset verification, appraisal, title search, rate lock,
    disclosure, or UDAAP check — does not exist, the request is rejected with
    `ERR_SUBRESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/error_subresource_not_found_on_appraisal
    """
    res = api.complete_appraisal(
        "00000000-0000-0000-0000-000000000000",
        complete_appraisal_payload(31_000_000),
        appraiser_headers,
    )
    validate_error(res, ApiErrorId.ERR_SUBRESOURCE_NOT_FOUND.value)
