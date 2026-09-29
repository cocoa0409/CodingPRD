"""
There is no settling window anywhere in this API.

One approval rewrites four aggregates. The response body that reports it is already terminal,
and the very next read of every neighbour it touched agrees with it — no second call, no delay,
no refresh trigger. The plan re-read afterwards is the same document the approval returned.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    REVIEWER_ALPHA,
    approve_plan,
    assert_fields,
    assert_instant,
    close_comment,
    stage_enrolled,
    stage_plan,
    submit_plan,
    technical_review,
)

APPROVAL_INSTANT = "2026-12-10T00:00:00Z"
DESIGN_TOTAL_CENTS = 115210677
NEXT_CERTIFICATION_DUE_ON = "2027-04-01"


def _a_remedy_with_both_branches_landed(api):
    """The chain to the join point, with the PROPOSED control still attached."""
    world = stage_enrolled(api)
    stage_plan(world)
    submit_plan(world)
    technical_review(world, decision="PASS")
    close_comment(world)
    return world


def test_the_approval_response_is_already_the_final_document(api):
    """
    Nothing in the approve response is left null for a later pass, and the re-read matches it.

    "When an operation touches more than one aggregate, every consequence lands inside the same
    request, and every row the cascade rewrites has its `updated_at` refreshed and its `version`
    incremented by 1."

    Design: Corner/consistency model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    world = _a_remedy_with_both_branches_landed(api)

    approved = approve_plan(world)
    assert_fields(
        approved,
        status="APPROVED",
        approved_by_user_id="reviewer-alpha",
        technical_review_state="PASSED",
        public_comment_state="CLOSED",
        total_estimate_cents=DESIGN_TOTAL_CENTS,
    )
    assert_instant(approved["approved_at"], APPROVAL_INSTANT, "approved_at")

    re_read = get_success_data(api.get_plan(approved["id"], REVIEWER_ALPHA))
    assert re_read == approved, (
        "the plan re-read differs from the approval response that produced it: "
        f"{re_read} != {approved}"
    )


def test_the_control_and_the_enrollment_read_final_in_the_next_request(api):
    """
    Both cascaded neighbours are already where the approval put them.

    "Approval records `approved_by_user_id` and `approved_at`, then cascades: every site control
    on this plan whose `status` is `PROPOSED` becomes `APPROVED` with its
    `next_certification_due_on` recomputed and its `version` incremented by 1;"

    Design: Corner/consistency model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    world = _a_remedy_with_both_branches_landed(api)
    proposed_version = world.control["version"]

    approve_plan(world)

    assert_fields(
        world.read_control(),
        status="APPROVED",
        next_certification_due_on=NEXT_CERTIFICATION_DUE_ON,
        version=proposed_version + 1,
    )
    assert_fields(
        world.read_enrollment(), status="REMEDY_APPROVED", reverted_completion_count=0
    )


def test_the_parcels_derived_posture_agrees_at_once(api):
    """
    The gate every later operation consults is current the instant the approval returns.

    "The system must therefore treat the parcel's **cleanup posture** as a derived,
    always-current gate rather than a status somebody sets by hand, and it must propagate every
    consequence synchronously inside the request that triggered it."

    Design: Corner/consistency model/every_cascade_is_visible_in_the_response_that_caused_it
    """
    world = _a_remedy_with_both_branches_landed(api)

    approve_plan(world)

    assert_fields(world.read_site(), cleanup_posture="OPEN", impaired_control_count=0)
