"""What the insurer will admit onto one insured's Side C capacity, and the two
other things acceptance reads off entities it does not own.

The admission test is per candidate period, not off the stored posture; the
wording gate outranks the capacity gate; and the insured's control posture can
block and then unblock the very same accept call.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    COMPLIANCE,
    UNDERWRITER,
    assert_capacity_derivation,
    conduct_term_of,
    find_part,
    issue_quote,
    make_risk_manager_headers,
    open_submission,
    read_coverage_parts,
    read_insured,
    read_quote,
    register_insured,
    resolve_term_as_insured,
    revise_insured,
    run_scoring,
    setup_insured_with_history,
    setup_offered_quote,
    update_insured_payload,
)


def _negotiated_quote(insured_id, **submission_overrides):
    """A quote in OFFERED on a fresh submission whose CONDUCT term is AGREED, so
    every accept precondition ahead of capacity already holds."""
    submission = run_scoring(
        open_submission(insured_id, **submission_overrides)["id"], "INDICATIVE"
    )
    quote_overrides = {
        key.replace("requested_", "offered_"): value
        for key, value in submission_overrides.items()
        if key in ("requested_limit_usd", "requested_retention_usd",
                   "requested_side_c_sublimit_usd")
    }
    quote = issue_quote(submission["id"], submission["version"], **quote_overrides)
    resolve_term_as_insured(conduct_term_of(quote["id"])["id"], insured_id, "AGREE")
    return quote


def test_a_period_abutting_another_period_end_does_not_consume_its_capacity(api):
    """PRD 3.4: "Sum the `limit_usd` of the qualifying `SIDE_C` parts whose policy
    period overlaps the candidate period running from `requested_period_start` to
    `requested_period_end`, add the quote's `offered_side_c_sublimit_usd`, and
    require the total to be no greater than the insured's
    `entity_capacity_cap_usd`. Overlap is judged on half-open intervals: two
    periods overlap when the first starts strictly before the second ends and the
    second starts strictly before the first ends, which means a period beginning
    exactly at another's `period_end` does not overlap it."

    Design: Difficulty/resource_temporal_overlap/side_c_capacity_over_half_open_overlapping_policy_periods
    """
    insured = setup_insured_with_history(
        insured_overrides={"entity_capacity_cap_usd": 5_000_000}
    )["insured"]
    first = _negotiated_quote(
        insured["id"], requested_program_target_limit_usd=10_000_000,
        requested_period_start="2026-09-01T00:00:00Z",
        requested_period_end="2027-09-01T00:00:00Z",
    )
    straddling = _negotiated_quote(
        insured["id"], requested_program_target_limit_usd=10_000_000,
        requested_period_start="2027-08-31T00:00:00Z",
        requested_period_end="2028-08-31T00:00:00Z",
    )
    abutting = _negotiated_quote(
        insured["id"], requested_program_target_limit_usd=10_000_000,
        requested_period_start="2027-09-01T00:00:00Z",
        requested_period_end="2028-09-01T00:00:00Z",
    )
    insured_headers = make_risk_manager_headers(insured["id"])

    # 0 + 5,000,000 <= 5,000,000: the cap comparison is inclusive.
    validate_success(api.accept_quote(first["id"], insured_headers), 201)
    exhausted = read_insured(insured["id"])
    assert exhausted["aggregate_bound_side_c_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert exhausted["available_side_c_capacity_usd"] == pytest.approx(0, abs=0.01)
    assert exhausted["capacity_posture"] == "EXHAUSTED"
    assert exhausted["open_policy_count"] == 1

    # One day of straddle is an overlap, so the candidate sees the full 5,000,000.
    validate_error(
        api.accept_quote(straddling["id"], insured_headers),
        ApiErrorId.ERR_ENTITY_CAPACITY_EXCEEDED,
        409,
    )

    # 2027-09-01 < 2027-09-01 is false, so the periods do not overlap and this
    # candidate's overlapping aggregate is 0 — even though the posture is EXHAUSTED.
    validate_success(api.accept_quote(abutting["id"], insured_headers), 201)

    assert read_quote(straddling["id"])["status"] == "OFFERED"
    policies, meta = validate_paginated(
        api.list_policies(UNDERWRITER, params={"insured_id": insured["id"]})
    )
    assert meta["total_count"] == 2


def test_the_stored_aggregate_is_not_filtered_by_period(api):
    """PRD 3.4: "The insured's `aggregate_bound_side_c_usd` is the sum of
    `limit_usd` over every `SIDE_C` coverage part that is `ACTIVE` and whose policy
    belongs to this insured with a `coverage_status` of `INCEPTED`, `ACTIVE` or
    `RUNOFF`. `available_side_c_capacity_usd` is `entity_capacity_cap_usd` less
    `aggregate_bound_side_c_usd`, floored at 0." The stored figure names no period,
    so it legitimately exceeds the cap while the per-period admission test keeps
    passing.

    Design: Difficulty/resource_temporal_overlap/side_c_capacity_over_half_open_overlapping_policy_periods
    """
    insured = setup_insured_with_history(
        insured_overrides={"entity_capacity_cap_usd": 5_000_000}
    )["insured"]
    insured_headers = make_risk_manager_headers(insured["id"])

    first = _negotiated_quote(
        insured["id"], requested_program_target_limit_usd=10_000_000,
        requested_period_start="2026-09-01T00:00:00Z",
        requested_period_end="2027-09-01T00:00:00Z",
    )
    abutting = _negotiated_quote(
        insured["id"], requested_program_target_limit_usd=10_000_000,
        requested_period_start="2027-09-01T00:00:00Z",
        requested_period_end="2028-09-01T00:00:00Z",
    )
    later_straddle = _negotiated_quote(
        insured["id"], requested_program_target_limit_usd=10_000_000,
        requested_period_start="2028-06-01T00:00:00Z",
        requested_period_end="2029-06-01T00:00:00Z",
    )

    validate_success(api.accept_quote(first["id"], insured_headers), 201)
    validate_success(api.accept_quote(abutting["id"], insured_headers), 201)

    holding = read_insured(insured["id"])
    assert holding["aggregate_bound_side_c_usd"] == pytest.approx(10_000_000, abs=0.01)
    assert holding["available_side_c_capacity_usd"] == pytest.approx(0, abs=0.01), (
        "5,000,000 less 10,000,000 is floored at 0, never negative"
    )
    assert holding["capacity_posture"] == "EXHAUSTED"
    assert holding["open_policy_count"] == 2
    assert_capacity_derivation(holding)

    # This candidate overlaps the second policy only; the first contributes nothing.
    validate_error(
        api.accept_quote(later_straddle["id"], insured_headers),
        ApiErrorId.ERR_ENTITY_CAPACITY_EXCEEDED,
        409,
    )
    assert read_quote(later_straddle["id"])["status"] == "OFFERED"


def _quote_over_cap_with_conduct(insured_id, resolution, sublimit):
    submission = run_scoring(
        open_submission(insured_id, requested_side_c_sublimit_usd=sublimit)["id"],
        "INDICATIVE",
    )
    quote = issue_quote(
        submission["id"], submission["version"], offered_side_c_sublimit_usd=sublimit
    )
    resolve_term_as_insured(conduct_term_of(quote["id"])["id"], insured_id, resolution)
    return quote


def test_a_rejected_conduct_exclusion_is_reported_ahead_of_the_capacity_breach(api):
    """PRD 2.7: "checks are evaluated in ascending order and the first one violated
    determines the response." PRD 2.7 also states that on a quote acceptance "both
    of those run before quote expiry, control posture and entity capacity". PRD
    3.3: "A rejected `CONDUCT` term is a special trap: because the conduct
    exclusion must be `AGREED` for a bind to proceed, rejecting it still fails the
    bind, with `ERR_MANDATORY_EXCLUSION_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/rejected_conduct_exclusion_and_capacity_exceeded_returns_mandatory_exclusion_error
    """
    insured = setup_insured_with_history(
        insured_overrides={"entity_capacity_cap_usd": 4_000_000}
    )["insured"]
    insured_headers = make_risk_manager_headers(insured["id"])

    both_violated = _quote_over_cap_with_conduct(insured["id"], "REJECT", 5_000_000)
    capacity_only = _quote_over_cap_with_conduct(insured["id"], "AGREE", 5_000_000)
    wording_only = _quote_over_cap_with_conduct(insured["id"], "REJECT", 3_000_000)

    # 0 + 5,000,000 > 4,000,000 holds too, but the safety rule is reported.
    validate_error(
        api.accept_quote(both_violated["id"], insured_headers),
        ApiErrorId.ERR_MANDATORY_EXCLUSION_MISSING,
        422,
    )
    assert read_quote(both_violated["id"])["status"] == "OFFERED"
    untouched = read_insured(insured["id"])
    assert untouched["aggregate_bound_side_c_usd"] == pytest.approx(0, abs=0.01)
    assert untouched["version"] == 1

    # Isolating each rule: the only change is which condition still holds.
    validate_error(
        api.accept_quote(capacity_only["id"], insured_headers),
        ApiErrorId.ERR_ENTITY_CAPACITY_EXCEEDED,
        409,
    )
    validate_error(
        api.accept_quote(wording_only["id"], insured_headers),
        ApiErrorId.ERR_MANDATORY_EXCLUSION_MISSING,
        422,
    )


def test_neither_rule_fires_once_the_conduct_term_is_agreed_and_the_sublimit_fits(api):
    """PRD 3.4: "A term with `exclusion_type` `CONDUCT` and `status` `AGREED` must
    exist on the quote, or the attempt is refused with
    `ERR_MANDATORY_EXCLUSION_MISSING`." A utilisation of 3,000,000 over 4,000,000
    is 0.75, and PRD 3.4 gives `capacity_posture` as "`OPEN` otherwise".

    Design: Difficulty/priority_pair_validation_conflict/rejected_conduct_exclusion_and_capacity_exceeded_returns_mandatory_exclusion_error
    """
    insured = setup_insured_with_history(
        insured_overrides={"entity_capacity_cap_usd": 4_000_000}
    )["insured"]
    quote = _quote_over_cap_with_conduct(insured["id"], "AGREE", 3_000_000)

    policy = validate_success(
        api.accept_quote(quote["id"], make_risk_manager_headers(insured["id"])), 201
    )

    parts = read_coverage_parts(policy["id"])
    assert len(parts) == 3
    assert find_part(parts, "SIDE_C")["limit_usd"] == pytest.approx(3_000_000, abs=0.01)

    bound = read_insured(insured["id"])
    assert bound["aggregate_bound_side_c_usd"] == pytest.approx(3_000_000, abs=0.01)
    assert bound["available_side_c_capacity_usd"] == pytest.approx(1_000_000, abs=0.01)
    assert bound["capacity_posture"] == "OPEN"


def test_an_announced_change_of_control_blocks_the_bind_and_reverting_it_unblocks(api):
    """PRD 3.4: "The insured's `control_status` must be `INDEPENDENT` at the moment
    of binding, because a company already in play is not a company this insurer
    will newly incept cover on; otherwise the attempt is refused with
    `ERR_CONTROL_CHANGE_BLOCKS_BIND`."

    Design: Difficulty/cross_entity_state_dependency/accept_blocked_by_insured_change_of_control
    """
    scenario = setup_offered_quote()
    insured_id = scenario["insured"]["id"]
    quote_id = scenario["quote"]["id"]
    insured_headers = make_risk_manager_headers(insured_id)
    resolve_term_as_insured(scenario["conduct_term"]["id"], insured_id, "AGREE")

    announced = revise_insured(
        insured_id, 1, control_status="CHANGE_OF_CONTROL_ANNOUNCED",
        change_of_control_date="2026-12-01T00:00:00Z",
    )
    assert announced["control_status"] == "CHANGE_OF_CONTROL_ANNOUNCED"
    assert announced["version"] == 2

    # The quote itself is OFFERED, fully negotiated and unexpired.
    validate_error(
        api.accept_quote(quote_id, insured_headers),
        ApiErrorId.ERR_CONTROL_CHANGE_BLOCKS_BIND,
        409,
    )
    assert read_quote(quote_id)["status"] == "OFFERED"
    _, meta = validate_paginated(
        api.list_policies(UNDERWRITER, params={"quote_id": quote_id})
    )
    assert meta["total_count"] == 0
    blocked = read_insured(insured_id)
    assert blocked["version"] == 2, "the refused accept wrote nothing"
    assert blocked["aggregate_bound_side_c_usd"] == pytest.approx(0, abs=0.01)

    reverted = revise_insured(insured_id, 2, control_status="INDEPENDENT")
    assert reverted["control_status"] == "INDEPENDENT"
    assert reverted["version"] == 3

    # The identical request now succeeds with no change to the quote.
    policy = validate_success(api.accept_quote(quote_id, insured_headers), 201)
    assert policy["coverage_status"] == "INCEPTED"
    assert policy["gross_premium_usd"] == pytest.approx(236_468.57, abs=0.01)

    bound = read_insured(insured_id)
    assert bound["version"] == 4
    assert bound["aggregate_bound_side_c_usd"] == pytest.approx(5_000_000, abs=0.01)
    assert bound["available_side_c_capacity_usd"] == pytest.approx(20_000_000, abs=0.01)
    assert bound["capacity_posture"] == "OPEN"
    assert bound["open_policy_count"] == 1


def test_replaying_a_spent_insured_version_after_the_revert_is_stale(api):
    """PRD 2.6: "`PATCH /dno/insureds/{id}` requires `expected_insured_version`,
    carrying the client's last observed `version` of the target `Insured`. An
    insured's version advances on every bind and on every release of Side C
    capacity ... If the submitted value does not equal the insured's current
    `version`, the update is rejected with `ERR_STALE_VERSION` and HTTP 412." Only
    the successful writes advanced the token.

    Design: Difficulty/cross_entity_state_dependency/accept_blocked_by_insured_change_of_control
    """
    insured = register_insured(entity_capacity_cap_usd=25_000_000)
    revise_insured(
        insured["id"], 1, control_status="CHANGE_OF_CONTROL_ANNOUNCED",
        change_of_control_date="2026-12-01T00:00:00Z",
    )
    revise_insured(insured["id"], 2, control_status="INDEPENDENT")

    validate_error(
        api.update_insured(
            insured["id"],
            update_insured_payload(
                2, control_status="ACQUIRED",
                change_of_control_date="2026-12-01T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_STALE_VERSION,
        412,
    )
    assert read_insured(insured["id"])["control_status"] == "INDEPENDENT"
    assert read_insured(insured["id"])["version"] == 3
