"""Validation precedence when two rules reject the same compensation request.

The PRD resolves competing rejections through one global ladder: a state gate
outranks a pay-mix bounds check on mix reallocation, the pre-meeting quiet
period outranks the same-investor window overlap on engagement scheduling, and
the peer-group approval gate outranks the benchmark cap on program approval. In
each pair both rules are genuinely violated, so the tests here pin which one the
API is required to report and then prove the loser was live all along.
"""

import pytest

from test_helpers import (
    CHAIR,
    CONSULTANT,
    IR_LEAD,
    ApiErrorId,
    api_client,
    approve_peer_group,
    assert_money,
    assert_ratio,
    create_engagement,
    mix_reallocation_payload,
    program_version,
    read_engagement,
    read_pay_program,
    read_peer_group,
    schedule_engagement,
    schedule_engagement_payload,
    setup_pay_program,
    validate_error,
    validate_success,
)


# ===========================================================================
# Program immutability (ladder step 11) versus mix component bounds (step 39)
# ===========================================================================
def test_committee_approved_program_reports_immutability_not_mix_bounds():
    """A reallocation that is both untimely and out of bounds reports the state gate.

    The program is COMMITTEE_APPROVED, so the reallocation is barred outright;
    the same request would also drive salary_pct from 15.00 down to 3.00. The PRD
    orders the two rejections: "Lower numbers are evaluated first and the first
    failure is the response; a rule further down the ladder never masks a rule
    above it." Reallocation sits at step 11 and the bounds check at step 39, and
    "Reallocation is only available while `design_status` is `DRAFT`; anything
    else is `ERR_PROGRAM_NOT_MUTABLE`."

    Design: Difficulty/priority_pair_validation_conflict/program_immutability_outranks_mix_component_bounds
    """
    env = setup_pay_program()
    program_id = env["program"]["id"]
    approved_version = program_version(program_id)

    response = api_client.reallocate_pay_mix(
        program_id,
        mix_reallocation_payload("SALARY", "LTI", 12.00, approved_version),
        CONSULTANT,
    )

    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_MUTABLE, 409)

    # Nothing moved: the mix, the target and the row version are all intact.
    after = read_pay_program(program_id)
    assert after["design_status"] == "COMMITTEE_APPROVED"
    assert_money(after["salary_pct"], 15.00, "salary_pct")
    assert_money(after["sti_pct"], 25.00, "sti_pct")
    assert_money(after["lti_pct"], 60.00, "lti_pct")
    assert_money(after["target_tdc_usd"], 15000000.00, "target_tdc_usd")
    assert after["version"] == approved_version


