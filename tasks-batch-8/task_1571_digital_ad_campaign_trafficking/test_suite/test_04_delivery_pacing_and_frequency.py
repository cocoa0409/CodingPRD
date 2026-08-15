"""Delivery snapshots, pacing projections and alerts, frequency capping."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_delivery_snapshot,
    create_delivery_snapshot_payload,
    ApiErrorId, TEST_USERS,
    setup_live_line_item, post_snapshot, void_snapshot, post_impression_event,
    set_clock, get_line_item,
)


def _parse_instant(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestSnapshotBasics:
    def test_snapshot_spend_computed(self, api, trafficker_headers):
        """PRD §3.4: "At posting, `spend_cents` is fixed as `impressions`
        multiplied by the line item's `cpm_rate_cents`, divided by 1000,
        rounded half up to a whole cent"

        Design: Corner/entities/snapshot_spend_computed
        """
        ctx = setup_live_line_item(li_overrides={"goal_impressions": 100000,
                                                 "cpm_rate_cents": 500})
        res = api.create_delivery_snapshot(
            create_delivery_snapshot_payload(ctx["line_item"]["id"],
                                             "2026-08-02", 10000, 40),
            trafficker_headers)
        snap = validate_success(res, 201)
        assert_delivery_snapshot(snap)
        assert snap["spend_cents"] == 5000
        assert snap["status"] == "POSTED"

    def test_snapshot_outside_line_item_flight_rejected(
            self, api, trafficker_headers):
        """PRD §3.4: "The `snapshot_date` must fall inside the line item's
        `start_date`-to-`end_date` range, failing with
        `ERR_SNAPSHOT_OUT_OF_FLIGHT` otherwise"

        Design: Corner/validations/snapshot_outside_line_item_flight_rejected
        """
        ctx = setup_live_line_item()
        res = api.create_delivery_snapshot(
            create_delivery_snapshot_payload(ctx["line_item"]["id"],
                                             "2026-07-31", 1000, 10),
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_SNAPSHOT_OUT_OF_FLIGHT.value, 422)

    def test_duplicate_snapshot_rejected_even_after_void(
            self, api, trafficker_headers):
        """PRD §3.4: "a second snapshot for the same line item and date —
        regardless of whether the first one was voided — is refused with
        `ERR_DUPLICATE_SNAPSHOT`."

        Design: Corner/validations/duplicate_snapshot_rejected_even_after_void
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        snap = post_snapshot(li_id, "2026-08-03", 1000, 10)
        void_snapshot(snap["id"])

        res = api.create_delivery_snapshot(
            create_delivery_snapshot_payload(li_id, "2026-08-03", 2000, 20),
            trafficker_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SNAPSHOT.value, 409)

    def test_double_void_snapshot_rejected(self, api, trafficker_headers):
        """PRD §3.4: "A snapshot already `VOIDED` rejects a second void with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/double_void_snapshot_rejected
        """
        ctx = setup_live_line_item()
        li_id = ctx["line_item"]["id"]
        snap = post_snapshot(li_id, "2026-08-03", 5000, 50)
        void_snapshot(snap["id"])

        res = api.transition_delivery_snapshot(snap["id"], {"action": "VOID"},
                                               trafficker_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)

        data, _ = validate_paginated(
            api.list_delivery_snapshots(li_id, trafficker_headers))
        snap_after = [s for s in data if s["id"] == snap["id"]][0]
        assert snap_after["status"] == "VOIDED"


class TestPostVoidInvariant:
    def test_snapshot_post_void_restores_delivered(
            self, api, trafficker_headers):
        """PRD §2.10: "after the pair completes, the line item's
        `delivered_impressions`, `delivered_clicks`, and
        `delivered_spend_cents` stand exactly where they stood before the
        post, because aggregates are sums over `POSTED` snapshots only."

        Design: Difficulty/compensating_invariant/snapshot_post_void_restores_delivered
        """
        ctx = setup_live_line_item(li_overrides={"goal_impressions": 100000,
                                                 "cpm_rate_cents": 500})
        li_id = ctx["line_item"]["id"]
        before = get_line_item(li_id)
        assert before["delivered_impressions"] == 0
        assert before["delivered_clicks"] == 0
        assert before["delivered_spend_cents"] == 0

        snap = post_snapshot(li_id, "2026-08-03", 5000, 50)
        assert snap["spend_cents"] == 2500
        voided = void_snapshot(snap["id"])
        assert voided["status"] == "VOIDED"

        after = get_line_item(li_id)
        assert after["delivered_impressions"] == 0
        assert after["delivered_clicks"] == 0
        assert after["delivered_spend_cents"] == 0

    def test_void_excludes_only_the_voided_snapshot(
            self, api, trafficker_headers):
        """PRD §3.4: "Voiding is the snapshot's compensating action: a
        `POSTED` snapshot moves to `VOIDED`, the delivery aggregates are
        recomputed over `POSTED` snapshots only, and the pacing fields are
        refreshed."

        Design: Difficulty/compensating_invariant/snapshot_post_void_restores_delivered
        """
        ctx = setup_live_line_item(li_overrides={"goal_impressions": 100000,
                                                 "cpm_rate_cents": 500})
        li_id = ctx["line_item"]["id"]
        snap_a = post_snapshot(li_id, "2026-08-03", 5000, 50)
        post_snapshot(li_id, "2026-08-04", 3000, 30)
        mid = get_line_item(li_id)
        assert mid["delivered_impressions"] == 8000
        assert mid["delivered_spend_cents"] == 4000

        void_snapshot(snap_a["id"])

        after = get_line_item(li_id)
        assert after["delivered_impressions"] == 3000
        assert after["delivered_clicks"] == 30
        assert after["delivered_spend_cents"] == 1500


