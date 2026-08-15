"""Temperature surveillance: readings, excursion lifecycle, quarantine cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_temperature_excursion,
    assert_temperature_reading,
    get_lot,
    get_site,
    get_unit,
    list_excursions,
    make_private_lot,
    make_product,
    make_site,
    make_unit,
    open_and_close_excursion,
    open_excursion,
    post_reading,
    resolve_excursion_viable,
    validate_error,
    validate_paginated,
    validate_success,
)

VM = TEST_USERS["vaccine_manager_headers"]
CA = TEST_USERS["compliance_auditor_headers"]


def _site_with_unit_and_lot(lot_qty=5):
    site = make_site()
    unit = make_unit(site["id"])
    product = make_product()
    lot = make_private_lot(
        site["id"], unit["id"], product["id"], quantity_on_hand=lot_qty
    )
    return site, unit, product, lot


class TestUnitRegistration:
    def test_units_reverse_reachable_via_site_list(self, api):
        """PRD §3.2: "The unit is anchored to its owning site through
        `provider_site_id`, recorded by the system at creation." PRD §2.3:
        "Paginated list responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/storage_unit_fk_reverse_reachable_via_site
        """
        site = make_site()
        u1 = make_unit(site["id"], unit_label="U1")
        u2 = make_unit(
            site["id"], unit_label="U2", unit_kind="FREEZER",
            min_temp_c=-50.0, max_temp_c=-15.0,
        )
        resp = api.list_storage_units(site["id"], VM)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2
        assert {u["id"] for u in data} == {u1["id"], u2["id"]}


class TestTemperatureReadings:
    def test_reading_is_append_only_without_version(self, api):
        """PRD §2.4: "a `TemperatureReading` carries only `id` and
        `created_at`. Both `updated_at` and `version` are absent from it,
        because a probe reading, once recorded, is never modified."

        Design: Corner/entities/temperature_reading_immutable_no_version_field
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        resp = api.record_temperature_reading(
            unit["id"], {"recorded_at": "2026-08-01T08:00:00Z", "temperature_c": 5.0}, VM
        )
        data = validate_success(resp, expected_status=201)
        assert_temperature_reading(data)

    def test_reading_exactly_at_either_bound_is_in_range(self, api):
        """PRD §2.6: "Each storage unit declares an acceptable Celsius range
        through `min_temp_c` and `max_temp_c`, and both bounds are inclusive:
        a reading exactly at either bound is in range."

        Design: Difficulty/boundary_precision_check/temperature_boundary_at_exactly_max_is_in_range
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        r_max = validate_success(
            api.record_temperature_reading(
                unit["id"], {"recorded_at": "2026-08-01T08:00:00Z", "temperature_c": 8.0}, VM
            ), expected_status=201
        )
        r_min = validate_success(
            api.record_temperature_reading(
                unit["id"], {"recorded_at": "2026-08-01T09:00:00Z", "temperature_c": 2.0}, VM
            ), expected_status=201
        )
        assert r_max["is_out_of_range"] is False, "8.0 == max_temp_c must be in range"
        assert r_min["is_out_of_range"] is False, "2.0 == min_temp_c must be in range"
        assert get_unit(unit["id"])["is_quarantined"] is False

    def test_reading_just_above_max_opens_excursion(self, api):
        """PRD §2.6: "A recorded reading is flagged `is_out_of_range` when it
        falls below `min_temp_c` or rises above `max_temp_c`." PRD §3.3: "the
        unit's `active_excursion_id` is set and `is_quarantined` becomes true".

        Design: Difficulty/boundary_precision_check/temperature_boundary_at_exactly_max_is_in_range
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        resp = api.record_temperature_reading(
            unit["id"], {"recorded_at": "2026-08-01T10:00:00Z", "temperature_c": 8.1}, VM
        )
        data = validate_success(resp, expected_status=201)
        assert data["is_out_of_range"] is True, "8.1 > max_temp_c must be out of range"
        assert get_unit(unit["id"])["is_quarantined"] is True


