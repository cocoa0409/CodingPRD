"""TRIR/DART rate variants and the establishment risk score / posture."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_summary,
    cancel_corrective_action,
    classify_case,
    create_case,
    create_classified_case,
    create_corrective_action,
    create_approved_hour_log,
    create_summary,
    get_establishment,
    get_success_data,
    get_summary,
    prepare_summary,
    certify_summary,
    set_clock,
    setup_org,
    setup_year_hour_logs,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COORDINATOR, OFFICER


class TestLiveRateInputSet:
    def test_live_rates_exclude_non_recordable_cases(self, api):
        """PRD §3.7: "Separately from the summary cycle, a live rates read-out
        answers the live variant for any requested `year`: always recomputed
        from current data, counting cases by their latest classification —
        including reclassified cases not yet re-determined — and drawing hours
        only from `APPROVED` or `LOCKED` logs."
        PRD §3.7: "It returns `trir`, `dart_rate`, `total_recordable_cases`,
        `total_dart_cases`, and `total_hours_worked`, with null rates when the
        year's hours are zero."

        Design: Corner/calculations/trir_input_set_filtering_excludes_not_recordable
        """
        _, establishment, employee = setup_org(fein="67-0000015",
                                               site_name="Site Calc")
        set_clock("2026-08-02T10:00:00Z")
        create_classified_case(establishment["id"], employee["id"],
                               "2026-08-01T10:00:00Z", description="A")
        create_classified_case(establishment["id"], employee["id"],
                               "2026-08-02T09:00:00Z",
                               classification="FIRST_AID_ONLY",
                               description="B", body_part="leg")
        create_case(establishment["id"], employee["id"],
                    "2026-08-02T09:30:00Z", description="C pending",
                    body_part="hand")
        create_approved_hour_log(establishment["id"], 2026, 8,
                                 hours_worked=40000, employment_count=10)

        rates = get_success_data(
            api.get_establishment_rates(establishment["id"], 2026, OFFICER))
        assert rates["total_recordable_cases"] == 1, (
            "NOT_RECORDABLE and PENDING_REVIEW cases are excluded")
        assert rates["total_hours_worked"] == 40000, (
            "Only APPROVED logs feed the hours total")
        assert rates["trir"] == pytest.approx(5.0, abs=0.01), (
            "1 x 200000 / 40000")

    def test_live_rates_zero_hours_return_null(self, api):
        """PRD §3.7: "It returns `trir`, `dart_rate`,
        `total_recordable_cases`, `total_dart_cases`, and
        `total_hours_worked`, with null rates when the year's hours are
        zero."
        PRD §2.6: "When the denominator hours for a year are zero, a
        published rate is null rather than zero: the annual-summary
        preparation step treats zero hours as a hard error (§3.7), while the
        live rate read-out simply returns null rates for that year."

        Design: Corner/endpoints/rates_endpoint_zero_hours_returns_null_rates
        """
        _, establishment, employee = setup_org(fein="08-0000027",
                                               site_name="NH Site")
        create_classified_case(establishment["id"], employee["id"],
                               "2026-08-01T10:00:00Z",
                               clock_iso="2026-08-01T12:00:00Z",
                               description="NH")

        rates = get_success_data(
            api.get_establishment_rates(establishment["id"], 2026, OFFICER))
        assert rates["total_hours_worked"] == 0
        assert rates["total_recordable_cases"] == 1
        assert rates["trir"] is None
        assert rates["dart_rate"] is None


class TestProvisionalVsCertifiedFreeze:
    def _certified_summary_then_late_case(self, fein):
        """Three recordable cases (Mar-May 2026), twelve approved 5000-hour
        logs, summary prepared then certified at clock 2026-06-20; afterwards
        a fourth case becomes recordable. Returns (establishment, summary)."""
        _, establishment, employee = setup_org(fein=fein, site_name="Plant 1")
        for occurred, clock, classification, desc, part in (
                ("2026-03-05T10:00:00Z", "2026-03-05T12:00:00Z",
                 "MEDICAL_TREATMENT", "Laceration sutured", "left hand"),
                ("2026-04-11T09:00:00Z", "2026-04-11T12:00:00Z",
                 "MEDICAL_TREATMENT", "Sprain Rx meds", "ankle"),
                ("2026-05-20T14:00:00Z", "2026-05-20T16:00:00Z",
                 "JOB_TRANSFER_RESTRICTION", "Back strain restricted duty",
                 "back")):
            create_classified_case(establishment["id"], employee["id"],
                                   occurred, classification=classification,
                                   clock_iso=clock, description=desc,
                                   body_part=part)
        logs = setup_year_hour_logs(establishment["id"], 2026)
        set_clock("2026-06-20T00:00:00Z")
        summary = create_summary(establishment["id"], 2026)
        prepared = prepare_summary(summary["id"])
        certified = certify_summary(summary["id"])

        set_clock("2026-08-01T12:00:00Z")
        create_classified_case(establishment["id"], employee["id"],
                               "2026-08-01T08:00:00Z",
                               description="Cut sutured", body_part="finger")
        return establishment, prepared, certified, logs

    def test_certified_rates_frozen_after_later_case(self, api):
        """PRD §3.7: "On success the summary moves to `CERTIFIED`,
        `certified_by` and `certified_at` are stamped, the rates freeze into
        their certified snapshot — later case changes never alter a certified
        summary's `trir` or `dart_rate` — and every `APPROVED` hour log for
        the year locks automatically to `LOCKED`, the terminal hour-log
        state."
        PRD §3.7: "stores provisional rates: `trir` as the recordable-case
        count multiplied by 200,000 and divided by the total hours worked, and
        `dart_rate` as the same expression over the DART-case count, each
        rounded half-up to one decimal place."

        Design: Difficulty/dual_variant_calc/trir_provisional_vs_certified_freeze
        """
        establishment, prepared, certified, logs = (
            self._certified_summary_then_late_case("12-3456789"))
        assert prepared["trir"] == pytest.approx(10.0, abs=0.01), (
            "Provisional: 3 recordable x 200000 / 60000")
        assert prepared["dart_rate"] == pytest.approx(3.3, abs=0.01), (
            "Provisional DART: 1 x 200000 / 60000 = 3.33 -> 3.3")
        assert certified["status"] == "CERTIFIED"
        for log in logs:
            refreshed = get_success_data(
                api.get_hour_log(log["id"], COORDINATOR))
            assert refreshed["status"] == "LOCKED", (
                "Certification locks the year's APPROVED hour logs")

        frozen = get_summary(certified["id"])
        assert_summary(frozen)
        assert frozen["status"] == "CERTIFIED"
        assert frozen["trir"] == pytest.approx(10.0, abs=0.01), (
            "A fourth recordable case must not alter the certified snapshot")
        assert frozen["dart_rate"] == pytest.approx(3.3, abs=0.01)

    def test_live_rates_diverge_from_certified_snapshot(self, api):
        """PRD §3.7: "Separately from the summary cycle, a live rates read-out
        answers the live variant for any requested `year`: always recomputed
        from current data"
        PRD §3.7: "later case changes never alter a certified summary's
        `trir` or `dart_rate`"

        Design: Difficulty/dual_variant_calc/trir_provisional_vs_certified_freeze
        """
        establishment, _, certified, _ = (
            self._certified_summary_then_late_case("12-3456790"))
        rates = get_success_data(
            api.get_establishment_rates(establishment["id"], 2026, OFFICER))
        assert rates["total_recordable_cases"] == 4
        assert rates["trir"] == pytest.approx(13.3, abs=0.01), (
            "LIVE variant: 4 x 200000 / 60000 = 13.33 -> 13.3")

        frozen = get_summary(certified["id"])
        assert frozen["trir"] == pytest.approx(10.0, abs=0.01)
        assert rates["trir"] != pytest.approx(frozen["trir"], abs=0.01), (
            "Certified snapshot and live variant diverge on identical year "
            "data")


class TestRiskScoreWeightedThreshold:
    def _four_overdue_actions(self, fein):
        """Five OPEN actions due 2026-08-10; one cancelled pre-sweep; clock
        advance to 2026-08-11 sweeps the remaining four to OVERDUE."""
        _, establishment, employee = setup_org(fein=fein, site_name="Foundry",
                                               naics_code="331511",
                                               state_code="PA",
                                               size_class="LARGE")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-04T10:00:00Z",
            clock_iso="2026-08-05T08:00:00Z", description="Burn",
            body_part="forearm")
        actions = [
            create_corrective_action(
                establishment["id"], case_id=case["id"],
                description=f"Guard repair {n}", assigned_to="op-fix-1",
                due_date="2026-08-10", priority="HIGH")
            for n in range(1, 6)
        ]
        cancel_corrective_action(actions[0]["id"])
        set_clock("2026-08-11T00:00:00Z")
        return establishment, actions

    def test_risk_score_twenty_from_four_overdue_actions(self, api):
        """PRD §2.7: "The score weighs five signals: 2.0 times the live TRIR
        for the logical clock's current year, plus 3.0 times the live DART
        rate for that year, plus 5.0 for each corrective action currently in
        `OVERDUE`, plus 8.0 for each citation currently in `OVERDUE`, plus
        10.0 for each severe-injury report filed `LATE` within the trailing
        365 days."
        PRD §2.7: "When the establishment has zero approved hours in the
        current year, the live rates enter this formula as 0.0 — not null."
        PRD §2.7: "anything below 25.0 yields `CLEAR`."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_multi_input_threshold
        """
        establishment, _ = self._four_overdue_actions("55-1212121")
        est = get_establishment(establishment["id"])
        assert est["risk_score"] == pytest.approx(20.0, abs=0.01), (
            "5.0 x 4 overdue actions; rate terms collapse to 0.0")
        assert est["posture"] == "CLEAR", (
            "20.0 sits below the inclusive 25.0 WATCH boundary")

    def test_overdue_sweep_skips_cancelled_action(self, api):
        """PRD §2.4: "Every clock repositioning triggers a compliance sweep.
        Each corrective action whose `due_date` falls before the new clock
        date and that still sits in `OPEN` or `REOPENED` moves to `OVERDUE`"
        PRD §3.5: "An action still in `OPEN` may instead be cancelled
        outright, landing in the terminal `CANCELLED` state with a posture
        recompute."

        Design: Difficulty/combinatorial_formula/risk_score_weighted_multi_input_threshold
        """
        establishment, actions = self._four_overdue_actions("55-1212122")
        overdue = get_success_data(
            api.list_establishment_corrective_actions(
                establishment["id"], OFFICER, params={"status": "OVERDUE"}))
        assert len(overdue) == 4, (
            "Exactly the four non-cancelled actions sweep to OVERDUE")
        cancelled = get_success_data(
            api.get_corrective_action(actions[0]["id"], OFFICER))
        assert cancelled["status"] == "CANCELLED", (
            "The cancelled action is terminal and never sweeps")

    def test_posture_watch_at_exactly_25(self, api):
        """PRD §2.7: "Posture derives from the score with inclusive
        boundaries: a score of 50.0 or higher yields `ELEVATED`; a score of
        25.0 or higher but below 50.0 yields `WATCH`; anything below 25.0
        yields `CLEAR`."
        PRD §2.4: "Every clock repositioning triggers a compliance sweep."

        Design: Corner/cross_cutting_layers/posture_watch_threshold_crossing_at_exactly_25
        """
        _, establishment, employee = setup_org(fein="18-0000037",
                                               site_name="WT Site")
        case = create_classified_case(
            establishment["id"], employee["id"], "2026-08-01T10:00:00Z",
            clock_iso="2026-08-01T12:00:00Z", description="WT")
        for n in range(1, 6):
            create_corrective_action(
                establishment["id"], case_id=case["id"],
                description=f"W{n}", assigned_to="op-w",
                due_date="2026-08-06")
        set_clock("2026-08-07T00:00:00Z")

        est = get_establishment(establishment["id"])
        assert est["risk_score"] == pytest.approx(25.0, abs=0.01), (
            "5 overdue actions x 5.0; live rates 0.0 with zero current-year "
            "hours")
        assert est["posture"] == "WATCH", (
            "The inclusive >= 25.0 boundary is crossed exactly")
