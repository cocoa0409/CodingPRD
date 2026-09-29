"""The upgrading skid's two independent state dimensions, and the downtime /
flare-backup accounting that drives month-to-date availability."""

from test_helpers import (
    ApiErrorId,
    alarm_reading_payload,
    approx_2dp,
    assert_downtime_event,
    assert_energy_balance_read,
    assert_instant_equals,
    assert_processing_plant,
    fixtures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIndependentStateDimensions:
    def test_off_spec_analysis_moves_only_the_spec_dimension(self, api, operator_headers):
        """PRD §3.4: "What makes a plant unusual in this system is that it carries **two
        independent state dimensions on the same row**, and neither one forces the other
        except where a transition explicitly says so."
        PRD §3.7: "If any one of the three comparisons fails, the batch lands on
        `OFF_SPEC`, `spec_failure_reason` is set to the **first** rule violated in the
        fixed order `LOW_METHANE`, then `HIGH_OXYGEN`, then `HIGH_CO2`, and — this is the
        asymmetry between the two branches — the plant itself is pushed from `ON_SPEC` to
        `OFF_SPEC` on its spec dimension if it was on spec."

        Design: Difficulty/non_linear_state_machine/plant_process_mode_and_spec_status_advance_independently
        """
        context = fixtures.setup_off_spec_plant()
        plant_id = context["plant"]["id"]

        analysed = context["off_spec_batch"]
        assert analysed["status"] == "OFF_SPEC"
        assert analysed["spec_failure_reason"] == "LOW_METHANE"

        plant = fixtures.read_plant(plant_id)
        assert_processing_plant(plant)
        assert plant["spec_status"] == "OFF_SPEC"
        assert plant["process_mode"] == "UPGRADING", (
            "the spec dimension moved without dragging the process dimension with it"
        )

    def test_plant_ends_on_flaring_and_on_spec_after_the_dimensions_walk_apart(
        self, api, operator_headers
    ):
        """PRD §3.4: "Both are advanced through the same operator action, which accepts
        a `process_mode` value, a `spec_status` value, or both, and requires at least one
        of them."
        PRD §3.4: "A manual switch to flaring leaves `spec_status` untouched and opens no
        downtime record."
        PRD §3.4: "Recovery is deliberately two-step: a `PlantOperator` first moves
        `OFF_SPEC → QUARANTINE`, and only then `QUARANTINE → ON_SPEC`."

        Design: Difficulty/non_linear_state_machine/plant_process_mode_and_spec_status_advance_independently
        """
        context = fixtures.setup_off_spec_plant()
        plant_id = context["plant"]["id"]
        batch = context["off_spec_batch"]

        flaring = validate_success(
            api.set_plant_status(plant_id, {"process_mode": "FLARING"}, operator_headers)
        )
        assert flaring["process_mode"] == "FLARING"
        assert flaring["spec_status"] == "OFF_SPEC", (
            "a manual switch to flaring leaves the spec dimension where it stood"
        )

        diverted = validate_success(
            api.set_injection_batch_status(
                batch["id"], {"to_status": "DIVERTED_TO_FLARE"}, operator_headers
            )
        )
        assert diverted["status"] == "DIVERTED_TO_FLARE"

        quarantined = validate_success(
            api.set_plant_status(plant_id, {"spec_status": "QUARANTINE"}, operator_headers)
        )
        assert quarantined["spec_status"] == "QUARANTINE"
        assert quarantined["process_mode"] == "FLARING"

        released = validate_success(
            api.set_plant_status(plant_id, {"spec_status": "ON_SPEC"}, operator_headers)
        )
        assert released["spec_status"] == "ON_SPEC"
        assert released["process_mode"] == "FLARING", (
            "a combination neither dimension could have produced alone"
        )

    def test_off_spec_cannot_return_to_on_spec_without_the_quarantine_step(
        self, api, operator_headers
    ):
        """PRD §3.4: "Recovery is deliberately two-step: a `PlantOperator` first moves
        `OFF_SPEC → QUARANTINE`, and only then `QUARANTINE → ON_SPEC`. Going directly
        from `OFF_SPEC` back to `ON_SPEC` is not a declared transition and is refused with
        `ERR_INVALID_TRANSITION` — the quarantine step is mandatory."

        Design: Corner/state_machines/plant_spec_status_off_spec_to_on_spec_without_quarantine_is_rejected
        """
        context = fixtures.setup_off_spec_plant()
        plant_id = context["plant"]["id"]

        validate_error(
            api.set_plant_status(plant_id, {"spec_status": "ON_SPEC"}, operator_headers),
            ApiErrorId.ERR_INVALID_TRANSITION.value,
        )

        plant = fixtures.read_plant(plant_id)
        assert plant["spec_status"] == "OFF_SPEC"
        assert plant["process_mode"] == "UPGRADING"
        assert context["off_spec_batch"]["status"] == "OFF_SPEC"
        assert context["off_spec_batch"]["spec_failure_reason"] == "LOW_METHANE"

    def test_quarantine_release_is_blocked_while_an_off_spec_batch_is_unresolved(
        self, api, operator_headers
    ):
        """PRD §3.4: "Leaving quarantine additionally requires that no injection batch of
        this plant still sits in `OFF_SPEC`; if one does, the request is refused with
        `ERR_OFF_SPEC_BATCH_UNRESOLVED`, forcing the operator to divert or void the
        offending batch before the plant is declared clean."

        Design: Corner/state_machines/quarantine_release_blocked_while_off_spec_batch_unresolved
        """
        context = fixtures.setup_off_spec_plant()
        plant_id = context["plant"]["id"]
        batch_id = context["off_spec_batch"]["id"]
        validate_success(
            api.set_plant_status(plant_id, {"spec_status": "QUARANTINE"}, operator_headers)
        )

        validate_error(
            api.set_plant_status(plant_id, {"spec_status": "ON_SPEC"}, operator_headers),
            ApiErrorId.ERR_OFF_SPEC_BATCH_UNRESOLVED.value,
        )
        assert fixtures.read_plant(plant_id)["spec_status"] == "QUARANTINE"

        diverted = fixtures.divert_batch(batch_id)
        assert diverted["status"] == "DIVERTED_TO_FLARE"

        released = validate_success(
            api.set_plant_status(plant_id, {"spec_status": "ON_SPEC"}, operator_headers)
        )
        assert released["spec_status"] == "ON_SPEC"
        assert released["process_mode"] == "UPGRADING"

    def test_upgrading_is_refused_while_the_site_has_not_reached_the_minimum_feed(
        self, api, operator_headers
    ):
        """PRD §3.4: "Going to `UPGRADING` demands that the plant's `spec_status` be
        `ON_SPEC` — otherwise `ERR_PLANT_OFF_SPEC` — and that the site's
        `collected_flow_scfm` have reached or exceeded the plant's `min_feed_scfm`,
        otherwise `ERR_INSUFFICIENT_FEED_FLOW`."

        Design: Corner/validations/upgrading_without_enough_collected_flow_is_rejected
        """
        context = fixtures.setup_site_with_wellfield(with_readings=False)
        plant_id = context["plant"]["id"]

        validate_error(
            api.set_plant_status(plant_id, {"process_mode": "UPGRADING"}, operator_headers),
            ApiErrorId.ERR_INSUFFICIENT_FEED_FLOW.value,
        )

        plant = fixtures.read_plant(plant_id)
        assert plant["process_mode"] == "STARTUP"
        assert plant["spec_status"] == "ON_SPEC"
        assert fixtures.read_site(context["site"]["id"])[
            "collected_flow_scfm"
        ] == approx_2dp(0.0)


class TestDowntimeAccounting:
    def test_month_to_date_downtime_merges_overlapping_and_touching_intervals(
        self, api, operator_headers
    ):
        """PRD §3.5: "They are then merged: two intervals join into one when they overlap
        **or** when they merely touch, meaning one ends at the exact instant the next
        begins. `downtime_minutes_mtd` is the total length of that merged union in
        minutes, rounded half up to two decimal places, so a plant that logged two
        overlapping outages is charged for the union once rather than for both.
        `flare_minutes_mtd` is computed the same way over the merged union restricted to
        candidates whose `disposition` is `FLARED`."
        PRD §3.5: "Otherwise availability is 100 multiplied by the elapsed minutes less
        `downtime_minutes_mtd`, divided by the elapsed minutes, rounded half up to two
        decimal places."
        PRD §3.5: "On success `duration_minutes` is set to the length from `start_at` to
        `end_at` expressed in minutes and rounded half up to two decimal places, and the
        site ledger moves: `energy_produced_mmbtu` rises by the sum of the flared and
        vented figures, `energy_flared_mmbtu` rises by the flared figure, and
        `energy_vented_mmbtu` rises by the vented figure."

        Design: Corner/calculations/availability_factor_merges_overlapping_and_touching_downtime_intervals
        """
        set_clock("2026-08-11T00:00:00Z")
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])

        # Two overlapping FLARED outages: 00:00-06:00 and 04:00-08:00 -> 480 minutes.
        first = fixtures.create_closed_downtime(
            plant["id"],
            "2026-08-02T00:00:00Z",
            "2026-08-02T06:00:00Z",
            cause="COMPRESSOR_TRIP",
            disposition="FLARED",
            flared_mmbtu=12.50,
        )
        second = fixtures.create_closed_downtime(
            plant["id"],
            "2026-08-02T04:00:00Z",
            "2026-08-02T08:00:00Z",
            cause="OFF_SPEC_TRIP",
            disposition="FLARED",
        )
        # Two touching VENTED outages: 00:00-02:00 and 02:00-05:00 -> 300 minutes.
        third = fixtures.create_closed_downtime(
            plant["id"],
            "2026-08-03T00:00:00Z",
            "2026-08-03T02:00:00Z",
            cause="PLANNED_MAINTENANCE",
            disposition="VENTED",
            vented_mmbtu=4.00,
        )
        fourth = fixtures.create_closed_downtime(
            plant["id"],
            "2026-08-03T02:00:00Z",
            "2026-08-03T05:00:00Z",
            cause="PLANNED_MAINTENANCE",
            disposition="VENTED",
        )

        for event, minutes in (
            (first, 360.0),
            (second, 240.0),
            (third, 120.0),
            (fourth, 180.0),
        ):
            assert_downtime_event(event)
            assert event["status"] == "CLOSED"
            assert event["duration_minutes"] == approx_2dp(minutes)

        plant_after = fixtures.read_plant(plant["id"])
        assert plant_after["downtime_minutes_mtd"] == approx_2dp(780.0), (
            "the union is charged once, not the 900.0 a naive sum would give"
        )
        assert plant_after["flare_minutes_mtd"] == approx_2dp(480.0)
        # Elapsed minutes 14400; 100 * (14400 - 780) / 14400 = 94.58.
        assert plant_after["availability_factor_pct"] == approx_2dp(94.58)

        balance = fixtures.read_energy_balance(site["id"])
        assert_energy_balance_read(balance)
        assert balance["energy_produced_mmbtu"] == approx_2dp(16.50)
        assert balance["energy_flared_mmbtu"] == approx_2dp(12.50)
        assert balance["energy_vented_mmbtu"] == approx_2dp(4.00)
        assert balance["balance_ok"] is True

    def test_closing_an_already_closed_downtime_record_is_refused(
        self, api, operator_headers
    ):
        """PRD §3.5: "Closing a record whose `status` is already `CLOSED` is refused with
        `ERR_DOWNTIME_ALREADY_CLOSED`."
        PRD §3.5: "On success `duration_minutes` is set to the length from `start_at` to
        `end_at` expressed in minutes and rounded half up to two decimal places, and the
        site ledger moves: `energy_produced_mmbtu` rises by the sum of the flared and
        vented figures, `energy_flared_mmbtu` rises by the flared figure, and
        `energy_vented_mmbtu` rises by the vented figure."

        Design: Corner/errors/closing_an_already_closed_downtime_event_is_rejected
        """
        set_clock("2026-08-11T00:00:00Z")
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])
        event = fixtures.create_closed_downtime(
            plant["id"],
            "2026-08-05T00:00:00Z",
            "2026-08-05T02:00:00Z",
            cause="COMPRESSOR_TRIP",
            disposition="FLARED",
            flared_mmbtu=10.00,
        )

        validate_error(
            api.close_downtime_event(
                event["id"],
                {"end_at": "2026-08-05T04:00:00Z", "flared_mmbtu": 10.00},
                operator_headers,
            ),
            ApiErrorId.ERR_DOWNTIME_ALREADY_CLOSED.value,
        )

        unchanged = fixtures.get_success_data(
            api.get_downtime_event(event["id"], operator_headers)
        )
        assert_instant_equals(unchanged["end_at"], "2026-08-05T02:00:00Z", "end_at")
        assert unchanged["duration_minutes"] == approx_2dp(120.0)
        assert unchanged["flared_mmbtu"] == approx_2dp(10.00)

        site_after = fixtures.read_site(site["id"])
        assert site_after["energy_flared_mmbtu"] == approx_2dp(10.00), (
            "the refused close must not double-book the flared energy"
        )
        assert site_after["energy_produced_mmbtu"] == approx_2dp(10.00)


