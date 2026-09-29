"""Rejection precedence on `POST /filing-records`: which violation answers when
several are live on one request.

Each pair of tests is built so that the two candidate violations hold at the same
time, and then the winner is cured so the loser becomes observable. Every test
builds its own world from scratch — the harness restarts the API server before
each individual test, so the database is empty and the logical clock sits at its
startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    DEFAULT_LOG_INSTANT,
    DUAL_ENGINEER,
    DUAL_OFFICER,
    DUAL_ROLE_USER_ID,
    ENGINEER_USER_ID,
    OFFICER,
    TEST_DEFAULTS,
    add_registered_device,
    api_client,
    evaluate_readiness,
    filing_record_payload,
    get_success_data,
    schedule_test_event,
    set_clock,
    setup_logged_test_event,
    setup_station,
    validate_error,
    validate_paginated,
)

# Aliased on import: a module-level name beginning with "test_" would otherwise be
# collected as a test case.
from test_helpers import test_event_version as current_test_event_version

# ---------------------------------------------------------------------------
# Shared instants. The canonical weekly window is
# [2026-08-12T00:00:00Z, 2026-08-12T01:00:00Z), so filing_deadline_at is
# 2026-08-17T01:00:00Z and the ten-day grace period ends 2026-08-27T01:00:00Z.
# ---------------------------------------------------------------------------
PAST_GRACE_INSTANT = "2026-08-28T01:00:00Z"
INSIDE_GRACE_INSTANT = "2026-08-24T01:00:00Z"

DUAL_ROLE_STATION = {
    "required_source_types": ("PEP", "NWS"),
    "call_sign": TEST_DEFAULTS["DUAL_ROLE_CALL_SIGN"],
    "engineer_user_ids": [DUAL_ROLE_USER_ID],
    "certification_officer_user_id": DUAL_ROLE_USER_ID,
    "engineer_headers": DUAL_ENGINEER,
}


def _filing_attempt(test_event_id, expected_test_event_version, headers, note):
    """Post a filing whose version guard is supplied explicitly, returning the
    raw response so a rejection can be inspected."""
    payload = filing_record_payload(test_event_id, expected_test_event_version)
    payload["attestation_note"] = note
    return api_client.create_filing_record(payload, headers)


def _filing_count(test_event_id):
    """How many filing records exist for one test event."""
    _, meta = validate_paginated(
        api_client.list_filing_records(ADMIN, {"test_event_id": test_event_id})
    )
    return meta["total_count"]


def _station_with_event_stuck_in_readiness_pending():
    """A station whose test event scores 60.00 twice, so it stays in
    READINESS_PENDING while the second evaluation makes the first version stale.

    One READY device and one REGISTERED device put the device ratio at 1/2, the
    single ACTIVE PEP assignment puts the coverage ratio at 1/1 and no alert has
    been logged, so 40 * 1/2 + 40 * 1/1 + 20 * 0 = 60.00.
    """
    ctx = setup_station()
    add_registered_device(ctx, device_role="MONITOR", firmware_version="5.2.0")
    event = schedule_test_event(ctx["station_id"])
    set_clock(DEFAULT_LOG_INSTANT)
    ctx["first_evaluation"] = evaluate_readiness(event["id"])
    ctx["second_evaluation"] = evaluate_readiness(event["id"])
    ctx["test_event_id"] = event["id"]
    return ctx


def _dual_role_station_with_logged_event(receipt_source_types):
    """A one-person station — the same opaque identifier is both the only
    engineer and the certifying officer — with a LOGGED test event whose log
    lines were all appended by that identifier."""
    ctx = setup_station(**DUAL_ROLE_STATION)
    return setup_logged_test_event(ctx, receipt_source_types=receipt_source_types)


class TestConcurrencyOutranksTestEventState:
    """A stale version guard answers before the event's status is inspected."""

    def test_stale_test_event_version_answers_before_the_status_check(self):
        """PRD §2.8: "When a single request violates more than one rule, the response reports the violation with the lowest ladder position below."
        PRD §2.8: "The ladder is evaluated strictly in this order, and a check never runs before every lower-numbered check has passed."
        PRD §2.7: "If that value does not equal the test event's current `version`, the filing is rejected with `ERR_STALE_TEST_EVENT_VERSION` and HTTP 412."
        PRD §3.6: "Every evaluation overwrites both `readiness_score` and `readiness_evaluated_at`, so a re-run replaces rather than supplements the earlier figures."
        PRD §2.5: "Most resources — state plans, stations, relay rules, EAS devices, monitoring assignments, equipment outages, alert events, test events, filing records and inspection requests — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increases by one on every mutation of that row."

        Design: Difficulty/priority_pair_validation_conflict/occ_priority_6_beats_test_not_logged_priority_7
        """
        ctx = _station_with_event_stuck_in_readiness_pending()
        first = ctx["first_evaluation"]
        second = ctx["second_evaluation"]

        for label, evaluation in (("first", first), ("second", second)):
            assert evaluation["readiness_score"] == pytest.approx(60.00, abs=0.01), (
                f"{label} evaluation: 40 * 1/2 + 40 * 1/1 + 20 * 0 is 60.00, got "
                f"{evaluation['readiness_score']}"
            )
            assert evaluation["status"] == "READINESS_PENDING", (
                f"{label} evaluation scored below 80.00, so the event stays "
                f"READINESS_PENDING, got {evaluation['status']}"
            )
        assert second["version"] == first["version"] + 1, (
            "the re-run overwrites readiness_score and readiness_evaluated_at, which "
            f"is a mutation: expected version {first['version'] + 1}, got "
            f"{second['version']}"
        )

        response = _filing_attempt(
            ctx["test_event_id"],
            first["version"],
            OFFICER,
            "filed from a stale view of the test event",
        )
        validate_error(response, "ERR_STALE_TEST_EVENT_VERSION", 412)

        assert _filing_count(ctx["test_event_id"]) == 0, (
            "a rejected filing stores no FilingRecord row"
        )

    def test_test_event_status_check_answers_once_the_version_guard_is_fresh(self):
        """PRD §2.8: "When a single request violates more than one rule, the response reports the violation with the lowest ladder position below."
        PRD §3.7: "The event's `status` must be `LOGGED` or `FILED`; anything else is rejected with `ERR_TEST_NOT_LOGGED`, except that an event already in `FAILED_UNFILED` is rejected with the more specific `ERR_TEST_ALREADY_FAILED_UNFILED`."

        Design: Difficulty/priority_pair_validation_conflict/occ_priority_6_beats_test_not_logged_priority_7
        """
        ctx = _station_with_event_stuck_in_readiness_pending()
        fresh_version = ctx["second_evaluation"]["version"]

        response = _filing_attempt(
            ctx["test_event_id"],
            fresh_version,
            OFFICER,
            "same body, current version",
        )
        validate_error(response, "ERR_TEST_NOT_LOGGED", 409)

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "READINESS_PENDING", (
            f"the rejected filing changed no status, got {event['status']}"
        )
        assert event["readiness_score"] == pytest.approx(60.00, abs=0.01), (
            f"readiness_score is untouched by the rejection, got {event['readiness_score']}"
        )
        assert _filing_count(ctx["test_event_id"]) == 0, (
            "a rejected filing stores no FilingRecord row"
        )


