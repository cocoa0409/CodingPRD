"""State-machine behaviour: initial states, legal loops, terminal lock-down and refused moves.

Each test walks one entity to a specific status and then exercises exactly one transition against
it — the fresh claim's opening state, the sponsor application's terminal statuses, the budget's
revision loop, the two branches a filed visit report can take, the season-close cascade over a
site's planned days, and the two transitions that are simply not defined from the status the entity
is sitting in.
"""

from test_helpers import (
    CLOCK_FIRST_WEEK_VISIT,
    CLOCK_JUNE_CLAIM_WINDOW,
    CLOCK_PROGRAM_INTAKE,
    ApiErrorId,
    assert_monitoring_visit,
    assert_site,
    assert_versioned_row,
    conduct_visit,
    create_approved_sponsor,
    create_area_record,
    create_budget,
    create_finalized_day,
    create_meal_claim_payload,
    create_open_day,
    create_planned_day,
    create_reported_visit,
    create_site,
    decide_budget,
    finding,
    list_actions_for_site,
    make_field_monitor_headers,
    make_site_supervisor_headers,
    make_sponsor_admin_headers,
    schedule_visit,
    set_clock,
    setup_program_baseline,
    sponsor_version,
    submit_budget,
    validate_error,
    validate_paginated,
    validate_success,
    visit_report_payload,
)

# The season close in this module runs on 2026-08-19, so the site's season is stretched past the
# 2026-08-20 day that the close is expected to void.
LATE_SEASON_SITE = {"operating_end_date": "2026-08-31"}
CLOCK_BEFORE_SEASON_CLOSE = "2026-08-19T08:00:00Z"

FIRST_MONITOR = "mon_1"
SECOND_MONITOR = "mon_2"
VISIT_DATE = "2026-06-10"


class TestMealClaimInitialState:
    """The status, revision counter and filing deadline a monthly claim opens with."""

    def test_new_meal_claim_opens_in_draft_with_revision_round_zero(self, api):
        """PRD §3.8: "A new claim opens in `status` `DRAFT` with `revision_round` at 0, and its `deadline_date` is fixed at creation as the last calendar day of the second month following `claim_month` — a claim for June 2026 is therefore due by 31 August 2026 — which is the 60-day filing window the program allows."

        Design: Corner/state_machines/new_meal_claim_starts_in_draft_initial_state
        """
        set_clock(CLOCK_PROGRAM_INTAKE)
        sponsor = create_approved_sponsor()
        set_clock(CLOCK_JUNE_CLAIM_WINDOW)
        sponsor_headers = make_sponsor_admin_headers(sponsor["id"])

        response = api.create_meal_claim(
            create_meal_claim_payload(sponsor["id"], sponsor_version(sponsor["id"]), "2026-06"),
            sponsor_headers,
        )

        claim = validate_success(response, 201)
        assert_versioned_row(claim)
        assert claim["status"] == "DRAFT", (
            f"a freshly opened claim must sit in DRAFT, got {claim['status']}"
        )
        assert claim["revision_round"] == 0, (
            f"a freshly opened claim must carry revision_round 0, got {claim['revision_round']}"
        )
        assert claim["version"] == 1, (
            f"a newly created row's version begins at 1, got {claim['version']}"
        )
        assert claim["deadline_date"] == "2026-08-31", (
            "a June 2026 claim is due by the last day of the second month following its "
            f"claim_month, so deadline_date must be 2026-08-31, got {claim['deadline_date']}"
        )
        assert claim["created_at"].startswith("2026-07-06T09:00:00"), (
            "created_at is stamped from the logical clock, which reads 2026-07-06T09:00:00Z, got "
            f"{claim['created_at']}"
        )

        _, meta = validate_paginated(
            api.list_claim_line_items(sponsor_headers, params={"meal_claim_id": claim["id"]})
        )
        assert meta["total_count"] == 0, (
            f"a claim opened with no line items must have none, got {meta['total_count']}"
        )