class TestWellfieldRecovery:
    def test_wellfield_recovery_returns_the_plant_to_upgrading_and_closes_its_auto_downtime(
        self, api, operator_headers, technician_headers
    ):
        """PRD §3.2: "Both promotions recompute the site's collected flow and efficiency,
        and both then run the recovery check in the other direction: if the recomputed
        collected flow has reached or exceeded the `min_feed_scfm` of a plant of that site
        that is currently flaring and whose `spec_status` is `ON_SPEC`, that plant is
        returned to upgrading."
        PRD §3.4: "`FLARING → UPGRADING` is the recovery leg: every downtime record of
        this plant that is `OPEN` and `auto_generated` is closed with its `end_at` set to
        `current_utc` and both `flared_mmbtu` and `vented_mmbtu` booked as 0, and the
        plant's `availability_factor_pct`, `downtime_minutes_mtd` and `flare_minutes_mtd`
        are then recomputed."

        Design: Corner/state_machines/wellfield_recovery_returns_plant_to_upgrading_and_closes_auto_downtime
        """
        context = fixtures.setup_upgrading_plant(reading_at="2026-08-09T01:00:00Z")
        site_id = context["site"]["id"]
        plant_id = context["plant"]["id"]
        well = context["wells"][0]

        # The alarm starves the plant: collected flow drops to 470.0, under min_feed 900.
        api.create_reading(
            well["id"], alarm_reading_payload("2026-08-09T02:00:00Z"), technician_headers
        )
        fixtures.set_plant_mode(plant_id, spec_status="QUARANTINE")
        fixtures.set_plant_mode(plant_id, spec_status="ON_SPEC")

        fixtures.post_good_reading(well["id"], "2026-08-09T03:00:00Z", flow_scfm=480.0)
        fixtures.post_good_reading(well["id"], "2026-08-09T04:00:00Z", flow_scfm=480.0)
        fixtures.set_well_state(well["id"], "THROTTLED", "Two consecutive good readings")
        fixtures.post_good_reading(well["id"], "2026-08-09T05:00:00Z", flow_scfm=480.0)

        set_clock("2026-08-10T06:00:00Z")
        recovered = validate_success(
            api.set_well_status(
                well["id"],
                {"to_state": "ONLINE", "reason": "Third consecutive good reading"},
                technician_headers,
            )
        )
        assert recovered["operating_state"] == "ONLINE"
        assert recovered["current_flow_scfm"] == approx_2dp(480.0)

        site_after = fixtures.read_site(site_id)
        assert site_after["collected_flow_scfm"] == approx_2dp(950.0)
        assert site_after["collection_efficiency_pct"] == approx_2dp(95.0)

        plant_after = fixtures.read_plant(plant_id)
        assert plant_after["process_mode"] == "UPGRADING"
        assert plant_after["spec_status"] == "ON_SPEC"

        rows, meta = validate_paginated(
            api.list_downtime_events(
                operator_headers,
                params={"plant_id": plant_id, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        outage = rows[0]
        assert outage["status"] == "CLOSED"
        assert outage["auto_generated"] is True
        assert outage["cause"] == "WELLFIELD_SHORTFALL"
        assert_instant_equals(outage["end_at"], "2026-08-10T06:00:00Z", "end_at")
        assert outage["duration_minutes"] == approx_2dp(360.0)
        assert outage["flared_mmbtu"] == approx_2dp(0.0)

        # Elapsed minutes 13320; 100 * (13320 - 360) / 13320 = 97.30.
        assert plant_after["downtime_minutes_mtd"] == approx_2dp(360.0)
        assert plant_after["flare_minutes_mtd"] == approx_2dp(360.0)
        assert plant_after["availability_factor_pct"] == approx_2dp(97.30)
