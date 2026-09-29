"""
The compound filing gate on the way into pre-opening.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import COUNSEL_HEADERS, fixtures as fx
from test_helpers.assertions import assert_fields_equal, assert_version_unchanged
from test_helpers.factories import advance_payload
from test_helpers.types import (
    AUTHORITY_DEPOSIT_INSURER,
    BLOCKED_REASON_NONE,
    CATEGORY_INSURANCE,
    CONDITION_OPEN,
    DISPOSITION_REOPENED,
    FILING_ADDITIONAL_INFO_REQUESTED,
    FILING_CONDITIONALLY_APPROVED,
    POLICY_EXAMINER_ACCEPTED,
    RAISE_ESCROW_LOCKED,
    STAGE_CONDITIONALLY_APPROVED,
    STAGE_PRE_OPENING,
    VENDOR_SIGNED,
)


def _every_gate_but_the_filings(api):
    """
    A group with escrow locked, all four policy domains examiner-accepted and the critical
    core-processing vendor signed, whose deposit-insurer application has been knocked off
    conditional approval by reopening a settled pre-opening blocker.
    """
    world = fx.conditionally_approved_group(api)
    fx.all_four_policies_accepted(api, world)
    fx.signed_core_vendor(api, world)
    world["c_di"] = fx.add_condition(
        api,
        world["f_di"],
        "INS-01",
        CATEGORY_INSURANCE,
        True,
        authority=AUTHORITY_DEPOSIT_INSURER,
    )
    fx.satisfy_condition(
        api,
        world["c_di"],
        "DEP-INS-APP-EXHIBIT-4-REVISION-2",
        authority=AUTHORITY_DEPOSIT_INSURER,
    )
    return world


def _fully_gated_group(api):
    """The same project with both applications left standing in conditional approval."""
    world = fx.conditionally_approved_group(api)
    fx.all_four_policies_accepted(api, world)
    fx.signed_core_vendor(api, world)
    return world


# ---------------------------------------------------------------------------
# Difficulty / cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_reopening_a_settled_blocker_takes_the_insurer_filing_off_approval(api):
    """
    Accepting the evidence had cleared the insurer's blocker and emptied its blocking set.
    Reopening it puts the blocker back and, because the count rose from nothing while the
    application stood conditionally approved, drags the application itself onto its first
    information round. The chartering application is a different file and is untouched.

    PRD: "`REOPENED` is legal only from `SATISFIED` and is the compensating half of the rework loop: it returns the condition's `status` to `OPEN`, so it must restore `open_blocking_condition_count` to exactly the value it held before the condition was satisfied."

    Design: Difficulty/cross_entity_state_dependency/pre_opening_advance_requires_both_filings_conditionally_approved
    """
    world = _every_gate_but_the_filings(api)
    assert_fields_equal(
        fx.read_filing(api, world["f_di"]),
        status=FILING_CONDITIONALLY_APPROVED,
        open_blocking_condition_count=0,
        pre_opening_clearance=True,
    )

    fx.adjudicate(
        api, world["c_di"], DISPOSITION_REOPENED, authority=AUTHORITY_DEPOSIT_INSURER
    )

    assert_fields_equal(fx.read_condition(api, world["c_di"]), status=CONDITION_OPEN)
    assert_fields_equal(
        fx.read_filing(api, world["f_di"]),
        status=FILING_ADDITIONAL_INFO_REQUESTED,
        info_request_round=1,
        open_blocking_condition_count=1,
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        status=FILING_CONDITIONALLY_APPROVED,
        info_request_round=0,
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]), stage=STAGE_CONDITIONALLY_APPROVED
    )


def test_pre_opening_is_refused_while_one_of_the_two_filings_is_off_approval(api):
    """
    Pre-opening is a statement about both regulators at once, so one application sitting on
    an information round is enough to hold the group where it is — even with escrow locked,
    every policy domain accepted and the core vendor signed, which is to say with every
    other gate on this transition already satisfied.

    PRD: "Both of the group's filings must be in `CONDITIONALLY_APPROVED` (`ERR_FILINGS_NOT_CONDITIONALLY_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/pre_opening_advance_requires_both_filings_conditionally_approved
    """
    world = _every_gate_but_the_filings(api)
    fx.adjudicate(
        api, world["c_di"], DISPOSITION_REOPENED, authority=AUTHORITY_DEPOSIT_INSURER
    )

    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]), status=RAISE_ESCROW_LOCKED
    )
    for key in ("pol_len", "pol_bsa", "pol_sec", "pol_risk"):
        assert_fields_equal(
            fx.read_policy(api, world[key]), status=POLICY_EXAMINER_ACCEPTED
        )
    assert_fields_equal(fx.read_contract(api, world["vc_id"]), status=VENDOR_SIGNED)

    before = fx.read_group(api, world["group_id"])
    validate_error(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_PRE_OPENING), COUNSEL_HEADERS
        ),
        "ERR_FILINGS_NOT_CONDITIONALLY_APPROVED",
        expected_status=409,
    )
    after = fx.read_group(api, world["group_id"])
    assert_fields_equal(after, stage=STAGE_CONDITIONALLY_APPROVED)
    assert_version_unchanged(before, after)


def test_with_both_filings_on_approval_the_advance_reaches_pre_opening(api):
    """
    With both applications standing in conditional approval and the same three downstream
    gates met, the advance the reopened blocker had blocked goes through and the group's
    record of what is holding opening back is cleared.

    PRD: "On success `opening_blocked_reason` is reset to `NONE`."

    Design: Difficulty/cross_entity_state_dependency/pre_opening_advance_requires_both_filings_conditionally_approved
    """
    world = _fully_gated_group(api)
    for filing_key in ("f_ca", "f_di"):
        assert_fields_equal(
            fx.read_filing(api, world[filing_key]),
            status=FILING_CONDITIONALLY_APPROVED,
            pre_opening_clearance=True,
        )

    advanced = get_success_data(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_PRE_OPENING), COUNSEL_HEADERS
        )
    )
    assert_fields_equal(
        advanced, stage=STAGE_PRE_OPENING, opening_blocked_reason=BLOCKED_REASON_NONE
    )
