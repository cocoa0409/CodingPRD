"""State machines that loop back and dimensions that do not follow each other.

A denied application does not die: it returns to the same reviewer for another
round on the same row. And a project's certification dimension can advance while
its compliance dimension stays parked on an unresolved breach.
"""

from test_helpers import assertions, fixtures, types, validate_success


def test_denied_part_two_resubmission_returns_the_same_row_to_shpo_review(api):
    """A revision reuses the row and counts a second review round.

    Part 1 is approved, so the property is certified. Part 2 is then submitted,
    recommended for approval and denied, which parks it in REVISION_REQUIRED on
    review round 1. Resubmitting with a replacement narrative moves that same row
    back to SHPO_REVIEW on round 2 rather than creating a new application, and the
    replacement narrative is what the row now carries.

    PRD: "The owning `Developer` resubmits an application in `REVISION_REQUIRED` with a replacement `narrative`, which advances it `REVISION_REQUIRED → SHPO_REVIEW` and hands it back to the reviewer already recorded in `shpo_reviewer_id` — who must still hold `credential_status` of `ACTIVE`, else `ERR_REVIEWER_NOT_ELIGIBLE`."
    PRD: "A determination of `DENIED` advances the application `NPS_REVIEW → REVISION_REQUIRED`, returning it to the developer for revision."
    PRD: "The revision loop reuses the same row rather than creating a new one."

    Design: Difficulty/non_linear_state_machine/part_application_revision_cycle_returns_to_shpo_review
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    fixtures.walk_part_to_approved(api, cast, project["id"], 1)
    part2 = fixtures.create_part_application(
        api, cast, project["id"], 2, narrative="Rehabilitation plan, revision 1."
    )
    fixtures.submit_part_application(api, cast, part2["id"])
    fixtures.shpo_recommend(api, cast, part2["id"])
    denied = fixtures.nps_determine(
        api,
        cast,
        part2["id"],
        determination="DENIED",
        review_note="Window replacement scope is inconsistent with Standard 6.",
    )
    assertions.assert_fields(
        denied, "denied part 2", status="REVISION_REQUIRED", review_round=1
    )

    revised = validate_success(
        api.resubmit_part_application(
            part2["id"],
            cast.developer_headers,
            narrative=(
                "Rehabilitation plan, revision 2: original windows repaired in "
                "place."
            ),
        )
    )

    types.assert_is_part_application(revised)
    assertions.assert_fields(
        revised,
        "resubmitted part 2",
        id=part2["id"],
        status="SHPO_REVIEW",
        review_round=2,
        narrative=(
            "Rehabilitation plan, revision 2: original windows repaired in place."
        ),
    )
    listed_items, _ = assertions.assert_page(
        api.list_part_applications(
            cast.developer_headers, project_id=project["id"], part_number=2
        ),
        total_count=1,
    )
    assertions.assert_ids_equal(listed_items, [part2["id"]], "part 2 applications")


def test_resubmission_clears_the_review_verdicts_but_keeps_the_shpo_reviewer(api):
    """The round resets the verdict fields and leaves the project alone.

    On resubmission the recommendation and the determination both go back to NONE
    and the decision timestamp and the NPS reviewer are cleared, so the second
    round starts from a clean verdict. The SHPO reviewer recorded at first
    submission is retained, because the revision goes back to the same office. The
    project's certification dimension is untouched by the whole cycle and still
    reads PART1_CERTIFIED.

    PRD: "On success, `review_round` increases by one, `shpo_recommendation` resets to `NONE`, `determination` resets to `NONE`, `nps_reviewer_id` resets to null, `decision_at` resets to null, `submitted_at` is re-stamped from the logical clock, `review_window_end` is re-derived as thirty days after it, and the `version` increments."
    PRD: "A denial of a Part 2 or Part 3 application, or of a Part 1 application on a project that has already moved past `PRE_CERTIFICATION`, mutates only the application."

    Design: Difficulty/non_linear_state_machine/part_application_revision_cycle_returns_to_shpo_review
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    fixtures.walk_part_to_approved(api, cast, project["id"], 1)
    part2 = fixtures.create_part_application(
        api, cast, project["id"], 2, narrative="Rehabilitation plan, revision 1."
    )
    fixtures.submit_part_application(api, cast, part2["id"])
    fixtures.shpo_recommend(api, cast, part2["id"])
    fixtures.nps_determine(api, cast, part2["id"], determination="DENIED")

    revised = validate_success(
        api.resubmit_part_application(
            part2["id"],
            cast.developer_headers,
            narrative=(
                "Rehabilitation plan, revision 2: original windows repaired in "
                "place."
            ),
        )
    )

    assertions.assert_fields(
        revised,
        "resubmitted part 2",
        shpo_recommendation="NONE",
        determination="NONE",
        decision_at=None,
        nps_reviewer_id=None,
        shpo_reviewer_id=cast.shpo_reviewer_id,
    )
    assert revised["submitted_at"] is not None, "resubmission re-stamps submitted_at"
    assert revised["review_window_end"] is not None, (
        "resubmission re-derives the review window"
    )
    project_after = fixtures.read_project(api, cast, project["id"])
    assertions.assert_project_state(
        project_after,
        certification_status="PART1_CERTIFIED",
        compliance_status="NOT_MONITORED",
    )