class TestReceiptCoverageOutranksSegregationOfDuties:
    """Both violations are 422s on the same request; coverage answers first."""

    def test_receipt_coverage_answers_while_the_filer_is_also_the_logger(self):
        """PRD §3.7: "Six substantive gates apply once the identity, schema, existence, ownership and version checks of §2.8 have passed, and they are evaluated in the ladder order given there."
        PRD §3.7: "Every source type listed in the governing plan's `required_source_types` must have at least one `RECEIPT` log line on that event; if any required source type has none, the filing is rejected with `ERR_RECEIPT_COVERAGE_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/receipt_coverage_priority_9_beats_segregation_of_duties_priority_11
        """
        # The plan requires PEP and NWS; only the PEP source gets a RECEIPT line.
        ctx = _dual_role_station_with_logged_event(receipt_source_types=("PEP",))

        for entry in ctx["log_entries"]:
            assert entry["logged_by_user_id"] == DUAL_ROLE_USER_ID, (
                "every log line was appended by the operator who will also file, so "
                "the segregation-of-duties violation is live too, got "
                f"{entry['logged_by_user_id']}"
            )

        response = _filing_attempt(
            ctx["test_event_id"],
            current_test_event_version(ctx["test_event_id"], DUAL_OFFICER),
            DUAL_OFFICER,
            "coverage gap plus self-filing",
        )
        validate_error(response, "ERR_RECEIPT_COVERAGE_INCOMPLETE", 422)

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "LOGGED", (
            f"the rejected filing left the event in LOGGED, got {event['status']}"
        )
        assert _filing_count(ctx["test_event_id"]) == 0, (
            "a rejected filing stores no FilingRecord row"
        )

    def test_segregation_of_duties_answers_once_receipt_coverage_is_complete(self):
        """PRD §3.7: "Six substantive gates apply once the identity, schema, existence, ownership and version checks of §2.8 have passed, and they are evaluated in the ladder order given there."
        PRD §2.12: "A `CertifyingOfficer` filing post-test results must not be the same operator who produced any of the evidence: if the acting `X-User-ID` equals the `logged_by_user_id` recorded on **any** `TestLogEntry` belonging to that test event, the filing is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/receipt_coverage_priority_9_beats_segregation_of_duties_priority_11
        """
        # Both required source types now carry a RECEIPT line, so the coverage gate
        # is satisfied and only the segregation-of-duties gate remains live.
        ctx = _dual_role_station_with_logged_event(receipt_source_types=("PEP", "NWS"))

        response = _filing_attempt(
            ctx["test_event_id"],
            current_test_event_version(ctx["test_event_id"], DUAL_OFFICER),
            DUAL_OFFICER,
            "coverage complete, still self-filing",
        )
        validate_error(response, "ERR_SEGREGATION_OF_DUTIES", 422)

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(0.00, abs=0.01), (
            "no filing landed, so the penalty ledger is untouched, got "
            f"{station['penalty_points_total']}"
        )
        assert _filing_count(ctx["test_event_id"]) == 0, (
            "a rejected filing stores no FilingRecord row"
        )


