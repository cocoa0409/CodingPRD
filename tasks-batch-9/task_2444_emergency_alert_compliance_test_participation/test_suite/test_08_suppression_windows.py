"""Temporal windows that decide whether two resources collide.

Three windows are exercised here, each with inside / outside probes pinned to
the second: the half-open test-event window that decides
`ERR_TEST_WINDOW_OVERLAP`, the closed and buffered wireless-notice window of
duplicate-suppression phase B, and the half-open station-repeat window of
phase A.
"""

import pytest

from test_helpers import (
    ADMIN,
    CLOCK_DEFAULT,
    TEST_DEFAULTS,
    ApiErrorId,
    api_client,
    assert_matched_rule,
    assert_not_suppressed,
    assert_suppressed,
    assert_unmatched,
    create_active_plan,
    create_relay_rule,
    log_alert,
    record_wireless_notice,
    register_station,
    schedule_test_event,
    set_clock,
    test_event_payload as make_test_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical test window every overlap probe is measured against.
TE1_START = "2026-08-12T00:00:00Z"
TE1_END = "2026-08-12T01:00:00Z"

# Duplicate-suppression probes are logged with the clock ahead of every
# operator-supplied received_at, so ERR_ALERT_RECEIVED_IN_FUTURE never applies.
PROBE_CLOCK = "2026-08-12T13:00:00Z"
WEA_SENT_AT = "2026-08-12T12:00:00Z"
BASE_RECEIVED_AT = "2026-08-12T12:00:00Z"
IN_AREA_FIPS = TEST_DEFAULTS["FIPS_CODE"]
OTHER_AREA_FIPS = TEST_DEFAULTS["OTHER_FIPS_CODE"]


# ---------------------------------------------------------------------------
# Local setup built out of the shared primitives
# ---------------------------------------------------------------------------
def _two_stations_and_one_scheduled_window():
    """Two stations on one active plan, with the canonical window booked on the first."""
    set_clock(CLOCK_DEFAULT)
    plan = create_active_plan(required_source_types=("PEP",))
    station_a = register_station(plan["id"], call_sign=TEST_DEFAULTS["CALL_SIGN"])
    station_b = register_station(
        plan["id"], call_sign=TEST_DEFAULTS["SECOND_CALL_SIGN"], service_type="FM"
    )
    booked = schedule_test_event(station_a["id"], TE1_START, TE1_END)
    return station_a, station_b, booked


def _schedule(station_id, window_start_at, window_end_at, test_type="WEEKLY"):
    return api_client.create_test_event(
        make_test_event_payload(
            station_id,
            window_start_at=window_start_at,
            window_end_at=window_end_at,
            test_type=test_type,
        ),
        ADMIN,
    )


def _station_with_statewide_optional_rule():
    """A station whose plan carries exactly one statewide OPTIONAL rule for TOR, so
    every non-suppressed TOR alert must settle on RELAY_PENDING / OPTIONAL / 25 s."""
    set_clock(PROBE_CLOCK)
    plan = create_active_plan(
        required_source_types=("PEP",), mandatory_relay_event_codes=()
    )
    station = register_station(plan["id"])
    rule = create_relay_rule(
        plan["id"],
        event_code="TOR",
        fips_codes=[],
        relay_class="OPTIONAL",
        priority=20,
        forward_delay_seconds=25,
    )
    return station, rule


class TestTestEventWindowOverlap:
    def test_windows_that_only_share_an_endpoint_are_both_accepted(self):
        """PRD §3.6: "Because both intervals are half-open, one window ending at exactly the instant the next begins is not an overlap."
        PRD §3.6: "A newly scheduled event sits in `SCHEDULED` with `readiness_score` and `readiness_evaluated_at` null, `logged_entry_count` 0 and `retention_until_max` null, and the server derives `filing_deadline_at` at create time as `window_end_at` plus five days."

        Design: Difficulty/resource_temporal_overlap/test_window_half_open_adjacency_versus_one_second_intersection
        """
        station_a, _station_b, _booked = _two_stations_and_one_scheduled_window()

        abuts_start = validate_success(
            _schedule(station_a["id"], "2026-08-11T23:00:00Z", TE1_START), 201
        )
        assert abuts_start["status"] == "SCHEDULED"
        assert abuts_start["filing_deadline_at"].startswith("2026-08-17T00:00:00")
        assert abuts_start["version"] == 1

        abuts_end = validate_success(
            _schedule(station_a["id"], TE1_END, "2026-08-12T02:00:00Z"), 201
        )
        assert abuts_end["status"] == "SCHEDULED"
        assert abuts_end["filing_deadline_at"].startswith("2026-08-17T02:00:00")
        assert abuts_end["version"] == 1

        read_back = validate_success(
            api_client.get_test_event(abuts_end["id"], ADMIN), 200
        )
        assert read_back["filing_deadline_at"] == abuts_end["filing_deadline_at"]

    @pytest.mark.parametrize(
        "window_start_at,window_end_at",
        [
            ("2026-08-12T00:59:59Z", "2026-08-12T01:00:00Z"),
            ("2026-08-12T00:10:00Z", "2026-08-12T00:20:00Z"),
        ],
        ids=["one_second_intersection", "strictly_contained"],
    )
    def test_intersecting_window_is_rejected(self, window_start_at, window_end_at):
        """PRD §3.6: "And the proposed half-open interval running from `window_start_at` up to but not including `window_end_at` must not intersect the same interval of any other test event of that station whose `status` is anything other than `FAILED_UNFILED`; an intersection is rejected with `ERR_TEST_WINDOW_OVERLAP`, which is the one member of the clock-relative family carrying HTTP 409 rather than 422."

        Design: Difficulty/resource_temporal_overlap/test_window_half_open_adjacency_versus_one_second_intersection
        """
        station_a, _station_b, _booked = _two_stations_and_one_scheduled_window()

        validate_error(
            _schedule(station_a["id"], window_start_at, window_end_at, "MONTHLY"),
            ApiErrorId.ERR_TEST_WINDOW_OVERLAP,
            409,
        )

    def test_the_identical_window_is_accepted_for_another_station(self):
        """PRD §3.6: "And the proposed half-open interval running from `window_start_at` up to but not including `window_end_at` must not intersect the same interval of any other test event of that station whose `status` is anything other than `FAILED_UNFILED`; an intersection is rejected with `ERR_TEST_WINDOW_OVERLAP`, which is the one member of the clock-relative family carrying HTTP 409 rather than 422."

        Design: Difficulty/resource_temporal_overlap/test_window_half_open_adjacency_versus_one_second_intersection
        """
        _station_a, station_b, booked = _two_stations_and_one_scheduled_window()

        twin = validate_success(_schedule(station_b["id"], TE1_START, TE1_END), 201)
        assert twin["status"] == "SCHEDULED"
        assert twin["station_id"] == station_b["id"]
        assert twin["id"] != booked["id"], "the overlap check is scoped to one station"


class TestWirelessNoticeSuppressionWindow:
    @pytest.mark.parametrize(
        "received_at,expect_suppressed",
        [
            ("2026-08-12T12:32:00Z", True),
            ("2026-08-12T12:32:01Z", False),
            ("2026-08-12T11:58:00Z", True),
            ("2026-08-12T11:57:59Z", False),
        ],
        ids=["upper_bound_inside", "upper_bound_outside", "lower_bound_inside", "lower_bound_outside"],
    )
    def test_phase_b_window_is_closed_at_both_ends(self, received_at, expect_suppressed):
        """PRD §3.5: "For each such notice the phase B window is **closed at both ends**: it starts 120 seconds before that notice's `wea_sent_at` and ends 1800 seconds plus 120 seconds after it — that is, from two minutes before the wireless send to thirty-two minutes after it — with both bounds included."
        PRD §3.5: "When both conditions hold, the alert again moves `RECEIVED` → `SUPPRESSED_DUPLICATE`, `suppression_source` becomes `WIRELESS_NOTICE`, and `suppression_reference_alert_id` is left null — the suppressing artefact is a carrier notice, not an alert row, so there is nothing to point at."
        PRD §3.5: "If neither phase fires, `suppression_source` is `NONE`, and in that case `matched_relay_rule_id` and `relay_class_applied` are decided by the selector rather than being left at their suppressed defaults; a suppressed alert keeps `matched_relay_rule_id` null and `relay_class_applied` `NONE`, since the selector is skipped."

        Design: Difficulty/resource_temporal_overlap/wea_phase_b_closed_buffered_window_and_fips_intersection_gate
        """
        station, rule = _station_with_statewide_optional_rule()
        record_wireless_notice(
            station["id"],
            WEA_SENT_AT,
            originator_sequence="KSWEA-0101",
            event_code="TOR",
            fips_codes=[IN_AREA_FIPS],
        )

        alert = log_alert(
            station["id"],
            received_at,
            event_code="TOR",
            originator_sequence="KSWEA-0101",
            fips_codes=[IN_AREA_FIPS],
        )

        if expect_suppressed:
            assert_suppressed(alert, "WIRELESS_NOTICE", None)
        else:
            assert_not_suppressed(alert)
            assert_matched_rule(alert, rule["id"], "OPTIONAL", 25)

    def test_phase_b_also_requires_a_shared_fips_code(self):
        """PRD §3.5: "Suppression additionally requires that the notice's `fips_codes` and the alert's `fips_codes` share at least one code; a notice whose window contains the reference instant but whose FIPS set is disjoint from the alert's does not suppress."

        Design: Difficulty/resource_temporal_overlap/wea_phase_b_closed_buffered_window_and_fips_intersection_gate
        """
        station, rule = _station_with_statewide_optional_rule()
        record_wireless_notice(
            station["id"],
            WEA_SENT_AT,
            originator_sequence="KSWEA-0105",
            event_code="TOR",
            fips_codes=[OTHER_AREA_FIPS],
        )

        alert = log_alert(
            station["id"],
            "2026-08-12T12:10:00Z",
            event_code="TOR",
            originator_sequence="KSWEA-0105",
            fips_codes=[IN_AREA_FIPS],
        )

        assert_not_suppressed(alert)
        assert_matched_rule(alert, rule["id"], "OPTIONAL", 25)


class TestStationRepeatSuppressionWindow:
    @pytest.mark.parametrize(
        "received_at,expect_suppressed",
        [
            ("2026-08-12T12:15:00Z", True),
            ("2026-08-12T12:15:01Z", False),
            ("2026-08-12T12:00:00Z", False),
        ],
        ids=["lower_bound_inside", "lower_bound_outside", "same_instant_excluded"],
    )
    def test_phase_a_window_includes_its_lower_bound_and_excludes_the_reference_instant(
        self, received_at, expect_suppressed
    ):
        """PRD §3.5: "The phase A window is **half-open**: it starts 900 seconds — fifteen minutes — before the reference instant, with that lower bound included, and ends at the reference instant itself, with that upper bound excluded."
        PRD §3.5: "If any pool row's `received_at` falls inside that window, the new alert is suppressed by moving `RECEIVED` → `SUPPRESSED_DUPLICATE`: `suppression_source` becomes `STATION_REPEAT`, and `suppression_reference_alert_id` is set to the `id` of the pool row with the greatest `received_at`, breaking a tie on equal `received_at` by taking the row with the earliest `created_at`."

        Design: Difficulty/resource_temporal_overlap/station_repeat_phase_a_half_open_window_ignores_fips_and_picks_latest_reference
        """
        station, rule = _station_with_statewide_optional_rule()
        base = log_alert(
            station["id"],
            BASE_RECEIVED_AT,
            event_code="TOR",
            originator_sequence="KSREP-0201",
            fips_codes=[IN_AREA_FIPS],
        )
        assert_not_suppressed(base)

        probe = log_alert(
            station["id"],
            received_at,
            event_code="TOR",
            originator_sequence="KSREP-0201",
            fips_codes=[IN_AREA_FIPS],
        )

        if expect_suppressed:
            assert_suppressed(probe, "STATION_REPEAT", base["id"])
        else:
            assert_not_suppressed(probe)
            assert_matched_rule(probe, rule["id"], "OPTIONAL", 25)

    def test_phase_a_compares_no_fips_codes_at_all(self):
        """PRD §3.5: "No buffer is applied and no FIPS comparison is made in phase A."

        Design: Difficulty/resource_temporal_overlap/station_repeat_phase_a_half_open_window_ignores_fips_and_picks_latest_reference
        """
        station, _rule = _station_with_statewide_optional_rule()
        base = log_alert(
            station["id"],
            BASE_RECEIVED_AT,
            event_code="TOR",
            originator_sequence="KSREP-0204",
            fips_codes=[IN_AREA_FIPS],
        )

        probe = log_alert(
            station["id"],
            "2026-08-12T12:10:00Z",
            event_code="TOR",
            originator_sequence="KSREP-0204",
            fips_codes=[OTHER_AREA_FIPS],
        )

        assert_suppressed(probe, "STATION_REPEAT", base["id"])

    def test_phase_a_pool_keys_on_event_code_as_well_as_sequence(self):
        """PRD §3.5: "Its pool is every existing alert row of the *same* `station_id` with the *same* `originator_sequence` and the *same* `event_code`, regardless of that row's `relay_state`."
        PRD §3.5: "When the candidate pool is empty the alert moves `RECEIVED` → `UNMATCHED_OPTIONAL`, `matched_relay_rule_id` stays null, `relay_class_applied` stays `NONE` and `forward_delay_seconds_applied` stays 0."

        Design: Difficulty/resource_temporal_overlap/station_repeat_phase_a_half_open_window_ignores_fips_and_picks_latest_reference
        """
        station, _rule = _station_with_statewide_optional_rule()
        log_alert(
            station["id"],
            BASE_RECEIVED_AT,
            event_code="TOR",
            originator_sequence="KSREP-0204",
            fips_codes=[IN_AREA_FIPS],
        )

        other_event = log_alert(
            station["id"],
            "2026-08-12T12:10:30Z",
            event_code="RWT",
            originator_sequence="KSREP-0204",
            fips_codes=[IN_AREA_FIPS],
        )

        assert_not_suppressed(other_event)
        assert_unmatched(other_event)

    def test_phase_a_reference_is_the_latest_candidate_even_when_already_suppressed(self):
        """PRD §3.5: "Its pool is every existing alert row of the *same* `station_id` with the *same* `originator_sequence` and the *same* `event_code`, regardless of that row's `relay_state`."
        PRD §3.5: "If any pool row's `received_at` falls inside that window, the new alert is suppressed by moving `RECEIVED` → `SUPPRESSED_DUPLICATE`: `suppression_source` becomes `STATION_REPEAT`, and `suppression_reference_alert_id` is set to the `id` of the pool row with the greatest `received_at`, breaking a tie on equal `received_at` by taking the row with the earliest `created_at`."

        Design: Difficulty/resource_temporal_overlap/station_repeat_phase_a_half_open_window_ignores_fips_and_picks_latest_reference
        """
        station, _rule = _station_with_statewide_optional_rule()
        chain = []
        for received_at in (
            BASE_RECEIVED_AT,
            "2026-08-12T12:05:00Z",
            "2026-08-12T12:09:00Z",
        ):
            chain.append(
                log_alert(
                    station["id"],
                    received_at,
                    event_code="TOR",
                    originator_sequence="KSREP-0205",
                    fips_codes=[IN_AREA_FIPS],
                )
            )
        chain_a, chain_b, chain_c = chain
        assert_not_suppressed(chain_a)
        assert_suppressed(chain_b, "STATION_REPEAT", chain_a["id"])
        assert_suppressed(chain_c, "STATION_REPEAT", chain_b["id"])

        probe = log_alert(
            station["id"],
            "2026-08-12T12:10:00Z",
            event_code="TOR",
            originator_sequence="KSREP-0205",
            fips_codes=[IN_AREA_FIPS],
        )
        assert_suppressed(probe, "STATION_REPEAT", chain_c["id"])

        rows, meta = validate_paginated(
            api_client.list_alert_events(
                ADMIN,
                params={
                    "station_id": station["id"],
                    "suppression_reference_alert_id": chain_c["id"],
                },
            )
        )
        assert meta["total_count"] == 1, f"expected exactly one referring alert, got {rows}"
        assert rows[0]["id"] == probe["id"]
