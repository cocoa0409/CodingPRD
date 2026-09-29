"""Wear load, marginal rest tiers, the late-cancellation branch and the running balance."""

from test_helpers import (
    assert_instant_equals,
    assert_running_balance_replays,
    assert_two_decimals,
    assert_usage_booking,
    fixtures,
    validate_paginated,
)


class TestRestRequirementTiers:
    def test_rest_requirement_uses_marginal_tier_spans_not_a_flat_rate(
        self, client, roster
    ):
        """Each tier rate applies only to the wear that falls inside that tier.

        "For `PLAYED` and `RAINED_OUT` the booking also computes
        `rest_requirement_hours`, using **marginal** tier rates applied to
        `wear_load_units` — each tier's rate applies only to the portion of the
        wear that falls inside that tier, never to the whole amount. The first
        6.00 wear units earn 0.50 rest hours each. Wear units above 6.00 and up to
        12.00 earn 1.00 rest hour each. Every wear unit above 12.00 earns 1.75
        rest hours."

        "If the field's `surface_type` is `SYNTHETIC_TURF`, the summed hours are
        multiplied by 0.40, because synthetic carpet recovers far faster than
        living grass."

        "`CONFIRMED → PLAYED` appends a single `UsageLedgerEntry` with
        `entry_type` `PLAY_WEAR`, carrying `wear_units_delta` equal to the positive
        `wear_load_units`, the booking's `rest_requirement_hours`, and a
        `rest_window_end_utc` equal to the booking's `window_end_utc` advanced by
        those rest hours."

        Design: Corner/calculations/rest_requirement_hours_uses_marginal_tier_spans_not_a_flat_rate
        """
        grass = fixtures.register_grass_main_1(client, roster)
        synthetic = fixtures.register_synthetic_stadium_1(client, roster)

        grass_booking = fixtures.request_booking(
            client,
            roster,
            grass["id"],
            activity_type="GAME",
            window_start_utc="2026-08-02T19:00:00Z",
            window_end_utc="2026-08-02T23:00:00Z",
            expected_participant_count=60,
        )
        synthetic_booking = fixtures.request_booking(
            client,
            roster,
            synthetic["id"],
            activity_type="PRACTICE",
            window_start_utc="2026-08-02T10:00:00Z",
            window_end_utc="2026-08-02T12:00:00Z",
            expected_participant_count=30,
        )
        fixtures.confirm_booking(client, roster, grass_booking["id"])
        fixtures.confirm_booking(client, roster, synthetic_booking["id"])

        # The synthetic slot is closed out as soon as its window has elapsed, so
        # its rest window is still running when the obligation is read back.
        fixtures.set_clock(client, roster, "2026-08-02T12:00:00Z")
        synthetic_closed = fixtures.close_out_booking(
            client,
            roster,
            synthetic_booking["id"],
            outcome="PLAYED",
            actual_duration_hours=2.0,
            actual_participant_count=30,
            weather_condition="DRY",
        )
        # 2.0 h x 1.00 PRACTICE x 1.00 crowd x 0.80 synthetic x 1.00 dry.
        assert_two_decimals(
            synthetic_closed["wear_load_units"], 1.60, "synthetic wear_load_units"
        )
        # 1.60 tier units at 0.50 is 0.80 hours, then the 0.40 synthetic multiplier.
        assert_two_decimals(
            synthetic_closed["rest_requirement_hours"],
            0.32,
            "synthetic rest_requirement_hours",
        )
        synthetic_field = fixtures.read_field(client, roster, synthetic["id"])
        assert_two_decimals(
            synthetic_field["rest_debt_hours"], 0.32, "synthetic Field.rest_debt_hours"
        )

        fixtures.set_clock(client, roster, "2026-08-02T23:00:00Z")
        grass_closed = fixtures.close_out_booking(
            client,
            roster,
            grass_booking["id"],
            outcome="PLAYED",
            actual_duration_hours=4.0,
            actual_participant_count=60,
            weather_condition="DRY",
        )
        assert_usage_booking(grass_closed)
        assert grass_closed["status"] == "PLAYED"
        # 4.0 h x 1.50 GAME x 1.20 crowd x 1.20 grass x 1.00 dry.
        assert_two_decimals(
            grass_closed["wear_load_units"], 8.64, "grass wear_load_units"
        )
        # 6.00 units at 0.50 plus the remaining 2.64 units at 1.00.
        assert_two_decimals(
            grass_closed["rest_requirement_hours"], 5.64, "grass rest_requirement_hours"
        )

        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.coordinator_headers,
                params={
                    "limit": 100,
                    "field_id": grass["id"],
                    "entry_type": "PLAY_WEAR",
                },
            )
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_two_decimals(entry["wear_units_delta"], 8.64, "wear_units_delta")
        assert_two_decimals(
            entry["rest_requirement_hours"], 5.64, "rest_requirement_hours"
        )
        # 23:00:00 advanced by 5 h 38 min 24 s.
        assert_instant_equals(
            entry["rest_window_end_utc"],
            "2026-08-03T04:38:24Z",
            "rest_window_end_utc",
        )

        grass_field = fixtures.read_field(client, roster, grass["id"])
        assert_two_decimals(
            grass_field["rest_debt_hours"], 5.64, "grass Field.rest_debt_hours"
        )
        assert grass_field["play_status"] == "RESTRICTED"


