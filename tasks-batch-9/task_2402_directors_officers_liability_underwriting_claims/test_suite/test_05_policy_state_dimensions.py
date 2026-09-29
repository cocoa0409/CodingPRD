"""A policy's two independent state dimensions, and the ledgers a cancellation
has to put back.

`coverage_status` and `premium_status` advance on their own axes, and a single
epoch advance may move both in one pass.
"""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    COMPLIANCE,
    advance_epoch,
    assert_capacity_derivation,
    assert_ops_run_counters,
    cancel_policy_payload,
    conduct_term_of,
    issue_quote,
    make_risk_manager_headers,
    open_submission,
    premium_payment_payload,
    read_coverage_parts,
    read_insured,
    read_policy,
    resolve_term_as_insured,
    run_scoring,
    set_clock,
    setup_bound_policy,
)

RESTRICTED_CAP = 6_250_000


def test_one_epoch_advance_moves_both_dimensions_of_the_same_policy(api):
    """PRD 2.10: "Neither dimension constrains the other's transition ... and a
    single epoch advance may move both dimensions of the same policy in one pass —
    for instance `coverage_status` from `INCEPTED` to `ACTIVE` while
    `premium_status` moves from `INVOICED` to `DELINQUENT`." PRD 2.9: "every record
    touched has its `updated_at` refreshed and its `version` incremented by exactly
    1".

    Design: Difficulty/non_linear_state_machine/policy_parallel_dimensions_activate_and_delinquent
    """
    scenario = setup_bound_policy()
    policy_id = scenario["policy"]["id"]

    before = read_policy(policy_id)
    assert before["coverage_status"] == "INCEPTED"
    assert before["premium_status"] == "INVOICED"
    assert before["tower_posture"] == "INCOMPLETE"
    assert before["version"] == 1

    set_clock("2026-09-01T00:00:00Z")
    sweep = validate_success(api.advance_epoch(COMPLIANCE), 200)

    assert_ops_run_counters(
        sweep,
        activated_policy_count=1,
        delinquent_policy_count=1,
        expired_policy_count=0,
        # The quote is ACCEPTED, hence terminal, so quote_valid_until cannot lapse it.
        lapsed_quote_count=0,
    )

    after = read_policy(policy_id)
    assert after["coverage_status"] == "ACTIVE"
    assert after["premium_status"] == "DELINQUENT"
    assert after["version"] > before["version"], (
        "the sweep wrote to the row, so its version advanced"
    )


def test_paying_late_cures_the_billing_dimension_and_expiry_moves_only_coverage(api):
    """PRD 3.6: "Payment is accepted while `premium_status` is `INVOICED` or
    `DELINQUENT`, so a late payer can still cure ... A successful payment sets
    `premium_status` to `PAID`, leaves `coverage_status` untouched, and increments
    the policy's `version` by 1." PRD 2.11: "policies whose `period_end` the clock
    has reached move from `INCEPTED` or `ACTIVE` to `EXPIRED`", and every policy the
    sweep expires "also triggers the release and capacity cascades of section 2.9".

    Design: Difficulty/non_linear_state_machine/policy_parallel_dimensions_activate_and_delinquent
    """
    scenario = setup_bound_policy()
    policy_id = scenario["policy"]["id"]
    insured_id = scenario["insured"]["id"]

    set_clock("2026-09-01T00:00:00Z")
    advance_epoch()
    swept = read_policy(policy_id)

    paid = validate_success(
        api.create_premium_payment(
            policy_id,
            premium_payment_payload(scenario["policy"]["gross_premium_usd"]),
            make_risk_manager_headers(insured_id),
        ),
        200,
    )
    assert paid["premium_status"] == "PAID"
    assert paid["coverage_status"] == "ACTIVE", "the coverage dimension does not move"
    assert paid["version"] == swept["version"] + 1, "the payment increments by exactly 1"

    # A repeated sweep at the same clock reading is a no-op on both dimensions.
    repeat = validate_success(api.advance_epoch(COMPLIANCE), 200)
    assert_ops_run_counters(
        repeat, activated_policy_count=0, delinquent_policy_count=0,
        expired_policy_count=0,
    )
    assert read_policy(policy_id)["version"] == paid["version"], (
        "a sweep that moved nothing wrote nothing"
    )

    set_clock("2027-09-01T00:00:00Z")
    expiry = validate_success(api.advance_epoch(COMPLIANCE), 200)
    assert_ops_run_counters(expiry, expired_policy_count=1)

    expired = read_policy(policy_id)
    assert expired["coverage_status"] == "EXPIRED"
    assert expired["premium_status"] == "PAID", "untouched by the coverage dimension"
    assert expired["tower_posture"] == "RELEASED"
    assert expired["version"] == paid["version"] + 1, (
        "the expiring sweep touched the row once"
    )

    parts = read_coverage_parts(policy_id)
    assert [p["status"] for p in parts] == ["RELEASED"] * 3

    insured = read_insured(insured_id)
    assert insured["aggregate_bound_side_c_usd"] == pytest.approx(0, abs=0.01)
    assert insured["available_side_c_capacity_usd"] == pytest.approx(
        25_000_000, abs=0.01
    )
    assert insured["capacity_posture"] == "OPEN"
    assert insured["open_policy_count"] == 0


