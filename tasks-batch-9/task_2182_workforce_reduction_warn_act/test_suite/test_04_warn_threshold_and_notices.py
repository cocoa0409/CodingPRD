"""Jurisdictional threshold counting, WARN notices and the aggregation window."""

from test_helpers import (
    ALICE,
    BEN,
    CARLA,
    ELENA,
    FEDERAL_NOTICE_CONTENT,
    NY_NOTICE_CONTENT,
    TEST_USERS,
    TX_NOTICE_CONTENT,
    ApiErrorId,
    assert_warn_notice,
    configure_federal_rule,
    configure_ny_state_rule,
    configure_rule,
    create_locked_plan,
    create_selection_payload,
    create_site,
    decide,
    draft_warn_notice,
    hire,
    issue_warn_notice,
    ny_state_rule_payload,
    propose,
    read_analysis,
    read_disclosure,
    read_employee,
    read_plan,
    read_site,
    read_warn_notice,
    render_legal_decision,
    rescind,
    run_and_clear_analysis,
    setup_dual_jurisdiction_roster,
    setup_ny_scenario_with_issued_state_notice,
    setup_ny_single_selection_with_paperwork,
    setup_ny_triggered_scenario,
    setup_site_with_roster,
    setup_tx_percent_boundary_scenario,
    submit_for_review,
    tx_state_rule_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warn_notice_payload,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestFederalAndStateCountingOnOneRoster:
    """The same roster on the same day yields two different determinations."""

    def test_federal_determination_drops_part_time_and_short_service_losses(self, api):
        """PRD 3.4: "The numerator — `employment_loss_count` — counts the site's
        employees whose `employment_status` is `PENDING_SEPARATION` or
        `SEPARATED`, whose `separation_date` falls inside the window under the
        jurisdiction's interval convention, who are not excluded as part-time
        (that is, either the rule's `counts_part_time` is true, or the person's
        `is_part_time` is false), and whose service — the number of days from
        their `hire_date` to their `separation_date` — is at least the rule's
        `min_service_days`."
        PRD 3.4: "The denominator — `workforce_count` — counts the site's
        employees whose `employment_status` is `ACTIVE`, `PENDING_SEPARATION` or
        `SEPARATED`, whose `hire_date` is on or before the window start, and who
        are not excluded as part-time on the same `counts_part_time` test."
        PRD 3.4: "The count test passes when the loss count is at least the
        rule's `min_loss_count`. The percent test passes when the rule's
        `min_percent` is 0, or when `loss_percent` is at least `min_percent`."

        Design: Difficulty/dual_variant_calc/warn_loss_count_federal_versus_state_on_identical_roster
        """
        scn = setup_dual_jurisdiction_roster()

        notice = validate_success(
            api.create_warn_notice(
                warn_notice_payload(
                    scn["plan"]["id"],
                    scn["site"]["id"],
                    "FEDERAL",
                    FEDERAL_NOTICE_CONTENT,
                ),
                COUNSEL,
            ),
            201,
        )
        assert_warn_notice(notice)
        assert notice["applied_rule_code"] == "FED-WARN-1988"
        assert notice["employment_loss_count"] == 2, (
            "the part-time and the sub-180-day-service losses drop out"
        )
        assert notice["workforce_count"] == 4, "the part-time person leaves the base too"
        assert notice["loss_percent"] == 50.00
        assert notice["threshold_met"] is False, "2 losses is below min_loss_count 3"
        assert notice["trigger_type"] == "NONE"
        assert notice["window_start_date"] == "2026-12-01"
        assert notice["window_end_date"] == "2027-03-01"

    def test_state_determination_keeps_them_and_crosses_its_threshold(self, api):
        """PRD 3.4: "Under the `FEDERAL` rule the window is half-open: a
        separation date counts when it falls on or after the window start and
        strictly before the window end. Under a `STATE` rule the window is
        closed: a separation date counts when it falls on or after the window
        start and on or before the window end."
        PRD 3.4: "The notice's `window_end_date` is its `window_start_date` plus
        the applied rule's `window_days`, and the interval it stands for is
        half-open at the end for a `FEDERAL` notice and closed for a `STATE`
        notice. Its `notice_deadline_utc` is the `window_start_date` at midnight
        UTC less `required_notice_days` days, and is null whenever
        `threshold_met` came out false."
        PRD 3.4: "When `threshold_met` is true and the loss count equals the
        workforce count, the `trigger_type` is `PLANT_CLOSING`; when
        `threshold_met` is true otherwise, it is `MASS_LAYOFF`; when the
        threshold is not met it is `NONE`."

        Design: Difficulty/dual_variant_calc/warn_loss_count_federal_versus_state_on_identical_roster
        """
        scn = setup_dual_jurisdiction_roster()

        notice = validate_success(
            api.create_warn_notice(
                warn_notice_payload(
                    scn["plan"]["id"], scn["site"]["id"], "STATE", NY_NOTICE_CONTENT
                ),
                COUNSEL,
            ),
            201,
        )
        assert notice["employment_loss_count"] == 4
        assert notice["workforce_count"] == 5
        assert notice["loss_percent"] == 80.00
        assert notice["threshold_met"] is True
        assert notice["trigger_type"] == "MASS_LAYOFF"
        assert notice["window_end_date"] == "2026-12-31", "30 closed days from 2026-12-01"
        assert notice["required_notice_days"] == 90
        assert notice["notice_deadline_utc"] == "2026-09-02T00:00:00.000Z"

    def test_site_carries_both_jurisdictions_counts_side_by_side(self, api):
        """PRD 3.4: "A site's `warn_trigger_status` is `PLANT_CLOSING` when a
        triggered jurisdiction's loss count equals its workforce count, otherwise
        `MASS_LAYOFF` when either jurisdiction reports its threshold met, and
        otherwise `NONE`. The site's `required_notice_days` is the largest
        `notice_days` among the jurisdictions whose threshold is met for that
        site, and is 0 when `warn_trigger_status` is `NONE`."
        PRD 3.4: "The counting algorithm is the same shape for both
        jurisdictions but differs in two pinned respects, and the two counts are
        maintained side by side on every site as `federal_loss_count` and
        `state_loss_count`."

        Design: Difficulty/dual_variant_calc/warn_loss_count_federal_versus_state_on_identical_roster
        """
        scn = setup_dual_jurisdiction_roster()

        site = read_site(scn["site"]["id"])
        assert site["federal_loss_count"] == 2
        assert site["state_loss_count"] == 4
        assert site["warn_trigger_status"] == "MASS_LAYOFF"
        assert site["required_notice_days"] == 90


class TestParallelGovernanceAndComplianceAxes:
    """approval_status and warn_status advance on entirely different triggers."""

    def test_warn_axis_reaches_threshold_pending_while_governance_is_still_draft(
        self, api
    ):
        """PRD 3.1: "Neither axis constrains the other's position: a plan may
        reach `APPROVED` while still sitting at `NOT_ASSESSED`, and it may sit at
        `THRESHOLD_PENDING` while its governance axis is still `DRAFT`."
        PRD 3.3: "The third hop fires when that recomputation moves the site's
        `warn_trigger_status` away from `NONE`: every reduction plan that holds a
        selected selection at that site advances its `warn_status` from
        `NOT_ASSESSED` to `THRESHOLD_PENDING` and re-derives its own
        `required_notice_days` and `notice_deadline_utc`."

        Design: Difficulty/non_linear_state_machine/reduction_plan_parallel_governance_and_warn_axes_advance_independently
        """
        scn = setup_ny_triggered_scenario()

        stage1 = read_plan(scn["plan"]["id"])
        assert stage1["approval_status"] == "DRAFT"
        assert stage1["warn_status"] == "THRESHOLD_PENDING"

        run_and_clear_analysis(
            scn["plan"]["id"],
            justification="Both roles eliminated; retained population documented.",
        )
        submit_for_review(scn["plan"]["id"])
        stage2 = render_legal_decision(scn["plan"]["id"], "APPROVE")

        assert stage2["approval_status"] == "APPROVED"
        assert stage2["warn_status"] == "THRESHOLD_PENDING", (
            "approving the plan must not move the compliance axis"
        )

    def test_issuing_the_notice_moves_only_the_compliance_axis(self, api):
        """PRD 3.4: "It advances the plan's `warn_status` from
        `THRESHOLD_PENDING` to `NOTICES_ISSUED`, but only once every site of the
        plan's selected selections whose `warn_trigger_status` is other than
        `NONE` now carries an issued notice for that plan-and-site pair."
        PRD 3.4: "A plan's `required_notice_days` is the largest
        `required_notice_days` among the distinct sites of that plan's selections
        in `SELECTED` or `SEPARATED` status, and is 0 when no site of the plan is
        triggered. Its `notice_deadline_utc` is the plan's
        `earliest_separation_date` taken at midnight UTC, less that many days; it
        is null whenever `required_notice_days` is 0 or
        `earliest_separation_date` is null."

        Design: Difficulty/non_linear_state_machine/reduction_plan_parallel_governance_and_warn_axes_advance_independently
        """
        scn = setup_ny_triggered_scenario()
        run_and_clear_analysis(
            scn["plan"]["id"],
            justification="Both roles eliminated; retained population documented.",
        )
        submit_for_review(scn["plan"]["id"])
        render_legal_decision(scn["plan"]["id"], "APPROVE")

        notice = draft_warn_notice(
            scn["plan"]["id"], scn["site"]["id"], "STATE", NY_NOTICE_CONTENT
        )
        issued = issue_warn_notice(notice["id"])
        assert issued["status"] == "ISSUED"

        stage3 = read_plan(scn["plan"]["id"])
        assert stage3["approval_status"] == "APPROVED", (
            "issuing a notice must not move the governance axis"
        )
        assert stage3["warn_status"] == "NOTICES_ISSUED"
        assert stage3["required_notice_days"] == 90
        assert stage3["notice_deadline_utc"] == "2026-09-02T00:00:00.000Z"
        assert stage3["selected_count"] == 2
        assert read_site(scn["site"]["id"])["warn_trigger_status"] == "MASS_LAYOFF"


class TestSelectDecisionCascadeDepth:
    """One decide runs employee, then site, then plan, then paperwork."""

    def test_first_two_hops_move_the_employee_and_the_site_counters(self, api):
        """PRD 3.3: "The first hop moves the employee from `ACTIVE` to
        `PENDING_SEPARATION` and copies the selection's
        `proposed_separation_date` onto the employee's `separation_date`. The
        second hop, triggered by that employee's status change, recomputes the
        employee's site: `active_headcount` falls by one,
        `pending_separation_count` rises by one, and `window_start_date`,
        `federal_loss_count`, `state_loss_count`, `required_notice_days` and
        `warn_trigger_status` are all re-derived."

        Design: Difficulty/transitive_cascade/select_decision_chains_employee_then_site_then_plan_then_disclosure
        """
        scn = setup_ny_single_selection_with_paperwork()
        assert scn["disclosure"]["snapshot_selected_count"] == 1

        decided = decide(scn["sel_carla"], "SELECT")
        assert decided["status"] == "SELECTED"

        carla = read_employee(scn["employees"][2]["id"])
        assert carla["employment_status"] == "PENDING_SEPARATION"
        assert carla["separation_date"] == "2026-12-01"

        site = read_site(scn["site"]["id"])
        assert site["pending_separation_count"] == 2
        assert site["active_headcount"] == 1
        assert site["state_loss_count"] == 2
        assert site["federal_loss_count"] == 2
        assert site["warn_trigger_status"] == "MASS_LAYOFF"
        assert site["required_notice_days"] == 90

    def test_third_and_fourth_hops_reach_the_plan_and_its_paperwork(self, api):
        """PRD 3.3: "The third hop fires when that recomputation moves the site's
        `warn_trigger_status` away from `NONE`: every reduction plan that holds a
        selected selection at that site advances its `warn_status` from
        `NOT_ASSESSED` to `THRESHOLD_PENDING` and re-derives its own
        `required_notice_days` and `notice_deadline_utc`."
        PRD 3.3: "The fourth hop propagates the change in the plan's selection
        set into its compliance paperwork: every OWBPA disclosure of the plan in
        status `ATTACHED` whose `snapshot_selected_count` or `snapshot_pool_count`
        no longer matches the plan's current counts becomes `STALE`, and every
        adverse-impact analysis of the plan in status `CLEARED` becomes `STALE`."

        Design: Difficulty/transitive_cascade/select_decision_chains_employee_then_site_then_plan_then_disclosure
        """
        scn = setup_ny_single_selection_with_paperwork()

        decide(scn["sel_carla"], "SELECT")

        plan = read_plan(scn["plan"]["id"])
        assert plan["warn_status"] == "THRESHOLD_PENDING"
        assert plan["required_notice_days"] == 90
        assert plan["notice_deadline_utc"] == "2026-09-02T00:00:00.000Z"
        assert plan["selected_count"] == 2

        assert read_analysis(scn["analysis"]["id"])["status"] == "STALE"
        assert read_disclosure(scn["disclosure"]["id"])["status"] == "STALE"


class TestPercentTestBoundary:
    """The percent test compares >= against the already-rounded loss_percent."""

    def test_one_loss_of_four_falls_below_the_fifty_percent_line(self, api):
        """PRD 3.4: "Otherwise `loss_percent` is 100 multiplied by the loss count
        and divided by the workforce count, rounded half up to two decimal
        places."
        PRD 3.4: "The percent test passes when the rule's `min_percent` is 0, or
        when `loss_percent` is at least `min_percent`."

        Design: Difficulty/boundary_precision_check/state_warn_percent_test_is_inclusive_at_exactly_min_percent
        """
        scn = setup_tx_percent_boundary_scenario()

        notice = validate_success(
            api.create_warn_notice(
                warn_notice_payload(
                    scn["plan"]["id"], scn["site"]["id"], "STATE", TX_NOTICE_CONTENT
                ),
                COUNSEL,
            ),
            201,
        )
        assert notice["employment_loss_count"] == 1
        assert notice["workforce_count"] == 4
        assert notice["loss_percent"] == 25.00
        assert notice["threshold_met"] is False
        assert notice["trigger_type"] == "NONE"

    def test_two_losses_of_four_land_exactly_on_the_line_and_pass(self, api):
        """PRD 3.4: "The percent test passes when the rule's `min_percent` is 0,
        or when `loss_percent` is at least `min_percent`."
        PRD 3.4: "Three tests then run against the rounded percentage and the
        raw counts."

        Design: Difficulty/boundary_precision_check/state_warn_percent_test_is_inclusive_at_exactly_min_percent
        """
        scn = setup_tx_percent_boundary_scenario()
        decide(scn["sel_ben"], "SELECT")

        notice = validate_success(
            api.create_warn_notice(
                warn_notice_payload(
                    scn["plan"]["id"], scn["site"]["id"], "STATE", TX_NOTICE_CONTENT
                ),
                COUNSEL,
            ),
            201,
        )
        assert notice["employment_loss_count"] == 2
        assert notice["workforce_count"] == 4
        assert notice["loss_percent"] == 50.00
        assert notice["threshold_met"] is True
        assert notice["trigger_type"] == "MASS_LAYOFF"
        assert notice["window_end_date"] == "2027-01-30"
        assert read_site(scn["site"]["id"])["warn_trigger_status"] == "MASS_LAYOFF"


class TestFrozenAggregationWindow:
    """An issued STATE notice freezes a closed interval with no buffer."""

    def test_a_separation_on_the_closed_window_end_collides(self, api):
        """PRD 3.4: "from that moment, a later proposal whose
        `proposed_separation_date` falls inside the notice's frozen interval — on
        or after `window_start_date` and strictly before `window_end_date` for a
        `FEDERAL` notice, or on or after `window_start_date` and on or before
        `window_end_date` for a `STATE` notice — is refused with
        `ERR_WARN_WINDOW_COLLISION`."

        Design: Difficulty/resource_temporal_overlap/warn_aggregation_window_on_site_is_closed_for_state_notices
        """
        scn = setup_ny_scenario_with_issued_state_notice()
        assert scn["notice"]["window_start_date"] == "2026-12-01"
        assert scn["notice"]["window_end_date"] == "2026-12-31"

        response = api.create_selection(
            create_selection_payload(
                scn["plan"]["id"],
                scn["employees"][1]["id"],
                proposed_separation_date="2026-12-31",
            ),
            LEAD,
        )
        validate_error(response, ApiErrorId.ERR_WARN_WINDOW_COLLISION.value)
        assert response.status_code == 409

    def test_a_separation_the_day_after_the_window_end_is_admitted(self, api):
        """PRD 3.4: "from that moment, a later proposal whose
        `proposed_separation_date` falls inside the notice's frozen interval — on
        or after `window_start_date` and strictly before `window_end_date` for a
        `FEDERAL` notice, or on or after `window_start_date` and on or before
        `window_end_date` for a `STATE` notice — is refused with
        `ERR_WARN_WINDOW_COLLISION`."
        PRD 3.3: "And a proposal whose `proposed_separation_date` falls inside
        the frozen aggregation window of an already-issued WARN notice for that
        person's site is refused with `ERR_WARN_WINDOW_COLLISION`"

        Design: Difficulty/resource_temporal_overlap/warn_aggregation_window_on_site_is_closed_for_state_notices
        """
        scn = setup_ny_scenario_with_issued_state_notice()

        admitted = validate_success(
            api.create_selection(
                create_selection_payload(
                    scn["plan"]["id"],
                    scn["employees"][1]["id"],
                    proposed_separation_date="2027-01-01",
                ),
                LEAD,
            ),
            201,
        )
        assert admitted["proposed_separation_date"] == "2027-01-01"
        assert admitted["status"] == "PROPOSED"

        rows, _meta = validate_paginated(
            api.list_selections(LEAD, params={"plan_id": scn["plan"]["id"]})
        )
        assert len(rows) == 3
        assert read_warn_notice(scn["notice"]["id"])["status"] == "ISSUED"


def test_second_statute_row_for_one_jurisdiction_and_state_is_refused(api):
    """PRD 3.4: "At most one row may exist per `jurisdiction` and `state_code`
    pair; a second attempt is refused with `ERR_WARN_RULE_ALREADY_EXISTS`."

    Design: Corner/errors/error_duplicate_warn_rule_for_one_jurisdiction_and_state
    """
    first = configure_ny_state_rule()

    response = api.create_warn_rule(
        ny_state_rule_payload(
            rule_code="NY-MINI-WARN-2027",
            min_loss_count=5,
            min_percent=10.0,
            absolute_count=0,
            notice_days=60,
            window_days=45,
            counts_part_time=False,
            min_service_days=90,
            required_content_codes=["EMPLOYER_NAME"],
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_WARN_RULE_ALREADY_EXISTS.value)
    assert response.status_code == 409

    assert validate_success(api.get_warn_rule(first["id"], COUNSEL))["rule_code"] == (
        "NY-MINI-WARN"
    )


def test_empty_federal_denominator_is_refused_rather_than_divided_by(api):
    """PRD 3.4: "If the denominator comes out at zero, an explicit notice request
    is refused with `ERR_WARN_WORKFORCE_EMPTY`, while a cascade recomputation
    instead treats `loss_percent` as 0 and lets the percent test evaluate false."
    PRD 3.4: "The denominator — `workforce_count` — counts the site's employees
    whose `employment_status` is `ACTIVE`, `PENDING_SEPARATION` or `SEPARATED`,
    whose `hire_date` is on or before the window start, and who are not excluded
    as part-time on the same `counts_part_time` test."

    Design: Corner/errors/error_warn_workforce_empty_when_the_federal_denominator_is_zero
    """
    configure_federal_rule()
    site = create_site(name="Austin Annex", state_code="TX")
    elena = hire(site["id"], ELENA)
    plan = create_locked_plan(
        name="Annex Reduction", decisional_unit_name="Austin Annex"
    )
    selection = propose(plan["id"], elena["id"])
    decide(selection["id"], "SELECT")

    response = api.create_warn_notice(
        warn_notice_payload(plan["id"], site["id"], "FEDERAL", FEDERAL_NOTICE_CONTENT),
        COUNSEL,
    )
    validate_error(response, ApiErrorId.ERR_WARN_WORKFORCE_EMPTY.value)
    assert response.status_code == 422

    assert read_employee(elena["id"])["is_part_time"] is True
    refreshed = read_site(site["id"])
    assert refreshed["federal_loss_count"] == 0
    assert refreshed["warn_trigger_status"] == "NONE"
    rows, _meta = validate_paginated(
        api.list_warn_notices(COUNSEL, params={"plan_id": plan["id"]})
    )
    assert rows == []


def test_notice_for_an_unconfigured_jurisdiction_is_refused(api):
    """PRD 3.4: "The applicable rule is the `FEDERAL` row for federal counting,
    and for state counting the `STATE` row whose `state_code` equals the site's
    `state_code`; when a cascade recomputation finds no such row, that
    jurisdiction simply contributes a loss count of 0 with the threshold unmet,
    whereas an explicit notice request naming a jurisdiction with no configured
    row is refused with `ERR_WARN_RULE_NOT_FOUND`."

    Design: Corner/errors/error_warn_rule_not_found_for_an_unconfigured_jurisdiction
    """
    configure_federal_rule()
    site = create_site(name="Austin Campus", state_code="TX")
    alice = hire(site["id"], ALICE)
    plan = create_locked_plan()
    selection = propose(plan["id"], alice["id"])
    decide(selection["id"], "SELECT")

    response = api.create_warn_notice(
        warn_notice_payload(plan["id"], site["id"], "STATE", TX_NOTICE_CONTENT), COUNSEL
    )
    validate_error(response, ApiErrorId.ERR_WARN_RULE_NOT_FOUND.value)
    assert response.status_code == 404
    assert read_site(site["id"])["state_loss_count"] == 0


def test_absolute_count_branch_triggers_where_count_and_percent_tests_fail(api):
    """PRD 3.4: "The absolute test passes when the rule's `absolute_count` is
    greater than 0 and the loss count is at least that `absolute_count`.
    `threshold_met` is true when both the count test and the percent test pass,
    or when the absolute test passes on its own."
    PRD 3.4: "The site's `required_notice_days` is the largest `notice_days`
    among the jurisdictions whose threshold is met for that site, and is 0 when
    `warn_trigger_status` is `NONE`."

    Design: Corner/cross_cutting_complexity_layers/absolute_count_test_triggers_even_when_the_percent_test_fails
    """
    from test_helpers import DAN, propose_batch, decide_many

    configure_rule(
        tx_state_rule_payload(
            min_loss_count=100, min_percent=90.00, absolute_count=2, notice_days=60
        )
    )
    site, employees = setup_site_with_roster((ALICE, BEN, CARLA, DAN), "TX")
    plan = create_locked_plan()
    batch = propose_batch(plan["id"], [employees[0]["id"], employees[2]["id"]])
    decide_many(plan["id"], batch["selection_ids"], "SELECT")

    notice = validate_success(
        api.create_warn_notice(
            warn_notice_payload(plan["id"], site["id"], "STATE", TX_NOTICE_CONTENT),
            COUNSEL,
        ),
        201,
    )
    assert notice["employment_loss_count"] == 2
    assert notice["workforce_count"] == 4
    assert notice["loss_percent"] == 50.00, "well short of the 90.00 percent test"
    assert notice["threshold_met"] is True, "the absolute test passes on its own"
    assert notice["trigger_type"] == "MASS_LAYOFF"
    assert notice["required_notice_days"] == 60

    refreshed = read_site(site["id"])
    assert refreshed["warn_trigger_status"] == "MASS_LAYOFF"
    assert refreshed["required_notice_days"] == 60


def test_rescission_voids_the_issued_notice_and_rewinds_the_compliance_axis(api):
    """PRD 3.4: "When a rescission recomputes a site back to a
    `warn_trigger_status` of `NONE`, every issued notice for that site moves
    `ISSUED → VOID`, its frozen aggregation window is released, and its
    `version` increments by 1."
    PRD 3.3: "Third, if that recomputation leaves no site of the plan with a
    `warn_trigger_status` other than `NONE`, the plan's `warn_status` returns
    from `THRESHOLD_PENDING` to `NOT_ASSESSED`, its `required_notice_days` resets
    to 0 and its `notice_deadline_utc` resets to null."

    Design: Corner/cross_cutting_complexity_layers/rescission_cascade_voids_the_issued_warn_notice
    """
    scn = setup_ny_scenario_with_issued_state_notice()
    assert scn["notice"]["status"] == "ISSUED"
    carla_selection = scn["selection_by_index"][2]["id"]

    rescind(carla_selection, "Redeployed to a retained requisition.")

    assert read_warn_notice(scn["notice"]["id"])["status"] == "VOID"
    site = read_site(scn["site"]["id"])
    assert site["state_loss_count"] == 1
    assert site["warn_trigger_status"] == "NONE"
    assert site["required_notice_days"] == 0
    assert site["active_headcount"] == 2
    assert site["pending_separation_count"] == 1

    plan = read_plan(scn["plan"]["id"])
    # PRD 3.3 names only the THRESHOLD_PENDING -> NOT_ASSESSED rewind arc, and no
    # PRD sentence states an arc out of NOTICES_ISSUED other than to
    # NOTICE_PERIOD_SATISFIED, so the resting warn_status here is not uniquely
    # derivable from PRD; the plan-level derived WARN figures of PRD 3.4 are.
    assert plan["required_notice_days"] == 0
    assert plan["notice_deadline_utc"] is None
    assert read_employee(scn["employees"][2]["id"])["employment_status"] == "ACTIVE"


def test_execution_needs_an_issued_notice_whose_content_is_complete(api):
    """PRD 3.10: "And for every distinct site of those selections whose
    `warn_trigger_status` is other than `NONE`, an issued WARN notice must exist
    for that plan-and-site pair; a triggered site without one is refused with
    `ERR_WARN_NOTICE_REQUIRED`."
    PRD 3.4: "A notice whose content omits a required code is refused with
    `ERR_WARN_CONTENT_INCOMPLETE`, and issuing a notice that is not in `DRAFT` is
    refused with `ERR_INVALID_NOTICE_STATE`."
    PRD 3.10: "On the compliance axis, `warn_status` becomes
    `NOTICE_PERIOD_SATISFIED` in the same request, arriving there from
    `NOTICES_ISSUED` on a plan that had triggered sites, and directly from
    `NOT_ASSESSED` on a plan no site of which was ever triggered."

    Design: Corner/errors/error_warn_notice_required_then_content_incomplete_then_notice_reissue
    """
    from test_helpers import deliver_notice

    scn = setup_ny_triggered_scenario()
    plan_id = scn["plan"]["id"]
    run_and_clear_analysis(plan_id)
    submit_for_review(plan_id)
    render_legal_decision(plan_id, "APPROVE")
    deliver_notice(scn["selection_by_index"][0]["id"], "MANAGER_SCRIPT_UNION")
    deliver_notice(scn["selection_by_index"][2]["id"], "MANAGER_SCRIPT_UNION")

    blocked = api.execute_plan(plan_id, LEAD)
    validate_error(blocked, ApiErrorId.ERR_WARN_NOTICE_REQUIRED.value)
    assert blocked.status_code == 422

    thin = draft_warn_notice(
        plan_id, scn["site"]["id"], "STATE", ["EMPLOYER_NAME", "SITE_ADDRESS"]
    )
    incomplete = api.issue_warn_notice(thin["id"], COUNSEL)
    validate_error(incomplete, ApiErrorId.ERR_WARN_CONTENT_INCOMPLETE.value)
    assert incomplete.status_code == 422

    full = draft_warn_notice(plan_id, scn["site"]["id"], "STATE", NY_NOTICE_CONTENT)
    assert issue_warn_notice(full["id"])["status"] == "ISSUED"

    reissue = api.issue_warn_notice(full["id"], COUNSEL)
    validate_error(reissue, ApiErrorId.ERR_INVALID_NOTICE_STATE.value)
    assert reissue.status_code == 409

    executed = validate_success(api.execute_plan(plan_id, LEAD))
    assert executed["approval_status"] == "EXECUTED"
    assert executed["warn_status"] == "NOTICE_PERIOD_SATISFIED"
    assert read_warn_notice(thin["id"])["status"] == "DRAFT"
    assert read_site(scn["site"]["id"])["separated_count"] == 2

    restrictions, _meta = validate_paginated(
        api.list_position_restrictions(COUNSEL, params={"site_id": scn["site"]["id"]})
    )
    assert len(restrictions) == 2