class TestFilingDeadlineOutranksPenaltyCeiling:
    """The clock-relative deadline answers before the fiscal ceiling is priced."""

    def test_filing_deadline_answers_when_the_grace_period_has_expired(self):
        """PRD §3.7: "Six substantive gates apply once the identity, schema, existence, ownership and version checks of §2.8 have passed, and they are evaluated in the ladder order given there."
        PRD §3.7: "The logical clock must be at or before `filing_deadline_at` plus a ten-day grace period; past that the filing is rejected with `ERR_FILING_DEADLINE_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/filing_deadline_priority_10_beats_penalty_ceiling_priority_12
        """
        ctx = setup_logged_test_event()
        assert len(ctx["log_entries"]) == 2, (
            "one TRANSMISSION and one RECEIPT line, so receipt coverage is complete"
        )

        # 2026-08-28T01:00:00Z is past filing_deadline_at 2026-08-17T01:00:00Z plus
        # the ten-day grace period, i.e. past 2026-08-27T01:00:00Z. The penalty this
        # filing would price also blows the 5.00 ceiling, but that gate never runs.
        set_clock(PAST_GRACE_INSTANT)
        response = _filing_attempt(
            ctx["test_event_id"],
            current_test_event_version(ctx["test_event_id"], OFFICER),
            OFFICER,
            "filed 11 days late",
        )
        validate_error(response, "ERR_FILING_DEADLINE_PASSED", 422)

        event = get_success_data(api_client.get_test_event(ctx["test_event_id"], ADMIN))
        assert event["status"] == "LOGGED", (
            f"the rejected filing left the event in LOGGED, got {event['status']}"
        )
        assert _filing_count(ctx["test_event_id"]) == 0, (
            "a rejected filing stores no FilingRecord row"
        )

    def test_penalty_ceiling_answers_once_the_filing_is_inside_the_grace_period(self):
        """PRD §3.7: "Six substantive gates apply once the identity, schema, existence, ownership and version checks of §2.8 have passed, and they are evaluated in the ladder order given there."
        PRD §3.7: "And last of all, the fiscal ceiling of §2.6 and §2.8 applies: the station's existing `penalty_points_total` plus the `penalty_points` this filing would compute must not exceed 5.00 points, otherwise `ERR_PENALTY_CEILING_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/filing_deadline_priority_10_beats_penalty_ceiling_priority_12
        """
        ctx = setup_logged_test_event()

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(0.00, abs=0.01), (
            "the station carries no accumulated penalty points yet, got "
            f"{station['penalty_points_total']}"
        )

        # 2026-08-24T01:00:00Z is seven days past filing_deadline_at
        # 2026-08-17T01:00:00Z and therefore still inside the ten-day grace period,
        # so the deadline gate is quiet and the ceiling gate becomes observable:
        # entry_subtotal 0.82 + 0.46 = 1.28 plus lateness 5.25 is 6.53 > 5.00.
        set_clock(INSIDE_GRACE_INSTANT)
        response = _filing_attempt(
            ctx["test_event_id"],
            current_test_event_version(ctx["test_event_id"], OFFICER),
            OFFICER,
            "same body, inside the grace window",
        )
        validate_error(response, "ERR_PENALTY_CEILING_EXCEEDED", 422)

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["penalty_points_total"] == pytest.approx(0.00, abs=0.01), (
            "the rejected filing charged nothing to the ledger, got "
            f"{station['penalty_points_total']}"
        )
        assert _filing_count(ctx["test_event_id"]) == 0, (
            "a rejected filing stores no FilingRecord row"
        )
        for entry in ctx["log_entries"]:
            assert entry["logged_by_user_id"] == ENGINEER_USER_ID, (
                "the evidence was produced by the engineer, not the filing officer, "
                "so the segregation-of-duties gate stays quiet, got "
                f"{entry['logged_by_user_id']}"
            )
