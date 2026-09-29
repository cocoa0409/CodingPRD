"""Rejection corners of the executive compensation and say-on-pay pipeline.

The behaviours exercised here are the gates the PRD places around the
compensation calendar: header authentication ahead of every other check, the
five declared uniqueness keys, the not-found error each unresolved row type
raises, the three design rules enforced when a pay program is opened, goal-curve
monotonicity in the metric's own direction, settlement of an award that is no
longer `GRANTED`, and the current-`ISS`-screen guard on legal clearance.
"""

import pytest

from test_helpers import (
    CHAIR,
    CONSULTANT,
    COUNSEL,
    COUNSEL_ONE,
    COUNSEL_TWO,
    COUNSEL_TWO_HEADERS,
    DEFAULT_MEETING_DATE,
    IR_LEAD,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_member_payload,
    analyze_payload,
    api_client,
    assert_money,
    create_cda_draft,
    create_cda_draft_payload,
    create_company_payload,
    create_incentive_metric_payload,
    create_pay_program_payload,
    create_screen,
    create_screen_payload,
    exclude_member_payload,
    hold_engagement_payload,
    peer_group_version,
    read_award,
    read_cda_draft,
    read_cda_drafts,
    read_company,
    read_metrics,
    read_pay_program,
    read_peer_group,
    read_screens,
    set_clock,
    settlement_payload,
    setup_award,
    setup_issuer,
    setup_mini_peer_group,
    setup_pay_program,
    submit_cda_review,
    validate_error,
    validate_success,
)

NO_CREDENTIALS: dict = {}