class TestPacingProjectionVariants:
    def test_pacing_projection_lifetime_vs_trailing(self, api,
                                                    trafficker_headers):
        """PRD §3.4: "The lifetime-average projection,
        `pacing_projection_impressions`, divides `delivered_impressions` by
        the elapsed days to obtain a daily rate — when no day has elapsed
        yet, the projection is simply `delivered_impressions` — and projects
        final delivery as `delivered_impressions` plus the remaining days
        multiplied by that rate, rounded half up to a whole impression. The
        trailing variant, `pacing_projection_trailing_impressions`, derives
        its rate from recent form only: sum the impressions over `POSTED`
        snapshots dated from two days before the logical current date through
        the current date — a three-calendar-day window in which days without
        a snapshot contribute zero — and divide by three; the projection is
        then `delivered_impressions` plus the remaining days multiplied by
        that trailing rate, again rounded half up."

        Design: Difficulty/dual_variant_calc/pacing_projection_lifetime_vs_trailing
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10"},
            li_overrides={"goal_impressions": 100000, "cpm_rate_cents": 500,
                          "start_date": "2026-08-01",
                          "end_date": "2026-08-10"})
        li_id = ctx["line_item"]["id"]
        for date, imps, clicks in (("2026-08-01", 10000, 100),
                                   ("2026-08-02", 10000, 100),
                                   ("2026-08-03", 6000, 60),
                                   ("2026-08-04", 6000, 60),
                                   ("2026-08-05", 8000, 80)):
            post_snapshot(li_id, date, imps, clicks)
        set_clock("2026-08-06T00:00:00Z")

        li = get_line_item(li_id)
        assert li["delivered_impressions"] == 40000
        assert li["delivered_clicks"] == 400
        # PRD §3.4 spend rule: 40000 impressions x 500 cpm / 1000 = 20000.
        assert li["delivered_spend_cents"] == 20000
        # Lifetime: rate 40000/5 = 8000 -> 40000 + 5*8000 = 80000.
        assert li["pacing_projection_impressions"] == 80000
        # Trailing: (6000 + 8000 + 0)/3 per day -> 40000 + 5*4666.67 = 63333.
        assert li["pacing_projection_trailing_impressions"] == 63333
        assert (li["pacing_projection_impressions"]
                != li["pacing_projection_trailing_impressions"])

    def test_pacing_projection_variants_diverge_on_second_dataset(
            self, api, trafficker_headers):
        """PRD §3.4: "sum the impressions over `POSTED` snapshots dated from
        two days before the logical current date through the current date —
        a three-calendar-day window in which days without a snapshot
        contribute zero — and divide by three"

        Design: Difficulty/dual_variant_calc/pacing_projection_lifetime_vs_trailing
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10"},
            li_overrides={"goal_impressions": 100000, "cpm_rate_cents": 500,
                          "start_date": "2026-08-01",
                          "end_date": "2026-08-10"})
        li_id = ctx["line_item"]["id"]
        post_snapshot(li_id, "2026-08-01", 5000, 50)
        post_snapshot(li_id, "2026-08-02", 5000, 50)
        set_clock("2026-08-03T00:00:00Z")

        li = get_line_item(li_id)
        assert li["delivered_impressions"] == 10000
        assert li["delivered_spend_cents"] == 5000
        # Lifetime: rate 10000/2 = 5000 -> 10000 + 8*5000 = 50000.
        assert li["pacing_projection_impressions"] == 50000
        # Trailing: (5000 + 5000 + 0)/3 per day -> 10000 + 8*3333.33 = 36667.
        assert li["pacing_projection_trailing_impressions"] == 36667
        assert (li["pacing_projection_impressions"]
                != li["pacing_projection_trailing_impressions"])

    def test_pacing_alert_threshold_crossing(self, api, trafficker_headers):
        """PRD §3.4: "the alert is true when `delivered_impressions` is less
        than ninety percent of that expectation, evaluated as an exact
        comparison without rounding."

        Design: Corner/calculations/pacing_alert_threshold_crossing
        """
        ctx = setup_live_line_item(
            io_overrides={"flight_start": "2026-08-01",
                          "flight_end": "2026-08-10"},
            li_overrides={"goal_impressions": 100000, "cpm_rate_cents": 500,
                          "start_date": "2026-08-01",
                          "end_date": "2026-08-10",
                          "pacing_mode": "EVEN"})
        li_id = ctx["line_item"]["id"]
        post_snapshot(li_id, "2026-08-01", 20000, 100)
        post_snapshot(li_id, "2026-08-02", 24000, 120)
        set_clock("2026-08-06T00:00:00Z")

        # Expected to date: 100000 * 5/10 = 50000; 90% = 45000.
        li = get_line_item(li_id)
        assert li["delivered_impressions"] == 44000
        assert li["pacing_alert"] is True, (
            "44000 < 45000 (90% of expected 50000) must raise pacing_alert")
        assert li["status"] == "LIVE"

        post_snapshot(li_id, "2026-08-03", 2000, 10)
        li = get_line_item(li_id)
        assert li["delivered_impressions"] == 46000
        assert li["pacing_alert"] is False, (
            "46000 >= 45000 must clear pacing_alert")
        assert li["status"] == "LIVE"