class TestSponsorApplicationStateLegality:
    """The sponsor application axis: submit is defined only from DRAFT and TERMINATED is terminal."""

    def test_application_submit_from_an_approved_sponsor_is_rejected(self, api):
        """PRD §3.1: "Only a `SponsorAdmin` acting for that sponsor may do so, and only from `DRAFT`; a submission attempted from any other status is rejected with `ERR_SPONSOR_STATE_INVALID`."

        Design: Corner/state_machines/sponsor_application_submit_from_approved_rejected
        """
        set_clock(CLOCK_PROGRAM_INTAKE)
        sponsor = create_approved_sponsor()
        sponsor_headers = make_sponsor_admin_headers(sponsor["id"])
        version_before = sponsor["version"]

        response = api.submit_sponsor_application(sponsor["id"], sponsor_headers)

        validate_error(response, ApiErrorId.ERR_SPONSOR_STATE_INVALID.value)

        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], sponsor_headers))
        assert sponsor_after["application_status"] == "APPROVED", (
            "the refused submission must leave the application in APPROVED, got "
            f"{sponsor_after['application_status']}"
        )
        assert sponsor_after["version"] == version_before, (
            "version increments only on a mutation, so a refused submission must leave it at "
            f"{version_before}, got {sponsor_after['version']}"
        )

    def test_terminated_sponsor_rejects_a_further_application_decision(self, api, reviewer_headers):
        """PRD §3.1: "`DENIED` and `TERMINATED` are terminal — no further application transition is possible from either."

        Design: Corner/state_machines/terminated_sponsor_cannot_be_decided_again_terminal_lockdown
        """
        set_clock(CLOCK_PROGRAM_INTAKE)
        sponsor = create_approved_sponsor()
        area_record = create_area_record()
        site = create_site(sponsor["id"], area_record["id"])
        terminated = validate_success(
            api.decide_sponsor_application(
                sponsor["id"],
                {"decision": "TERMINATED", "reason": "Sponsor withdrew from the program."},
                reviewer_headers,
            )
        )
        assert terminated["application_status"] == "TERMINATED", (
            f"the termination decision must land in TERMINATED, got {terminated['application_status']}"
        )

        response = api.decide_sponsor_application(
            sponsor["id"], {"decision": "APPROVED"}, reviewer_headers
        )

        validate_error(response, ApiErrorId.ERR_SPONSOR_STATE_INVALID.value)

        sponsor_after = validate_success(api.get_sponsor(sponsor["id"], reviewer_headers))
        assert sponsor_after["application_status"] == "TERMINATED", (
            "TERMINATED is terminal, so the refused decision must leave it in place, got "
            f"{sponsor_after['application_status']}"
        )

        # The termination cascade denies the sponsor's pending site, stamps SPONSOR_TERMINATED and
        # raises the site's claim hold; the refused second decision must not disturb any of that.
        site_after = validate_success(api.get_site(site["id"], reviewer_headers))
        assert_site(site_after)
        assert site_after["approval_status"] == "DENIED", (
            "the site the termination denied must stay DENIED, got "
            f"{site_after['approval_status']}"
        )
        assert site_after["suspension_reason"] == "SPONSOR_TERMINATED", (
            "the termination cascade stamps the literal SPONSOR_TERMINATED, got "
            f"{site_after['suspension_reason']}"
        )
        assert site_after["claim_hold"] is True, (
            f"the termination cascade raises claim_hold, got {site_after['claim_hold']}"
        )