def test_part_three_certification_advances_certification_while_cure_stays_pending(api):
    """The certification axis moves; the compliance axis does not follow it.

    A single-tier project with 62500013 of qualified cost clears Part 1 and Part 2,
    is placed in service on 2029-01-15, and then has its only covenant attested
    with an EXCEPTION, which parks compliance at CURE_PENDING while certification
    is still PART2_APPROVED. Walking Part 3 to approval moves certification to
    PART3_CERTIFIED and leaves compliance exactly where the breach put it, because
    neither dimension writes the other.

    PRD: "A project row carries two enumerated state fields that advance on separate axes and never write each other."
    PRD: "The compliance dimension is untouched by all of this: it has already left `NOT_MONITORED` at the placed-in-service declaration, which Part 3 approval presupposes."
    PRD: "The certification dimension is not an input to it at any step."

    Design: Difficulty/non_linear_state_machine/project_certification_and_compliance_dimensions_evolve_independently
    """
    scenario = fixtures.in_service_project(
        api,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        headers=fixtures.MONITOR,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2030-01-14",
    )
    fixtures.attest_covenant(
        api, cast, covenant["id"], "2029-01-31", "EXCEPTION", headers=fixtures.MONITOR
    )
    before = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(
        before, certification_status="PART2_APPROVED", compliance_status="CURE_PENDING"
    )

    fixtures.walk_part_to_approved(api, cast, project_id, 3)

    after = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(
        after, certification_status="PART3_CERTIFIED", compliance_status="CURE_PENDING"
    )
    breached = validate_success(
        api.get_compliance_covenant(covenant["id"], cast.developer_headers)
    )
    assertions.assert_fields(breached, "covenant", status="BREACHED")


def test_part_three_certification_freezes_the_schedule_and_locks_the_costs(api):
    """The third hop of approval freezes the credit and locks every cost.

    The same Part 3 approval sets the freeze flag, drives the project's one
    qualified cost from QRE to LOCKED_QRE, and leaves the annual instalment at the
    2500001 the substantial test earned before certification. The covenant breach
    that keeps compliance at CURE_PENDING is unaffected by any of it.

    PRD: "For Part 3 only, a third hop sets `frozen_at_certification` to true, which permanently stops recomputation of `annual_credit_cents` and `total_claimable_credit_cents`, and drives every cost line item of the project from `QRE` to `LOCKED_QRE` and from `NON_QRE` to `LOCKED_NON_QRE`, bumping each of those line items' `version`."
    PRD: "On Part 3 certification every `QRE` item becomes `LOCKED_QRE` and every `NON_QRE` item becomes `LOCKED_NON_QRE`, and a `Developer` who then attempts to reclassify one is refused with `ERR_COST_ITEM_LOCKED`."

    Design: Difficulty/non_linear_state_machine/project_certification_and_compliance_dimensions_evolve_independently
    """
    scenario = fixtures.in_service_project(
        api,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    cost_id = scenario["cost"]["id"]
    covenant = fixtures.create_covenant(
        api,
        cast,
        project_id,
        headers=fixtures.MONITOR,
        covenant_type="USE_RESTRICTION",
        monitoring_frequency="ANNUAL",
        window_start_date="2029-01-15",
        window_end_date="2030-01-14",
    )
    fixtures.attest_covenant(
        api, cast, covenant["id"], "2029-01-31", "EXCEPTION", headers=fixtures.MONITOR
    )

    fixtures.walk_part_to_approved(api, cast, project_id, 3)

    project = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        project,
        frozen_at_certification=True,
        annual_credit_cents=2_500_001,
        total_claimable_credit_cents=12_500_005,
        substantial_test_status="MET",
    )
    locked = validate_success(api.get_cost_line_item(cost_id, cast.developer_headers))
    assertions.assert_fields(locked, "certified cost", classification="LOCKED_QRE")
