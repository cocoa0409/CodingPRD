"""The betterment test, the plan revision cycle and the gates on plan approval."""
from test_helpers import (
    CANON_BETTERMENT_AMOUNT_CENTS,
    CANON_BETTERMENT_RATIO,
    CANON_STATE_LIABILITY_CENTS,
    apply_permit,
    assert_settlement_figures,
    assert_version_advanced_by,
    grant_permit,
    make_utility_coordinator_headers,
    plan_payload,
    read_agreement,
    read_conflict,
    read_plan,
    read_project,
    read_settlement_preview,
    settle_agreement,
    start_plan_review,
    validate_error,
    validate_success,
    world_agreement_drafted,
    world_cost_documents,
    world_plan_submitted,
)

TWO_ACCEPTED_LINES = [
    {
        "doc_type": "LABOR",
        "amount_cents": 12_345_678,
        "incurred_on": "2027-04-02T00:00:00Z",
        "support_reference": "PR-2027-04-A",
        "review": "ACCEPT",
    },
    {
        "doc_type": "MATERIAL",
        "amount_cents": 9_876_543,
        "incurred_on": "2027-04-10T00:00:00Z",
        "support_reference": "INV-88213",
        "review": "ACCEPT",
    },
]

REVISION_LAPS = [
    {
        "note": "Reduce conduit count to replacement in kind.",
        "body": {
            "estimated_cost_cents": 39_000_000,
            "replacement_in_kind_cost_cents": 32_000_000,
            "proposed_capacity_ratio": 1.20,
            "work_days": 11,
        },
        "ratio": 0.316239,
        "amount": 12_333_321,
        "liability": 26_666_679,
    },
    {
        "note": "Capacity still above in-kind.",
        "body": {
            "estimated_cost_cents": 38_000_000,
            "replacement_in_kind_cost_cents": 32_000_000,
            "proposed_capacity_ratio": 1.10,
            "work_days": 10,
        },
        "ratio": 0.234450,
        "amount": 8_909_100,
        "liability": 29_090_900,
    },
    {
        "note": "Work days must fit the paving window.",
        "body": {
            "estimated_cost_cents": 37_000_000,
            "replacement_in_kind_cost_cents": 32_000_000,
            "proposed_capacity_ratio": 1.05,
            "work_days": 9,
        },
        "ratio": 0.176319,
        "amount": 6_523_803,
        "liability": 30_476_197,
    },
]


def test_the_settlement_credit_is_summed_from_individually_rounded_lines(api):
    """PRD 3.5: "Each line is rounded before summing — rounding the aggregate
    instead can differ by up to one cent per line, and lines of 12,345,678,
    9,876,543 and a 1,000,000 salvage credit at a ratio of 0.360000 yield
    4,444,444 plus 3,555,555 minus 360,000, which is 7,639,999 per line against
    7,640,000 in aggregate."

    Design: Difficulty/combinatorial_formula/betterment_credit_per_line_rounding_beats_aggregate_rounding
    """
    world = world_cost_documents(api, documents=TWO_ACCEPTED_LINES)
    assert world["plan"]["betterment_ratio"] == CANON_BETTERMENT_RATIO

    settled = settle_agreement(api, world["agreement_id"], "ASB-2258-0011")

    assert_settlement_figures(
        settled,
        cost_basis="ACTUAL_BASIS",
        eligible_cost_cents=22_222_221,
        betterment_credit_cents=7_999_999,
        indirect_cost_cents=2_777_778,
        net_allowable_cents=17_000_000,
        participation_tier_pct=95,
        state_share_cents=16_150_000,
        owner_share_cents=850_000,
    )
    assert settled["betterment_credit_cents"] != 8_000_000
    assert settled["settlement_status"] == "SETTLED"


def test_the_preview_reports_the_per_line_credit_without_moving_the_agreement(api):
    """PRD 2.10: "An agreement's settlement preview re-runs the full settlement
    chain on the actual cost basis without mutating anything, reporting
    `cost_basis`, `eligible_cost_cents`, `indirect_cost_cents`,
    `betterment_credit_cents`, `net_allowable_cents`, `participation_tier_pct`,
    `state_share_cents`, `owner_share_cents`, and the `included_document_count`
    and `excluded_document_count` that the chronological not-to-exceed cutoff
    would produce."

    Design: Difficulty/combinatorial_formula/betterment_credit_per_line_rounding_beats_aggregate_rounding
    """
    world = world_cost_documents(api, documents=TWO_ACCEPTED_LINES)
    before = read_agreement(api, world["agreement_id"])

    preview = read_settlement_preview(api, world["agreement_id"])

    assert_settlement_figures(
        preview,
        eligible_cost_cents=22_222_221,
        betterment_credit_cents=7_999_999,
        indirect_cost_cents=2_777_778,
        net_allowable_cents=17_000_000,
        participation_tier_pct=95,
        state_share_cents=16_150_000,
        owner_share_cents=850_000,
        included_document_count=2,
        excluded_document_count=0,
    )
    assert preview["betterment_credit_cents"] != 8_000_000

    after = read_agreement(api, world["agreement_id"])
    assert after["version"] == before["version"]
    assert after["cost_basis"] == "ESTIMATE_BASIS"
    assert after["betterment_credit_cents"] == CANON_BETTERMENT_AMOUNT_CENTS
    assert after["settlement_status"] == "PENDING_FINAL_INVOICE"