class TestBudgetRevisionLoop:
    """Re-submitting a REVISION_REQUESTED budget returns it to SUBMITTED and counts the round."""

    def _revision_requested_budget(self, sponsor_id: str) -> dict:
        budget = create_budget(sponsor_id)
        submit_budget(budget)
        return decide_budget(
            budget["id"],
            decision="REVISION_REQUESTED",
            reason="Split the food and labour lines before we approve a ceiling.",
        )

    def test_resubmitting_a_revision_requested_budget_returns_to_submitted(self, api):
        """PRD §3.2: "From `REVISION_REQUESTED` it moves the budget back to `SUBMITTED`, increments `revision_round` by 1, and clears `decision_reason` to null — this is the revision loop, and it can run any number of times."

        Design: Corner/state_machines/budget_revision_loop_returns_to_submitted_and_increments_round
        """
        set_clock(CLOCK_PROGRAM_INTAKE)
        sponsor = create_approved_sponsor()
        budget = self._revision_requested_budget(sponsor["id"])
        assert budget["status"] == "REVISION_REQUESTED", (
            f"the revision request must land in REVISION_REQUESTED, got {budget['status']}"
        )

        response = api.submit_sponsor_budget(
            budget["id"], make_sponsor_admin_headers(sponsor["id"])
        )

        resubmitted = validate_success(response, 200)
        assert resubmitted["status"] == "SUBMITTED", (
            f"the revision loop returns the budget to SUBMITTED, got {resubmitted['status']}"
        )
        assert resubmitted["revision_round"] == 1, (
            "the first pass through the revision loop increments revision_round to 1, got "
            f"{resubmitted['revision_round']}"
        )
        assert resubmitted["decision_reason"] is None, (
            "the re-submit clears decision_reason to null, got "
            f"{resubmitted['decision_reason']!r}"
        )
        assert resubmitted["version"] == 4, (
            "the budget was created, submitted, decided and re-submitted, so its version must be "
            f"4, got {resubmitted['version']}"
        )
        assert resubmitted["approved_operating_cost_cents"] is None, (
            "ceilings are written only by an approval, and this budget was never approved, got "
            f"{resubmitted['approved_operating_cost_cents']!r}"
        )
        assert resubmitted["approved_admin_cost_cents"] is None, (
            "ceilings are written only by an approval, and this budget was never approved, got "
            f"{resubmitted['approved_admin_cost_cents']!r}"
        )

    def test_second_pass_through_the_revision_loop_reaches_round_two(self, api):
        """PRD §3.2: "From `REVISION_REQUESTED` it moves the budget back to `SUBMITTED`, increments `revision_round` by 1, and clears `decision_reason` to null — this is the revision loop, and it can run any number of times."

        Design: Corner/state_machines/budget_revision_loop_returns_to_submitted_and_increments_round
        """
        set_clock(CLOCK_PROGRAM_INTAKE)
        sponsor = create_approved_sponsor()
        sponsor_headers = make_sponsor_admin_headers(sponsor["id"])
        budget = self._revision_requested_budget(sponsor["id"])
        first_pass = validate_success(
            api.submit_sponsor_budget(budget["id"], sponsor_headers), 200
        )
        assert first_pass["revision_round"] == 1, (
            f"the first pass must reach revision_round 1, got {first_pass['revision_round']}"
        )
        decide_budget(
            budget["id"],
            decision="REVISION_REQUESTED",
            reason="The administrative line still needs itemising.",
        )

        response = api.submit_sponsor_budget(budget["id"], sponsor_headers)

        second_pass = validate_success(response, 200)
        assert second_pass["status"] == "SUBMITTED", (
            f"the loop may run any number of times, so status returns to SUBMITTED, got {second_pass['status']}"
        )
        assert second_pass["revision_round"] == 2, (
            "the second pass through the revision loop increments revision_round to 2, got "
            f"{second_pass['revision_round']}"
        )
        assert second_pass["decision_reason"] is None, (
            "every re-submit clears decision_reason to null, got "
            f"{second_pass['decision_reason']!r}"
        )