class TestLateCancellationBranch:
    def test_late_cancellation_applies_half_wear_and_opens_no_rest_window(
        self, client, roster
    ):
        """A called-off fixture substitutes the plan for the actuals and halves it.

        "The duration used is `actual_duration_hours` for `PLAYED` and for
        `RAINED_OUT`, but for `CANCELLED_LATE` it is instead the full scheduled
        window length, measured in hours from `window_start_utc` to
        `window_end_utc`. The headcount used is `actual_participant_count` for
        `PLAYED` and for `RAINED_OUT`, but for `CANCELLED_LATE` it is the
        booking's `expected_participant_count`."

        "For `CANCELLED_LATE`, the raw load is first multiplied by a
        late-cancellation fraction of 0.50 — a fixture called off after the window
        has passed still cost the surface something, in stand-by preparation and
        marking, but only half of what playing it would have — and the result of
        that multiplication is rounded half up to two decimal places."

        "For a `CANCELLED_LATE` outcome, `rest_requirement_hours` is 0.00 and no
        rest window is opened at all."

        "`CONFIRMED → CANCELLED_LATE` appends one entry with `entry_type`
        `LATE_CANCEL_WEAR` carrying the halved wear as its `wear_units_delta`, a
        `rest_requirement_hours` of 0.00 and a `rest_window_end_utc` of null.
        `Field.cumulative_wear_units` is recomputed and so are
        `condition_index_agronomic` and `play_status`, but `usage_hours_ytd` is
        left **unchanged** — nothing was played — and `Field.version` increments by
        1."

        Design: Corner/calculations/late_cancellation_applies_half_wear_and_opens_no_rest_window
        """
        field = fixtures.register_grass_main_1(client, roster)
        booking = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-02T19:00:00Z",
            window_end_utc="2026-08-02T23:00:00Z",
            expected_participant_count=60,
        )
        fixtures.confirm_booking(client, roster, booking["id"])
        fixtures.set_clock(client, roster, "2026-08-02T23:00:00Z")

        closed = fixtures.close_out_booking(
            client,
            roster,
            booking["id"],
            outcome="CANCELLED_LATE",
            actual_duration_hours=0.0,
            actual_participant_count=0,
            weather_condition="DRY",
        )
        assert closed["status"] == "CANCELLED_LATE"
        # 0.50 x 4.0 scheduled hours x 1.50 GAME x 1.20 crowd of 60 x 1.20 grass.
        assert_two_decimals(closed["wear_load_units"], 4.32, "wear_load_units")
        assert_two_decimals(
            closed["rest_requirement_hours"], 0.00, "rest_requirement_hours"
        )

        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.coordinator_headers,
                params={"limit": 100, "field_id": field["id"]},
            )
        )
        assert meta["total_count"] == 1
        entry = entries[0]
        assert entry["entry_type"] == "LATE_CANCEL_WEAR"
        assert_two_decimals(entry["wear_units_delta"], 4.32, "wear_units_delta")
        assert_two_decimals(
            entry["rest_requirement_hours"], 0.00, "rest_requirement_hours"
        )
        assert entry.get("rest_window_end_utc") is None
        assert_two_decimals(
            entry["running_balance_after"], 4.32, "running_balance_after"
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            after["cumulative_wear_units"], 4.32, "Field.cumulative_wear_units"
        )
        assert_two_decimals(after["rest_debt_hours"], 0.00, "Field.rest_debt_hours")
        # No rest window was opened, so the surface is not restricted.
        assert after["play_status"] == "OPEN"
        assert_two_decimals(after["usage_hours_ytd"], 0.00, "Field.usage_hours_ytd")