def _live_policy_on_a_restricted_cap():
    """A live policy whose 5,000,000 Side C part takes a 6,250,000 cap to exactly
    0.80 utilisation, made ACTIVE (and incidentally DELINQUENT) by one sweep."""
    scenario = setup_bound_policy(
        insured_overrides={"entity_capacity_cap_usd": RESTRICTED_CAP}
    )
    set_clock("2026-10-01T00:00:00Z")
    advance_epoch()
    scenario["policy"] = read_policy(scenario["policy"]["id"])
    return scenario


def test_cancellation_credits_the_unearned_premium_and_releases_the_parts(api):
    """PRD 3.6: "On cancellation the unearned premium is credited to
    `return_premium_usd`: count the whole days from the `effective_date` to the
    policy's `period_end`, discarding any part-day, clamp that count to no less
    than 0 and no more than 365 ... then multiply the policy's
    `gross_premium_usd` by that day count divided by 365 and round half-up to 2
    decimal places." Cancellation "then runs the release cascade of section 2.9 —
    active coverage parts to `RELEASED`, attached layers to `RELEASED` — and
    recomputes the insured's `aggregate_bound_side_c_usd`,
    `available_side_c_capacity_usd`, `capacity_posture` and `open_policy_count`".

    Design: Difficulty/compensating_invariant/cancel_releases_side_c_capacity
    """
    scenario = _live_policy_on_a_restricted_cap()
    policy_id = scenario["policy"]["id"]
    insured_id = scenario["insured"]["id"]

    live = read_insured(insured_id)
    assert live["aggregate_bound_side_c_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert live["available_side_c_capacity_usd"] == pytest.approx(1_250_000, abs=0.01)
    assert live["capacity_posture"] == "RESTRICTED"
    assert live["open_policy_count"] == 1

    cancelled = validate_success(
        api.cancel_policy(
            policy_id,
            cancel_policy_payload("2026-10-01T00:00:00Z", "INSURED_REQUEST"),
            COMPLIANCE,
        ),
        200,
    )

    assert cancelled["coverage_status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "INSURED_REQUEST"
    # 335 whole days remain from 2026-10-01 to period_end 2027-09-01, below the
    # 365-day clamp: round(236468.57 x 335 / 365, 2).
    assert cancelled["return_premium_usd"] == pytest.approx(217_032.80, abs=0.01)
    assert cancelled["premium_status"] == "DELINQUENT", (
        "cancellation acts on the coverage dimension only"
    )

    assert [p["status"] for p in read_coverage_parts(policy_id)] == ["RELEASED"] * 3

    released = read_insured(insured_id)
    assert released["aggregate_bound_side_c_usd"] == pytest.approx(0, abs=0.01)
    assert released["available_side_c_capacity_usd"] == pytest.approx(
        RESTRICTED_CAP, abs=0.01
    )
    assert released["capacity_posture"] == "OPEN"
    assert released["open_policy_count"] == 0
    assert_capacity_derivation(released)


def test_capacity_freed_by_a_cancellation_can_be_bound_again(api):
    """PRD 3.4: the aggregate reads "every `SIDE_C` coverage part that is `ACTIVE`
    and whose policy belongs to this insured with a `coverage_status` of
    `INCEPTED`, `ACTIVE` or `RUNOFF`", so a cancelled policy is outside the input
    set and its Side C limit is genuinely re-usable even by an overlapping period.

    Design: Difficulty/compensating_invariant/cancel_releases_side_c_capacity
    """
    scenario = _live_policy_on_a_restricted_cap()
    cancelled_policy_id = scenario["policy"]["id"]
    insured_id = scenario["insured"]["id"]

    validate_success(
        api.cancel_policy(
            cancelled_policy_id,
            cancel_policy_payload("2026-10-01T00:00:00Z", "INSURED_REQUEST"),
            COMPLIANCE,
        ),
        200,
    )

    # A fresh period that overlaps the cancelled one.
    submission = open_submission(
        insured_id,
        requested_period_start="2026-10-15T00:00:00Z",
        requested_period_end="2027-10-15T00:00:00Z",
    )
    submission = run_scoring(submission["id"], "INDICATIVE")
    quote = issue_quote(
        submission["id"], submission["version"],
        quote_valid_until="2026-10-31T00:00:00Z",
    )
    resolve_term_as_insured(conduct_term_of(quote["id"])["id"], insured_id, "AGREE")

    rebound = validate_success(
        api.accept_quote(quote["id"], make_risk_manager_headers(insured_id)), 201
    )
    assert rebound["coverage_status"] == "INCEPTED"

    insured = read_insured(insured_id)
    assert insured["aggregate_bound_side_c_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert insured["available_side_c_capacity_usd"] == pytest.approx(1_250_000, abs=0.01)
    assert insured["capacity_posture"] == "RESTRICTED"
    assert insured["open_policy_count"] == 1

    # The reversal is not undone by the later bind.
    still_cancelled = read_policy(cancelled_policy_id)
    assert still_cancelled["coverage_status"] == "CANCELLED"
    assert still_cancelled["return_premium_usd"] == pytest.approx(217_032.80, abs=0.01)
    assert [p["status"] for p in read_coverage_parts(cancelled_policy_id)] == (
        ["RELEASED"] * 3
    )