class TestVisitReportBranches:
    """Filing a report either closes the visit outright or parks it until its action closes."""

    def test_report_with_no_findings_closes_the_visit_and_opens_no_action(
        self, api, reviewer_headers
    ):
        """PRD §3.7: "On the **no-deficiency branch**, `findings` arrives empty: the visit stores that empty array, sets `highest_severity` to `NONE`, moves straight from `CONDUCTED` to `CLOSED`, and creates no corrective action whatsoever."

        Design: Corner/state_machines/visit_report_with_no_findings_closes_visit_and_opens_no_actions
        """
        scenario = setup_program_baseline(include_budget=False)
        visit = schedule_visit(
            scenario["site"]["id"], monitor_user_id=FIRST_MONITOR, scheduled_date=VISIT_DATE
        )
        set_clock(CLOCK_FIRST_WEEK_VISIT)
        conduct_visit(visit)

        response = api.report_monitoring_visit(
            visit["id"], visit_report_payload([]), make_field_monitor_headers(FIRST_MONITOR)
        )

        reported = validate_success(response, 200)
        assert_monitoring_visit(reported)
        assert reported["status"] == "CLOSED", (
            "an empty findings array moves the visit straight from CONDUCTED to CLOSED, got "
            f"{reported['status']}"
        )
        assert reported["highest_severity"] == "NONE", (
            f"the no-deficiency branch sets highest_severity to NONE, got {reported['highest_severity']}"
        )
        assert reported["findings"] == [], (
            f"the visit stores the empty findings array it was given, got {reported['findings']!r}"
        )
        assert reported["conducted_at"].startswith("2026-06-10T09:00:00"), (
            "conducted_at is stamped from the logical clock at 2026-06-10T09:00:00Z, got "
            f"{reported['conducted_at']}"
        )

        actions, meta = validate_paginated(
            api.list_corrective_actions(
                reviewer_headers, params={"monitoring_visit_id": visit["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "the no-deficiency branch creates no corrective action whatsoever, got "
            f"{meta['total_count']}"
        )
        assert actions == [], f"no corrective action row may exist, got {actions!r}"

        site_after = validate_success(api.get_site(scenario["site"]["id"], reviewer_headers))
        assert site_after["approval_status"] == "APPROVED", (
            "with no corrective action created, nothing suspends the site, got "
            f"{site_after['approval_status']}"
        )
        assert site_after["claim_hold"] is False, (
            f"with no corrective action created, no claim hold is raised, got {site_after['claim_hold']}"
        )

    def test_report_filed_visit_closes_when_its_only_action_closes(self, api, reviewer_headers):
        """PRD §3.7: "And if every action sharing the same `monitoring_visit_id` is now `CLOSED`, the originating visit bubbles up on its own from `REPORT_FILED` to `CLOSED`."

        Design: Corner/state_machines/report_filed_visit_auto_closes_when_its_last_action_closes
        """
        scenario = setup_program_baseline(include_budget=False)
        site = scenario["site"]
        visit = create_reported_visit(
            site["id"],
            findings=[finding(finding_code="MEAL_PATTERN_INCOMPLETE", severity="MAJOR")],
            monitor_user_id=FIRST_MONITOR,
            scheduled_date=VISIT_DATE,
        )
        assert visit["status"] == "REPORT_FILED", (
            f"a MAJOR finding parks the visit in REPORT_FILED, got {visit['status']}"
        )
        actions = list_actions_for_site(site["id"])
        assert len(actions) == 1, (
            f"the deficiency branch opens exactly one corrective action, got {len(actions)}"
        )
        action = actions[0]
        validate_success(
            api.respond_corrective_action(
                action["id"],
                {"response_note": "Meal pattern retraining completed for all site staff."},
                make_sponsor_admin_headers(scenario["sponsor"]["id"]),
            ),
            200,
        )

        response = api.review_corrective_action(
            action["id"], {"decision": "CLOSED"}, make_field_monitor_headers(SECOND_MONITOR)
        )

        reviewed = validate_success(response, 200)
        assert reviewed["status"] == "CLOSED", (
            f"accepting the response moves the action to CLOSED, got {reviewed['status']}"
        )

        visit_after = validate_success(api.get_monitoring_visit(visit["id"], reviewer_headers))
        assert visit_after["status"] == "CLOSED", (
            "with its only action closed the visit bubbles up from REPORT_FILED to CLOSED without "
            f"any call against the visit, got {visit_after['status']}"
        )

        site_after = validate_success(api.get_site(site["id"], reviewer_headers))
        assert site_after["approval_status"] == "APPROVED", (
            "only a CRITICAL action suspends a site, so a MAJOR finding leaves it APPROVED, got "
            f"{site_after['approval_status']}"
        )


class TestSeasonCloseCascade:
    """Closing the operating axis voids the planned days still ahead of the logical clock."""

    def test_closing_the_season_voids_the_future_planned_day_only(self, api, reviewer_headers):
        """PRD §3.5: "Moving from `OPERATING` to `CLOSED_FOR_SEASON` requires that no service day of the site is currently in `OPEN` — an unclosed day blocks the season close and is reported as `ERR_DAY_HAS_OPEN_SERVICE` — and it voids every remaining `PLANNED` day whose `service_date` is on or after the current logical clock date, with `void_reason` set to the literal string `SEASON_CLOSED` and `voided_day_count` incremented per voided day."

        Design: Corner/state_machines/closing_site_for_season_voids_only_planned_days
        """
        scenario = setup_program_baseline(include_budget=False, site_overrides=dict(LATE_SEASON_SITE))
        site = scenario["site"]
        finalized_day = create_finalized_day(site["id"], scenario["sponsor"]["id"], "2026-06-08")
        set_clock(CLOCK_BEFORE_SEASON_CLOSE)
        future_day = create_planned_day(site["id"], "2026-08-20")

        response = api.set_site_operating_status(
            site["id"], {"to_status": "CLOSED_FOR_SEASON"}, scenario["sponsor_headers"]
        )

        closed = validate_success(response, 200)
        assert_site(closed)
        assert closed["operating_status"] == "CLOSED_FOR_SEASON", (
            f"the operating axis must land in CLOSED_FOR_SEASON, got {closed['operating_status']}"
        )
        assert closed["approval_status"] == "APPROVED", (
            "closing the season leaves the approval axis untouched, so the site is still APPROVED, "
            f"got {closed['approval_status']}"
        )
        assert closed["voided_day_count"] == 1, (
            "exactly one planned day sat on or after the clock date, so voided_day_count must be "
            f"1, got {closed['voided_day_count']}"
        )

        future_after = validate_success(
            api.get_meal_service_day(future_day["id"], reviewer_headers)
        )
        assert future_after["status"] == "VOIDED", (
            "the 2026-08-20 planned day is on or after the 2026-08-19 clock date, so it is voided, "
            f"got {future_after['status']}"
        )
        assert future_after["void_reason"] == "SEASON_CLOSED", (
            f"the season-close cascade stamps the literal SEASON_CLOSED, got {future_after['void_reason']!r}"
        )

        finalized_after = validate_success(
            api.get_meal_service_day(finalized_day["id"], reviewer_headers)
        )
        assert finalized_after["status"] == "FINALIZED", (
            "the day already finalized remains fully claimable, so it stays FINALIZED, got "
            f"{finalized_after['status']}"
        )
        assert finalized_after["void_reason"] is None, (
            f"a day the cascade never touched carries no void_reason, got {finalized_after['void_reason']!r}"
        )

    def test_closing_the_season_leaves_a_past_planned_day_untouched(self, api, reviewer_headers):
        """PRD §3.1: "The denial cascade is the one cascade that voids planned days irrespective of their `service_date`: a planned day already in the past is voided along with the rest, which is not true of the suspension and season-close cascades described in §3.5."

        Design: Corner/state_machines/closing_site_for_season_voids_only_planned_days
        """
        scenario = setup_program_baseline(include_budget=False, site_overrides=dict(LATE_SEASON_SITE))
        site = scenario["site"]
        past_day = create_planned_day(site["id"], "2026-06-15")
        set_clock(CLOCK_BEFORE_SEASON_CLOSE)
        future_day = create_planned_day(site["id"], "2026-08-20")

        response = api.set_site_operating_status(
            site["id"], {"to_status": "CLOSED_FOR_SEASON"}, scenario["sponsor_headers"]
        )

        closed = validate_success(response, 200)
        assert closed["operating_status"] == "CLOSED_FOR_SEASON", (
            f"the operating axis must land in CLOSED_FOR_SEASON, got {closed['operating_status']}"
        )
        assert closed["voided_day_count"] == 1, (
            "only the day on or after the 2026-08-19 clock date is voided, so voided_day_count "
            f"must be 1, got {closed['voided_day_count']}"
        )

        past_after = validate_success(api.get_meal_service_day(past_day["id"], reviewer_headers))
        assert past_after["status"] == "PLANNED", (
            "the season-close cascade never reaches a planned day already in the past, so the "
            f"2026-06-15 day stays PLANNED, got {past_after['status']}"
        )
        assert past_after["void_reason"] is None, (
            f"a day the cascade never touched carries no void_reason, got {past_after['void_reason']!r}"
        )

        future_after = validate_success(
            api.get_meal_service_day(future_day["id"], reviewer_headers)
        )
        assert future_after["status"] == "VOIDED", (
            f"the 2026-08-20 planned day is voided by the season close, got {future_after['status']}"
        )
        assert future_after["void_reason"] == "SEASON_CLOSED", (
            f"the season-close cascade stamps the literal SEASON_CLOSED, got {future_after['void_reason']!r}"
        )


class TestServiceDayOpenTransition:
    """Opening a day is defined only from PLANNED, so the same call twice is not idempotent."""

    def test_opening_an_already_open_service_day_is_rejected(self, api):
        """PRD §3.6: "The day must be in `PLANNED`, or the attempt reports `ERR_SERVICE_DAY_STATE_INVALID`."

        Design: Corner/state_machines/opening_an_already_open_service_day_rejected
        """
        scenario = setup_program_baseline(include_budget=False)
        site = scenario["site"]
        supervisor_headers = make_site_supervisor_headers(site["id"])
        day = create_open_day(
            site["id"], "2026-06-08",
            production_counts={"LUNCH": 150},
            food_received_at="2026-06-08T10:30:00Z",
        )
        assert day["status"] == "OPEN", (
            f"the setup day must already be OPEN before the second attempt, got {day['status']}"
        )

        response = api.open_meal_service_day(
            day["id"],
            {"production_counts": {"LUNCH": 200}, "food_received_at": "2026-06-08T11:00:00Z"},
            supervisor_headers,
        )

        validate_error(response, ApiErrorId.ERR_SERVICE_DAY_STATE_INVALID.value)

        day_after = validate_success(api.get_meal_service_day(day["id"], supervisor_headers))
        assert day_after["status"] == "OPEN", (
            f"the refused second open must leave the day in OPEN, got {day_after['status']}"
        )
        assert day_after["food_received_at"].startswith("2026-06-08T10:30:00"), (
            "a refused open must not overwrite the food_received_at the first open stored, got "
            f"{day_after['food_received_at']}"
        )
        assert day_after["production_counts"] == {"LUNCH": 150}, (
            "a refused open must not overwrite the production_counts the first open stored, got "
            f"{day_after['production_counts']!r}"
        )


class TestVisitCancellation:
    """Cancelling is defined only from SCHEDULED, so a conducted visit cannot be cancelled."""

    def test_cancelling_a_conducted_visit_is_rejected(self, api, reviewer_headers):
        """PRD §3.7: "A visit still `SCHEDULED` may instead be cancelled by its own monitor with a `reason` stored as `cancel_reason`, which moves `status` to `CANCELLED`."

        Design: Corner/state_machines/cancelling_a_conducted_visit_rejected
        """
        scenario = setup_program_baseline(include_budget=False)
        visit = schedule_visit(
            scenario["site"]["id"], monitor_user_id=FIRST_MONITOR, scheduled_date=VISIT_DATE
        )
        set_clock(CLOCK_FIRST_WEEK_VISIT)
        conducted = conduct_visit(visit)
        assert conducted["status"] == "CONDUCTED", (
            f"the setup visit must be CONDUCTED before the cancel attempt, got {conducted['status']}"
        )

        response = api.cancel_monitoring_visit(
            visit["id"],
            {"reason": "Monitor reassigned to another region."},
            make_field_monitor_headers(FIRST_MONITOR),
        )

        validate_error(response, ApiErrorId.ERR_VISIT_STATE_INVALID.value)

        visit_after = validate_success(api.get_monitoring_visit(visit["id"], reviewer_headers))
        assert visit_after["status"] == "CONDUCTED", (
            f"the refused cancel must leave the visit in CONDUCTED, got {visit_after['status']}"
        )
        assert visit_after["conducted_at"].startswith("2026-06-10T09:00:00"), (
            "the refused cancel must leave conducted_at intact at the 2026-06-10T09:00:00Z instant "
            f"it was stamped with, got {visit_after['conducted_at']}"
        )
        assert visit_after.get("cancel_reason") is None, (
            f"a visit that was never cancelled carries no cancel_reason, got {visit_after.get('cancel_reason')!r}"
        )
