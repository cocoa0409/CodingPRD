"""Escapes, incident axes, wildfire cascade, parcel monitoring gap, and report
lifecycle (PRD §3.2, §3.6–§3.8)."""
from test_helpers import (
    ANY_READER_HEADERS,
    TEST_USERS,
    ApiErrorId,
    assess_costs_payload,
    create_assignment_payload,
    create_burn_plan_payload,
    create_contractor_payload,
    create_incident_payload,
    ctx_add_agreement,
    ctx_add_contingency,
    ctx_add_execution,
    ctx_add_parcel,
    ctx_add_permit,
    ctx_add_plan,
    ctx_author,
    ctx_brief,
    ctx_complete_ignition,
    ctx_escape,
    ctx_go_no_go,
    ctx_ignite,
    ctx_landowner,
    ctx_patrol_mopup_close,
    ctx_reports,
    ctx_reviewer,
    ctx_set_burn_day,
    get_success_data,
    make_contractor_headers,
    reject_reason_payload,
    set_clock_payload,
    setup_approved_plan_ctx,
    setup_burn_ready_ctx,
    setup_closed_execution_ctx,
    setup_registry,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COMMANDER = TEST_USERS["commander_headers"]
BURN_DAY = "2026-05-12"


def _setup_wildfire_ready(api):
    """Burn-ready plan with an APPROVED agreement, driven to ESCAPED with the escape
    incident CONFIRMED — one call away from the wildfire declaration."""
    ctx = setup_burn_ready_ctx()
    ctx_add_agreement(ctx, tier="STANDARD",
                      lines=[{"category": "BROADCAST", "rate_class": "GRASS", "acres": 100}])
    ctx_set_burn_day(ctx)
    ctx_brief(ctx)
    ctx_go_no_go(ctx)
    ctx_ignite(ctx)
    ctx_escape(ctx)
    get_success_data(api.confirm_incident(ctx["incident"]["id"], COMMANDER))
    return ctx


class TestWildfireCascade:
    def test_wildfire_declaration_moves_incident_and_execution(self, api):
        """PRD §3.7: "The gravest move converts a `CONFIRMED` incident to
        `DECLARED_WILDFIRE` — and that conversion cascades: the parent execution, waiting
        in `ESCAPED`, moves to `WILDFIRE_RESPONSE`"

        Design: Difficulty/transitive_cascade/wildfire_declaration_full_chain
        """
        ctx = _setup_wildfire_ready(api)
        incident = validate_success(
            api.declare_incident_wildfire(ctx["incident"]["id"], COMMANDER), 200)
        assert incident["response_status"] == "DECLARED_WILDFIRE"  # link A
        execution = validate_success(
            api.get_execution(ctx["execution"]["id"], ANY_READER_HEADERS), 200)
        assert execution["phase"] == "WILDFIRE_RESPONSE"  # link B, caused by link A

    def test_wildfire_declaration_suspends_permit_and_agreement(self, api):
        """PRD §3.7: "that move suspends the plan's `ISSUED` permit; and the permit's
        suspension suspends the plan's cost-share agreements in `APPROVED` or
        `PARTIALLY_DISBURSED`."

        Design: Difficulty/transitive_cascade/wildfire_declaration_full_chain
        """
        ctx = _setup_wildfire_ready(api)
        validate_success(api.declare_incident_wildfire(ctx["incident"]["id"], COMMANDER), 200)
        permit = validate_success(api.get_permit(ctx["permit"]["id"], ANY_READER_HEADERS), 200)
        assert permit["status"] == "SUSPENDED"  # link C, caused by the execution's move
        agreement = validate_success(
            api.get_cost_share_agreement(ctx["agreement"]["id"], ANY_READER_HEADERS), 200)
        assert agreement["status"] == "SUSPENDED"  # link D, caused by the permit's move


class TestIncidentParallelAxes:
    def test_incident_response_axis_advances_independently(self, api):
        """PRD §3.7: "Incident response runs on two independent axes."
        PRD §3.7: "On the billing axis, once an incident is `CONTAINED`, `CLOSED`, or
        `DECLARED_WILDFIRE` (`ERR_INCIDENT_NOT_COSTABLE` otherwise) and its billing is
        still `UNASSESSED` (`ERR_BILLING_NOT_UNASSESSED`), the commander assesses costs,
        recording `suppression_cost_cents` and `escaped_acres` and moving billing to
        `ASSESSED`."

        Design: Difficulty/non_linear_state_machine/incident_parallel_axes_independent
        """
        ctx = setup_burn_ready_ctx()
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        incident = ctx_escape(ctx)
        get_success_data(api.confirm_incident(incident["id"], COMMANDER))
        contained = validate_success(api.mark_incident_contained(incident["id"], COMMANDER), 200)
        assert contained["response_status"] == "CONTAINED"
        assert contained["billing_status"] == "UNASSESSED"  # response axis moved alone
        assessed = validate_success(api.assess_incident_costs(
            incident["id"], assess_costs_payload(), COMMANDER), 200)
        assert assessed["response_status"] == "CONTAINED"  # unchanged
        assert assessed["billing_status"] == "ASSESSED"    # billing axis moved alone

    def test_incident_billing_axis_advances_independently(self, api):
        """PRD §3.9: "the claim is born `FILED` with `outcome` `PENDING`, copies
        `total_suppression_cost_cents` from the incident, binds to it via `incident_id`,
        and the filing itself moves the incident's billing to `BILLED`."

        Design: Difficulty/non_linear_state_machine/incident_parallel_axes_independent
        """
        ctx = setup_burn_ready_ctx()
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        incident = ctx_escape(ctx)
        get_success_data(api.confirm_incident(incident["id"], COMMANDER))
        get_success_data(api.mark_incident_contained(incident["id"], COMMANDER))
        get_success_data(api.assess_incident_costs(incident["id"], assess_costs_payload(), COMMANDER))
        claim = validate_success(api.create_liability_claim(incident["id"], {}, COMMANDER), 201)
        assert claim["status"] == "FILED" and claim["outcome"] == "PENDING"
        after_claim = validate_success(api.get_incident(incident["id"], ANY_READER_HEADERS), 200)
        assert after_claim["response_status"] == "CONTAINED"
        assert after_claim["billing_status"] == "BILLED"  # claim creation moved billing only
        closed = validate_success(api.close_incident(incident["id"], COMMANDER), 200)
        assert closed["response_status"] == "CLOSED"
        assert closed["billing_status"] == "BILLED"  # response closes independent of billing


class TestPlanCancelCascade:
    def _setup_confirmed_order(self, api):
        """Approved plan; order SUBMITTED; ENGINE contractor (capacity 4) fully
        confirmed against the 4-engine requirement."""
        ctx = setup_approved_plan_ctx()
        contractor = get_success_data(api.create_contractor(
            create_contractor_payload(resource_type="ENGINE", capacity_units=4), ADMIN))
        order = get_success_data(api.create_resource_order(ctx["plan"]["id"], {}, ctx_author(ctx)))
        ctx["order"] = get_success_data(api.submit_resource_order(order["id"], ctx_author(ctx)))
        asg = get_success_data(api.create_assignment(
            ctx["order"]["id"], create_assignment_payload(contractor["id"], units=4),
            ctx_author(ctx)))
        ctx["assignment"] = get_success_data(api.confirm_assignment(
            asg["id"], make_contractor_headers(contractor["id"])))
        ctx["contractor"] = contractor
        return ctx

    def test_plan_cancel_cascades_order_and_assignment(self, api):
        """PRD §3.2: "Cancellation cascades downward: the plan's resource orders in
        `DRAFT`, `SUBMITTED`, or `PARTIALLY_FILLED` move to `CANCELLED`, their crew
        assignments in `ASSIGNED` or `CONFIRMED` move to `RELEASED` (restoring contractor
        availability)"

        Design: Difficulty/transitive_cascade/plan_cancel_releases_contractor_capacity
        """
        ctx = self._setup_confirmed_order(api)
        cancelled = validate_success(api.cancel_plan(ctx["plan"]["id"], ctx_author(ctx)), 200)
        assert cancelled["status"] == "CANCELLED"
        order = validate_success(api.get_resource_order(ctx["order"]["id"], ANY_READER_HEADERS), 200)
        assert order["status"] == "CANCELLED"  # link B, caused by the plan cancel
        assignments = validate_success(
            api.list_order_assignments(ctx["order"]["id"], ANY_READER_HEADERS), 200)
        assert assignments[0]["status"] == "RELEASED"  # link C, caused by the order cancel

    def test_plan_cancel_restores_contractor_availability(self, api):
        """PRD §3.2: "their crew assignments in `ASSIGNED` or `CONFIRMED` move to
        `RELEASED` (restoring contractor availability)"
        PRD §3.5: "The availability invariant is compensating throughout: an assignment
        followed by a release, decline, no-show, or completion restores `available_units`
        to exactly its prior value."

        Design: Difficulty/transitive_cascade/plan_cancel_releases_contractor_capacity
        """
        ctx = self._setup_confirmed_order(api)
        before = validate_success(
            api.get_contractor(ctx["contractor"]["id"], ANY_READER_HEADERS), 200)
        assert before["available_units"] == 0  # 4 capacity - 4 confirmed
        validate_success(api.cancel_plan(ctx["plan"]["id"], ctx_author(ctx)), 200)
        after = validate_success(
            api.get_contractor(ctx["contractor"]["id"], ANY_READER_HEADERS), 200)
        assert after["available_units"] == 4  # capacity exactly restored by the cascade


class TestSuccessorSupersession:
    def _setup_superseding_plan(self, api):
        """plan1 APPROVED with ISSUED permit and APPROVED agreement; plan2 drafted with
        supersedes_plan_id=plan1 and SUBMITTED."""
        ctx = setup_approved_plan_ctx()
        ctx_add_contingency(ctx)
        ctx_add_permit(ctx, notifications_required=1)
        ctx_add_agreement(ctx, tier="STANDARD",
                          lines=[{"category": "BROADCAST", "rate_class": "GRASS", "acres": 100}])
        parcel = validate_success(api.get_parcel(ctx["parcel"]["id"], ANY_READER_HEADERS), 200)
        plan2 = validate_success(api.create_burn_plan(
            create_burn_plan_payload(
                parcel["id"], parcel["version"],
                supersedes_plan_id=ctx["plan"]["id"], planned_acres=90,
                planned_window_start="2026-05-11", planned_window_end="2026-05-21",
                max_wind_mph=14, min_fuel_moisture_pct=9, max_fuel_moisture_pct=19,
                min_rh_pct=26, min_temp_f=41, max_temp_f=84, min_mixing_height_ft=1600,
                treatment_lines=[{"category": "BROADCAST", "rate_class": "GRASS", "acres": 90}]),
            ctx_author(ctx)), 201)
        ctx["plan2"] = validate_success(api.submit_plan(plan2["id"], ctx_author(ctx)), 200)
        return ctx

    def test_successor_approval_supersedes_prior_plan(self, api):
        """PRD §3.2: "it fires the supersession cascade: if `supersedes_plan_id` is set
        and that prior plan is currently `APPROVED`, the prior plan moves to `SUPERSEDED`"

        Design: Difficulty/transitive_cascade/successor_approval_supersedes_prior_chain
        """
        ctx = self._setup_superseding_plan(api)
        approved2 = validate_success(api.approve_plan(ctx["plan2"]["id"], ctx_reviewer(ctx)), 200)
        assert approved2["status"] == "APPROVED"
        plan1 = validate_success(api.get_burn_plan(ctx["plan"]["id"], ANY_READER_HEADERS), 200)
        assert plan1["status"] == "SUPERSEDED"  # link B, caused by the approval

    def test_successor_approval_suspends_permit_and_agreement(self, api):
        """PRD §3.2: "the prior plan's `ISSUED` permit (if any) moves to `SUSPENDED`, and
        any cost-share agreement on the superseded plan sitting in `APPROVED` or
        `PARTIALLY_DISBURSED` moves to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/successor_approval_supersedes_prior_chain
        """
        ctx = self._setup_superseding_plan(api)
        validate_success(api.approve_plan(ctx["plan2"]["id"], ctx_reviewer(ctx)), 200)
        permit = validate_success(api.get_permit(ctx["permit"]["id"], ANY_READER_HEADERS), 200)
        assert permit["status"] == "SUSPENDED"  # link C, caused by plan1's supersession
        agreement = validate_success(
            api.get_cost_share_agreement(ctx["agreement"]["id"], ANY_READER_HEADERS), 200)
        assert agreement["status"] == "SUSPENDED"  # link D, caused by the permit suspension


class TestParcelMonitoringGap:
    def _setup_closed_then_successor_plan(self, api):
        """plan1 driven to CLOSED at 2026-05-12T07:30Z; plan2 (window 2026-06-01..30)
        approved as its superseding successor."""
        ctx = setup_closed_execution_ctx(acres_blackened=95)
        parcel = validate_success(api.get_parcel(ctx["parcel"]["id"], ANY_READER_HEADERS), 200)
        plan2 = validate_success(api.create_burn_plan(
            create_burn_plan_payload(
                parcel["id"], parcel["version"],
                supersedes_plan_id=ctx["plan"]["id"], planned_acres=50,
                planned_window_start="2026-06-01", planned_window_end="2026-06-30",
                treatment_lines=[{"category": "BROADCAST", "rate_class": "GRASS", "acres": 50}]),
            ctx_author(ctx)), 201)
        get_success_data(api.submit_plan(plan2["id"], ctx_author(ctx)))
        ctx["plan2"] = get_success_data(api.approve_plan(plan2["id"], ctx_reviewer(ctx)))
        return ctx

    def test_parcel_monitoring_gap_blocks_reschedule(self, api):
        """PRD §3.6: "when a prior execution on the parcel has closed, the new
        `scheduled_date` must fall strictly more than thirty days after that execution's
        `closed_at` — either violation is `ERR_PARCEL_EXECUTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/parcel_monitoring_gap_blocks_reschedule
        """
        ctx = self._setup_closed_then_successor_plan(api)
        # closed_at 2026-05-12T07:30Z + 30 days = 2026-06-11T07:30Z; 06-11 is within
        validate_error(api.create_execution(
            ctx["plan2"]["id"], {"scheduled_date": "2026-06-11"}, ctx_author(ctx)),
            ApiErrorId.ERR_PARCEL_EXECUTION_WINDOW_CONFLICT)

    def test_parcel_monitoring_gap_allows_after_30_days(self, api):
        """PRD §3.6: "when a prior execution on the parcel has closed, the new
        `scheduled_date` must fall strictly more than thirty days after that execution's
        `closed_at`"
        PRD §3.6: "Scheduling pins `plan_version_at_schedule` to the plan's current
        `version` and opens the execution with its `phase` at `SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/parcel_monitoring_gap_blocks_reschedule
        """
        ctx = self._setup_closed_then_successor_plan(api)
        execution = validate_success(api.create_execution(
            ctx["plan2"]["id"], {"scheduled_date": "2026-06-12"}, ctx_author(ctx)), 201)
        assert execution["phase"] == "SCHEDULED"  # first day outside the gap


class TestIncidentsBlockProgression:
    def test_open_incident_blocks_patrol(self, api):
        """PRD §3.7: "Beginning patrol requires `HOLDING` (`ERR_EXECUTION_NOT_HOLDING`)
        and that no incident of the execution sits in `REPORTED` or `CONFIRMED`
        (`ERR_OPEN_INCIDENTS_EXIST`), moving to `PATROL`."
        PRD §3.7: "the `IncidentCommander` confirms a `REPORTED` incident
        (`ERR_INCIDENT_NOT_REPORTED`) to `CONFIRMED`, or dismisses it from `REPORTED` to
        `DISMISSED` as a false alarm."

        Design: Corner/state_machines/open_incident_blocks_patrol
        """
        ctx = setup_burn_ready_ctx()
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        ctx_complete_ignition(ctx, 50)  # HOLDING
        incident = validate_success(api.report_incident(
            ctx["execution"]["id"], create_incident_payload(incident_type="SPOT"),
            COMMANDER), 201)
        validate_error(api.begin_patrol(ctx["execution"]["id"], ctx_author(ctx)),
                       ApiErrorId.ERR_OPEN_INCIDENTS_EXIST)
        dismissed = validate_success(api.dismiss_incident(incident["id"], COMMANDER), 200)
        assert dismissed["response_status"] == "DISMISSED"
        patrol = validate_success(api.begin_patrol(ctx["execution"]["id"], ctx_author(ctx)), 200)
        assert patrol["phase"] == "PATROL"


class TestMonitoringReports:
    def test_clock_sweep_marks_first_report_overdue(self, api):
        """PRD §3.8: "Closing an execution creates three monitoring reports, one of each
        `report_type`: `FIRST_24H` due 24 hours after `closed_at`, `SEVEN_DAY` due 7 days
        after, and `THIRTY_DAY` due 30 days after, each born `DUE` with its `due_at` set
        accordingly. The clock sweep flips a `DUE` report whose `due_at` has passed to
        `OVERDUE` without a version bump."
        PRD §3.8: "An execution's reports list in `due_at` ascending order"

        Design: Corner/state_machines/clock_sweep_marks_first_report_overdue
        """
        ctx = setup_closed_execution_ctx(acres_blackened=80)  # closed 2026-05-12T07:30Z
        validate_success(api.set_clock(set_clock_payload("2026-05-14T00:00:00Z"), ADMIN), 200)
        reports = ctx_reports(ctx)
        assert [r["report_type"] for r in reports] == ["FIRST_24H", "SEVEN_DAY", "THIRTY_DAY"]
        assert reports[0]["status"] == "OVERDUE"   # due 2026-05-13T07:30Z < clock
        assert reports[1]["status"] == "DUE"       # due 2026-05-19T07:30Z not reached

    def test_monitoring_report_deficient_resubmit_cycle(self, api):
        """PRD §3.8: "The reviewer may instead mark a `SUBMITTED` report deficient,
        recording the supplied `reason` into `deficiency_reason` and moving it to
        `DEFICIENT`, from which the author may resubmit"
        PRD §3.8: "the score is one hundred times the actual weighted acreage divided by
        the planned weighted acreage, rounded half-up to an integer percent with no upper
        clamp."

        Design: Corner/state_machines/monitoring_report_deficient_resubmit_cycle
        """
        ctx = setup_burn_ready_ctx()
        ctx_add_agreement(ctx, tier="STANDARD", approve=False,
                          lines=[{"category": "BROADCAST", "rate_class": "GRASS", "acres": 100}])
        ctx_set_burn_day(ctx)
        ctx_brief(ctx)
        ctx_go_no_go(ctx)
        ctx_ignite(ctx)
        ctx_complete_ignition(ctx, 80)
        ctx_patrol_mopup_close(ctx, [{"category": "BROADCAST", "rate_class": "GRASS", "acres": 80}])
        thirty_day = ctx_reports(ctx)[2]
        submitted = validate_success(api.submit_monitoring_report(
            thirty_day["id"],
            {"actual_treatment_lines": [{"category": "BROADCAST", "rate_class": "GRASS", "acres": 80}]},
            ctx_author(ctx)), 200)
        assert submitted["status"] == "SUBMITTED" and submitted["effectiveness_score"] == 80
        deficient = validate_success(api.mark_report_deficient(
            thirty_day["id"], reject_reason_payload("unverifiable acres"), ctx_reviewer(ctx)), 200)
        assert deficient["status"] == "DEFICIENT"
        assert deficient["deficiency_reason"] == "unverifiable acres"
        resubmitted = validate_success(api.submit_monitoring_report(
            thirty_day["id"],
            {"actual_treatment_lines": [{"category": "BROADCAST", "rate_class": "GRASS", "acres": 90}]},
            ctx_author(ctx)), 200)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["effectiveness_score"] == 90  # recomputed on resubmission
        accepted = validate_success(api.accept_monitoring_report(
            thirty_day["id"], ctx_reviewer(ctx)), 200)
        assert accepted["status"] == "ACCEPTED"

    def test_reinstate_rejected_with_open_claims(self, api):
        """PRD §3.8: "Reinstatement by an `AssociationAdmin` requires a `SUSPENDED`
        agreement (`ERR_AGREEMENT_NOT_SUSPENDED`), every liability claim on incidents of
        the plan's executions resolved into `CLOSED`, `DISMISSED`, or `PAYMENT_REVERSED`
        (`ERR_CLAIMS_NOT_RESOLVED`), and the plan's permit back in `ISSUED`
        (`ERR_PERMIT_NOT_ISSUED`)"

        Design: Corner/errors/reinstate_rejected_with_open_claims
        """
        ctx = _setup_wildfire_ready(api)
        validate_success(api.declare_incident_wildfire(ctx["incident"]["id"], COMMANDER), 200)
        agreement = validate_success(
            api.get_cost_share_agreement(ctx["agreement"]["id"], ANY_READER_HEADERS), 200)
        assert agreement["status"] == "SUSPENDED"  # cascade-suspended
        # Assess the wildfire incident and file a claim, which stays FILED (unresolved)
        incident = validate_success(api.assess_incident_costs(
            ctx["incident"]["id"], assess_costs_payload(), COMMANDER), 200)
        claim = validate_success(api.create_liability_claim(incident["id"], {}, COMMANDER), 201)
        assert claim["status"] == "FILED"
        # Restore the permit so the claims gate is the only outstanding failure
        reinstated = validate_success(api.reinstate_permit(ctx["permit"]["id"], ctx_reviewer(ctx)), 200)
        assert reinstated["status"] == "ISSUED"
        validate_error(api.reinstate_agreement(agreement["id"], ADMIN),
                       ApiErrorId.ERR_CLAIMS_NOT_RESOLVED)
        after = validate_success(
            api.get_cost_share_agreement(agreement["id"], ANY_READER_HEADERS), 200)
        assert after["status"] == "SUSPENDED"