class TestCumulativeWearRunningBalance:
    def test_cumulative_wear_units_is_a_chronological_running_balance(
        self, client, roster
    ):
        """Each entry records the balance as it stood after that entry landed.

        "replaying a field's ledger in order of `effective_at_utc` ascending and
        then `created_at` ascending must reproduce that column exactly"

        "Otherwise — that is, on a `NATURAL_GRASS` field — if `weather_condition`
        is `WET`, a flat surcharge of 2.00 hours is added, because a saturated
        root zone needs longer before it can take traffic again."

        "`Field.cumulative_wear_units` is recomputed, `usage_hours_ytd` increases
        by `actual_duration_hours`, `rest_debt_hours` and
        `condition_index_agronomic` and `play_status` are all recomputed, and
        `Field.version` increments by 1."

        Design: Corner/calculations/field_cumulative_wear_units_is_a_chronological_running_balance
        """
        field = fixtures.register_grass_main_1(client, roster)
        first = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-02T19:00:00Z",
            window_end_utc="2026-08-02T23:00:00Z",
            expected_participant_count=60,
        )
        second = fixtures.request_booking(
            client,
            roster,
            field["id"],
            activity_type="GAME",
            window_start_utc="2026-08-03T08:00:00Z",
            window_end_utc="2026-08-03T09:30:00Z",
            expected_participant_count=40,
        )
        fixtures.confirm_booking(client, roster, first["id"])
        fixtures.confirm_booking(client, roster, second["id"])

        fixtures.set_clock(client, roster, "2026-08-02T23:00:00Z")
        fixtures.close_out_booking(
            client,
            roster,
            first["id"],
            outcome="PLAYED",
            actual_duration_hours=4.0,
            actual_participant_count=60,
            weather_condition="DRY",
        )

        fixtures.set_clock(client, roster, "2026-08-03T09:30:00Z")
        wet = fixtures.close_out_booking(
            client,
            roster,
            second["id"],
            outcome="PLAYED",
            actual_duration_hours=1.5,
            actual_participant_count=40,
            weather_condition="WET",
        )
        # 1.5 x 1.50 GAME x 1.00 crowd x 1.20 grass x 1.35 wet = 3.645.
        assert_two_decimals(wet["wear_load_units"], 3.65, "wear_load_units")
        # 3.65 units at 0.50 is 1.825 tier hours, plus the 2.00 h wet surcharge.
        assert_two_decimals(
            wet["rest_requirement_hours"], 3.83, "rest_requirement_hours"
        )

        entries, meta = validate_paginated(
            client.list_usage_ledger_entries(
                roster.coordinator_headers,
                params={
                    "limit": 100,
                    "field_id": field["id"],
                    "entry_type": "PLAY_WEAR",
                },
            )
        )
        assert meta["total_count"] == 2
        assert_running_balance_replays(entries)

        by_delta = {round(float(e["wear_units_delta"]), 2): e for e in entries}
        assert_two_decimals(
            by_delta[8.64]["running_balance_after"], 8.64, "first running_balance_after"
        )
        assert_two_decimals(
            by_delta[3.65]["running_balance_after"],
            12.29,
            "second running_balance_after",
        )
        # 09:30:00 advanced by 3 h 49 min 48 s.
        assert_instant_equals(
            by_delta[3.65]["rest_window_end_utc"],
            "2026-08-03T13:19:48Z",
            "rest_window_end_utc",
        )

        after = fixtures.read_field(client, roster, field["id"])
        assert_two_decimals(
            after["cumulative_wear_units"], 12.29, "Field.cumulative_wear_units"
        )
        assert_two_decimals(after["usage_hours_ytd"], 5.50, "Field.usage_hours_ytd")
        # Wear 96.93 x 0.50 + age 30.83 x 0.20 + safety 50.00 x 0.30 = 69.631.
        assert_two_decimals(
            after["condition_index_agronomic"], 69.63, "Field.condition_index_agronomic"
        )