class TestFrequencyCapping:
    def _setup_capped_line_item(self):
        return setup_live_line_item(
            li_overrides={"goal_impressions": 100000, "cpm_rate_cents": 500,
                          "frequency_cap_max_impressions": 3,
                          "frequency_cap_window_hours": 24})

    def test_frequency_cap_exact_boundary(self, api, trafficker_headers):
        """PRD §3.4: "the server counts already-persisted events for the same
        line item and `user_key` whose `occurred_at` lies inside the trailing
        window that starts `frequency_cap_window_hours` before the current
        logical time and runs up to but does not include it — an event
        exactly `frequency_cap_window_hours` old is excluded from the count.
        If that count has already reached the cap, the new event is rejected
        with `ERR_FREQUENCY_CAP_EXCEEDED`; a count exactly one below the cap
        still accepts."

        Design: Difficulty/boundary_precision_check/frequency_cap_exact_boundary
        """
        ctx = self._setup_capped_line_item()
        li_id = ctx["line_item"]["id"]
        set_clock("2026-08-05T12:00:00Z")
        # Exactly 24h old -> excluded from the window count, but persisted.
        validate_success(post_impression_event(
            li_id, "u1", "2026-08-04T12:00:00Z"), 201)
        for ts in ("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z",
                   "2026-08-05T11:30:00Z"):
            validate_success(post_impression_event(li_id, "u1", ts), 201)

        # In-window count is now exactly 3 == cap -> reject.
        res = post_impression_event(li_id, "u1", "2026-08-05T11:45:00Z")
        validate_error(res, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED.value, 422)

        data, meta = validate_paginated(
            api.list_impression_events(li_id, trafficker_headers,
                                       params={"user_key": "u1"}))
        assert len(data) == 4, (
            "The rejected event must not persist; the exactly-24h-old event "
            "is stored but excluded from the window count")

    def test_frequency_cap_accepts_one_below_cap_after_window_exclusion(
            self, api, trafficker_headers):
        """PRD §3.4: "an event exactly `frequency_cap_window_hours` old is
        excluded from the count. If that count has already reached the cap,
        the new event is rejected with `ERR_FREQUENCY_CAP_EXCEEDED`; a count
        exactly one below the cap still accepts."

        Design: Difficulty/boundary_precision_check/frequency_cap_exact_boundary
        """
        ctx = self._setup_capped_line_item()
        li_id = ctx["line_item"]["id"]
        set_clock("2026-08-05T12:00:00Z")
        validate_success(post_impression_event(
            li_id, "u1", "2026-08-04T12:00:00Z"), 201)  # exactly 24h: excluded
        validate_success(post_impression_event(
            li_id, "u1", "2026-08-05T10:00:00Z"), 201)
        validate_success(post_impression_event(
            li_id, "u1", "2026-08-05T11:00:00Z"), 201)

        # In-window count is 2, one below the cap -> accept.
        accepted = validate_success(
            post_impression_event(li_id, "u1", "2026-08-05T11:45:00Z"), 201)
        assert accepted["user_key"] == "u1"

        # Now the count has reached 3 -> reject.
        res = post_impression_event(li_id, "u1", "2026-08-05T11:50:00Z")
        validate_error(res, ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED.value, 422)

    def test_impression_event_occurred_at_defaults_to_logical_clock(
            self, api, trafficker_headers):
        """PRD §3.4: "Recording an impression event takes `line_item_id`, the
        `user_key` the cap is enforced against, and an optional `occurred_at`
        that defaults to the server's logical clock when omitted"

        Design: Corner/entities/impression_event_occurred_at_defaults_to_logical_clock
        """
        ctx = setup_live_line_item()  # uncapped line item
        li_id = ctx["line_item"]["id"]
        set_clock("2026-08-02T09:30:00Z")

        res = post_impression_event(li_id, "u9")
        event = validate_success(res, 201)
        assert _parse_instant(event["occurred_at"]) == datetime(
            2026, 8, 2, 9, 30, 0, tzinfo=timezone.utc), (
            "Omitted occurred_at must stamp the server logical clock, "
            "not wall-clock time")
