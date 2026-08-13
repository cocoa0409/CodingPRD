"""Visit execution lifecycle: state legality, timing gates, evidence
enforcement, terminal lockdown, batch auto-execution, and the
NO_ACCESS reschedule cycle."""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    api_client,
    create_batch, add_visit, get_batch, get_visit, get_plan,
    create_unit, create_asset,
    publish_batch, set_clock, start_visit, complete_visit, no_access_visit,
    record_evidence,
    setup_property_scaffold, setup_published_visit, setup_in_progress_visit,
    setup_completed_visit,
    make_technician_headers,
)

TEST_PM = TEST_USERS["property_manager_headers"]


class TestVisitStartFromScheduledInvalid:
    def test_start_from_scheduled_rejected(self, api):
        """PRD §3.4: "Starting is legal only from `NOTIFIED` — attempting to start
        a `SCHEDULED` visit fails with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/visit_start_from_scheduled_invalid
        """
        ctx = setup_property_scaffold()
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T18:00:00Z")
        visit = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                          ctx["asset"]["id"], ctx["plan"]["id"],
                          scheduled_start="2026-08-10T09:00:00Z")
        resp = api.start_visit(visit["id"], make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestStateBeatsTemporalOnEarlyStart:
    def _setup_scheduled_visit(self):
        ctx = setup_property_scaffold()
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-10T18:00:00Z")
        visit = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                          ctx["asset"]["id"], ctx["plan"]["id"],
                          scheduled_start="2026-08-10T09:00:00Z")
        return ctx, visit

    def test_state_error_reported_when_state_and_timing_both_fail(self, api):
        """PRD §2.6: "Stages are evaluated in the priority order below, and a
        failure at an earlier stage masks every later stage — the client always
        receives the error from the first failing stage." State legality (stage 5)
        precedes visit timing (stage 7); with the clock (2026-08-01) before
        scheduled_start (2026-08-10T09:00) and the visit still SCHEDULED, the
        reported error is the state error.
        PRD §3.4: "Starting is legal only from `NOTIFIED` — attempting to start a
        `SCHEDULED` visit fails with `ERR_INVALID_STATE`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_early_start
        """
        _ctx, visit = self._setup_scheduled_visit()
        resp = api.start_visit(visit["id"], make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_error_reported_even_when_timing_would_pass(self, api):
        """PRD §3.4: "Starting is legal only from `NOTIFIED` — attempting to start
        a `SCHEDULED` visit fails with `ERR_INVALID_STATE`". With the clock moved
        past scheduled_start (so no timing rule can fail), the state rule alone
        still rejects the start.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_early_start
        """
        _ctx, visit = self._setup_scheduled_visit()
        set_clock("2026-08-11T00:00:00Z")
        resp = api.start_visit(visit["id"], make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestNoticeLeadExactBoundary:
    """Occupied unit, notice_lead_hours=48. The batch is published at logical
    clock 2026-08-02T09:00, so notice_sent_at + 48h lands at 2026-08-04T09:00.
    The visit is scheduled at 2026-08-04T08:00 so the notice-lead check (not the
    too-early check) is the one under probe at 08:59 / 09:00."""

    def _setup(self):
        ctx = setup_property_scaffold(occupancy="OCCUPIED", notice_lead_hours=48)
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-04T08:00:00Z",
                             window_end="2026-08-04T18:00:00Z")
        visit = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                          ctx["asset"]["id"], ctx["plan"]["id"],
                          scheduled_start="2026-08-04T08:00:00Z")
        set_clock("2026-08-02T09:00:00Z")
        publish_batch(batch["id"])
        return ctx, visit

    def test_one_minute_before_lead_boundary_rejected(self, api):
        """PRD §3.4: "when the unit is `OCCUPIED`, the clock must also have reached
        the batch's `notice_sent_at` plus the property's `notice_lead_hours` — an
        arrival exactly at that instant is permitted — failing with
        `ERR_NOTICE_LEAD_VIOLATION`." At 2026-08-04T08:59 the clock is one minute
        short of notice_sent_at (2026-08-02T09:00) + 48h.

        Design: Difficulty/boundary_precision_check/notice_lead_exact_boundary_allowed
        """
        _ctx, visit = self._setup()
        set_clock("2026-08-04T08:59:00Z")
        resp = api.start_visit(visit["id"], make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_NOTICE_LEAD_VIOLATION)

    def test_exactly_at_lead_boundary_allowed(self, api):
        """PRD §3.4: "an arrival exactly at that instant is permitted". At
        2026-08-04T09:00 the clock equals notice_sent_at + 48h exactly.

        Design: Difficulty/boundary_precision_check/notice_lead_exact_boundary_allowed
        """
        _ctx, visit = self._setup()
        set_clock("2026-08-04T09:00:00Z")
        started = start_visit(visit["id"], technician_id="tech-1")
        assert started["visit_status"] == "IN_PROGRESS"