def test_missing_credentials_are_rejected_with_unauthenticated_before_id_resolution():
    """A request carrying neither header is refused ahead of path resolution.

    "If either header is absent, or if `X-User-Role` is not one of the five
    recognised role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)." "Lower numbers are evaluated first and the first failure is the
    response; a rule further down the ladder never masks a rule above it."

    Design: Corner/errors/an_unauthenticated_request_is_rejected_before_any_role_or_state_check
    """
    env = setup_issuer()
    issuer_id = env["issuer"]["id"]

    validate_error(
        api_client.get_company(issuer_id, NO_CREDENTIALS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    # The same call against an id that does not exist still reports the
    # authentication failure, not the not-found the resolved path would raise.
    validate_error(
        api_client.get_company(NON_EXISTENT_UUID, NO_CREDENTIALS),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    unchanged = read_company(issuer_id)
    assert unchanged["version"] == 1, "a rejected read must not mutate the company row"
    assert unchanged["ticker"] == "ACME"


class TestDeclaredUniquenessKeys:
    """The five uniqueness constraints the PRD declares, each with its neighbour."""

    def test_second_issuer_registration_with_the_same_ticker_is_rejected(self):
        """A repeated ticker and issuer flag cannot be registered twice.

        "Tickers are unique across the registry and at most one company may
        carry `is_issuer` as true; a second attempt at either is rejected with
        `ERR_ISSUER_ALREADY_EXISTS`."

        Design: Corner/errors/every_declared_uniqueness_constraint_rejects_its_duplicate
        """
        setup_issuer()

        validate_error(
            api_client.create_company(create_company_payload("ACME"), CONSULTANT),
            ApiErrorId.ERR_ISSUER_ALREADY_EXISTS,
            409,
        )

    def test_readding_the_same_peer_company_to_a_group_is_rejected(self):
        """A company may not hold two memberships in one group.

        "A company may not appear twice in the same group even if its earlier
        membership has since been excluded — the second attempt is
        `ERR_PEER_ALREADY_IN_GROUP` — and a group's own issuer may never be
        added as a peer of itself, which is `ERR_PEER_IS_ISSUER`."

        Design: Corner/errors/every_declared_uniqueness_constraint_rejects_its_duplicate
        """
        env = setup_mini_peer_group(target_status="DRAFT")
        group_id = env["peer_group"]["id"]

        # A different inclusion_reason does not make it a new membership.
        validate_error(
            api_client.add_peer_group_member(
                group_id,
                add_member_payload(
                    env["peer"]["id"],
                    peer_group_version(group_id),
                    "TALENT_COMPETITOR",
                ),
                CONSULTANT,
            ),
            ApiErrorId.ERR_PEER_ALREADY_IN_GROUP,
            409,
        )

        group = read_peer_group(group_id)
        assert group["accepted_member_count"] == 1, (
            "the rejected duplicate must not increment accepted_member_count"
        )

    def test_duplicate_metric_code_and_vehicle_pair_is_rejected_while_other_vehicle_is_free(self):
        """The uniqueness key is the program, the metric code and the vehicle.

        "The triple of program, `metric_code` and `vehicle` is unique; a
        duplicate is `ERR_METRIC_ALREADY_DEFINED`."

        Design: Corner/errors/every_declared_uniqueness_constraint_rejects_its_duplicate
        """
        env = setup_pay_program(metric_curves=("ADJ_EPS_LINEAR",), approve=False)
        program_id = env["program"]["id"]

        validate_error(
            api_client.create_incentive_metric(
                program_id,
                create_incentive_metric_payload("ADJ_EPS_LINEAR", weight_pct=40.00),
                CONSULTANT,
            ),
            ApiErrorId.ERR_METRIC_ALREADY_DEFINED,
            409,
        )

        # The same metric code under the other vehicle is a different key.
        psu = validate_success(
            api_client.create_incentive_metric(
                program_id,
                create_incentive_metric_payload(
                    "ADJ_EPS_LINEAR", vehicle="LONG_TERM_PSU", weight_pct=100.00
                ),
                CONSULTANT,
            ),
            201,
        )
        assert psu["vehicle"] == "LONG_TERM_PSU"
        assert len(read_metrics(program_id)) == 2, "only the duplicate was refused"

    def test_duplicate_section_code_is_rejected_while_another_section_code_is_free(self):
        """One disclosure row may exist per program and section code.

        "Only one row may exist per program per section code, and a duplicate is
        `ERR_CDA_SECTION_ALREADY_EXISTS`."

        Design: Corner/errors/every_declared_uniqueness_constraint_rejects_its_duplicate
        """
        env = setup_pay_program(approve=False)
        program_id = env["program"]["id"]
        create_cda_draft(program_id, "CD_AND_A", 2000, True, COUNSEL_ONE)

        validate_error(
            api_client.create_cda_draft(
                program_id,
                create_cda_draft_payload("CD_AND_A", 1800, True),
                COUNSEL,
            ),
            ApiErrorId.ERR_CDA_SECTION_ALREADY_EXISTS,
            409,
        )

        summary = validate_success(
            api_client.create_cda_draft(
                program_id,
                create_cda_draft_payload("SUMMARY_COMP_TABLE", 400, True),
                COUNSEL,
            ),
            201,
        )
        assert summary["section_code"] == "SUMMARY_COMP_TABLE"
        assert len(read_cda_drafts(program_id)) == 2

    def test_duplicate_advisor_screen_is_rejected_while_the_other_advisor_is_free(self):
        """One screen may exist per program and advisor.

        "Either an `InvestorRelationsLead` or a `CompConsultant` opens a screen
        naming the `advisor`, which is `ISS` or `GLASS_LEWIS`; only one screen
        may exist per program per advisor, and a second attempt is
        `ERR_SCREEN_ALREADY_EXISTS` with the instruction to re-run the existing
        one instead."

        Design: Corner/errors/every_declared_uniqueness_constraint_rejects_its_duplicate
        """
        env = setup_pay_program(approve=False)
        program_id = env["program"]["id"]
        create_screen(program_id, "ISS")

        validate_error(
            api_client.create_proxy_advisor_screen(
                program_id, create_screen_payload("ISS"), IR_LEAD
            ),
            ApiErrorId.ERR_SCREEN_ALREADY_EXISTS,
            409,
        )

        glass_lewis = validate_success(
            api_client.create_proxy_advisor_screen(
                program_id, create_screen_payload("GLASS_LEWIS"), IR_LEAD
            ),
            201,
        )
        assert glass_lewis["advisor"] == "GLASS_LEWIS"
        assert len(read_screens(program_id)) == 2


def test_unresolvable_path_identifiers_each_report_their_own_row_type():
    """Every unresolved child id names the row type that failed to resolve.

    "A request naming a non-existent company therefore fails with
    `ERR_COMPANY_NOT_FOUND` before any question about the sub-resource is asked;
    the same discipline yields `ERR_PEER_GROUP_NOT_FOUND`,
    `ERR_PEER_GROUP_MEMBER_NOT_FOUND`, `ERR_EXECUTIVE_NOT_FOUND`,
    `ERR_PAY_PROGRAM_NOT_FOUND`, `ERR_INCENTIVE_METRIC_NOT_FOUND`,
    `ERR_PAYOUT_AWARD_NOT_FOUND`, `ERR_CDA_DRAFT_NOT_FOUND`,
    `ERR_SCREEN_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`,
    `ERR_RESTATEMENT_EVENT_NOT_FOUND` and `ERR_DETERMINATION_NOT_FOUND` for
    their respective row types."

    Design: Corner/errors/every_remaining_resource_id_that_does_not_exist_returns_its_own_not_found
    """
    probes = [
        (
            "peer group member exclusion",
            api_client.exclude_peer_group_member(
                NON_EXISTENT_UUID,
                exclude_member_payload("No such membership row exists."),
                CONSULTANT,
            ),
            ApiErrorId.ERR_PEER_GROUP_MEMBER_NOT_FOUND,
        ),
        (
            "pay program read",
            api_client.get_pay_program(NON_EXISTENT_UUID, CHAIR),
            ApiErrorId.ERR_PAY_PROGRAM_NOT_FOUND,
        ),
        (
            "metric certification",
            api_client.certify_metric_result(NON_EXISTENT_UUID, CHAIR),
            ApiErrorId.ERR_INCENTIVE_METRIC_NOT_FOUND,
        ),
        (
            "award read",
            api_client.get_payout_award(NON_EXISTENT_UUID, CONSULTANT),
            ApiErrorId.ERR_PAYOUT_AWARD_NOT_FOUND,
        ),
        (
            "disclosure filing",
            api_client.file_cda_draft(NON_EXISTENT_UUID, COUNSEL),
            ApiErrorId.ERR_CDA_DRAFT_NOT_FOUND,
        ),
        (
            "screen re-run",
            api_client.rerun_proxy_advisor_screen(NON_EXISTENT_UUID, IR_LEAD),
            ApiErrorId.ERR_SCREEN_NOT_FOUND,
        ),
        (
            "engagement hold",
            api_client.hold_outreach_engagement(
                NON_EXISTENT_UUID, hold_engagement_payload("SUPPORTIVE"), IR_LEAD
            ),
            ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND,
        ),
        (
            "restatement analysis",
            api_client.analyze_restatement_event(
                NON_EXISTENT_UUID, analyze_payload([]), COUNSEL
            ),
            ApiErrorId.ERR_RESTATEMENT_EVENT_NOT_FOUND,
        ),
        (
            "determination read",
            api_client.get_clawback_determination(NON_EXISTENT_UUID, COUNSEL),
            ApiErrorId.ERR_DETERMINATION_NOT_FOUND,
        ),
    ]
    for label, response, expected_error in probes:
        assert response.status_code == 404, f"{label} must report 404"
        validate_error(response, expected_error, 404)


def test_unresolvable_ceo_executive_body_reference_reports_executive_not_found():
    """A body foreign key raises the not-found error of the entity it points at.

    "Foreign keys supplied in a request body are resolved after every path
    identifier has resolved, and among themselves in the order the endpoint's
    input list declares them: `peer_company_id`, `peer_group_id`,
    `ceo_executive_id`, `executive_id` and `payout_award_id` each raise the
    not-found error of the entity they point at."

    Design: Corner/errors/every_remaining_resource_id_that_does_not_exist_returns_its_own_not_found
    """
    env = setup_mini_peer_group(target_status="APPROVED")

    # The issuer and the peer group in the same body both resolve correctly.
    validate_error(
        api_client.create_pay_program(
            create_pay_program_payload(
                env["issuer"]["id"], env["peer_group"]["id"], NON_EXISTENT_UUID
            ),
            CONSULTANT,
        ),
        ApiErrorId.ERR_EXECUTIVE_NOT_FOUND,
        404,
    )


class TestPayProgramCreationDesignRules:
    """The mix and meeting-date rules checked when a program is opened."""

    def test_pay_mix_that_does_not_total_one_hundred_is_rejected(self):
        """Three in-bounds shares that sum to 95.00 still fail the total rule.

        "The pay mix is expressed as three percentages of target pay —
        `salary_pct`, `sti_pct` and `lti_pct` — each of which must lie in the
        closed range from 5.00 to 80.00, on pain of
        `ERR_MIX_COMPONENT_OUT_OF_BOUNDS`, and which together must total exactly
        100.00, on pain of `ERR_PAY_MIX_MUST_TOTAL_100`."

        Design: Corner/errors/program_creation_rejects_a_short_mix_an_out_of_bounds_component_and_a_past_meeting_date
        """
        env = setup_mini_peer_group(target_status="APPROVED")

        validate_error(
            api_client.create_pay_program(
                create_pay_program_payload(
                    env["issuer"]["id"],
                    env["peer_group"]["id"],
                    env["ceo"]["id"],
                    salary_pct=20.00,
                    sti_pct=25.00,
                    lti_pct=50.00,
                ),
                CONSULTANT,
            ),
            ApiErrorId.ERR_PAY_MIX_MUST_TOTAL_100,
            422,
        )

    def test_mix_component_below_the_floor_is_rejected_even_when_the_total_is_exact(self):
        """A 2.00 salary leg breaches the floor although the mix totals 100.00.

        "The pay mix is expressed as three percentages of target pay —
        `salary_pct`, `sti_pct` and `lti_pct` — each of which must lie in the
        closed range from 5.00 to 80.00, on pain of
        `ERR_MIX_COMPONENT_OUT_OF_BOUNDS`, and which together must total exactly
        100.00, on pain of `ERR_PAY_MIX_MUST_TOTAL_100`."

        Design: Corner/errors/program_creation_rejects_a_short_mix_an_out_of_bounds_component_and_a_past_meeting_date
        """
        env = setup_mini_peer_group(target_status="APPROVED")

        validate_error(
            api_client.create_pay_program(
                create_pay_program_payload(
                    env["issuer"]["id"],
                    env["peer_group"]["id"],
                    env["ceo"]["id"],
                    salary_pct=2.00,
                    sti_pct=18.00,
                    lti_pct=80.00,
                ),
                CONSULTANT,
            ),
            ApiErrorId.ERR_MIX_COMPONENT_OUT_OF_BOUNDS,
            422,
        )

    def test_meeting_date_not_in_the_future_is_rejected(self):
        """A meeting date behind the logical clock cannot open a program.

        "The meeting date must be strictly after the current logical time when
        the program is created; otherwise the creation is rejected with
        `ERR_MEETING_DATE_NOT_FUTURE`."

        Design: Corner/errors/program_creation_rejects_a_short_mix_an_out_of_bounds_component_and_a_past_meeting_date
        """
        env = setup_mini_peer_group(target_status="APPROVED")

        validate_error(
            api_client.create_pay_program(
                create_pay_program_payload(
                    env["issuer"]["id"],
                    env["peer_group"]["id"],
                    env["ceo"]["id"],
                    meeting_date="2026-07-01T00:00:00Z",
                ),
                CONSULTANT,
            ),
            ApiErrorId.ERR_MEETING_DATE_NOT_FUTURE,
            422,
        )

        # The identical body with a future meeting date is accepted, so the
        # meeting date was the only offending input.
        program = validate_success(
            api_client.create_pay_program(
                create_pay_program_payload(
                    env["issuer"]["id"],
                    env["peer_group"]["id"],
                    env["ceo"]["id"],
                    meeting_date=DEFAULT_MEETING_DATE,
                ),
                CONSULTANT,
            ),
            201,
        )
        assert program["design_status"] == "DRAFT"
        assert_money(program["target_tdc_usd"], 15000000.00, "target_tdc_usd")


def test_goal_curve_must_be_strictly_ordered_in_the_metrics_direction():
    """The same numeric ordering is legal for one direction and illegal for the other.

    "The three goal values must be **strictly** ordered in the metric's
    direction: for `HIGHER_IS_BETTER` the threshold must be less than the target
    and the target less than the maximum; for `LOWER_IS_BETTER` the threshold
    must be greater than the target and the target greater than the maximum."
    "A curve that violates this, whether at definition or at adjustment, is
    rejected with `ERR_GOAL_CURVE_NOT_MONOTONIC`."

    Design: Corner/errors/non_monotonic_goal_curves_are_rejected_in_both_directions
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]

    # HIGHER_IS_BETTER with the maximum below the target.
    validate_error(
        api_client.create_incentive_metric(
            program_id,
            create_incentive_metric_payload(
                "ADJ_EPS_LINEAR", target_value=6.00, maximum_value=5.00
            ),
            CONSULTANT,
        ),
        ApiErrorId.ERR_GOAL_CURVE_NOT_MONOTONIC,
        422,
    )

    # LOWER_IS_BETTER with a strictly ascending curve.
    validate_error(
        api_client.create_incentive_metric(
            program_id,
            create_incentive_metric_payload(
                "COST_RATIO_STEP",
                threshold_value=0.60,
                target_value=0.65,
                maximum_value=0.70,
            ),
            CONSULTANT,
        ),
        ApiErrorId.ERR_GOAL_CURVE_NOT_MONOTONIC,
        422,
    )

    # The descending curve is accepted for that same direction.
    accepted = validate_success(
        api_client.create_incentive_metric(
            program_id, create_incentive_metric_payload("COST_RATIO_STEP"), CONSULTANT
        ),
        201,
    )
    assert accepted["direction"] == "LOWER_IS_BETTER"
    assert accepted["threshold_value"] == pytest.approx(0.70, abs=0.01)
    assert accepted["maximum_value"] == pytest.approx(0.60, abs=0.01)

    metrics = read_metrics(program_id)
    assert len(metrics) == 1, "the rejected definitions wrote nothing"
    assert metrics[0]["metric_code"] == "COST_RATIO"


def test_settling_an_already_forfeited_award_reports_award_not_granted():
    """Forfeiture is terminal for settlement and outranks the certification gate.

    "A `CompConsultant` settles a `GRANTED` award — any other status is
    `ERR_AWARD_NOT_GRANTED` — supplying a `disposition` of either `VEST` or
    `FORFEIT` together with a `settlement_date`, and optionally a
    `vest_price_usd` override."

    Design: Corner/errors/settling_an_already_forfeited_award_returns_award_not_granted
    """
    env = setup_pay_program()
    env = setup_award(env, "psu", "LONG_TERM_PSU")
    award_id = env["awards"]["psu"]["id"]
    assert_money(
        read_award(award_id)["realizable_value_usd"], 5000000.00, "realizable_value_usd"
    )

    set_clock("2026-10-01T00:00:00Z")
    forfeited = validate_success(
        api_client.settle_payout_award(
            award_id, settlement_payload("FORFEIT", "2026-09-30T00:00:00Z"), CONSULTANT
        )
    )
    assert forfeited["status"] == "FORFEITED"

    # The program has no metric of this vehicle, so a VEST on a GRANTED award
    # would trip the certification gate; the settlement state gate wins.
    validate_error(
        api_client.settle_payout_award(
            award_id,
            settlement_payload("VEST", "2026-09-30T00:00:00Z", vest_price_usd=60.00),
            CONSULTANT,
        ),
        ApiErrorId.ERR_AWARD_NOT_GRANTED,
        409,
    )

    award = read_award(award_id)
    assert award["status"] == "FORFEITED"
    assert_money(award["realized_value_usd"], 0.00, "realized_value_usd")
    assert_money(award["realizable_value_usd"], 0.00, "realizable_value_usd")
    assert award["vest_price_usd"] is None, "a rejected vest must not freeze a price"

    program = read_pay_program(env["program"]["id"])
    assert_money(program["realized_pay_total_usd"], 0.00, "realized_pay_total_usd")
    assert_money(program["realizable_pay_total_usd"], 0.00, "realizable_pay_total_usd")


def test_legal_clearance_requires_a_current_iss_screen():
    """Only an `ISS` screen in `SCREENED` satisfies the clearance guard.

    "Finally, a cross-entity guard: the owning program must carry an `ISS`
    proxy-advisor screen whose status is `SCREENED`, so that counsel is clearing
    a disclosure against a current advisor read; a missing or `STALE` `ISS`
    screen is `ERR_ISS_SCREEN_NOT_CURRENT`."

    Design: Corner/errors/legal_clearance_without_a_current_iss_screen_is_rejected_even_when_glass_lewis_exists
    """
    env = setup_pay_program()
    program_id = env["program"]["id"]
    draft = create_cda_draft(program_id, "CD_AND_A", 2000, True, COUNSEL_ONE)
    submit_cda_review(draft["id"], COUNSEL_ONE)

    # No screens at all.
    validate_error(
        api_client.legal_clear_cda_draft(draft["id"], COUNSEL_TWO_HEADERS),
        ApiErrorId.ERR_ISS_SCREEN_NOT_CURRENT,
        409,
    )

    # A GLASS_LEWIS screen does not satisfy a guard that names ISS.
    create_screen(program_id, "GLASS_LEWIS")
    validate_error(
        api_client.legal_clear_cda_draft(draft["id"], COUNSEL_TWO_HEADERS),
        ApiErrorId.ERR_ISS_SCREEN_NOT_CURRENT,
        409,
    )

    iss = create_screen(program_id, "ISS")
    assert iss["advisor"] == "ISS"
    assert iss["status"] == "SCREENED"

    cleared = validate_success(
        api_client.legal_clear_cda_draft(draft["id"], COUNSEL_TWO_HEADERS)
    )
    assert cleared["status"] == "LEGAL_CLEARED"
    assert cleared["cleared_by_user_id"] == COUNSEL_TWO
    assert read_cda_draft(program_id, draft["id"])["revision_round"] == 0
