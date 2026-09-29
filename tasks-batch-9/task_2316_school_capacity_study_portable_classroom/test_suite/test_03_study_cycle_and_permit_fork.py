"""The bounded study review loop and the permit fork with its two joins."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    CERTIFIER_HEADERS,
    OFFICIAL_HEADERS,
    PERMIT_HEADERS,
    PLANNER_HEADERS,
)
from test_helpers.assertions import assert_budget_partition, assert_capacity_fields
from test_helpers.factories import permit_decision_payload, permit_resubmit_payload
from test_helpers.fixtures import (
    build_campus,
    build_request_context,
    create_study,
    reopen_study,
    return_study,
    submit_study,
)


def _returned_twice(api):
    """A Pinecrest study that has been through two full return cycles."""
    ctx = build_campus(api, school_overrides={"name": "Pinecrest Middle",
                                              "site_acreage": 8.0,
                                              "electrical_spare_capacity_kw": 40,
                                              "sewer_spare_connections": 1})
    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    ctx["study_id"] = study["id"]

    submit_study(api, study["id"])
    return_study(api, study["id"], "Recheck the grade 6 cohort survival rate.")
    reopen_study(api, study["id"])
    submit_study(api, study["id"])
    ctx["second_return"] = return_study(api, study["id"],
                                        "Attach the developer yield memo.")
    return ctx


def test_third_return_caps_the_revision_cycle_and_blocks_the_next_reopen(api):
    """PRD §3.3: "**Reopening** closes the cycle. A `FacilitiesPlanner` reopens a study
    in `RETURNED`, moving it `RETURNED → DRAFT` and incrementing its `version` by 1,
    but only while `revision_round` is strictly less than 3. The fourth reopen attempt
    is refused with `ERR_REVISION_LIMIT_REACHED`, which is what caps the `DRAFT →
    SUBMITTED → RETURNED → DRAFT` loop at three revision rounds." The return itself
    "increments `revision_round` by 1, clears the frozen capacity and utilization
    fields back to their defaults so no stale figure can be mistaken for a live one".

    Design: Difficulty/non_linear_state_machine/study_revision_cycle_to_round_cap
    """
    ctx = _returned_twice(api)
    reopen_study(api, ctx["study_id"])
    submit_study(api, ctx["study_id"])

    returned = validate_success(
        api.return_study(ctx["study_id"], {"correction_note": "Third and final return."},
                         CERTIFIER_HEADERS)
    )
    assert returned["status"] == "RETURNED"
    assert returned["revision_round"] == 3
    assert returned["program_capacity_seats"] == 0
    assert returned["utilization_pct"] == 0

    refused = api.reopen_study(ctx["study_id"], {}, PLANNER_HEADERS)
    validate_error(refused, ApiErrorId.REVISION_LIMIT_REACHED)

    unchanged = validate_success(
        api.get_capacity_study(ctx["study_id"], PLANNER_HEADERS)
    )
    assert unchanged["status"] == "RETURNED"
    assert unchanged["revision_round"] == 3


def test_reopened_study_refreezes_its_figures_and_certify_is_refused_from_returned(api):
    """PRD §3.3: "**Submission** is the moment all of this is frozen." — on success the
    server "freezes `gross_room_seats`, `set_aside_deduction_seats`,
    `program_capacity_seats`, `projected_enrollment_total`, `utilization_pct`,
    `portable_trigger_met`, `seat_deficit` and `required_portable_count` onto the
    study". PRD §2.6 rule 10: "The target row is in a state from which the requested
    transition is declared — `ERR_STUDY_STATE_INVALID` ... on every action endpoint",
    while PRD §3.3 declares certification only for "a study in `SUBMITTED`".

    Design: Difficulty/non_linear_state_machine/study_revision_cycle_to_round_cap
    """
    ctx = _returned_twice(api)
    assert ctx["second_return"]["revision_round"] == 2

    refused = api.certify_study(ctx["study_id"], {}, CERTIFIER_HEADERS)
    validate_error(refused, ApiErrorId.STUDY_STATE_INVALID)

    reopen_study(api, ctx["study_id"])
    resubmitted = submit_study(api, ctx["study_id"])

    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 2
    assert_capacity_fields(
        resubmitted,
        program_capacity_seats=56,
        utilization_pct=107.1,
        portable_trigger_met=True,
        seat_deficit=7,
        required_portable_count=1,
    )


def test_permit_join_fires_only_when_the_last_permit_is_approved(api):
    """PRD §3.7: "When, and only when, every permit of the request now stands
    `APPROVED`, the request joins on the favourable arm: it moves `PERMIT_PENDING →
    PERMITTED`, and three linked effects follow. ... the estimate is copied into the
    request's `encumbered_cost_cents`, added to the appropriation's `encumbered_cents`,
    and `uncommitted_cents` is recomputed. Third, the reserved unit moves `RESERVED →
    SCHEDULED`, and because the unit is now scheduled onto that pad, the pad's
    `occupied_by_unit_id` is set to the unit."

    Design: Difficulty/non_linear_state_machine/placement_request_fork_join_over_permit_set
    """
    ctx = build_request_context(api, stage="permit_pending")
    permits = ctx["permit_ids"]
    assert set(permits) == {"DSA_STRUCTURAL", "FIRE_MARSHAL", "ELECTRICAL"}

    for permit_type in ("DSA_STRUCTURAL", "FIRE_MARSHAL"):
        validate_success(
            api.decide_permit(permits[permit_type],
                              permit_decision_payload("APPROVED"), OFFICIAL_HEADERS)
        )

    held = validate_success(api.get_placement_request(ctx["request_id"], PLANNER_HEADERS))
    assert held["status"] == "PERMIT_PENDING"
    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=0, expended_cents=0,
        uncommitted_cents=500_000_000,
    )
    assert validate_success(
        api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS)
    )["allocation_status"] == "RESERVED"
    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] is None

    final = validate_success(
        api.decide_permit(permits["ELECTRICAL"], permit_decision_payload("APPROVED"),
                          OFFICIAL_HEADERS)
    )
    assert final["status"] == "APPROVED"

    joined = validate_success(
        api.get_placement_request(ctx["request_id"], PLANNER_HEADERS)
    )
    assert joined["status"] == "PERMITTED"
    assert joined["required_permit_count"] == 3
    assert joined["encumbered_cost_cents"] == 7_741_440

    assert_budget_partition(
        validate_success(api.get_capital_budget(ctx["budget_id"], PLANNER_HEADERS)),
        authorized_cents=500_000_000, encumbered_cents=7_741_440, expended_cents=0,
        uncommitted_cents=492_258_560,
    )
    unit = validate_success(api.get_portable_unit(ctx["unit_id"], PLANNER_HEADERS))
    assert unit["allocation_status"] == "SCHEDULED"
    assert unit["condition_status"] == "SERVICEABLE"
    assert validate_success(
        api.get_placement_site(ctx["site_id"], PLANNER_HEADERS)
    )["occupied_by_unit_id"] == ctx["unit_id"]


def test_correction_loop_counts_review_cycles_on_the_looping_permit_only(api):
    """PRD §3.7: "The `PermitCoordinator` then refiles, supplying a
    `correction_response`; refiling requires the permit to be in
    `CORRECTIONS_REQUIRED` and the owning request still to be `PERMIT_PENDING`, moves
    the permit `CORRECTIONS_REQUIRED → SUBMITTED`, increments `review_cycle_count` by 1,
    refreshes `submitted_on` from the logical clock, and increments the permit's
    `version` by 1. This review loop is unbounded — a permit may cycle between
    `SUBMITTED` and `CORRECTIONS_REQUIRED` as many times as the building official
    requires."

    Design: Difficulty/non_linear_state_machine/placement_request_fork_join_over_permit_set
    """
    ctx = build_request_context(api, stage="permit_pending")
    dsa = ctx["permit_ids"]["DSA_STRUCTURAL"]
    fire = ctx["permit_ids"]["FIRE_MARSHAL"]

    for note, response in (("Add the tie-down calculations.", "Tie-down calculations attached."),
                           ("Seal the calculations.", "Sealed set attached.")):
        corrections = validate_success(
            api.decide_permit(
                dsa, permit_decision_payload("CORRECTIONS_REQUIRED", correction_note=note),
                OFFICIAL_HEADERS,
            )
        )
        assert corrections["status"] == "CORRECTIONS_REQUIRED"
        assert corrections["correction_note"] == note
        validate_success(
            api.resubmit_permit(dsa, permit_resubmit_payload(correction_response=response),
                                PERMIT_HEADERS)
        )

    validate_success(
        api.decide_permit(dsa, permit_decision_payload("APPROVED"), OFFICIAL_HEADERS)
    )

    looped = validate_success(api.get_permit(dsa, PERMIT_HEADERS))
    assert looped["status"] == "APPROVED"
    assert looped["review_cycle_count"] == 2

    quiet = validate_success(api.get_permit(fire, PERMIT_HEADERS))
    assert quiet["review_cycle_count"] == 0
    assert quiet["status"] == "SUBMITTED"
