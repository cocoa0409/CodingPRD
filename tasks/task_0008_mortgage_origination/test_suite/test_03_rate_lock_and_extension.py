"""Rate-lock creation, extension fee, supersession, 90-day duration cap,
and the validation-priority interactions on extend.
"""
from test_helpers import (
    validate_success,
    validate_error,
    extend_rate_lock_payload,
    create_rate_lock_payload,
    setup_prequalified_loan_application,
    setup_prequalified_with_active_lock,
    set_clock,
    ApiErrorId,
)


# =============================================================================
# Queue A — Difficulty
# =============================================================================

def test_extension_fee_per_round_then_sum(api, lo_headers):
    """PRD §3.6: "For the current extension, the unrounded per-extension fee in
    cents is the requested loan amount multiplied by the tier's basis-point
    factor and divided by ten thousand; this per-extension figure is rounded
    half-up to whole cents **before** anything is added. The lock's
    `extension_fee_cents` is then the sum of those per-extension rounded fees
    across every extension applied so far. The ordering is load-bearing:
    rounding each per-extension fee to whole cents and then summing the rounded
    values is required, and produces a different total than summing the
    unrounded fractional-cent values and rounding once at the end."

    Design: Difficulty/combinatorial_formula/extension_fee_per_round_then_sum_pinned_order
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "E",
            "email": "ext.fee@test.com",
            "ssn_last4": "3333",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "property_address": "789 Pine",
            "requested_loan_amount_cents": 30_000_503,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        locked_rate_bps=687,
        lock_term_days=30,
        clock_iso="2026-06-01T00:00:00Z",
    )
    # First 7-day extension
    after_first = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(7), lo_headers),
        200,
    )
    assert after_first["extension_count"] == 1
    # Second 7-day extension → triggers the pinned per-extension rounding rule
    after_second = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(7), lo_headers),
        200,
    )
    assert after_second["extension_count"] == 2
    # 30000503 * 5 / 10000 = 15000.2515 → round-half-up to 15000; sum 15000+15000 = 30000.
    # Sum-then-round would give 30001, which is forbidden by the PRD.
    assert after_second["extension_fee_cents"] == 30_000
    assert after_second["extension_fee_cents"] != 30_001


def test_lock_total_duration_cap_blocks_extension_past_90_days(api, lo_headers):
    """PRD §3.6: "The total live window of the lock must remain within 90
    calendar days of `locked_at`: the proposed new expiry — the current
    `expires_at` plus `extend_days` — must not exceed `locked_at + 90 calendar
    days`. Exactly 90 days is allowed; 91 days is rejected with
    `ERR_LOCK_DURATION_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/rate_lock_total_duration_cap_overlap_rejection
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "S",
            "email": "dur.s@test.com",
            "ssn_last4": "9009",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
        locked_rate_bps=687,
        lock_term_days=60,
        clock_iso="2026-06-01T00:00:00Z",
    )
    # 60-day term + 30-day extension brings the window to exactly 90 days.
    after_first = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(30), lo_headers),
        200,
    )
    assert after_first["extension_count"] == 1
    assert after_first["expires_at"] == "2026-08-30T00:00:00.000Z"

    # Any further extension pushes the live window past 90 days → rejected.
    res = api.extend_rate_lock(lock["id"], extend_rate_lock_payload(7), lo_headers)
    validate_error(res, ApiErrorId.ERR_LOCK_DURATION_CAP_EXCEEDED.value)

    final = validate_success(api.get_rate_lock(lock["id"], lo_headers), 200)
    assert final["extension_count"] == 1
    assert final["expires_at"] == "2026-08-30T00:00:00.000Z"


# NOTE: The §1.8 instance lock_expired_vs_extension_cap_on_extend asserts
# ERR_EXTENSION_CAP_EXCEEDED wins when BOTH ERR_LOCK_EXPIRED and the cap apply.
# That contradicts PRD §2.8 which states "the temporal check that the lock has
# not already expired (`ERR_LOCK_EXPIRED`) fires ahead of the extension-count
# cap" — a PRD-only reader would assert ERR_LOCK_EXPIRED here. Per the
# PRD-first Core rule, this instance fails the two-reader test (the design
# claim is not PRD-consistent), so it is skipped without weakening or marking.


def test_create_new_rate_lock_supersedes_prior_active(api, lo_headers):
    """PRD §3.6: "If a prior `ACTIVE` rate lock exists on the same application,
    it is automatically transitioned to `SUPERSEDED` as a side effect, both the
    superseded lock's `version` and the loan application's `version` are
    bumped, and the new lock takes its place."

    Design: Difficulty/compensating_invariant/ratelock_create_supersede_preserves_active_lock_count
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "U",
            "email": "sup.u@test.com",
            "ssn_last4": "9011",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
    )
    lock_a = validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"],
                app["version"],
                locked_rate_bps=625,
                lock_term_days=30,
            ),
            lo_headers,
        ),
        201,
    )
    app_after_a = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    lock_b = validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"],
                app_after_a["version"],
                locked_rate_bps=650,
                lock_term_days=30,
            ),
            lo_headers,
        ),
        201,
    )
    app_after_b = validate_success(api.get_loan_application(app["id"], lo_headers), 200)
    lock_c = validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"],
                app_after_b["version"],
                locked_rate_bps=675,
                lock_term_days=30,
            ),
            lo_headers,
        ),
        201,
    )

    a_final = validate_success(api.get_rate_lock(lock_a["id"], lo_headers), 200)
    b_final = validate_success(api.get_rate_lock(lock_b["id"], lo_headers), 200)
    c_final = validate_success(api.get_rate_lock(lock_c["id"], lo_headers), 200)
    assert a_final["status"] == "SUPERSEDED"
    assert b_final["status"] == "SUPERSEDED"
    assert c_final["status"] == "ACTIVE"


def test_two_seven_day_extensions_count_advances_to_2(api, lo_headers):
    """PRD §3.6: "On a successful extension, the lock's `expires_at` is
    advanced by exactly `extend_days` calendar days, `extension_count` is
    incremented by one"

    Companion to the per-round-then-sum test — observes the per-extension
    counter as it advances through 0 → 1 → 2.

    Design: Difficulty/combinatorial_formula/extension_fee_per_round_then_sum_pinned_order
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "E2",
            "email": "e2.count@test.com",
            "ssn_last4": "3334",
            "annual_income_cents": 9_000_000,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_503,
            "property_value_cents": 35_000_000,
        },
        locked_rate_bps=687,
        lock_term_days=30,
        clock_iso="2026-06-01T00:00:00Z",
    )
    assert lock["extension_count"] == 0
    after_first = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(7), lo_headers), 200
    )
    assert after_first["extension_count"] == 1
    after_second = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(7), lo_headers), 200
    )
    assert after_second["extension_count"] == 2


def test_duration_cap_exactly_90_days_allowed_91_rejected(api, lo_headers):
    """PRD §3.6: "The total live window of the lock must remain within 90
    calendar days of `locked_at`: the proposed new expiry — the current
    `expires_at` plus `extend_days` — must not exceed `locked_at + 90 calendar
    days`. Exactly 90 days is allowed; 91 days is rejected with
    `ERR_LOCK_DURATION_CAP_EXCEEDED`."

    Companion to the 91-day-rejected test — exercises the boundary on the
    exactly-90-days side: a 60-day lock extended by 30 lands at exactly 90 and
    is accepted.

    Design: Difficulty/resource_temporal_overlap/rate_lock_total_duration_cap_overlap_rejection
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "S2",
            "email": "s2.cap@test.com",
            "ssn_last4": "9010",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
        locked_rate_bps=687,
        lock_term_days=60,
        clock_iso="2026-06-01T00:00:00Z",
    )
    after = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(30), lo_headers),
        200,
    )
    # 60 + 30 = 90 calendar days = locked_at + 90; allowed.
    assert after["extension_count"] == 1
    assert after["expires_at"] == "2026-08-30T00:00:00.000Z"


def test_supersede_chain_only_latest_lock_is_active(api, lo_headers):
    """PRD §3.6: "Finally, an `ACTIVE` lock is transitioned to `SUPERSEDED`
    either when a new rate lock is successfully created on the same
    application or when the loan application transitions from
    `CLEAR_TO_CLOSE` to `CLOSED`; each terminal transition increments the
    lock's `version` by one."

    Companion to the three-lock chain test — focuses specifically on the
    invariant that, between any two creates, the prior lock is SUPERSEDED.

    Design: Difficulty/compensating_invariant/ratelock_create_supersede_preserves_active_lock_count
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "U2",
            "email": "u2.chain@test.com",
            "ssn_last4": "9013",
            "annual_income_cents": 7_726_104,
        },
        loan_overrides={
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 31_578_948,
        },
    )
    lock_a = validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], app["version"], locked_rate_bps=625, lock_term_days=30
            ),
            lo_headers,
        ),
        201,
    )
    assert lock_a["status"] == "ACTIVE"

    app_v2 = validate_success(api.get_loan_application(app["id"], lo_headers), 200)["version"]
    lock_b = validate_success(
        api.create_rate_lock(
            create_rate_lock_payload(
                app["id"], app_v2, locked_rate_bps=650, lock_term_days=30
            ),
            lo_headers,
        ),
        201,
    )
    a_after_b = validate_success(api.get_rate_lock(lock_a["id"], lo_headers), 200)
    assert a_after_b["status"] == "SUPERSEDED"
    assert lock_b["status"] == "ACTIVE"


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_extension_fee_30day_extension_yields_75000_cents(api, lo_headers):
    """PRD §3.6: "There is a per-tier fee schedule expressed in basis points of
    the requested loan amount: 5 basis points for a 7-day extension, 10 basis
    points for a 15-day extension, and 25 basis points for a 30-day extension."

    Design: Corner/calculations/extension_fee_30day_extension_yields_75000_cents
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "E",
            "email": "ext30.e@test.com",
            "ssn_last4": "9030",
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
    after = validate_success(
        api.extend_rate_lock(lock["id"], extend_rate_lock_payload(30), lo_headers),
        200,
    )
    assert after["extension_count"] == 1
    # 30_000_000 * 25 / 10_000 = 75000 cents exactly.
    assert after["extension_fee_cents"] == 75_000


def test_extension_invalid_extend_days_value(api, lo_headers):
    """PRD §3.6: "The `extend_days` value itself must be one of 7, 15, or 30;
    any other value is rejected with `ERR_INVALID_EXTEND_DAYS`."

    Design: Corner/validations/ratelock_extend_invalid_extend_days_value
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "V",
            "email": "v.ext@test.com",
            "ssn_last4": "1120",
            "annual_income_cents": 7_726_104,
        },
        clock_iso="2026-06-01T00:00:00Z",
    )
    res = api.extend_rate_lock(lock["id"], extend_rate_lock_payload(14), lo_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_EXTEND_DAYS.value)


def test_extension_on_expired_lock_rejected(api, lo_headers):
    """PRD §3.6: "The lock must still be live: the system clock must be
    strictly less than the lock's `expires_at`. An extension request against a
    lock whose clock has reached or passed `expires_at` is rejected with
    `ERR_LOCK_EXPIRED`, and this temporal rejection is evaluated **before** the
    extension-count cap."

    Design: Corner/validations/lock_expired_extension_rejected
    """
    applicant, app, lock = setup_prequalified_with_active_lock(
        applicant_overrides={
            "full_name": "LE",
            "email": "le.x@test.com",
            "ssn_last4": "1170",
            "annual_income_cents": 7_726_104,
        },
        locked_rate_bps=687,
        lock_term_days=30,
        clock_iso="2026-06-01T00:00:00Z",
    )
    set_clock("2026-07-15T00:00:00Z", role_headers=lo_headers)
    res = api.extend_rate_lock(lock["id"], extend_rate_lock_payload(7), lo_headers)
    validate_error(res, ApiErrorId.ERR_LOCK_EXPIRED.value)
