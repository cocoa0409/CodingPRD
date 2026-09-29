"""Dual-variant derived figures: the two downtime clocks and the two station
scoring variants.

Every test builds its own world from scratch — the harness restarts the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    SOURCE_CALL_SIGNS,
    api_client,
    append_log_entry,
    assert_score_and_posture,
    assert_summary_inputs,
    evaluate_readiness,
    file_results,
    get_success_data,
    run_log_review,
    schedule_test_event,
    set_clock,
    setup_restored_outage,
    setup_station,
    setup_submitted_filing,
    station_summary,
)

# ---------------------------------------------------------------------------
# Shared instants. detected_at lands exactly on an obligation-window open and
# restored_at exactly on an obligation-window close four calendar days later.
# ---------------------------------------------------------------------------
OUTAGE_DETECTED_AT = "2026-08-03T08:00:00Z"
OUTAGE_RESTORED_AT = "2026-08-06T20:00:00Z"

TE1_WINDOW_START = "2026-08-12T00:00:00Z"
TE1_WINDOW_END = "2026-08-12T01:00:00Z"
TE2_WINDOW_START = "2026-08-13T00:00:00Z"
TE2_WINDOW_END = "2026-08-13T01:00:00Z"
LATE_FILING_INSTANT = "2026-08-17T02:00:00Z"
REVIEW_INSTANT = "2026-08-19T00:00:00Z"


def _restored_outage_over_four_obligation_windows():
    """A station whose only device fails at 2026-08-03T08:00:00Z and is reported
    restored at 2026-08-06T20:00:00Z, i.e. across four full obligation windows."""
    ctx = setup_station(required_source_types=("PEP", "NWS"))
    set_clock(OUTAGE_DETECTED_AT)
    ctx["outage"] = setup_restored_outage(
        ctx["device_id"], OUTAGE_DETECTED_AT, OUTAGE_RESTORED_AT
    )
    return ctx


class TestOutageDowntimeVariants:
    """The same detected_at / restored_at pair measured under both conventions."""

    def test_continuous_clock_counts_every_elapsed_second_and_breaches_sixty_hours(self):
        """PRD §3.4: "Subtract `detected_at` from `restored_at`, divide the resulting number of seconds by 3600, and round half-up to two decimal places; the result is `continuous_downtime_hours`."
        PRD §3.4: "Then `continuous_clock_breached` is true when `continuous_downtime_hours` is strictly greater than 60 hours — two and a half days of unbroken outage — and false when it equals 60 hours or is less."

        Design: Difficulty/dual_variant_calc/outage_downtime_variants_diverge_on_breach_verdict
        """
        ctx = _restored_outage_over_four_obligation_windows()
        outage = ctx["outage"]

        assert outage["status"] == "RESTORED", (
            f"expected status RESTORED, got {outage['status']}"
        )
        assert outage["restored_at"].startswith("2026-08-06T20:00:00"), (
            f"restored_at is stamped from the logical clock, got {outage['restored_at']}"
        )
        assert outage["continuous_downtime_hours"] == pytest.approx(84.00, abs=0.01), (
            "302400 elapsed seconds / 3600 is 84.00 continuous hours, got "
            f"{outage['continuous_downtime_hours']}"
        )
        assert outage["continuous_clock_breached"] is True, (
            "84.00 is strictly greater than 60 hours, so the continuous clock breaches"
        )

    def test_obligation_clock_counts_only_daily_windows_and_does_not_breach_at_exactly_48(self):
        """PRD §3.4: "Accumulate the day contributions in seconds, divide the accumulated total by 3600, and round half-up to two decimal places to obtain `obligation_downtime_hours`."
        PRD §3.4: "Then `obligation_breached` is true when `obligation_downtime_hours` is strictly greater than 48 hours — the statutory repair deadline — and false at exactly 48 hours or below."

        Design: Difficulty/dual_variant_calc/outage_downtime_variants_diverge_on_breach_verdict
        """
        ctx = _restored_outage_over_four_obligation_windows()
        outage = ctx["outage"]

        assert outage["obligation_downtime_hours"] == pytest.approx(48.00, abs=0.01), (
            "four daily windows of 12.00 obligation hours each is 48.00, got "
            f"{outage['obligation_downtime_hours']}"
        )
        assert outage["obligation_breached"] is False, (
            "the comparison is strictly greater than 48 hours, so exactly 48.00 does "
            "not breach"
        )
        assert outage["continuous_clock_breached"] != outage["obligation_breached"], (
            "the two conventions return opposite verdicts on one identical "
            "detected_at / restored_at pair"
        )

    def test_station_score_reflects_the_suspended_assignments_left_by_the_outage(self):
        """PRD §2.11: "Hop 3 is caused by those assignments leaving `ACTIVE`: the station's `accessible_source_count` is recomputed and the station scoring re-runs, moving `compliance_posture` per the bands in §2.10."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"

        Design: Difficulty/dual_variant_calc/outage_downtime_variants_diverge_on_breach_verdict
        """
        ctx = _restored_outage_over_four_obligation_windows()

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["accessible_source_count"] == 0, (
            "both ACTIVE assignments on the failed device were pushed to SUSPENDED, "
            f"got accessible_source_count {station['accessible_source_count']}"
        )
        assert_score_and_posture(station, 50.00, "SUSPENDED_FILINGS")
        assert station["compliance_variant_applied"] == "PROVISIONAL", (
            "no filing has been accepted, so the provisional variant applies"
        )


class TestStationScoringVariantFlip:
    """Accepting a filing latches the certified variant without changing any input."""

    def test_provisional_variant_ignores_penalty_points_total_before_acceptance(self):
        """PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."
        PRD §3.7: "Finally the station's ledger is resynchronised: `penalty_points_total` becomes the sum of `penalty_points` across all of that station's filing records whose `status` is `SUBMITTED` or `ACCEPTED`, rounded half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/station_score_variant_flips_provisional_to_certified_on_filing_accept
        """
        ctx = setup_submitted_filing(file_at=LATE_FILING_INSTANT)

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(0.94, abs=0.01), (
            "the single SUBMITTED filing carries 0.94 penalty points, got "
            f"{station['penalty_points_total']}"
        )
        assert station["compliance_variant_applied"] == "PROVISIONAL", (
            "a SUBMITTED filing does not confer certified eligibility, got "
            f"{station['compliance_variant_applied']}"
        )
        assert_score_and_posture(station, 100.00, "COMPLIANT")

    def test_accepting_the_filing_flips_the_variant_and_charges_penalty_points(self):
        """PRD §3.8: "When it is certified-eligible, `compliance_variant_applied` is `CERTIFIED` and all six deductions are applied."
        PRD §3.7: "Acceptance fires a station recompute event, and its consequence is significant: an accepted filing is what makes the station eligible for the certified scoring variant of §3.8, so a station scoring a perfect 100.00 provisionally can drop two posture bands the moment its first filing is accepted."

        Design: Difficulty/dual_variant_calc/station_score_variant_flips_provisional_to_certified_on_filing_accept
        """
        ctx = setup_submitted_filing(file_at=LATE_FILING_INSTANT)

        accepted = get_success_data(api_client.accept_filing(ctx["filing_id"], ADMIN))
        assert accepted["status"] == "ACCEPTED", (
            f"expected the filing in ACCEPTED, got {accepted['status']}"
        )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            compliance_variant_applied="CERTIFIED",
            penalty_points_total=0.94,
            unfiled_test_count=0,
            missing_source_count=0,
            silent_assignment_count=0,
            outage_breach_count=0,
        )
        assert_score_and_posture(summary, 99.06, "COMPLIANT")


def _station_with_filed_te1_and_abandoned_te2(accept_filing: bool):
    """One station, two disjoint weekly test windows: te1 is logged and filed,
    te2 is evaluated READY and then abandoned past its filing deadline.

    The clock is left at 2026-08-19T00:00:00Z, which is past te2's
    filing_deadline_at (2026-08-18T01:00:00Z) but still inside eight days of the
    PEP assignment's last_receipt_at (2026-08-12T00:30:00Z).
    """
    ctx = setup_station()
    te1 = schedule_test_event(ctx["station_id"], TE1_WINDOW_START, TE1_WINDOW_END)
    te2 = schedule_test_event(ctx["station_id"], TE2_WINDOW_START, TE2_WINDOW_END)

    set_clock("2026-08-12T00:30:00Z")
    evaluate_readiness(te1["id"])
    append_log_entry(te1["id"], ctx["device_id"], "TRANSMISSION")
    append_log_entry(
        te1["id"],
        ctx["device_id"],
        "RECEIPT",
        source_call_sign=SOURCE_CALL_SIGNS["PEP"],
    )
    get_success_data(api_client.close_logging(te1["id"], ENGINEER))

    set_clock("2026-08-13T00:30:00Z")
    evaluate_readiness(te2["id"])

    set_clock(LATE_FILING_INSTANT)
    filing = file_results(te1["id"])
    if accept_filing:
        get_success_data(api_client.accept_filing(filing["id"], ADMIN))

    set_clock(REVIEW_INSTANT)
    ctx["te1_id"] = te1["id"]
    ctx["te2_id"] = te2["id"]
    ctx["filing"] = filing
    return ctx


class TestCertifiedVariantUnfiledAndPenaltyDeductions:
    """The unfiled sweep of phase 2 feeds a deduction only the certified variant applies."""

    def test_certified_variant_drops_a_band_when_the_review_sweeps_an_unfiled_event(self):
        """PRD §3.8: "Every test event of the station whose `status` is `READY` or `LOGGED` and whose `filing_deadline_at` is strictly earlier than the current logical clock is pushed to `FAILED_UNFILED`."
        PRD §3.8: "20.00 points for each test event counted in the unfiled test count — **certified variant only**;"

        Design: Difficulty/dual_variant_calc/certified_variant_adds_unfiled_and_penalty_deductions_dropping_a_posture_band
        """
        ctx = _station_with_filed_te1_and_abandoned_te2(accept_filing=True)

        review = run_log_review(ctx["station_id"])
        assert review["last_log_review_at"].startswith("2026-08-19T00:00:00"), (
            "last_log_review_at is stamped from the logical clock, got "
            f"{review['last_log_review_at']}"
        )

        te2 = get_success_data(api_client.get_test_event(ctx["te2_id"], ADMIN))
        assert te2["status"] == "FAILED_UNFILED", (
            "te2 sat in READY past its filing deadline, so phase 2 swept it, got "
            f"{te2['status']}"
        )
        te1 = get_success_data(api_client.get_test_event(ctx["te1_id"], ADMIN))
        assert te1["status"] == "FILED", (
            f"a FILED event is outside the phase-2 sweep, got {te1['status']}"
        )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            compliance_variant_applied="CERTIFIED",
            unfiled_test_count=1,
            penalty_points_total=0.94,
            missing_source_count=0,
            silent_assignment_count=0,
            outage_breach_count=0,
        )
        assert_score_and_posture(summary, 79.06, "WATCH")

    def test_provisional_variant_holds_at_100_on_exactly_the_same_swept_data(self):
        """PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."
        PRD §3.8: "All three are reported regardless of which variant was applied, even though the last one only ever affects a `CERTIFIED` score."

        Design: Difficulty/dual_variant_calc/certified_variant_adds_unfiled_and_penalty_deductions_dropping_a_posture_band
        """
        ctx = _station_with_filed_te1_and_abandoned_te2(accept_filing=False)

        run_log_review(ctx["station_id"])

        te2 = get_success_data(api_client.get_test_event(ctx["te2_id"], ADMIN))
        assert te2["status"] == "FAILED_UNFILED", (
            "the phase-2 sweep runs whichever variant scores, got "
            f"{te2['status']}"
        )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            compliance_variant_applied="PROVISIONAL",
            unfiled_test_count=1,
            penalty_points_total=0.94,
            missing_source_count=0,
            silent_assignment_count=0,
            outage_breach_count=0,
        )
        assert_score_and_posture(summary, 100.00, "COMPLIANT")
