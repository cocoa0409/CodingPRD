"""The three interval conventions probed on their shared day: cycle windows, roll segments, lanes.

Cycle windows are half-open, so touching dates are legal; pouch-roll segments are closed and
inclusive, so an abutting day collides; the cold-chain lane imposes a minimum separation between
two staging instants rather than an interval to intersect.
"""

from test_helpers import (
    TECHNICIAN_ID,
    ApiErrorId,
    api_client,
    assert_cycle_state,
    assert_shipment_state,
    assert_total_count,
    cold_chain_shipment_payload,
    create_cycle,
    create_rx,
    do_adjudicate,
    do_generate_roll,
    do_stage_shipment,
    fill_cycle_payload,
    insulin_payload,
    line_by_prescription,
    metformin_payload,
    ops_headers,
    prescription_payload,
    read_cycle,
    read_lines,
    read_shipments,
    set_clock,
    setup_adjudicated_cycle,
    setup_draft_cycle,
    setup_rolled_cycle,
    technician_headers,
    validate_error,
    validate_paginated,
)


def _sertraline_payload(patient_id, last_dispensed_date):
    """An evening generic tablet dispensed elsewhere for 30 days on the given date."""
    return prescription_payload(
        patient_id,
        drug_name="Sertraline",
        ndc="00093-7201-56",
        strength="50mg",
        form="TABLET",
        copay_tier="GENERIC",
        dose_times=["EVENING"],
        quantity_per_dose=1,
        days_supply_written=30,
        last_dispensed_date=last_dispensed_date,
        last_dispensed_days_supply=30,
    )


