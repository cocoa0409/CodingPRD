"""Consistency-model corners: what a single write already knows when it answers.

Alert logging resolves duplicate suppression and relay-rule selection inside its own
request, and filing computes every penalty figure and resynchronises the station ledger
inside its own request — so the create response and the next read never disagree.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    OFFICER,
    SOURCE_CALL_SIGNS,
    TEST_DEFAULTS,
    alert_event_payload,
    api_client,
    append_log_entry,
    assert_matched_rule,
    assert_not_suppressed,
    assert_score_and_posture,
    assert_suppressed,
    create_relay_rule,
    evaluate_readiness,
    filing_record_payload,
    schedule_test_event,
    set_clock,
    setup_station,
    station_summary,
    test_event_version as read_test_event_version,
    validate_success,
)

ALERT_SEQUENCE = "KSAXS-9501"


# ---------------------------------------------------------------------------
# Alert logging: the whole decision tree resolves before the create returns
# ---------------------------------------------------------------------------
def _relay_scope():
    """Covered station plus one ACTIVE MANDATORY TOR rule with a 120-second delay."""
    ctx = setup_station(required_source_types=("PEP",))
    ctx["rule"] = create_relay_rule(
        ctx["plan_id"],
        event_code="TOR",
        fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        relay_class="MANDATORY",
        priority=1,
        forward_delay_seconds=120,
    )
    ctx["rule_id"] = ctx["rule"]["id"]
    set_clock("2026-08-12T08:00:00Z")
    return ctx


def _log_first_alert(ctx, received_at="2026-08-12T08:00:00Z"):
    return validate_success(
        api_client.create_alert_event(
            alert_event_payload(
                ctx["station_id"],
                received_at,
                event_code="TOR",
                originator_sequence=ALERT_SEQUENCE,
                fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
            ),
            ENGINEER,
        ),
        201,
    )


def test_alert_create_already_carries_the_selector_verdict():
    """PRD §3.5: "Logging a received alert is a single `StationEngineer` write that resolves an entire decision tree before it returns."
    PRD §3.5: "The forwarding dimension is `relay_state`, which begins at `RECEIVED` and settles into `RELAY_PENDING`, `UNMATCHED_OPTIONAL` or `SUPPRESSED_DUPLICATE` before the create returns — because the whole decision runs inside that one request, `RECEIVED` is never observable in a response body."
    PRD §3.5: "When a rule is selected, the alert moves `RECEIVED` → `RELAY_PENDING`, `matched_relay_rule_id` is set to that rule's `id`, and `forward_delay_seconds_applied` is copied from the rule's `forward_delay_seconds`."
    PRD §3.5: "The effective `relay_class_applied` is `MANDATORY` when either the selected rule's `relay_class` is `MANDATORY` **or** the alert's `event_code` appears in the governing plan's `mandatory_relay_event_codes`; otherwise it is `OPTIONAL`."
    PRD §3.5: "The accessibility dimension is `accessibility_state`, which begins at `ACCESSIBILITY_UNVERIFIED` and ends at either `ACCESSIBILITY_PASSED` or `ACCESSIBILITY_FAILED`."

    Design: Corner/consistency_model/alert_create_resolves_selector_and_suppression_inside_its_own_response
    """
    ctx = _relay_scope()

    created = _log_first_alert(ctx)
    assert_matched_rule(created, ctx["rule_id"], "MANDATORY", 120)
    assert_not_suppressed(created)
    assert created["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED"

    read_back = validate_success(api_client.get_alert_event(created["id"], ADMIN))
    assert read_back == created, (
        "the create response already carried the settled decision, so the immediate "
        "read must agree with it"
    )


def test_alert_create_already_carries_the_station_repeat_suppression_verdict():
    """PRD §3.5: "Its pool is every existing alert row of the *same* `station_id` with the *same* `originator_sequence` and the *same* `event_code`, regardless of that row's `relay_state`."
    PRD §3.5: "The phase A window is **half-open**: it starts 900 seconds — fifteen minutes — before the reference instant, with that lower bound included, and ends at the reference instant itself, with that upper bound excluded."
    PRD §3.5: "If any pool row's `received_at` falls inside that window, the new alert is suppressed by moving `RECEIVED` → `SUPPRESSED_DUPLICATE`: `suppression_source` becomes `STATION_REPEAT`, and `suppression_reference_alert_id` is set to the `id` of the pool row with the greatest `received_at`, breaking a tie on equal `received_at` by taking the row with the earliest `created_at`."
    PRD §3.5: "If neither phase fires, `suppression_source` is `NONE`, and in that case `matched_relay_rule_id` and `relay_class_applied` are decided by the selector rather than being left at their suppressed defaults; a suppressed alert keeps `matched_relay_rule_id` null and `relay_class_applied` `NONE`, since the selector is skipped."

    Design: Corner/consistency_model/alert_create_resolves_selector_and_suppression_inside_its_own_response
    """
    ctx = _relay_scope()
    first = _log_first_alert(ctx)

    set_clock("2026-08-12T08:10:00Z")
    repeat = validate_success(
        api_client.create_alert_event(
            alert_event_payload(
                ctx["station_id"],
                "2026-08-12T08:10:00Z",
                event_code="TOR",
                originator_sequence=ALERT_SEQUENCE,
                fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
            ),
            ENGINEER,
        ),
        201,
    )
    assert_suppressed(repeat, "STATION_REPEAT", first["id"])

    read_back = validate_success(api_client.get_alert_event(repeat["id"], ADMIN))
    assert read_back == repeat, (
        "suppression was decided inside the create, so the immediate read must agree"
    )

    unchanged_first = validate_success(api_client.get_alert_event(first["id"], ADMIN))
    assert unchanged_first["relay_state"] == "RELAY_PENDING", (
        "the reference row keeps its own forwarding verdict"
    )


def test_confirm_relay_response_shows_relayed_without_touching_accessibility():
    """PRD §3.5: "Confirming that the forward actually went out moves the alert `RELAY_PENDING` → `RELAYED`; attempting it on an alert whose `relay_state` is anything else is rejected with `ERR_ALERT_NOT_RELAY_PENDING`."
    PRD §3.5: "Confirmation touches only the forwarding dimension and leaves `accessibility_state` exactly as it was."

    Design: Corner/consistency_model/alert_create_resolves_selector_and_suppression_inside_its_own_response
    """
    ctx = _relay_scope()
    created = _log_first_alert(ctx)
    assert created["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED"

    confirmed = validate_success(api_client.confirm_relay(created["id"], ENGINEER))
    assert confirmed["relay_state"] == "RELAYED"
    assert confirmed["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED"
    assert confirmed["matched_relay_rule_id"] == ctx["rule_id"]
    assert confirmed["forward_delay_seconds_applied"] == 120

    read_back = validate_success(api_client.get_alert_event(created["id"], ADMIN))
    assert read_back == confirmed, (
        "the confirmation response is already the settled row"
    )


# ---------------------------------------------------------------------------
# Filing: every derived figure lands in the create response, ledger included
# ---------------------------------------------------------------------------
def _late_filing_scope():
    """A LOGGED test event whose window closed on 2026-08-05, with two log lines.

    ``filing_deadline_at`` derives as 2026-08-10T01:00:00Z, so filing at
    2026-08-13T01:00:00Z is exactly three whole days late.
    """
    ctx = setup_station(required_source_types=("PEP",))
    event = schedule_test_event(
        ctx["station_id"], "2026-08-05T00:00:00Z", "2026-08-05T01:00:00Z"
    )
    set_clock("2026-08-04T00:00:00Z")
    event = evaluate_readiness(event["id"])
    assert event["status"] == "READY"
    assert event["readiness_score"] == pytest.approx(80.00, abs=0.01)

    set_clock("2026-08-05T00:30:00Z")
    append_log_entry(
        event["id"],
        ctx["device_id"],
        "RECEIPT",
        source_call_sign=SOURCE_CALL_SIGNS["PEP"],
    )
    append_log_entry(event["id"], ctx["device_id"], "TRANSMISSION")
    ctx["test_event"] = validate_success(
        api_client.close_logging(event["id"], ENGINEER)
    )
    ctx["test_event_id"] = event["id"]
    ctx["event_version_before_filing"] = ctx["test_event"]["version"]
    return ctx


def test_filing_create_returns_every_derived_penalty_figure():
    """PRD §3.7: "Lateness comes first: `late_days` is 0 when `filed_at` is at or before the event's `filing_deadline_at`, and otherwise the number of whole days obtained by dividing the elapsed time between `filing_deadline_at` and `filed_at` by 86400 seconds and rounding that quotient **up** to the next whole number — so any part of a day late counts as a full day late."
    PRD §3.7: "Each log line of the event carries a kind weight: 1.0 for a `RECEIPT` line and 1.8 for a `TRANSMISSION` line."
    PRD §3.7: "For each log line — taking every line whose `test_event_id` matches, in `created_at` ascending order, with no status filter whatsoever since log lines have no status — multiply `late_days` by a per-entry late rate of 0.065 points and by that line's kind weight, and **round that per-line product half-up to two decimal places immediately**."
    PRD §3.7: "Sum the rounded per-line values to obtain `entry_subtotal_points`."
    PRD §3.7: "`lateness_points` is `late_days` multiplied by 0.75 points per late day, rounded half-up to two decimals."
    PRD §3.7: "`penalty_points` is then the smaller of a per-filing cap of 25.00 points and the sum of `entry_subtotal_points`, `lateness_points` and `unconfirmed_relay_points`, rounded half-up to two decimal places."
    PRD §3.7: "The filing stamps `filed_at` from the logical clock and records the acting `X-User-ID` as `filed_by_user_id`."

    Design: Corner/consistency_model/filing_create_returns_every_derived_figure_and_the_ledger_is_current_on_the_next_read
    """
    ctx = _late_filing_scope()
    assert ctx["test_event"]["filing_deadline_at"].startswith("2026-08-10T01:00:00")

    set_clock("2026-08-13T01:00:00Z")
    filing = validate_success(
        api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], read_test_event_version(ctx["test_event_id"], OFFICER)
            ),
            OFFICER,
        ),
        201,
    )

    assert filing["status"] == "SUBMITTED"
    assert filing["late_days"] == 3
    assert filing["entry_subtotal_points"] == pytest.approx(0.55, abs=0.01)
    assert filing["lateness_points"] == pytest.approx(2.25, abs=0.01)
    assert filing["unconfirmed_relay_points"] == pytest.approx(0.00, abs=0.01)
    assert filing["penalty_points"] == pytest.approx(2.80, abs=0.01)
    assert filing["filed_by_user_id"] == "cert-1"
    assert filing["filed_at"].startswith("2026-08-13T01:00:00"), (
        f"filed_at is stamped from the logical clock, got {filing['filed_at']}"
    )

    read_back = validate_success(api_client.get_filing_record(filing["id"], OFFICER))
    assert read_back == filing, (
        "every figure was computed inside the create, so the read agrees with it"
    )


def test_station_ledger_is_current_on_the_read_after_the_filing():
    """PRD §3.7: "Finally the station's ledger is resynchronised: `penalty_points_total` becomes the sum of `penalty_points` across all of that station's filing records whose `status` is `SUBMITTED` or `ACCEPTED`, rounded half-up to two decimal places."
    PRD §3.7: "A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."
    PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."
    PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
    PRD §3.6: "It raises the event's `logged_entry_count` by one."

    Design: Corner/consistency_model/filing_create_returns_every_derived_figure_and_the_ledger_is_current_on_the_next_read
    """
    ctx = _late_filing_scope()

    set_clock("2026-08-13T01:00:00Z")
    filing = validate_success(
        api_client.create_filing_record(
            filing_record_payload(
                ctx["test_event_id"], read_test_event_version(ctx["test_event_id"], OFFICER)
            ),
            OFFICER,
        ),
        201,
    )
    assert filing["penalty_points"] == pytest.approx(2.80, abs=0.01)

    station = validate_success(api_client.get_station(ctx["station_id"], ADMIN))
    assert station["penalty_points_total"] == pytest.approx(2.80, abs=0.01), (
        "the ledger is already resynchronised on the very next read of the station"
    )

    summary = station_summary(ctx["station_id"])
    assert summary["penalty_points_total"] == pytest.approx(2.80, abs=0.01)
    assert summary["compliance_variant_applied"] == "PROVISIONAL"
    assert_score_and_posture(summary, 100.00, "COMPLIANT")
    assert summary["unfiled_test_count"] == 0

    event = validate_success(
        api_client.get_test_event(ctx["test_event_id"], OFFICER)
    )
    assert event["status"] == "FILED"
    assert event["logged_entry_count"] == 2
    assert event["version"] > ctx["event_version_before_filing"]
