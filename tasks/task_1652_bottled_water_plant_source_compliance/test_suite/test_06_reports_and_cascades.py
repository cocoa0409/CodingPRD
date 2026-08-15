"""Community water reports (rounding, locking, supersession), the test-FAIL
suspension cascade, the posture watch boundary, and conservation on void."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_permit_view_consistency,
    create_community_report_payload,
    create_permit,
    create_plant,
    create_source_raw_test,
    create_treatment_run,
    create_withdrawal_event_payload,
    get_success_data,
    post_withdrawal_event,
    run_compliance,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, SOURCE_MONITOR, COMPLIANCE_OFFICER, PL1, QA1,
)


class TestPerSourceRounding:
    def _july_backfill(self, api):
        """Plant with SPRING permit A and WELL permit B; backfilled July
        events A=163088 gal and B=1 gal, finalized by a compliance run at the
        default clock (2026-08-01 is after both July dates)."""
        plant = create_plant("Plant CF2")
        perm_a = create_permit(
            plant["id"], permit_number="SP-CF2", source_classification="SPRING",
            daily_cap_gallons=200000, monthly_cap_gallons=5000000,
        )
        perm_b = create_permit(
            plant["id"], permit_number="WL-CF2", source_classification="WELL",
            daily_cap_gallons=200000, monthly_cap_gallons=5000000,
        )
        post_withdrawal_event(perm_a["id"], gallons=163088,
                              withdrawal_date="2026-07-10")
        post_withdrawal_event(perm_b["id"], gallons=1,
                              withdrawal_date="2026-07-11")
        summary = run_compliance(plant["id"])
        return plant, perm_a, perm_b, summary

    def test_community_report_per_source_rounding_totals(self, api):
        """PRD §3.9: "For each permit, the period's finalized gallons are
        summed exactly, then converted to acre-feet by dividing by 325,851
        gallons per acre-foot and rounding half-up to 3 decimal places. The
        report's `total_withdrawn_gallons` is the exact integer sum of the
        per-source gallons; its `total_acre_feet` is the sum of the
        already-rounded per-source acre-feet figures".

        Design: Difficulty/combinatorial_formula/community_report_per_source_rounding
        """
        plant, perm_a, perm_b, summary = self._july_backfill(api)
        assert summary["events_finalized"] == 2

        rep = validate_success(api.create_community_report(
            plant["id"], {"period_year": 2026, "period_month": 7}, COMPLIANCE_OFFICER
        ), expected_status=201)
        assert rep["total_withdrawn_gallons"] == 163089
        # Per-source order: round_half_up(163088/325851, 3) = 0.500 and
        # round_half_up(1/325851, 3) = 0.000 -> total 0.500 (not the 0.501
        # that the forbidden sum-then-convert order would yield).
        assert rep["total_acre_feet"] == pytest.approx(0.5, abs=1e-9)

    def test_community_report_per_source_breakdown_ordered(self, api):
        """PRD §3.9: "`per_source_breakdown` is the ordered array of
        per-permit entries, each carrying its `permit_id`, `gallons`, and
        `acre_feet`" and "Permits are processed in ascending order of their
        `created_at`."

        Design: Difficulty/combinatorial_formula/community_report_per_source_rounding
        """
        plant, perm_a, perm_b, _summary = self._july_backfill(api)
        rep = validate_success(api.create_community_report(
            plant["id"], {"period_year": 2026, "period_month": 7}, COMPLIANCE_OFFICER
        ), expected_status=201)
        read = validate_success(api.get_community_report(rep["id"], COMPLIANCE_OFFICER))
        breakdown = read["per_source_breakdown"]
        assert len(breakdown) == 2
        # Permit A was created first, so it leads the breakdown.
        assert breakdown[0]["permit_id"] == perm_a["id"]
        assert breakdown[0]["gallons"] == 163088
        assert breakdown[0]["acre_feet"] == pytest.approx(0.5, abs=1e-9)
        assert breakdown[1]["permit_id"] == perm_b["id"]
        assert breakdown[1]["gallons"] == 1
        assert breakdown[1]["acre_feet"] == pytest.approx(0.0, abs=1e-9)


class TestReportPublishGate:
    def test_publish_blocked_while_recorded_events_exist_in_period(self, api):
        """PRD §3.9: "Publication by a `ComplianceOfficer` requires the
        report to be `DRAFT` and requires that no `RECORDED` — unfinalized —
        withdrawal event exist for any of the plant's permits with a
        `withdrawal_date` inside the period, otherwise
        `ERR_UNFINALIZED_WITHDRAWALS` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/report_publish_requires_finalized_withdrawals
        """
        plant = create_plant("Plant CE2")
        permit = create_permit(plant["id"], permit_number="SP-CE2")
        ev, _ = post_withdrawal_event(permit["id"], gallons=7500)
        assert ev["status"] == "RECORDED"

        rep = validate_success(api.create_community_report(
            plant["id"], {"period_year": 2026, "period_month": 8}, COMPLIANCE_OFFICER
        ), expected_status=201)
        assert rep["total_withdrawn_gallons"] == 0, (
            "creation-time snapshot: RECORDED events are excluded"
        )

        resp = api.publish_community_report(rep["id"], COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_UNFINALIZED_WITHDRAWALS)

    def test_publish_after_finalization_recomputes_totals(self, api):
        """PRD §3.9: "Publication ... recomputes `total_withdrawn_gallons`,
        `total_acre_feet`, and `per_source_breakdown` from the finalized
        events as of publish time, moves the report to `PUBLISHED`".

        Design: Difficulty/cross_entity_state_dependency/report_publish_requires_finalized_withdrawals
        """
        plant = create_plant("Plant CE2")
        permit = create_permit(plant["id"], permit_number="SP-CE2")
        post_withdrawal_event(permit["id"], gallons=7500)
        rep = validate_success(api.create_community_report(
            plant["id"], {"period_year": 2026, "period_month": 8}, COMPLIANCE_OFFICER
        ), expected_status=201)

        set_clock("2026-08-02T00:00:00Z")
        summary = run_compliance(plant["id"])
        assert summary["events_finalized"] == 1

        published = validate_success(api.publish_community_report(
            rep["id"], COMPLIANCE_OFFICER
        ))
        assert published["status"] == "PUBLISHED"
        assert published["total_withdrawn_gallons"] == 7500
        # round_half_up(7500 / 325851, 3) == 0.023
        assert published["total_acre_feet"] == pytest.approx(0.023, abs=1e-9)


class TestReportPeriodLockAndSupersede:
    def _published_report_fixture(self, api):
        """Plant + permit + one FINALIZED 4000-gal event on 2026-08-01 and a
        PUBLISHED report for (2026, 8); clock sits at 2026-08-02."""
        plant = create_plant("Plant SM7")
        permit = create_permit(plant["id"], permit_number="SP-SM7")
        ev, _ = post_withdrawal_event(permit["id"], gallons=4000)
        set_clock("2026-08-02T00:00:00Z")
        run_compliance(plant["id"])
        rep = validate_success(api.create_community_report(
            plant["id"], {"period_year": 2026, "period_month": 8}, COMPLIANCE_OFFICER
        ), expected_status=201)
        validate_success(api.publish_community_report(rep["id"], COMPLIANCE_OFFICER))
        return plant, permit, ev, rep

    def test_supersede_finalized_blocked_by_published_report(self, api):
        """PRD §3.9: "while a `PUBLISHED` report covers a plant and
        year-month, superseding a finalized event of that period is refused
        with `ERR_REPORT_PERIOD_LOCKED` (§3.1)."

        Design: Corner/state_machines/supersede_finalized_blocked_by_published_report
        """
        plant, permit, ev, rep = self._published_report_fixture(api)
        permit_now = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        payload = create_withdrawal_event_payload(
            gallons=4500, meter_reading_start_gallons=4000,
            meter_reading_end_gallons=8500,
            expected_permit_version=permit_now["version"],
            supersedes_event_id=ev["id"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_LOCKED)

    def test_report_supersede_unlocks_period_correction(self, api):
        """PRD §3.9: "Superseding a `PUBLISHED` report ... moves it to the
        terminal `SUPERSEDED` state, creates a successor report in `DRAFT`
        covering the same period with `addendum_of_report_id` pointing back at
        the superseded report and totals recomputed from the current finalized
        events, returns the successor, and releases the period's publication
        lock so finalized events in the period become supersedable again until
        the successor publishes."

        Design: Corner/state_machines/report_supersede_unlocks_period_correction
        """
        plant, permit, ev, rep = self._published_report_fixture(api)

        successor = validate_success(api.supersede_community_report(
            rep["id"], COMPLIANCE_OFFICER
        ))
        assert successor["status"] == "DRAFT"
        assert successor["addendum_of_report_id"] == rep["id"]

        # The lock is released: the finalized 4000-gallon event is superseded.
        ev2, _permit_after = post_withdrawal_event(
            permit["id"], gallons=4500, meter_start=4000,
            supersedes_event_id=ev["id"],
        )
        assert ev2["status"] == "RECORDED"

        # Clock is 2026-08-02; the replacement event is dated 2026-08-01, so
        # the next compliance run finalizes exactly it.
        summary = run_compliance(plant["id"])
        assert summary["events_finalized"] == 1

        republished = validate_success(api.publish_community_report(
            successor["id"], COMPLIANCE_OFFICER
        ))
        assert republished["status"] == "PUBLISHED"
        assert republished["total_withdrawn_gallons"] == 4500

        original = validate_success(api.get_community_report(rep["id"], COMPLIANCE_OFFICER))
        assert original["status"] == "SUPERSEDED"

    def test_report_duplicate_period_rejected(self, api):
        """PRD §3.9: "Only one report that is not `SUPERSEDED` may exist per
        plant and period; a duplicate fails with
        `ERR_DUPLICATE_REPORT_PERIOD` (HTTP 409)."

        Design: Corner/state_machines/report_duplicate_period_rejected
        """
        plant = create_plant("Plant SM30")
        validate_success(api.create_community_report(
            plant["id"], create_community_report_payload(period_year=2026, period_month=8),
            COMPLIANCE_OFFICER,
        ), expected_status=201)
        resp = api.create_community_report(
            plant["id"], create_community_report_payload(period_year=2026, period_month=8),
            COMPLIANCE_OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)

    def test_report_supersede_from_draft_rejected(self, api):
        """PRD §3.9: "Superseding a `PUBLISHED` report — a
        `ComplianceOfficer` action — moves it to the terminal `SUPERSEDED`
        state" — a DRAFT report is not in a state that admits supersession
        (§2.7 rung 5, `ERR_INVALID_STATE`).

        Design: Corner/state_machines/report_supersede_from_draft_rejected
        """
        plant = create_plant("Plant SM31")
        rep = validate_success(api.create_community_report(
            plant["id"], create_community_report_payload(period_year=2026, period_month=8),
            COMPLIANCE_OFFICER,
        ), expected_status=201)
        resp = api.supersede_community_report(rep["id"], COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReportInputSetFiltering:
    def test_community_report_input_set_filtering(self, api):
        """PRD §3.9: "its totals are computed immediately from the certified
        view: only `FINALIZED` withdrawal events whose `withdrawal_date` falls
        inside the period count" and §2.11: "Events in `VOIDED` status feed
        neither view."

        Design: Corner/calculations/community_report_input_set_filtering
        """
        plant = create_plant("Plant CA4")
        permit = create_permit(plant["id"], permit_number="SP-CA4")
        ev_a, _ = post_withdrawal_event(permit["id"], gallons=1000,
                                        withdrawal_date="2026-07-10")
        ev_b, _ = post_withdrawal_event(permit["id"], gallons=500,
                                        withdrawal_date="2026-07-11", meter_start=1000)
        ev_c, _ = post_withdrawal_event(permit["id"], gallons=2000,
                                        withdrawal_date="2026-08-01", meter_start=1500)
        # VOIDED events feed neither view.
        validate_success(api.void_withdrawal_event(ev_b["id"], SOURCE_MONITOR))

        # Finalize the July event and the Aug-1 event (both strictly before
        # the new logical date); the VOIDED event is untouched.
        set_clock("2026-08-02T00:00:00Z")
        summary = run_compliance(plant["id"])
        assert summary["events_finalized"] == 2

        # A backdated RECORDED July event, posted after the run, stays
        # RECORDED and is excluded from the period until finalized.
        ev_d, _ = post_withdrawal_event(permit["id"], gallons=700,
                                        withdrawal_date="2026-07-31", meter_start=3500)

        rep = validate_success(api.create_community_report(
            plant["id"], {"period_year": 2026, "period_month": 7}, COMPLIANCE_OFFICER
        ), expected_status=201)
        assert rep["total_withdrawn_gallons"] == 1000
        # round_half_up(1000 / 325851, 3) == 0.003
        assert rep["total_acre_feet"] == pytest.approx(0.003, abs=1e-9)
        d_now = validate_success(api.get_withdrawal_event(ev_d["id"], SOURCE_MONITOR))
        assert d_now["status"] == "RECORDED"


class TestSourceFailCascade:
    def test_source_test_fail_suspends_permit(self, api):
        """PRD §3.4: "A failing `SOURCE_RAW` result suspends the subject
        permit with `suspension_reason` `SOURCE_TEST_FAIL`, cascading exactly
        as a manual suspension would".

        Design: Difficulty/transitive_cascade/source_test_fail_cascade_suspends_permit_cancels_runs
        """
        plant = create_plant("Plant TC1")
        permit = create_permit(plant["id"], permit_number="SP-TC1")
        run = create_treatment_run(plant["id"], permit["id"])
        test = create_source_raw_test(plant["id"], permit["id"], due_date="2026-08-05")

        recorded = validate_success(api.record_lab_result(
            test["id"], {"result": "FAIL", "collected_at": "2026-08-03T09:00:00Z"}, QA1
        ))
        assert recorded["status"] == "COMPLETED_FAIL"

        permit_now = validate_success(api.get_permit(permit["id"], COMPLIANCE_OFFICER))
        assert permit_now["status"] == "SUSPENDED"
        assert permit_now["suspension_reason"] == "SOURCE_TEST_FAIL"

    def test_source_test_fail_cancels_runs_and_forces_breach(self, api):
        """PRD §3.1: "Any suspension cancels every treatment run still
        `SCHEDULED` against that permit and recomputes the plant's posture —
        a suspended permit forces `BREACH`."

        Design: Difficulty/transitive_cascade/source_test_fail_cascade_suspends_permit_cancels_runs
        """
        plant = create_plant("Plant TC1")
        permit = create_permit(plant["id"], permit_number="SP-TC1")
        run = create_treatment_run(plant["id"], permit["id"])
        test = create_source_raw_test(plant["id"], permit["id"], due_date="2026-08-05")

        validate_success(api.record_lab_result(
            test["id"], {"result": "FAIL", "collected_at": "2026-08-03T09:00:00Z"}, QA1
        ))

        # Hop 3: the run cancellation is caused by the permit suspension,
        # not by the record-result call directly.
        run_now = validate_success(api.get_treatment_run(run["id"], PL1))
        assert run_now["status"] == "CANCELLED"

        # Hop 4: posture recompute caused by the suspension.
        plant_now = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert plant_now["compliance_posture"] == "BREACH"


class TestPostureWatchBoundary:
    def test_posture_green_below_ninety_percent(self, api):
        """PRD §3.2: "it reads `WATCH` when ... any `ACTIVE` permit's
        `withdrawn_month_provisional_gallons` has reached at least 90 percent
        of its `monthly_cap_gallons`" — below the threshold the plant stays
        GREEN.

        Design: Corner/cross_cutting_complexity_layers/posture_watch_at_ninety_percent_boundary
        """
        plant = create_plant("Plant CC3")
        permit = create_permit(plant["id"], permit_number="SP-CC3",
                               daily_cap_gallons=10000, monthly_cap_gallons=10000)
        post_withdrawal_event(permit["id"], gallons=8999)
        read = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert read["compliance_posture"] == "GREEN", "8999 < 90.0% of 10000"

    def test_posture_watch_at_exactly_ninety_percent(self, api):
        """PRD §3.2: "usage exactly at 90 percent triggers `WATCH`, and the
        comparison is the exact integer test of §2.9."

        Design: Corner/cross_cutting_complexity_layers/posture_watch_at_ninety_percent_boundary
        """
        plant = create_plant("Plant CC3")
        permit = create_permit(plant["id"], permit_number="SP-CC3",
                               daily_cap_gallons=10000, monthly_cap_gallons=10000)
        post_withdrawal_event(permit["id"], gallons=8999)
        post_withdrawal_event(permit["id"], gallons=1, meter_start=8999)
        read = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert read["compliance_posture"] == "WATCH", (
            "9000 >= 90.0% of 10000, exactly at the threshold"
        )


class TestVoidConservation:
    def test_withdrawal_record_void_gallons_conservation(self, api):
        """PRD §3.1: "Voiding is the compensating action for an event still
        in `RECORDED` status: the event moves to `VOIDED` and drops out of
        every aggregate" and §2.5: "The `version` is an integer that
        increments by exactly 1 on every mutation of the resource".

        Design: Difficulty/compensating_invariant/withdrawal_record_void_gallons_conservation
        """
        plant = create_plant("Plant CI2")
        permit = create_permit(plant["id"], permit_number="SP-CI2")
        baseline = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert baseline["withdrawn_month_provisional_gallons"] == 0
        assert baseline["withdrawn_month_certified_gallons"] == 0
        assert baseline["version"] == 1

        ev, after_post = post_withdrawal_event(permit["id"], gallons=4000)
        assert after_post["withdrawn_month_provisional_gallons"] == 4000

        voided = validate_success(api.void_withdrawal_event(ev["id"], SOURCE_MONITOR))
        assert voided["status"] == "VOIDED"

        final = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert final["withdrawn_month_provisional_gallons"] == 0
        assert final["withdrawn_month_certified_gallons"] == 0
        # Conservation of the quantity, not of the version: create (+1) and
        # void (+1) each advanced the permit's version.
        assert final["version"] == 3
        assert_permit_view_consistency(final)

    def test_withdrawal_void_also_restores_daily_view(self, api):
        """PRD §2.11: "Events in `VOIDED` status feed neither view."

        Design: Difficulty/compensating_invariant/withdrawal_record_void_gallons_conservation
        """
        plant = create_plant("Plant CI2")
        permit = create_permit(plant["id"], permit_number="SP-CI2")
        ev, after_post = post_withdrawal_event(permit["id"], gallons=4000)
        assert after_post["withdrawn_today_provisional_gallons"] == 4000

        validate_success(api.void_withdrawal_event(ev["id"], SOURCE_MONITOR))
        final = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert final["withdrawn_today_provisional_gallons"] == 0
        assert final["withdrawn_today_certified_gallons"] == 0


class TestComplianceRunSummary:
    def test_compliance_run_summary_is_computed_read(self, api):
        """PRD §3.2: "The run returns a summary object containing
        `ops_run_index`, `events_finalized`, `tests_flipped`,
        `tests_auto_created`, `permits_suspended`, `permits_expired`, and the
        resulting `posture`."

        Design: Corner/endpoints/compliance_run_summary_is_computed_read
        """
        plant = create_plant("Plant EP4")
        permit = create_permit(plant["id"], permit_number="SP-EP4")
        ev, _ = post_withdrawal_event(permit["id"], gallons=500)
        set_clock("2026-08-02T00:00:00Z")

        summary = run_compliance(plant["id"])
        assert summary["events_finalized"] == 1
        # The run also auto-schedules one SOURCE_RAW test for the ACTIVE
        # permit lacking an upcoming one (§3.4).
        assert summary["tests_auto_created"] == 1
        assert summary["permits_suspended"] == 0
        assert summary["permits_expired"] == 0
        assert summary["posture"] == "GREEN"
        assert summary["ops_run_index"] == 1

        finalized = validate_success(api.get_withdrawal_event(ev["id"], SOURCE_MONITOR))
        assert finalized["status"] == "FINALIZED"
        assert finalized["finalized_at"] is not None