class TestExcursionPeakAndDuration:
    def test_peak_tracks_the_larger_deviation_across_both_bounds(self, api):
        """PRD §3.3: "the reading's candidate deviation is how far it exceeds
        its violated bound — the reading minus `max_temp_c` when it is above
        the range, or `min_temp_c` minus the reading when it is below" and
        "The incoming reading replaces `peak_temperature_c` only when its
        candidate deviation is strictly greater than the existing deviation".

        Readings: 9.0 (+1.0) opens, 11.5 (+3.5) replaces, -2.0 (4.0 below the
        min) replaces again — the lower-bound breach wins over the high-side
        peak.

        Design: Difficulty/combinatorial_formula/excursion_peak_deviation_max_of_two_branches
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        post_reading(unit["id"], "2026-08-01T10:00:00Z", 9.0)
        post_reading(unit["id"], "2026-08-01T11:00:00Z", 11.5)
        post_reading(unit["id"], "2026-08-01T12:00:00Z", -2.0)
        post_reading(unit["id"], "2026-08-01T13:00:00Z", 5.0)
        excursion = list_excursions(unit["id"])[0]
        assert_temperature_excursion(excursion)
        assert excursion["peak_temperature_c"] == -2.0, (
            f"deviation 4.0 below min beats +3.5 above max; peak must be -2.0, "
            f"got {excursion['peak_temperature_c']}"
        )

    def test_closed_excursion_reports_whole_minutes_and_stays_open(self, api):
        """PRD §3.3: "When an in-range reading arrives while an excursion is
        active, the excursion closes: `closed_at` is set to the reading's
        `recorded_at`, and `duration_minutes` is computed as the whole minutes
        elapsed between `opened_at` and `closed_at`, any partial minute
        discarded." The excursion remains in `OPEN` status until review begins
        (begin-review moves it `OPEN` -> `UNDER_REVIEW`, PRD §3.3).

        Design: Difficulty/combinatorial_formula/excursion_peak_deviation_max_of_two_branches
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        post_reading(unit["id"], "2026-08-01T10:00:00Z", 9.0)
        post_reading(unit["id"], "2026-08-01T11:00:00Z", 11.5)
        post_reading(unit["id"], "2026-08-01T12:00:00Z", -2.0)
        post_reading(unit["id"], "2026-08-01T13:00:00Z", 5.0)
        excursion = list_excursions(unit["id"])[0]
        assert excursion["duration_minutes"] == 180, (
            f"10:00 -> 13:00 is exactly 180 whole minutes, got {excursion['duration_minutes']}"
        )
        assert excursion["closed_at"] is not None
        assert excursion["status"] == "OPEN"

    def test_duration_discards_partial_minute(self, api):
        """PRD §3.3: "`duration_minutes` is computed as the whole minutes
        elapsed between `opened_at` and `closed_at`, any partial minute
        discarded."

        Design: Corner/calculations/excursion_duration_minutes_floored_to_whole_minutes
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        post_reading(unit["id"], "2026-08-01T10:00:00Z", 12.0)
        post_reading(unit["id"], "2026-08-01T10:01:30Z", 5.0)
        excursion = list_excursions(unit["id"])[0]
        assert excursion["duration_minutes"] == 1, (
            f"90 seconds floors to 1 whole minute, got {excursion['duration_minutes']}"
        )


class TestSingleActiveExcursion:
    def test_repeated_out_of_range_readings_share_one_excursion(self, api):
        """PRD §3.3: "When a further out-of-range reading arrives while an
        excursion is active, the excursion's peak is reconsidered" — no new
        excursion is opened. PRD §2.6: "The owning site's
        `excursion_count_open` reflects, at all times, the number of excursions
        in `OPEN` or `UNDER_REVIEW` across all of that site's storage units."

        Design: Difficulty/resource_temporal_overlap/single_active_excursion_per_unit
        """
        site, unit, _, _ = _site_with_unit_and_lot()
        post_reading(unit["id"], "2026-08-01T10:00:00Z", 9.0)
        post_reading(unit["id"], "2026-08-01T11:00:00Z", 11.0)
        post_reading(unit["id"], "2026-08-01T12:00:00Z", 10.0)
        assert get_site(site["id"])["excursion_count_open"] == 1
        excursions = list_excursions(unit["id"])
        assert len(excursions) == 1, (
            f"three out-of-range readings must share one excursion, got {len(excursions)}"
        )

    def test_shared_excursion_accumulates_max_peak(self, api):
        """PRD §3.3: "The incoming reading replaces `peak_temperature_c` only
        when its candidate deviation is strictly greater than the existing
        deviation".

        Design: Difficulty/resource_temporal_overlap/single_active_excursion_per_unit
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        post_reading(unit["id"], "2026-08-01T10:00:00Z", 9.0)
        post_reading(unit["id"], "2026-08-01T11:00:00Z", 11.0)
        post_reading(unit["id"], "2026-08-01T12:00:00Z", 10.0)
        excursion = list_excursions(unit["id"])[0]
        assert excursion["peak_temperature_c"] == 11.0