def test_draft_program_reports_mix_bounds_for_the_same_reallocation():
    """On a DRAFT program the same twelve points breach the component floor.

    With the state gate satisfied the lower rule is what remains, and the PRD
    states it: "If either resulting component falls below 5.00 or rises above
    80.00 the reallocation is rejected with `ERR_MIX_COMPONENT_OUT_OF_BOUNDS`,
    and if the three resulting components do not sum to exactly 100.00 it is
    rejected with `ERR_PAY_MIX_MUST_TOTAL_100`."

    Design: Difficulty/priority_pair_validation_conflict/program_immutability_outranks_mix_component_bounds
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]
    draft_version = program_version(program_id)
    assert read_pay_program(program_id)["design_status"] == "DRAFT"

    response = api_client.reallocate_pay_mix(
        program_id,
        mix_reallocation_payload("SALARY", "LTI", 12.00, draft_version),
        CONSULTANT,
    )

    validate_error(response, ApiErrorId.ERR_MIX_COMPONENT_OUT_OF_BOUNDS, 422)

    after = read_pay_program(program_id)
    assert_money(after["salary_pct"], 15.00, "salary_pct")
    assert_money(after["lti_pct"], 60.00, "lti_pct")
    assert after["version"] == draft_version


# ===========================================================================
# Quiet period (ladder step 21) versus same-investor overlap (step 35)
# ===========================================================================
def _program_with_scheduled_blackrock_slot():
    """Program whose meeting is 2027-05-12, plus a held-free BLACKROCK slot.

    The scheduled slot runs [2027-04-28, 2027-04-30), wholly clear of the closed
    quiet period that opens on 2027-05-02.
    """
    env = setup_pay_program(approve=False)
    first = create_engagement(env["program"]["id"], "BlackRock", 20.00, "CALL")
    schedule_engagement(first["id"], "2027-04-28T00:00:00Z", "2027-04-30T00:00:00Z")
    second = create_engagement(env["program"]["id"], "BlackRock", 20.00, "MEETING")
    env["engagements"] = [first, second]
    return env


def test_slot_breaching_blackout_and_colliding_reports_the_quiet_period():
    """A slot that both intrudes on the blackout and collides reports the blackout.

    The candidate window [2027-04-29, 2027-05-03) reaches into the closed
    blackout that opens ten days before the 2027-05-12 meeting, and it also
    overlaps the same investor's booked [2027-04-28, 2027-04-30) slot. The PRD
    fixes the winner: "The quiet-period blackout at step 21 is evaluated before
    the same-investor overlap at step 35, so an engagement that both intrudes on
    the blackout and collides with an existing slot reports the blackout."

    Design: Difficulty/priority_pair_validation_conflict/quiet_period_safety_outranks_same_investor_window_overlap
    """
    env = _program_with_scheduled_blackrock_slot()
    program_id = env["program"]["id"]
    first, second = env["engagements"]

    response = api_client.schedule_outreach_engagement(
        second["id"],
        schedule_engagement_payload("2027-04-29T00:00:00Z", "2027-05-03T00:00:00Z"),
        IR_LEAD,
    )

    validate_error(response, ApiErrorId.ERR_QUIET_PERIOD_ENGAGEMENT, 409)

    # The rejected candidate never left REQUESTED and never took a window.
    rejected = read_engagement(program_id, second["id"])
    assert rejected["engagement_status"] == "REQUESTED"
    assert rejected.get("window_start") is None
    assert rejected.get("window_end") is None

    # The rival booking is untouched and no coverage has accrued.
    rival = read_engagement(program_id, first["id"])
    assert rival["engagement_status"] == "SCHEDULED"
    assert_money(read_pay_program(program_id)["outreach_coverage_pct"], 0.00, "outreach_coverage_pct")


def test_slot_colliding_outside_the_blackout_reports_the_window_overlap():
    """Clear of the blackout, the same-investor collision is what rejects the slot.

    The candidate [2027-04-29, 2027-04-30) ends long before the blackout opens,
    so only the second interval rule can bite: "Second the **same-investor
    overlap**: gather the program's other engagements sharing the candidate's
    `investor_key` whose status is `SCHEDULED` or `HELD` — `REQUESTED` rivals are
    ignored entirely — and refuse the candidate with
    `ERR_OUTREACH_WINDOW_OVERLAP` if the candidate's start falls strictly before
    a rival's end while that rival's start falls strictly before the candidate's
    end."

    Design: Difficulty/priority_pair_validation_conflict/quiet_period_safety_outranks_same_investor_window_overlap
    """
    env = _program_with_scheduled_blackrock_slot()
    program_id = env["program"]["id"]
    second = env["engagements"][1]

    response = api_client.schedule_outreach_engagement(
        second["id"],
        schedule_engagement_payload("2027-04-29T00:00:00Z", "2027-04-30T00:00:00Z"),
        IR_LEAD,
    )

    validate_error(response, ApiErrorId.ERR_OUTREACH_WINDOW_OVERLAP, 409)
    assert read_engagement(program_id, second["id"])["engagement_status"] == "REQUESTED"


def test_slot_abutting_the_rival_window_schedules_because_adjacency_is_permitted():
    """A slot starting the instant the rival ends is neither a collision nor a blackout.

    Half-open windows make the boundary case a success rather than a rejection:
    "Because both intervals are half-open, exact adjacency is permitted: a slot
    beginning at the very instant a prior slot ends does not overlap it."

    Design: Difficulty/priority_pair_validation_conflict/quiet_period_safety_outranks_same_investor_window_overlap
    """
    env = _program_with_scheduled_blackrock_slot()
    program_id = env["program"]["id"]
    second = env["engagements"][1]

    response = api_client.schedule_outreach_engagement(
        second["id"],
        schedule_engagement_payload("2027-04-30T00:00:00Z", "2027-05-01T00:00:00Z"),
        IR_LEAD,
    )

    data = validate_success(response, 200)
    assert data["engagement_status"] == "SCHEDULED"
    assert read_engagement(program_id, second["id"])["engagement_status"] == "SCHEDULED"


# ===========================================================================
# Peer-group approval gate (step 25) versus the benchmark cap (step 46)
# ===========================================================================
def _program_over_cap_on_a_screened_group():
    """ACME plus ECHO screened but unapproved, sizing an 18,000,000.00 target.

    ECHO's disclosed compensation of 9,000,000.00 is the group's benchmark, so
    the approval cap is 13,500,000.00 while Morgan Vale's fixed leg of
    6,000,000.00 drives target_tdc_usd to 18,000,000.00.
    """
    return setup_pay_program(
        approve=False,
        peer_tickers=("ECHO",),
        peer_group_status="SCREENED",
        executive_profiles=("CEO_LARGE",),
        executive_label="CEO_LARGE",
    )


def test_unapproved_peer_group_reports_referential_gate_not_the_benchmark_cap():
    """An unapproved group is reported even though the target also breaches the cap.

    Target compensation of 18,000,000.00 stands far above the 13,500,000.00 cap,
    yet the group is only SCREENED, and the PRD orders the two failures: "The
    referenced peer group must be `APPROVED`, or the answer is
    `ERR_PEER_GROUP_NOT_APPROVED` — and per §2.10 this referential gate is
    evaluated before the fiscal cap, so an unapproved group is reported even when
    the cap would also fail."

    Design: Difficulty/priority_pair_validation_conflict/peer_group_referential_gate_outranks_benchmark_cap_at_program_approval
    """
    env = _program_over_cap_on_a_screened_group()
    program_id = env["program"]["id"]
    peer_group_id = env["peer_group"]["id"]

    # The cap breach is real before the trigger: 18,000,000.00 against 13,500,000.00.
    before = read_pay_program(program_id)
    assert_ratio(before["benchmark_ratio"], 1.6667, "benchmark_ratio")
    assert before["lti_multiple"] == pytest.approx(2.0, abs=0.01)
    assert_money(before["lti_target_usd"], 12000000.00, "lti_target_usd")
    assert_money(before["target_tdc_usd"], 18000000.00, "target_tdc_usd")
    assert_money(
        read_peer_group(peer_group_id)["benchmark_target_tdc_usd"],
        9000000.00,
        "benchmark_target_tdc_usd",
    )

    response = api_client.approve_pay_program(program_id, CHAIR)

    validate_error(response, ApiErrorId.ERR_PEER_GROUP_NOT_APPROVED, 409)

    after = read_pay_program(program_id)
    assert after["design_status"] == "DRAFT"
    assert_money(after["target_tdc_usd"], 18000000.00, "target_tdc_usd")
    assert read_peer_group(peer_group_id)["status"] == "SCREENED"


def test_benchmark_cap_rejects_the_same_approval_once_the_group_is_approved():
    """With the referential gate satisfied the fiscal cap is what refuses approval.

    Approving the peer group removes the higher-priority failure and leaves the
    cap: "And `target_tdc_usd` may not exceed one and a half times the group's
    `benchmark_target_tdc_usd`, that product being rounded to two decimal places
    before the comparison — exceeding it is `ERR_TDC_EXCEEDS_BENCHMARK_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/peer_group_referential_gate_outranks_benchmark_cap_at_program_approval
    """
    env = _program_over_cap_on_a_screened_group()
    program_id = env["program"]["id"]

    approved_group = approve_peer_group(env["peer_group"]["id"])
    assert approved_group["status"] == "APPROVED"

    response = api_client.approve_pay_program(program_id, CHAIR)

    validate_error(response, ApiErrorId.ERR_TDC_EXCEEDS_BENCHMARK_CAP, 422)
    assert read_pay_program(program_id)["design_status"] == "DRAFT"