class TestEvidenceRequiredBlocksCompletion:
    def test_completion_requires_evidence_when_template_demands_it(self, api):
        """PRD §3.4: "If the visit's template has `requires_evidence` true and not
        a single evidence row exists for the visit, completion is rejected with
        `ERR_EVIDENCE_REQUIRED`."

        Design: Corner/validations/evidence_required_blocks_completion
        """
        ctx = setup_in_progress_visit(requires_evidence=True, estimated_labor_minutes=15,
                                      frequency_days=30)
        resp = api.complete_visit(
            ctx["visit"]["id"], {"actual_minutes": 15, "condition_score_recorded": 4},
            make_technician_headers("tech-1"),
        )
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_REQUIRED)

        record_evidence(ctx["visit"]["id"], technician_id="tech-1",
                        evidence_type="FILTER_REPLACEMENT", serial_or_lot="LOT-9")
        completed = complete_visit(ctx["visit"]["id"], 15, 4, technician_id="tech-1")
        assert completed["visit_status"] == "COMPLETED"


class TestCompletedVisitTerminalLockdown:
    def test_no_access_from_completed_rejected(self, api):
        """PRD §3.4: "they record a failed entry on a `NOTIFIED` visit" — a failed
        entry is declared only from `NOTIFIED`. PRD §2.6 (stage 5): "The target
        resource must be in a state from which the requested transition is
        declared (`ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/completed_visit_terminal_lockdown
        """
        ctx = setup_completed_visit(actual_minutes=30, condition_score=4)
        resp = api.no_access_visit(ctx["visit"]["id"], make_technician_headers("tech-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBatchAutoExecutesWhenAllVisitsTerminal:
    def test_batch_transitions_to_executed_after_last_visit_completes(self, api):
        """PRD §3.3: "the moment every non-`CANCELLED` visit in a `PUBLISHED` or
        `LOCKED` batch has reached a terminal state — `COMPLETED` or `NO_ACCESS` —
        the batch transitions itself to `EXECUTED`."

        Design: Corner/state_machines/batch_executes_automatically_when_all_visits_terminal
        """
        ctx = setup_in_progress_visit()
        complete_visit(ctx["visit"]["id"], 30, 4, technician_id="tech-1")
        batch = get_batch(ctx["batch"]["id"])
        assert batch["status"] == "EXECUTED", f"expected EXECUTED, got {batch['status']}"


class TestVisitNoAccessRescheduleCycle:
    """b1 published (window 2026-08-03) with the visit; the technician records a
    failed entry at 2026-08-03T09:00, releasing the committed estimate in full.
    b2 is a second batch with window 2026-08-10."""

    def _setup_no_access(self):
        ctx = setup_published_visit(
            occupancy="OCCUPIED", notice_lead_hours=24,
            window_start="2026-08-03T08:00:00Z", window_end="2026-08-03T18:00:00Z",
            scheduled_start="2026-08-03T09:00:00Z",
        )
        set_clock("2026-08-03T09:00:00Z")
        no_access_visit(ctx["visit"]["id"], technician_id="tech-1")
        batch2 = create_batch(ctx["property"]["id"], batch_label="b2",
                              window_start="2026-08-10T08:00:00Z",
                              window_end="2026-08-10T18:00:00Z")
        return ctx, batch2

    def test_reschedule_into_draft_batch_lands_scheduled(self, api):
        """PRD §3.4: "rescheduling into a `DRAFT` batch lands it in `SCHEDULED`,
        where it waits to commit at that batch's publish."

        Design: Difficulty/non_linear_state_machine/visit_no_access_reschedule_cycle
        """
        ctx, batch2 = self._setup_no_access()
        resp = api.reschedule_visit(
            ctx["visit"]["id"],
            {"target_batch_id": batch2["id"], "new_scheduled_start": "2026-08-10T09:00:00Z"},
            TEST_PM,
        )
        visit = validate_success(resp)
        assert visit["visit_status"] == "SCHEDULED"
        assert visit["batch_id"] == batch2["id"]

    def test_no_access_releases_commit_and_draft_target_commits_nothing(self, api):
        """PRD §3.4: "A failed entry charges nothing: the ledger releases the
        committed estimate in full." and "rescheduling into a `DRAFT` batch lands
        it in `SCHEDULED`, where it waits to commit at that batch's publish."

        Design: Difficulty/non_linear_state_machine/visit_no_access_reschedule_cycle
        """
        ctx, batch2 = self._setup_no_access()
        plan_after_no_access = get_plan(ctx["plan"]["id"])
        assert plan_after_no_access["committed_cents"] == 0, (
            f"no-access must release the estimate in full, committed={plan_after_no_access['committed_cents']}"
        )
        validate_success(api.reschedule_visit(
            ctx["visit"]["id"],
            {"target_batch_id": batch2["id"], "new_scheduled_start": "2026-08-10T09:00:00Z"},
            TEST_PM,
        ))
        plan_after_reschedule = get_plan(ctx["plan"]["id"])
        assert plan_after_reschedule["committed_cents"] == 0, (
            "a DRAFT target commits nothing until its own publish"
        )

    def test_reschedule_into_published_batch_lands_notified_and_recommits(self, api):
        """PRD §3.4: "rescheduling into a `PUBLISHED` batch lands the visit
        directly in `NOTIFIED` and immediately commits the estimated cost to the
        ledger".

        Design: Difficulty/non_linear_state_machine/visit_no_access_reschedule_cycle
        """
        ctx = setup_published_visit(
            occupancy="OCCUPIED", notice_lead_hours=24,
            window_start="2026-08-03T08:00:00Z", window_end="2026-08-03T18:00:00Z",
            scheduled_start="2026-08-03T09:00:00Z",
        )
        set_clock("2026-08-03T09:00:00Z")
        no_access_visit(ctx["visit"]["id"], technician_id="tech-1")
        # Published target batch with its own visit on a different unit (30-min
        # template at 6000 cents/h commits 3000 per visit).
        unit2 = create_unit(ctx["building"]["id"], unit_number="102", occupancy_status="VACANT")
        asset2 = create_asset(unit2["id"])
        batch2 = create_batch(ctx["property"]["id"], batch_label="b2",
                              window_start="2026-08-10T08:00:00Z",
                              window_end="2026-08-10T18:00:00Z")
        add_visit(batch2["id"], unit2["id"], ctx["template"]["id"], asset2["id"],
                  ctx["plan"]["id"], scheduled_start="2026-08-10T09:00:00Z")
        publish_batch(batch2["id"])

        resp = api.reschedule_visit(
            ctx["visit"]["id"],
            {"target_batch_id": batch2["id"], "new_scheduled_start": "2026-08-10T11:00:00Z"},
            TEST_PM,
        )
        visit = validate_success(resp)
        assert visit["visit_status"] == "NOTIFIED"
        assert visit["batch_id"] == batch2["id"]
        plan = get_plan(ctx["plan"]["id"])
        assert plan["committed_cents"] == 6000, (
            f"expected both 3000 estimates committed, got {plan['committed_cents']}"
        )