class TestExcursionOpenCascade:
    def test_opening_excursion_quarantines_every_available_lot(self, api):
        """PRD §3.3: "every `AVAILABLE` lot stored in the unit transitions
        automatically to `QUARANTINED`".

        Design: Difficulty/transitive_cascade/excursion_open_cascades_lot_quarantine_and_site_counter
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        lots = [
            make_private_lot(site["id"], unit["id"], product["id"],
                             quantity_on_hand=q, lot_number=f"L{i}")
            for i, q in enumerate((5, 3, 2), start=1)
        ]
        open_excursion(unit["id"])
        for lot in lots:
            reloaded = get_lot(lot["id"])
            assert reloaded["status"] == "QUARANTINED", (
                f"lot {lot['lot_number']} must be QUARANTINED, got {reloaded['status']}"
            )

    def test_opening_excursion_sets_unit_flag_and_site_counter(self, api):
        """PRD §3.3: "the unit's `active_excursion_id` is set and
        `is_quarantined` becomes true; every `AVAILABLE` lot stored in the
        unit transitions automatically to `QUARANTINED`; and the site's
        `excursion_count_open` increases by one."

        Design: Difficulty/transitive_cascade/excursion_open_cascades_lot_quarantine_and_site_counter
        """
        site, unit, _, _ = _site_with_unit_and_lot()
        excursion = open_excursion(unit["id"])
        unit_after = get_unit(unit["id"])
        assert unit_after["is_quarantined"] is True
        assert unit_after["active_excursion_id"] == excursion["id"]
        assert excursion["status"] == "OPEN"
        assert get_site(site["id"])["excursion_count_open"] == 1


class TestExcursionDisposition:
    def test_begin_review_rejected_while_excursion_still_open(self, api):
        """PRD §3.3: begin-review "is rejected with `ERR_INVALID_STATE` when
        the excursion is not `OPEN`, and with `ERR_EXCURSION_STILL_OPEN` when
        no in-range reading has yet closed it, since a still-open excursion
        cannot meaningfully be reviewed."

        Design: Corner/state_machines/temperature_excursion_begin_review_blocked_while_still_open
        """
        _, unit, _, _ = _site_with_unit_and_lot()
        excursion = open_excursion(unit["id"])
        resp = api.begin_excursion_review(unit["id"], excursion["id"], VM)
        validate_error(resp, ApiErrorId.ERR_EXCURSION_STILL_OPEN)

    def test_resolve_viable_returns_lots_and_clears_quarantine(self, api):
        """PRD §3.3: "Resolving as viable — with free-text `resolution_notes`
        recorded — moves the excursion to `RESOLVED_VIABLE`, returns every
        `QUARANTINED` lot in the unit to `AVAILABLE`, clears the unit's
        `active_excursion_id` and drops `is_quarantined` to false".

        Design: Corner/state_machines/excursion_resolve_viable_returns_lots_to_available
        """
        site = make_site()
        unit = make_unit(site["id"])
        product = make_product()
        l1 = make_private_lot(site["id"], unit["id"], product["id"],
                              quantity_on_hand=5, lot_number="L1")
        l2 = make_private_lot(site["id"], unit["id"], product["id"],
                              quantity_on_hand=3, lot_number="L2")
        excursion = open_and_close_excursion(unit["id"])
        resolved = resolve_excursion_viable(unit["id"], excursion["id"])
        assert resolved["status"] == "RESOLVED_VIABLE"
        for lot, qty in ((l1, 5), (l2, 3)):
            reloaded = get_lot(lot["id"])
            assert reloaded["status"] == "AVAILABLE"
            assert reloaded["quantity_on_hand"] == qty
        unit_after = get_unit(unit["id"])
        assert unit_after["is_quarantined"] is False
        assert unit_after["active_excursion_id"] is None

    def test_excursion_count_open_increments_then_decrements(self, api):
        """PRD §2.6: "The owning site's `excursion_count_open` reflects, at
        all times, the number of excursions in `OPEN` or `UNDER_REVIEW` across
        all of that site's storage units." PRD §3.3: resolving "decrements the
        site's `excursion_count_open` by one."

        Design: Corner/cross_cutting_layers/derived_field_excursion_count_open_updates
        """
        site, unit, _, _ = _site_with_unit_and_lot()
        excursion = open_and_close_excursion(unit["id"])
        assert get_site(site["id"])["excursion_count_open"] == 1
        resolve_excursion_viable(unit["id"], excursion["id"], notes="OK")
        assert get_site(site["id"])["excursion_count_open"] == 0
