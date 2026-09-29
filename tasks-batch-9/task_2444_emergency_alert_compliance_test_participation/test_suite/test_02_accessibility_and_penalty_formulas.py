"""Combinatorial formulas: the nested caps of the accessibility deficiency
calculation and the pinned rounding order of the filing penalty.

Every test builds its own world from scratch — the harness restarts the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    OFFICER,
    SOURCE_CALL_SIGNS,
    api_client,
    append_log_entry,
    create_active_plan,
    filing_record_payload,
    get_success_data,
    log_alert,
    register_station,
    set_clock,
    setup_logged_test_event,
    setup_ready_test_event,
    validate_error,
    validate_success,
    verify_alert_accessibility,
)
from test_helpers import test_event_version as read_test_event_version

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
ONE_DAY_LATE_INSTANT = "2026-08-17T02:00:00Z"
THREE_DAYS_LATE_INSTANT = "2026-08-19T02:00:00Z"


def _station_with_two_unverified_alerts():
    """A plan and station carrying no relay rules at all, plus two alerts that
    differ in `originator_sequence` so neither can suppress the other."""
    plan = create_active_plan(required_source_types=("PEP",))
    station = register_station(plan["id"])
    capped = log_alert(
        station["id"], DEFAULT_CLOCK, originator_sequence="KSACC-0001"
    )
    uncapped = log_alert(
        station["id"], DEFAULT_CLOCK, originator_sequence="KSACC-0002"
    )
    return {
        "plan": plan,
        "station_id": station["id"],
        "capped_alert_id": capped["id"],
        "uncapped_alert_id": uncapped["id"],
        "capped_alert": capped,
        "uncapped_alert": uncapped,
    }


class TestAccessibilityNestedCaps:
    """Three measurements feed a capped coupling term inside a capped sum."""

    def test_worst_case_measurements_bind_both_the_coupling_and_deficiency_ceilings(self):
        """PRD §3.5: "The base term is the crawl shortfall in seconds multiplied by 0.05 points per second, plus the loudness excess multiplied by 0.10 points per loudness unit."
        PRD §3.5: "The coupling term multiplies the crawl shortfall in seconds by the loudness excess in loudness units and by a coupling rate of 0.01, then takes the smaller of that product and a coupling ceiling of 3.00 points — audio deviation is amplified when the crawl is also short, but the amplification alone can never exceed 3.00 points."
        PRD §3.5: "Add the base term, the capped coupling term and the caption penalty; take the smaller of that sum and the overall deficiency ceiling of 8.00 points; and round the result half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/accessibility_nested_min_max_with_both_caps_binding
        """
        ctx = _station_with_two_unverified_alerts()

        verified = verify_alert_accessibility(
            ctx["capped_alert_id"],
            visual_crawl_seconds=0,
            audio_loudness_lufs=-60.0,
            caption_interaction="CAPTION_SUPPRESSED",
        )

        assert verified["accessibility_deficiency_points"] == pytest.approx(
            8.00, abs=0.01
        ), (
            "base 6.40 plus the coupling term capped at 3.00 plus caption 1.50 is "
            "10.90, which the 8.00 deficiency ceiling clamps; got "
            f"{verified['accessibility_deficiency_points']}"
        )
        assert verified["accessibility_state"] == "ACCESSIBILITY_FAILED", (
            "8.00 is strictly greater than 1.00, so the verdict fails; got "
            f"{verified['accessibility_state']}"
        )
        assert verified["relay_state"] == "UNMATCHED_OPTIONAL", (
            "no relay rule exists for the alert, and verification leaves the "
            f"forwarding dimension alone; got {verified['relay_state']}"
        )

    def test_moderate_measurements_leave_both_ceilings_slack(self):
        """PRD §3.5: "The caption penalty is 0.00 points when `caption_interaction` is `NONE`, 1.50 points when it is `CAPTION_SUPPRESSED`, and 2.00 points when it is `CRAWL_OVERLAP`."
        PRD §3.5: "The coupling term multiplies the crawl shortfall in seconds by the loudness excess in loudness units and by a coupling rate of 0.01, then takes the smaller of that product and a coupling ceiling of 3.00 points — audio deviation is amplified when the crawl is also short, but the amplification alone can never exceed 3.00 points."
        PRD §3.5: "The verdict is inclusive at the boundary: `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_PASSED` when `accessibility_deficiency_points` is 1.00 or less, and `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_FAILED` when it is strictly greater than 1.00."

        Design: Difficulty/combinatorial_formula/accessibility_nested_min_max_with_both_caps_binding
        """
        ctx = _station_with_two_unverified_alerts()

        verified = verify_alert_accessibility(
            ctx["uncapped_alert_id"],
            visual_crawl_seconds=30,
            audio_loudness_lufs=-18.0,
            caption_interaction="CRAWL_OVERLAP",
        )

        assert verified["accessibility_deficiency_points"] == pytest.approx(
            5.10, abs=0.01
        ), (
            "base 1.90 plus an uncapped coupling term of 1.20 plus caption 2.00 is "
            f"5.10, below the 8.00 ceiling; got "
            f"{verified['accessibility_deficiency_points']}"
        )
        assert verified["accessibility_state"] == "ACCESSIBILITY_FAILED", (
            "5.10 is strictly greater than 1.00, so the verdict fails; got "
            f"{verified['accessibility_state']}"
        )


def _late_filing_on_two_log_lines():
    """A LOGGED weekly test event carrying exactly one TRANSMISSION and one
    RECEIPT line, with the clock parked one hour past filing_deadline_at."""
    ctx = setup_logged_test_event()
    set_clock(ONE_DAY_LATE_INSTANT)
    return ctx


def _file_results_expecting_created(event_id, note):
    """File post-test results and require the 201 that a created row carries."""
    payload = filing_record_payload(event_id, read_test_event_version(event_id, OFFICER))
    payload["attestation_note"] = note
    return validate_success(api_client.create_filing_record(payload, OFFICER), 201)


class TestFilingPenaltyPinnedRounding:
    """Per-log-line rounding happens before the per-line values are summed."""

    def test_entry_subtotal_rounds_each_log_line_before_summing(self):
        """PRD §3.7: "Each log line of the event carries a kind weight: 1.0 for a `RECEIPT` line and 1.8 for a `TRANSMISSION` line."
        PRD §3.7: "Sum the rounded per-line values to obtain `entry_subtotal_points`."
        PRD §3.7: "Rounding per line before summing is normative: summing the raw per-line products and rounding the sum once produces a different number of cents and is not what this system does."

        Design: Difficulty/combinatorial_formula/filing_penalty_pinned_round_per_entry_then_sum
        """
        ctx = _late_filing_on_two_log_lines()

        filing = _file_results_expecting_created(
            ctx["test_event_id"], "one day late, two log lines"
        )

        assert filing["late_days"] == 1, (
            "filed one hour past the deadline, so any part of a day counts as a "
            f"whole late day; got {filing['late_days']}"
        )
        assert filing["entry_subtotal_points"] == pytest.approx(0.19, abs=0.01), (
            "round(0.117) is 0.12 for the TRANSMISSION line and round(0.065) is "
            "0.07 for the RECEIPT line, summing to 0.19; got "
            f"{filing['entry_subtotal_points']}"
        )
        assert filing["entry_subtotal_points"] != pytest.approx(0.18, abs=0.001), (
            "0.18 is round(0.117 + 0.065), the rounding order this specification "
            "rejects"
        )

    def test_penalty_points_combine_the_three_terms_and_resync_the_station_ledger(self):
        """PRD §3.7: "`lateness_points` is `late_days` multiplied by 0.75 points per late day, rounded half-up to two decimals."
        PRD §3.7: "`penalty_points` is then the smaller of a per-filing cap of 25.00 points and the sum of `entry_subtotal_points`, `lateness_points` and `unconfirmed_relay_points`, rounded half-up to two decimal places."
        PRD §3.7: "Finally the station's ledger is resynchronised: `penalty_points_total` becomes the sum of `penalty_points` across all of that station's filing records whose `status` is `SUBMITTED` or `ACCEPTED`, rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/filing_penalty_pinned_round_per_entry_then_sum
        """
        ctx = _late_filing_on_two_log_lines()

        filing = _file_results_expecting_created(
            ctx["test_event_id"], "one day late, two log lines"
        )

        assert filing["lateness_points"] == pytest.approx(0.75, abs=0.01), (
            f"one late day at 0.75 points; got {filing['lateness_points']}"
        )
        assert filing["unconfirmed_relay_points"] == pytest.approx(0.00, abs=0.01), (
            "the station logged no alerts at all, so the unconfirmed mandatory relay "
            f"pool is empty; got {filing['unconfirmed_relay_points']}"
        )
        assert filing["penalty_points"] == pytest.approx(0.94, abs=0.01), (
            "0.19 + 0.75 + 0.00 is below the 25.00 per-filing cap; got "
            f"{filing['penalty_points']}"
        )
        assert filing["status"] == "SUBMITTED", (
            f"a successful filing is stored in SUBMITTED, got {filing['status']}"
        )

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(0.94, abs=0.01), (
            "the ledger resynchronises to the single SUBMITTED filing; got "
            f"{station['penalty_points_total']}"
        )


def _station_with_three_days_late_filing_of_three_dollars():
    """A LOGGED weekly test event carrying three log lines, filed three days
    late so its penalty_points is exactly 3.00, leaving the station's
    penalty_points_total at 3.00 with the clock still at the filing instant."""
    ctx = setup_ready_test_event()
    append_log_entry(ctx["test_event_id"], ctx["device_id"], "TRANSMISSION")
    append_log_entry(
        ctx["test_event_id"],
        ctx["device_id"],
        "RECEIPT",
        source_call_sign=SOURCE_CALL_SIGNS["PEP"],
    )
    append_log_entry(
        ctx["test_event_id"],
        ctx["device_id"],
        "RECEIPT",
        source_call_sign=SOURCE_CALL_SIGNS["PEP"],
    )
    get_success_data(api_client.close_logging(ctx["test_event_id"], ENGINEER))

    set_clock(THREE_DAYS_LATE_INSTANT)
    ctx["filing"] = _file_results_expecting_created(
        ctx["test_event_id"], "original filing, three days late"
    )
    ctx["filing_id"] = ctx["filing"]["id"]
    return ctx


class TestPenaltyCeilingOnAmendment:
    """The fiscal ceiling reads the station's existing total, not a post-reversal one."""

    def test_first_filing_of_three_points_passes_the_ceiling(self):
        """PRD §3.7: "And last of all, the fiscal ceiling of §2.6 and §2.8 applies: the station's existing `penalty_points_total` plus the `penalty_points` this filing would compute must not exceed 5.00 points, otherwise `ERR_PENALTY_CEILING_EXCEEDED`."
        PRD §3.7: "A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."

        Design: Difficulty/combinatorial_formula/penalty_ceiling_reads_pre_write_total_and_rejects_the_amendment
        """
        ctx = _station_with_three_days_late_filing_of_three_dollars()
        filing = ctx["filing"]

        assert filing["late_days"] == 3, (
            "two days and one hour past the deadline rounds up to three late days; "
            f"got {filing['late_days']}"
        )
        assert filing["entry_subtotal_points"] == pytest.approx(0.75, abs=0.01), (
            "round(0.351) is 0.35 for the TRANSMISSION line plus two RECEIPT lines "
            f"at round(0.195) = 0.20 each; got {filing['entry_subtotal_points']}"
        )
        assert filing["lateness_points"] == pytest.approx(2.25, abs=0.01), (
            f"three late days at 0.75 points; got {filing['lateness_points']}"
        )
        assert filing["penalty_points"] == pytest.approx(3.00, abs=0.01), (
            f"0.75 + 2.25 + 0.00; got {filing['penalty_points']}"
        )
        assert filing["status"] == "SUBMITTED", (
            f"a successful filing is stored in SUBMITTED, got {filing['status']}"
        )
        assert filing["reversal_reason"] is None, (
            "a successful filing is stored with reversal_reason null, got "
            f"{filing['reversal_reason']}"
        )

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(3.00, abs=0.01), (
            f"0.00 existing plus 3.00 is inside the ceiling; got "
            f"{station['penalty_points_total']}"
        )

    def test_amendment_is_rejected_against_the_existing_total_and_leaks_nothing(self):
        """PRD §3.7: "And last of all, the fiscal ceiling of §2.6 and §2.8 applies: the station's existing `penalty_points_total` plus the `penalty_points` this filing would compute must not exceed 5.00 points, otherwise `ERR_PENALTY_CEILING_EXCEEDED`."
        PRD §3.7: "An amendment reverses whichever earlier filing for the same event is still in `SUBMITTED` or `ACCEPTED`, moving that earlier row to `REVERSED` with its `reversal_reason` set to the literal string `SUPERSEDED_BY_AMENDMENT`, and sets the new filing's `superseded_filing_id` to the reversed row's `id`; a first filing on an event leaves `superseded_filing_id` null."

        Design: Difficulty/combinatorial_formula/penalty_ceiling_reads_pre_write_total_and_rejects_the_amendment
        """
        ctx = _station_with_three_days_late_filing_of_three_dollars()
        version_before = read_test_event_version(ctx["test_event_id"], OFFICER)

        payload = filing_record_payload(ctx["test_event_id"], version_before)
        payload["attestation_note"] = "amendment that would reverse filing #1"
        response = api_client.create_filing_record(payload, OFFICER)
        validate_error(response, "ERR_PENALTY_CEILING_EXCEEDED", 422)

        original = get_success_data(
            api_client.get_filing_record(ctx["filing_id"], ADMIN)
        )
        assert original["status"] == "SUBMITTED", (
            "the rejected amendment must not have reversed the earlier filing; got "
            f"{original['status']}"
        )
        assert original["reversal_reason"] is None, (
            "no SUPERSEDED_BY_AMENDMENT reason may be written by a rejected "
            f"amendment; got {original['reversal_reason']}"
        )
        assert original["superseded_filing_id"] is None, (
            "a first filing on an event leaves superseded_filing_id null; got "
            f"{original['superseded_filing_id']}"
        )

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(3.00, abs=0.01), (
            "the ledger is untouched by the rejected amendment; got "
            f"{station['penalty_points_total']}"
        )
        assert read_test_event_version(ctx["test_event_id"], OFFICER) == version_before, (
            "only a successful filing increments the test event's version"
        )