def test_three_revision_laps_are_allowed_and_the_fourth_resubmission_is_refused(api):
    """PRD 3.5: "A plan may be resubmitted only while `revision_round` is strictly
    below 3; the fourth attempt is refused with `ERR_REVISION_LIMIT_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle_reenters_submitted_three_times_then_hits_the_limit
    """
    world = world_plan_submitted(api)
    coordinator = make_utility_coordinator_headers()
    plan_id = world["plan_id"]
    assert world["plan"]["revision_round"] == 0

    for expected_round, lap in enumerate(REVISION_LAPS, start=1):
        validate_success(api.start_plan_review(plan_id, coordinator))
        validate_success(
            api.request_plan_revision(plan_id, {"revision_note": lap["note"]}, coordinator)
        )
        resubmitted = validate_success(
            api.resubmit_plan(plan_id, lap["body"], world["rep_headers"])
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_round"] == expected_round

    validate_success(api.start_plan_review(plan_id, coordinator))
    validate_success(
        api.request_plan_revision(plan_id, {"revision_note": "Fourth pass requested."}, coordinator)
    )

    validate_error(
        api.resubmit_plan(
            plan_id,
            {
                "estimated_cost_cents": 36_000_000,
                "replacement_in_kind_cost_cents": 32_000_000,
                "proposed_capacity_ratio": 1.00,
                "work_days": 9,
            },
            world["rep_headers"],
        ),
        "ERR_REVISION_LIMIT_EXCEEDED",
    )

    plan = read_plan(api, plan_id)
    assert plan["revision_round"] == 3
    assert plan["status"] == "REVISION_REQUESTED"
    assert plan["estimated_cost_cents"] == 37_000_000
    assert plan["proposed_capacity_ratio"] == 1.05
    assert plan["betterment_ratio"] == 0.176319
    assert plan["betterment_amount_cents"] == 6_523_803
    assert read_conflict(api, world["conflict_id"])["status"] == "RESPONSIBILITY_SET"


def test_each_lap_rebuilds_the_betterment_figures_and_the_forward_liability(api):
    """PRD 3.5: "Resubmission — open to the owner's representative and to a
    coordinator — moves it `REVISION_REQUESTED → SUBMITTED`, increments
    `revision_round` by 1, and overwrites all four substantive numbers
    (`estimated_cost_cents`, `replacement_in_kind_cost_cents`,
    `proposed_capacity_ratio` and `work_days`) from the request body, then
    recomputes `betterment_ratio` and `betterment_amount_cents` and, from the
    revised governing plan, the project's `estimated_state_liability_cents` and
    `clearance_posture`."

    Design: Difficulty/non_linear_state_machine/plan_revision_cycle_reenters_submitted_three_times_then_hits_the_limit
    """
    world = world_plan_submitted(api)
    coordinator = make_utility_coordinator_headers()
    plan_id = world["plan_id"]
    assert world["plan"]["betterment_ratio"] == CANON_BETTERMENT_RATIO
    assert world["plan"]["betterment_amount_cents"] == CANON_BETTERMENT_AMOUNT_CENTS
    assert read_project(api, world["project_id"])["estimated_state_liability_cents"] == (
        CANON_STATE_LIABILITY_CENTS
    )

    previous = world["plan"]
    for lap in REVISION_LAPS:
        under_review = validate_success(api.start_plan_review(plan_id, coordinator))
        assert under_review["status"] == "UNDER_REVIEW"
        returned = validate_success(
            api.request_plan_revision(plan_id, {"revision_note": lap["note"]}, coordinator)
        )
        assert returned["status"] == "REVISION_REQUESTED"

        resubmitted = validate_success(
            api.resubmit_plan(plan_id, lap["body"], world["rep_headers"])
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["estimated_cost_cents"] == lap["body"]["estimated_cost_cents"]
        assert resubmitted["work_days"] == lap["body"]["work_days"]
        assert resubmitted["betterment_ratio"] == lap["ratio"]
        assert resubmitted["betterment_amount_cents"] == lap["amount"]
        assert_version_advanced_by(previous, resubmitted, 3)
        previous = resubmitted

        project = read_project(api, world["project_id"])
        assert project["estimated_state_liability_cents"] == lap["liability"]
        assert project["clearance_posture"] == "CLEARANCE_PENDING"


def test_approval_waits_for_the_last_outstanding_permit_of_the_conflict(api):
    """PRD 3.5: "Moving a plan `UNDER_REVIEW → APPROVED` requires the conflict
    behind it to have a determination in status `ISSUED` or `FINAL` with a
    non-null `state_share_pct` — otherwise `ERR_PRIOR_RIGHTS_NOT_ISSUED` — and
    requires every permit record of that conflict to be in status `GRANTED`, with
    at least one permit record existing at all — otherwise
    `ERR_PERMIT_NOT_GRANTED`."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_depends_on_every_permit_record_being_granted
    """
    world = world_plan_submitted(
        api, project_overrides={"name": "SR-14 Easement Reach"}
    )
    coordinator = make_utility_coordinator_headers()
    granted = grant_permit(api, world["conflict_id"])
    outstanding = apply_permit(
        api, world["conflict_id"], permit_type="EASEMENT_ACQUISITION"
    )
    assert granted["status"] == "GRANTED"
    assert outstanding["status"] == "APPLIED"
    assert world["determination"]["status"] == "ISSUED"

    under_review = start_plan_review(api, world["plan_id"], coordinator)
    assert under_review["status"] == "UNDER_REVIEW"

    validate_error(
        api.approve_plan(world["plan_id"], coordinator), "ERR_PERMIT_NOT_GRANTED"
    )
    assert read_plan(api, world["plan_id"])["status"] == "UNDER_REVIEW"
    assert read_conflict(api, world["conflict_id"])["status"] == "RESPONSIBILITY_SET"

    decided = validate_success(
        api.decide_permit(
            outstanding["id"],
            {"decision": "GRANT", "decision_note": "Easement acquired and recorded."},
            coordinator,
        )
    )
    assert decided["status"] == "GRANTED"
    assert decided["granted_on"] == "2026-08-01T00:00:00Z"

    approved = validate_success(api.approve_plan(world["plan_id"], coordinator))
    assert approved["status"] == "APPROVED"
    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_PLANNED"


def test_a_conflict_with_no_permit_record_at_all_cannot_have_its_plan_approved(api):
    """PRD 2.9: "Every permit record of the conflict is in status `GRANTED`, and at
    least one permit record exists — otherwise `ERR_PERMIT_NOT_GRANTED`. Applies
    to plan approval."

    Design: Difficulty/cross_entity_state_dependency/plan_approve_depends_on_every_permit_record_being_granted
    """
    world = world_plan_submitted(
        api, project_overrides={"name": "SR-14 Easement Reach"}
    )
    coordinator = make_utility_coordinator_headers()
    start_plan_review(api, world["plan_id"], coordinator)

    validate_error(
        api.approve_plan(world["plan_id"], coordinator), "ERR_PERMIT_NOT_GRANTED"
    )
    assert read_plan(api, world["plan_id"])["status"] == "UNDER_REVIEW"
    assert read_conflict(api, world["conflict_id"])["status"] == "RESPONSIBILITY_SET"

    grant_permit(api, world["conflict_id"])
    approved = validate_success(api.approve_plan(world["plan_id"], coordinator))
    assert approved["status"] == "APPROVED"
    assert read_conflict(api, world["conflict_id"])["status"] == "RELOCATION_PLANNED"


def test_a_newer_plan_retires_the_old_one_and_voids_its_drafted_agreement(api):
    """PRD 3.5: "That retirement reaches into the agreement world: every
    reimbursement agreement of a superseded plan sitting in `execution_status`
    `DRAFT` or `PENDING_OWNER_SIGNATURE` moves to `execution_status` `VOIDED` and
    `settlement_status` `VOIDED_OUT`."

    Design: Corner/state_machines/a_newer_plan_supersedes_the_old_one_and_voids_its_draft_agreement
    """
    world = world_agreement_drafted(api)
    conflict_before = read_conflict(api, world["conflict_id"])
    assert world["agreement"]["execution_status"] == "DRAFT"
    assert read_project(api, world["project_id"])["estimated_state_liability_cents"] == (
        CANON_STATE_LIABILITY_CENTS
    )

    second_plan = validate_success(
        api.create_relocation_plan(
            plan_payload(
                world["conflict_id"],
                conflict_before["version"],
                estimated_cost_cents=39_000_000,
                replacement_in_kind_cost_cents=32_000_000,
                proposed_capacity_ratio=1.20,
                work_days=10,
            ),
            world["rep_headers"],
        ),
        201,
    )
    assert second_plan["status"] == "SUBMITTED"
    assert second_plan["revision_round"] == 0
    assert second_plan["betterment_ratio"] == 0.316239
    assert second_plan["betterment_amount_cents"] == 12_333_321

    assert read_plan(api, world["plan_id"])["status"] == "SUPERSEDED"

    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["execution_status"] == "VOIDED"
    assert agreement["settlement_status"] == "VOIDED_OUT"

    project = read_project(api, world["project_id"])
    assert project["estimated_state_liability_cents"] == 26_666_679
    assert project["total_committed_reimbursement_cents"] == 0

    conflict_after = read_conflict(api, world["conflict_id"])
    assert conflict_after["status"] == "RELOCATION_PLANNED"
    assert_version_advanced_by(conflict_before, conflict_after)