def _patient_with_one_draft_cycle():
    """A synchronized patient holding a single draft cycle over [2026-08-15, 2026-09-12)."""
    return setup_draft_cycle(
        clock="2026-08-10T00:00:00Z",
        prescriptions=[metformin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )


def _rolled_cycle_then_second_cycle(sertraline_last_dispensed_date):
    """A rolled first cycle, a second evening prescription, and an adjudicated second cycle."""
    scenario = setup_rolled_cycle(
        clock="2026-08-10T00:00:00Z",
        prescriptions=[metformin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    evening_rx = create_rx(
        scenario.patient_id,
        lambda patient_id: _sertraline_payload(
            patient_id, sertraline_last_dispensed_date
        ),
    )
    successor = create_cycle(scenario.patient_id, "2026-09-12", 28)
    do_adjudicate(successor["id"])
    return scenario, evening_rx, successor


def _cold_chain_lane_with_one_staged_parcel():
    """A refrigerated-only patient with C1's parcel staged and a touching C2 adjudicated."""
    scenario = setup_adjudicated_cycle(
        clock="2026-08-10T00:00:00Z",
        prescriptions=[insulin_payload],
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    first_parcel = do_stage_shipment(scenario.cycle_id, cold_chain_shipment_payload())
    successor = create_cycle(scenario.patient_id, "2026-09-12", 28)
    do_adjudicate(successor["id"])
    return scenario, first_parcel, successor


class TestCycleWindowHalfOpenTouchingDates:
    """A new cycle window may touch a live window on either side but may not intersect it."""

    def test_new_cycle_may_start_on_the_day_the_live_cycle_ends(self):
        """A cycle starting on the exact day an existing cycle ends is accepted.

        A fill cycle covers `cycle_start_date` inclusive through `cycle_end_date` exclusive, where
        `cycle_end_date` is `cycle_start_date` advanced by `day_supply_days` calendar days.
        Two half-open windows collide only when each one's start is strictly before the other's
        end; windows that merely touch, where one window's start equals the other's end, do not
        collide.
        The new cycle is created with `cycle_end_date` computed as `cycle_start_date` advanced by
        `day_supply_days` days, exclusive; `packaging_status` `DRAFT`; `insurance_status`
        `NOT_ADJUDICATED`; `is_partial_reissue` false; `reissue_of_cycle_id` null;
        `vacation_exception_id` null; `approved_vacation_extra_days` 0; `reissue_required` false;
        `roll_pouch_count` 0; `total_copay_cents` 0; `final_copay_cents` null;
        `reissue_fee_cents` 0; `credit_applied_cents` 0; `rounding_delta_cents` null; and
        `version` 1.

        Design: Difficulty/resource_temporal_overlap/cycle_window_half_open_touching_dates_are_legal
        """
        scenario = _patient_with_one_draft_cycle()
        assert scenario.cycle["cycle_end_date"] == "2026-09-12", scenario.cycle

        successor = create_cycle(scenario.patient_id, "2026-09-12", 28)

        assert successor["cycle_start_date"] == "2026-09-12", successor
        assert successor["cycle_end_date"] == "2026-10-10", successor
        assert_cycle_state(
            successor, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
        )

    def test_new_cycle_may_end_on_the_day_the_live_cycle_starts(self):
        """A cycle ending on the exact day an existing cycle starts is equally accepted.

        A fill cycle covers `cycle_start_date` inclusive through `cycle_end_date` exclusive, where
        `cycle_end_date` is `cycle_start_date` advanced by `day_supply_days` calendar days.
        Two half-open windows collide only when each one's start is strictly before the other's
        end; windows that merely touch, where one window's start equals the other's end, do not
        collide.

        Design: Difficulty/resource_temporal_overlap/cycle_window_half_open_touching_dates_are_legal
        """
        scenario = _patient_with_one_draft_cycle()
        assert scenario.cycle["cycle_start_date"] == "2026-08-15", scenario.cycle

        predecessor = create_cycle(scenario.patient_id, "2026-07-18", 28)

        assert predecessor["cycle_start_date"] == "2026-07-18", predecessor
        assert predecessor["cycle_end_date"] == "2026-08-15", predecessor

    def test_one_day_of_true_intersection_is_rejected(self):
        """A window overlapping a live window by a single day is rejected and creates nothing.

        Two half-open windows collide only when each one's start is strictly before the other's
        end; windows that merely touch, where one window's start equals the other's end, do not
        collide.
        The new cycle's half-open window must not collide with any live cycle of the same patient,
        otherwise `ERR_CYCLE_WINDOW_OVERLAP`; only cycles whose `packaging_status` is neither
        `CANCELLED` nor `CLOSED` and whose `is_partial_reissue` is false participate in that test,
        so a partial-reissue child never blocks a later cycle and a closed or cancelled cycle never
        blocks anything.
        The **first** rule whose condition holds returns its error immediately; no later rule is
        evaluated, and no state change is applied.

        Design: Difficulty/resource_temporal_overlap/cycle_window_half_open_touching_dates_are_legal
        """
        scenario = _patient_with_one_draft_cycle()
        create_cycle(scenario.patient_id, "2026-09-12", 28)
        create_cycle(scenario.patient_id, "2026-07-18", 28)

        response = api_client.create_fill_cycle(
            fill_cycle_payload(scenario.patient_id, "2026-09-11", 28), ops_headers()
        )

        validate_error(response, ApiErrorId.CYCLE_WINDOW_OVERLAP)
        assert_total_count(
            api_client.list_fill_cycles(
                ops_headers(), {"patient_id": scenario.patient_id, "limit": 100}
            ),
            3,
        )


class TestRollSegmentClosedInclusiveAbuttingDay:
    """A pouch-roll segment abutting a live segment on the shared day collides."""

    def test_bridge_day_pulls_the_new_line_one_day_before_its_cycle_start(self):
        """A one-day gap in on-hand supply lengthens the line and starts it before the cycle.

        Begin by locating the date through which the patient is already covered: it is
        `last_dispensed_date` advanced by `last_dispensed_days_supply` days.
        The gap is the number of days by which the cycle start date falls after the covered-through
        date, or zero if it does not.
        Under `BRIDGE_TO_START`, the fill is **lengthened** so the patient is covered from the day
        their current supply runs out through the end of the common cycle. `bridge_days_applied` is
        the gap, `trim_days_applied` is zero, and `days_supply_filled` is the cycle's
        `day_supply_days` plus the gap.
        The line's own window follows from that: `line_start_date` is the cycle's
        `cycle_start_date` moved **earlier** by `bridge_days_applied` days and is inclusive, and
        `line_end_date` is `line_start_date` advanced by `days_supply_filled` days and is
        exclusive.

        Design: Difficulty/resource_temporal_overlap/roll_segment_closed_inclusive_abutting_day_collides
        """
        _, evening_rx, successor = _rolled_cycle_then_second_cycle("2026-08-12")

        line = line_by_prescription(read_lines(successor["id"]), evening_rx["id"])

        assert line["bridge_days_applied"] == 1, line
        assert line["trim_days_applied"] == 0, line
        assert line["days_supply_filled"] == 29, line
        assert line["line_start_date"] == "2026-09-11", line

    def test_segment_starting_on_the_live_segments_last_pouch_day_collides(self):
        """A new segment starting on the live segment's inclusive end day is rejected.

        A pouch roll covers `segment_start_date` through `segment_end_date`, both inclusive —
        `segment_end_date` is the last calendar date for which a pouch physically exists.
        Two closed segments collide when each one's start is on or before the other's end, so
        segments that merely abut, where one segment's start equals the other's end, *do* collide.
        Its gates are evaluated in this order: the cycle's `packaging_status` must be
        `LINES_ADJUDICATED`, otherwise `ERR_INVALID_CYCLE_STATE`; `insurance_status` must not be
        `EDITS_PENDING`, otherwise `ERR_CYCLE_NOT_CLEARED`; at least one line must have
        `line_status` `ADJUDICATED` and `packable_route` `POUCH`, otherwise
        `ERR_NO_PACKABLE_LINES`; every line whose `line_status` is `ADJUDICATED` must reference a
        prescription whose `status` is `ACTIVE`, otherwise `ERR_RX_PENDING_AUTHORIZATION`; the
        segment the new roll would occupy must not collide with a live roll of the same patient
        under closed-inclusive semantics, otherwise `ERR_REISSUE_SEGMENT_OVERLAP`; and only then,
        if `insurance_status` is `REJECTED_TOO_SOON`, the request fails with
        `ERR_REFILL_TOO_SOON`.
        The **first** rule whose condition holds returns its error immediately; no later rule is
        evaluated, and no state change is applied.

        Design: Difficulty/resource_temporal_overlap/roll_segment_closed_inclusive_abutting_day_collides
        """
        scenario, _, successor = _rolled_cycle_then_second_cycle("2026-08-12")
        assert scenario.roll["segment_start_date"] == "2026-08-15", scenario.roll
        assert scenario.roll["segment_end_date"] == "2026-09-11", scenario.roll

        response = api_client.generate_roll(
            successor["id"], technician_headers(TECHNICIAN_ID)
        )

        validate_error(response, ApiErrorId.REISSUE_SEGMENT_OVERLAP)
        rolls, _meta = validate_paginated(
            api_client.list_pouch_rolls(
                ops_headers(), {"cycle_id": successor["id"], "limit": 100}
            )
        )
        assert rolls == [], rolls
        assert_cycle_state(
            read_cycle(successor["id"]), packaging_status="LINES_ADJUDICATED"
        )

    def test_segment_starting_one_day_past_the_live_segment_is_built(self):
        """A new segment starting the day after the live segment's end day is built in full.

        A pouch roll covers `segment_start_date` through `segment_end_date`, both inclusive —
        `segment_end_date` is the last calendar date for which a pouch physically exists.
        Two closed segments collide when each one's start is on or before the other's end, so
        segments that merely abut, where one segment's start equals the other's end, *do* collide.
        One pouch is produced for each distinct pairing of a calendar date with a slot such that at
        least one contributing line both covers that date, meaning the date is on or after that
        line's `line_start_date` and strictly before its `line_end_date`, and lists that slot in
        its prescription's `dose_times`.
        `PouchRoll.pouch_count` is the number of such pairs, counting only pouches whose
        `verification_result` is not `VOID`, and the cycle's `roll_pouch_count` is set to that same
        figure.
        The roll itself is created with `verification_status` `BUILT`, a stamped human-readable
        `roll_serial`, `segment_start_date` equal to the earliest `line_start_date` among
        contributing lines, and `segment_end_date` equal to the latest `line_end_date` among
        contributing lines moved back by one day — because `segment_end_date` is inclusive, it
        names the last date for which a pouch exists, whereas `line_end_date` is exclusive.

        Design: Difficulty/resource_temporal_overlap/roll_segment_closed_inclusive_abutting_day_collides
        """
        scenario, evening_rx, successor = _rolled_cycle_then_second_cycle("2026-08-13")
        assert scenario.roll["segment_end_date"] == "2026-09-11", scenario.roll
        line = line_by_prescription(read_lines(successor["id"]), evening_rx["id"])
        assert line["bridge_days_applied"] == 0, line

        roll = do_generate_roll(successor["id"], TECHNICIAN_ID)

        assert roll["segment_start_date"] == "2026-09-12", roll
        assert roll["segment_end_date"] == "2026-10-09", roll
        assert roll["pouch_count"] == 56, roll
        assert read_cycle(successor["id"])["roll_pouch_count"] == 56


class TestColdChainStagingSeparation:
    """Two cold-chain stagings for one patient must be at least 48 hours apart."""

    def test_staging_forty_seven_hours_after_the_live_parcel_is_rejected(self):
        """A second cold-chain staging 47 hours after the first is rejected and stages nothing.

        The cold-chain separation rule compares two staging instants and treats them as
        conflicting when the absolute difference between them is strictly less than the 48-hour
        minimum gap.
        For a `COLD_CHAIN` parcel only, no other cold-chain shipment of the same patient whose
        `status` is neither `CANCELLED` nor `EXCEPTION_RETURNED` may have a `staged_at` whose
        absolute distance from the clock is under 48 hours, otherwise
        `ERR_COLD_CHAIN_GAP_VIOLATION`.
        The **first** rule whose condition holds returns its error immediately; no later rule is
        evaluated, and no state change is applied.

        Design: Difficulty/resource_temporal_overlap/cold_chain_stage_buffer_exactly_48_hours_apart_is_legal
        """
        _, first_parcel, successor = _cold_chain_lane_with_one_staged_parcel()
        assert_shipment_state(first_parcel, status="STAGED")
        assert first_parcel["staged_at"].startswith("2026-08-10T00:00:00"), first_parcel
        set_clock("2026-08-11T23:00:00Z")

        response = api_client.stage_shipment(
            successor["id"], cold_chain_shipment_payload(), ops_headers()
        )

        validate_error(response, ApiErrorId.COLD_CHAIN_GAP_VIOLATION)
        assert read_shipments(successor["id"]) == []

    def test_staging_exactly_forty_eight_hours_after_the_live_parcel_is_accepted(self):
        """A second cold-chain staging exactly 48 hours after the first is accepted and priced.

        The cold-chain separation rule compares two staging instants and treats them as
        conflicting when the absolute difference between them is strictly less than the 48-hour
        minimum gap. A separation of exactly 48 hours is permitted.
        The new shipment starts with `status` `STAGED`, `staged_at` at the clock,
        `tracking_number` null, `dispatched_at`, `delivered_at` and `pickup_confirmed_at` null,
        `cold_chain_excursion_minutes` 0 and `version` 1.
        `ship_cost_cents` is stamped at staging as the sum of three independent additive
        components.
        The kind contributes 0 cents for `POUCH_ROLL`, 495 cents for `NON_PACKABLE_LOOSE` and 1295
        cents for `COLD_CHAIN`.
        The packaging contributes 0 cents for `STANDARD`, 350 cents for `INSULATED_GEL` and 900
        cents for `INSULATED_DRY_ICE`.
        The service contributes 0 cents for `GROUND`, 600 cents for `TWO_DAY` and 1800 cents for
        `OVERNIGHT`.

        Design: Difficulty/resource_temporal_overlap/cold_chain_stage_buffer_exactly_48_hours_apart_is_legal
        """
        _, first_parcel, successor = _cold_chain_lane_with_one_staged_parcel()
        assert first_parcel["staged_at"].startswith("2026-08-10T00:00:00"), first_parcel
        set_clock("2026-08-12T00:00:00Z")

        second_parcel = do_stage_shipment(successor["id"], cold_chain_shipment_payload())

        assert_shipment_state(second_parcel, status="STAGED", ship_cost_cents=3445)
        assert second_parcel["staged_at"].startswith("2026-08-12T00:00:00"), (
            second_parcel
        )
        assert second_parcel["cold_chain_excursion_minutes"] == 0, second_parcel
