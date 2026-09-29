"""
The deepest cascade in the service: rejecting a policy that had already been accepted.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import CHARTERING_EXAMINER_HEADERS, COUNSEL_HEADERS, fixtures as fx
from test_helpers.assertions import assert_condition_counts_conserved, assert_fields_equal
from test_helpers.factories import advance_payload, policy_review_payload
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    BLOCKED_REASON_FILING_INFO_REQUESTED,
    CATEGORY_POLICY,
    CONDITION_FAILED,
    EXAM_CANCELLED,
    FILING_ADDITIONAL_INFO_REQUESTED,
    FILING_CONDITIONALLY_APPROVED,
    POLICY_EXAMINER_ACCEPTED,
    POLICY_REJECTED,
    RAISE_ESCROW_LOCKED,
    REVIEW_REJECTED,
    STAGE_CONDITIONALLY_APPROVED,
    STAGE_PRE_OPENING,
)

_FINDING_NOTE = "Concentration limits absent from the credit policy."


def _pre_opening_with_a_satisfied_policy_condition(api):
    """
    The project standing in pre-opening with a single blocking policy condition already
    satisfied, all four policy domains accepted, and a full-scope examination on the books.
    """
    world = fx.conditionally_approved_group(api)
    world["c_pol"] = fx.add_condition(
        api, world["f_ca"], "POL-01", CATEGORY_POLICY, True, authority=AUTHORITY_CHARTERING
    )
    fx.satisfy_condition(api, world["c_pol"], "BOARD-MIN-2026-08-15-POLICY-ADOPTION-PACKET")
    fx.all_four_policies_accepted(api, world)
    fx.signed_core_vendor(api, world)
    get_success_data(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_PRE_OPENING), COUNSEL_HEADERS
        )
    )
    world["ex1"] = fx.schedule_exam(api, world)
    return world


def _reject_the_lending_policy(api, world):
    return get_success_data(
        api.review_policy_document(
            world["pol_len"],
            policy_review_payload(REVIEW_REJECTED, finding_note=_FINDING_NOTE),
            CHARTERING_EXAMINER_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# Difficulty / transitive_cascade
# ---------------------------------------------------------------------------
def test_policy_rejection_fails_the_satisfied_policy_condition(api):
    """
    The rejection lands on the policy and immediately re-fails the settled policy condition
    it had underwritten. The condition's audit counter climbs to two — one for the original
    satisfaction and one for the cascade — while the number of conditions attached to the
    filing is conserved at one.

    PRD: "Second, because the policy became `REJECTED`, every approval condition whose `category` is `POLICY` and whose `status` is `SATISFIED` on the group's `CHARTERING_AUTHORITY` filing becomes `FAILED`, with `adjudication_count` incremented by one on each."

    Design: Difficulty/transitive_cascade/policy_rejection_cascades_five_levels_to_exam_cancellation
    """
    world = _pre_opening_with_a_satisfied_policy_condition(api)
    rejected = _reject_the_lending_policy(api, world)

    assert_fields_equal(rejected, status=POLICY_REJECTED, finding_note=_FINDING_NOTE)
    assert_fields_equal(
        fx.read_condition(api, world["c_pol"]),
        status=CONDITION_FAILED,
        adjudication_count=2,
    )
    assert_condition_counts_conserved(fx.read_filing(api, world["f_ca"]), 1)


def test_the_failed_condition_drives_the_chartering_filing_back_to_information_requested(api):
    """
    Because the condition re-entered the blocking set, the filing's posture is recomputed
    from zero open blockers to one, its clearance is withdrawn, and the filing itself falls
    out of conditional approval — consuming a round from the same three-round budget an
    examiner would have used.

    PRD: "Fourth, because `open_blocking_condition_count` rose from 0 while the filing was `CONDITIONALLY_APPROVED`, the filing moves to `ADDITIONAL_INFO_REQUESTED` and `info_request_round` increments by one — consuming a round from the same three-round budget an examiner would have used."

    Design: Difficulty/transitive_cascade/policy_rejection_cascades_five_levels_to_exam_cancellation
    """
    world = _pre_opening_with_a_satisfied_policy_condition(api)
    before = fx.read_filing(api, world["f_ca"])
    assert_fields_equal(
        before,
        status=FILING_CONDITIONALLY_APPROVED,
        open_blocking_condition_count=0,
        settled_condition_count=1,
        pre_opening_clearance=True,
    )

    _reject_the_lending_policy(api, world)

    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        status=FILING_ADDITIONAL_INFO_REQUESTED,
        info_request_round=1,
        open_blocking_condition_count=1,
        settled_condition_count=0,
        condition_total_count=1,
        pre_opening_clearance=False,
    )


def test_the_group_falls_out_of_pre_opening_and_the_scheduled_examination_is_cancelled(api):
    """
    The filing leaving conditional approval pulls the group back a stage with the
    information-request block recorded, and because the group left pre-opening its booked
    field visit is cancelled — five links away from the single review call that started it.

    PRD: "Sixth, because the group left `PRE_OPENING`, every readiness examination of the group whose `status` is `SCHEDULED` becomes `CANCELLED`."

    Design: Difficulty/transitive_cascade/policy_rejection_cascades_five_levels_to_exam_cancellation
    """
    world = _pre_opening_with_a_satisfied_policy_condition(api)
    _reject_the_lending_policy(api, world)

    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_CONDITIONALLY_APPROVED,
        opening_blocked_reason=BLOCKED_REASON_FILING_INFO_REQUESTED,
    )
    assert_fields_equal(fx.read_exam(api, world["ex1"]), status=EXAM_CANCELLED)


def test_the_cascade_spares_the_other_policies_the_insurer_filing_and_the_escrow(api):
    """
    The cascade is precisely bounded. The three other accepted policies keep their
    acceptance, the deposit insurer's application is not a chartering-authority filing and
    is untouched, and the money stays locked in escrow.

    PRD: "Note that the cascade reaches only the chartering authority's filing and only `POLICY`-category conditions; the deposit insurer's filing is untouched by a policy rejection, and a `POLICY` condition that was merely `OPEN` rather than `SATISFIED` is left where it is."

    Design: Difficulty/transitive_cascade/policy_rejection_cascades_five_levels_to_exam_cancellation
    """
    world = _pre_opening_with_a_satisfied_policy_condition(api)
    _reject_the_lending_policy(api, world)

    for key in ("pol_bsa", "pol_sec", "pol_risk"):
        assert_fields_equal(
            fx.read_policy(api, world[key]), status=POLICY_EXAMINER_ACCEPTED
        )
    assert_fields_equal(
        fx.read_filing(api, world["f_di"]), status=FILING_CONDITIONALLY_APPROVED
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]), status=RAISE_ESCROW_LOCKED
    )
