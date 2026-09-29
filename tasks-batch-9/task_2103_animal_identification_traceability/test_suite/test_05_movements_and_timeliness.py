"""Reporting departures and arrivals: timeliness, the receive cascade, disputes and corrections."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    correct_movement_payload,
    create_movement_payload,
    dispute_movement,
    dispute_movement_payload,
    enroll_producer,
    make_program_admin_headers,
    make_state_official_headers,
    read_animal,
    read_movement,
    read_premises,
    read_producer,
    receive_arrival,
    receive_movement_payload,
    report_departure,
    set_clock,
    setup_two_premises_scenario,
    sightings_of_animal,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")


class TestReportingTimeliness:
    def test_reporting_lag_of_exactly_seventy_two_hours_counts_as_on_time(self, api):
        """PRD §3.5: "A movement's `reporting_lag_hours` is the interval from `departed_at` to the frozen `reported_at`, taken in seconds, divided by 3600, and rounded half up to two decimal places. The movement's `on_time` flag is true when that lag is at most 72.00 hours — three days, with a lag of exactly 72.00 counting as on time."

        Design: Difficulty/boundary_precision_check/reporting_lag_exactly_72_hours_counts_as_on_time
        """
        scenario = setup_two_premises_scenario(
            origin_state="ID", destination_state="ID", capacity=20, quantity=10
        )
        set_clock("2026-08-04T00:00:00Z")

        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )
        assert movement["reporting_lag_hours"] == 72.00
        assert movement["on_time"] is True, "a lag of exactly 72.00 hours is on time"

    def test_on_time_departure_gives_full_producer_credit_and_stays_intrastate(self, api):
        """PRD §3.5: "Whether a movement crosses a state line is derived, not declared: `interstate` is true exactly when the origin premises' `state_code` differs from the destination premises' `state_code`."
        PRD §3.5: "Rolled up to the producer, `on_time_movement_pct` counts every movement whose origin premises belongs to that producer and whose `status` is `REPORTED`, `RECEIVED` or `DISPUTED` as the denominator, and those of them whose `on_time` is true as the numerator; the percentage is 100.0 multiplied by numerator over denominator, rounded half up to two decimal places."

        Design: Difficulty/boundary_precision_check/reporting_lag_exactly_72_hours_counts_as_on_time
        """
        scenario = setup_two_premises_scenario(
            origin_state="ID", destination_state="ID", capacity=20, quantity=10
        )
        set_clock("2026-08-04T00:00:00Z")

        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )
        assert movement["interstate"] is False, "both premises sit in the same state"
        assert read_producer(scenario["producer"]["id"])["on_time_movement_pct"] == 100.00

    def test_reporting_lag_one_minute_past_the_boundary_is_late(self, api):
        """PRD §3.5: "A movement's `reporting_lag_hours` is the interval from `departed_at` to the frozen `reported_at`, taken in seconds, divided by 3600, and rounded half up to two decimal places. The movement's `on_time` flag is true when that lag is at most 72.00 hours — three days, with a lag of exactly 72.00 counting as on time."
        PRD §3.5: "Rolled up to the producer, `on_time_movement_pct` counts every movement whose origin premises belongs to that producer and whose `status` is `REPORTED`, `RECEIVED` or `DISPUTED` as the denominator, and those of them whose `on_time` is true as the numerator; the percentage is 100.0 multiplied by numerator over denominator, rounded half up to two decimal places."

        Design: Corner/calculations/reporting_lag_just_over_seventy_two_hours_is_late
        """
        scenario = setup_two_premises_scenario(
            origin_state="ID", destination_state="ID", capacity=10, quantity=10
        )
        set_clock("2026-08-04T00:01:00Z")

        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )
        assert movement["reporting_lag_hours"] == 72.02, "72 hours and one minute is 72.02 hours"
        assert movement["on_time"] is False
        assert read_producer(scenario["producer"]["id"])["on_time_movement_pct"] == 0.00


class TestInterstateAndTemporalGuards:
    def test_interstate_movement_needs_an_icvi_and_then_succeeds_with_one(self, api):
        """PRD §3.5: "Whether a movement crosses a state line is derived, not declared: `interstate` is true exactly when the origin premises' `state_code` differs from the destination premises' `state_code`. An interstate movement requires a non-null `icvi_number` — the Interstate Certificate of Veterinary Inspection — and omitting it is refused with `ERR_ICVI_REQUIRED`. Intrastate movements may leave it null."
        PRD §3.5: "Reporting the departure advances the animal from `ACTIVE` to `IN_TRANSIT`. The movement is created with `status` `REPORTED` and a `reported_at` stamped from the logical clock; that stamp is **frozen at creation and is never re-stamped**, not even by a later correction."

        Design: Corner/validations/interstate_movement_requires_icvi_then_succeeds_with_one
        """
        scenario = setup_two_premises_scenario(
            origin_state="TX", destination_state="OK", capacity=10, quantity=10
        )
        payload = create_movement_payload(
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )
        missing_icvi = api.create_movement_event(payload, scenario["producer_headers"])
        validate_error(missing_icvi, ApiErrorId.ERR_ICVI_REQUIRED, expected_status=409)

        payload_with_icvi = dict(payload, icvi_number="ICVI-TX-88231")
        movement = validate_success(
            api.create_movement_event(payload_with_icvi, scenario["producer_headers"]),
            expected_status=201,
        )
        assert movement["interstate"] is True
        assert movement["icvi_number"] == "ICVI-TX-88231"
        assert movement["status"] == "REPORTED"
        assert read_animal(scenario["animal"]["id"])["lifecycle_status"] == "IN_TRANSIT"

    def test_future_and_backdated_departure_instants_are_both_rejected(self, api):
        """PRD §2.5: "None of `departed_at`, `arrived_at` or `harvested_at` may be later than the logical clock's current instant, else `ERR_FUTURE_TIMESTAMP`. Both `departed_at` and `harvested_at` must be the same instant as or later than the `observed_at` of the animal's non-reversed sighting bearing the highest `sequence_no`, else `ERR_BACKDATED_EVENT`."
        PRD §3.4: "A `TAG_APPLIED` sighting is appended with `sequence_no` 1 and `observed_at` taken from the logical clock."

        Design: Corner/validations/future_and_backdated_business_instants_are_rejected
        """
        set_clock("2026-08-05T00:00:00Z")
        scenario = setup_two_premises_scenario(
            origin_state="CO", destination_state="CO", capacity=10, quantity=10
        )

        future = api.create_movement_event(
            create_movement_payload(
                scenario["animal"]["id"],
                scenario["origin"]["id"],
                scenario["destination"]["id"],
                "2026-08-06T00:00:00Z",
            ),
            scenario["producer_headers"],
        )
        validate_error(future, ApiErrorId.ERR_FUTURE_TIMESTAMP, expected_status=422)

        backdated = api.create_movement_event(
            create_movement_payload(
                scenario["animal"]["id"],
                scenario["origin"]["id"],
                scenario["destination"]["id"],
                "2026-08-01T00:00:00Z",
            ),
            scenario["producer_headers"],
        )
        validate_error(backdated, ApiErrorId.ERR_BACKDATED_EVENT, expected_status=422)

        animal = read_animal(scenario["animal"]["id"])
        assert animal["lifecycle_status"] == "ACTIVE"
        assert animal["sighting_count"] == 1

        rows, meta = validate_paginated(
            api.list_movement_events(ADMIN, params={"animal_id": scenario["animal"]["id"]})
        )
        assert rows == [] and meta["total_count"] == 0


class TestReceiveCascade:
    def test_receive_appends_the_arrival_observation_and_reprojects_the_animal(self, api):
        """PRD §3.5: "Success runs Cascade A end to end: the movement advances `REPORTED → RECEIVED`; an `ARRIVAL` sighting is appended with `observed_at` equal to `arrived_at`; the new sighting re-projects the animal from `IN_TRANSIT` back to `ACTIVE` with `current_premises_id` set to the destination; the destination premises' `animal_count` rises by one; and, because that head count changed, the destination producer's `enrolled_head_count` is recomputed and its `incentive_tier` re-derived."
        PRD §2.11: "The `sequence_no` starts at 1 for an animal's first observation and increases by exactly one on every subsequent append, including appends that are later reversed. Sequence numbers are never reused and never renumbered."

        Design: Difficulty/transitive_cascade/receive_cascade_movement_sighting_animal_premises_producer
        """
        scenario = setup_two_premises_scenario(
            origin_state="KS", destination_state="KS", capacity=30, quantity=50
        )
        enroll_producer(scenario["producer"]["id"])

        set_clock("2026-08-02T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-02T00:00:00Z",
        )
        set_clock("2026-08-03T00:00:00Z")

        received = validate_success(
            api.receive_movement_event(
                movement["id"],
                receive_movement_payload("2026-08-02T06:00:00Z"),
                scenario["producer_headers"],
            )
        )
        assert received["status"] == "RECEIVED"

        rows = sightings_of_animal(scenario["animal"]["id"])
        assert len(rows) == 3
        arrival = rows[-1]
        assert arrival["sequence_no"] == 3
        assert arrival["sighting_type"] == "ARRIVAL"
        assert arrival["premises_id"] == scenario["destination"]["id"]
        assert_same_instant(arrival["observed_at"], "2026-08-02T06:00:00Z", "observed_at")

        animal = read_animal(scenario["animal"]["id"])
        assert animal["current_premises_id"] == scenario["destination"]["id"]
        assert animal["lifecycle_status"] == "ACTIVE"
        assert animal["sighting_count"] == 3

    def test_receive_moves_the_head_count_and_re_derives_the_producer_tier(self, api):
        """PRD §3.5: "Success runs Cascade A end to end: the movement advances `REPORTED → RECEIVED`; an `ARRIVAL` sighting is appended with `observed_at` equal to `arrived_at`; the new sighting re-projects the animal from `IN_TRANSIT` back to `ACTIVE` with `current_premises_id` set to the destination; the destination premises' `animal_count` rises by one; and, because that head count changed, the destination producer's `enrolled_head_count` is recomputed and its `incentive_tier` re-derived."
        PRD §3.1: "That head count is the sum of `animal_count` across every premises the producer owns whose `registration_status` is `ACTIVE`; premises still in `PENDING_REVIEW`, and premises that have been suspended, contribute nothing."
        PRD §3.9: "an enrolled head count of 0 is `TIER_0` with a factor of 0.00; from 1 through 99 head is `TIER_1` with a factor of 1.00; from 100 through 499 head is `TIER_2` with a factor of 1.15; and 500 head or more is `TIER_3` with a factor of 1.30."

        Design: Difficulty/transitive_cascade/receive_cascade_movement_sighting_animal_premises_producer
        """
        scenario = setup_two_premises_scenario(
            origin_state="KS", destination_state="KS", capacity=30, quantity=50
        )
        enrolled = enroll_producer(scenario["producer"]["id"])
        assert enrolled["incentive_tier"] == "TIER_1", "one resident head sits in TIER_1"

        set_clock("2026-08-02T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-02T00:00:00Z",
        )
        in_transit = read_producer(scenario["producer"]["id"])
        assert in_transit["enrolled_head_count"] == 0, "an in-transit animal counts nowhere"
        assert in_transit["incentive_tier"] == "TIER_0"

        set_clock("2026-08-03T00:00:00Z")
        receive_arrival(movement["id"], scenario["producer"]["id"], "2026-08-02T06:00:00Z")

        assert read_premises(scenario["origin"]["id"])["animal_count"] == 0
        assert read_premises(scenario["destination"]["id"])["animal_count"] == 1

        after = read_producer(scenario["producer"]["id"])
        assert after["enrolled_head_count"] == 1
        assert after["incentive_tier"] == "TIER_1"


class TestDisputeAndCorrectionCycle:
    def test_disputing_a_merely_reported_movement_reverses_nothing(self, api):
        """PRD §3.5: "Disputing a movement that was merely `REPORTED` reverses no sighting and leaves the animal's `lifecycle_status` untouched — it stays `IN_TRANSIT`. Disputing a movement that had already been `RECEIVED` triggers a conditional cascade: the `ARRIVAL` sighting is marked `reversed`, the animal re-projects from `ACTIVE` back to `IN_TRANSIT`, and the destination premises' `animal_count` falls by one."
        PRD §2.11: "a `DEPARTURE` row clears the current premises to null and sets `lifecycle_status` to `IN_TRANSIT`"

        Design: Corner/state_machines/dispute_of_reported_movement_reverses_nothing
        """
        scenario = setup_two_premises_scenario(
            origin_state="WY", destination_state="WY", capacity=10, quantity=10
        )
        set_clock("2026-08-02T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-02T00:00:00Z",
        )

        disputed = validate_success(
            api.dispute_movement_event(
                movement["id"],
                dispute_movement_payload(reason="paperwork query"),
                make_state_official_headers("saho-1"),
            )
        )
        assert disputed["status"] == "DISPUTED"

        animal = read_animal(scenario["animal"]["id"])
        assert animal["lifecycle_status"] == "IN_TRANSIT"
        assert animal["current_premises_id"] is None
        assert animal["sighting_count"] == 2, "no observation was reversed"

        assert read_premises(scenario["origin"]["id"])["animal_count"] == 0
        assert read_premises(scenario["destination"]["id"])["animal_count"] == 0

    def test_correction_returns_the_movement_to_reported_and_counts_the_cycle(self, api):
        """PRD §3.5: "Correction is available only from `DISPUTED`; it requires the movement's `correction_count` to be strictly below 3, with a fourth attempt refused as `ERR_CORRECTION_LIMIT_EXCEEDED`; and it requires the origin premises not to be `QUARANTINED`, else `ERR_PREMISES_UNDER_HOLD`."
        PRD §3.5: "Reporting the departure advances the animal from `ACTIVE` to `IN_TRANSIT`. The movement is created with `status` `REPORTED` and a `reported_at` stamped from the logical clock; that stamp is **frozen at creation and is never re-stamped**, not even by a later correction."

        Design: Difficulty/non_linear_state_machine/movement_dispute_correct_cycle_recomputes_timeliness
        """
        scenario = setup_two_premises_scenario(
            origin_state="OK", destination_state="OK", capacity=40, quantity=50
        )
        set_clock("2026-08-05T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )
        assert movement["reporting_lag_hours"] == 96.00
        assert movement["on_time"] is False
        dispute_movement(movement["id"], reason="shipment manifest mismatch")

        corrected = validate_success(
            api.correct_movement_event(
                movement["id"],
                correct_movement_payload("2026-08-04T00:00:00Z"),
                scenario["producer_headers"],
            )
        )
        assert corrected["status"] == "REPORTED", "the cycle returns to a state it already held"
        assert corrected["correction_count"] == 1
        assert_same_instant(
            corrected["reported_at"], "2026-08-05T00:00:00Z", "reported_at"
        )

    def test_correction_recomputes_timeliness_against_the_frozen_report_instant(self, api):
        """PRD §3.5: "Correction moves the movement `DISPUTED → REPORTED`, increments `correction_count` by one, overwrites `departed_at` and `icvi_number` with the corrected values, and rewrites the `DEPARTURE` sighting's `observed_at` to match. Because `reported_at` stays frozen while `departed_at` moves, `reporting_lag_hours` and `on_time` are recomputed from the frozen report instant against the corrected departure instant — which means moving `departed_at` forward can legitimately flip a late movement to on time — and the origin producer's `on_time_movement_pct` is re-derived."

        Design: Difficulty/non_linear_state_machine/movement_dispute_correct_cycle_recomputes_timeliness
        """
        scenario = setup_two_premises_scenario(
            origin_state="OK", destination_state="OK", capacity=40, quantity=50
        )
        set_clock("2026-08-05T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )
        dispute_movement(movement["id"], reason="shipment manifest mismatch")

        corrected = validate_success(
            api.correct_movement_event(
                movement["id"],
                correct_movement_payload("2026-08-04T00:00:00Z"),
                scenario["producer_headers"],
            )
        )
        assert corrected["reporting_lag_hours"] == 24.00
        assert corrected["on_time"] is True, "moving departed_at forward flips it to on time"
        assert read_producer(scenario["producer"]["id"])["on_time_movement_pct"] == 100.00

        rows = sightings_of_animal(scenario["animal"]["id"])
        departure = [row for row in rows if row["sequence_no"] == 2][0]
        assert departure["sighting_type"] == "DEPARTURE"
        assert_same_instant(departure["observed_at"], "2026-08-04T00:00:00Z", "observed_at")

    def test_fourth_correction_is_refused_by_the_bounded_cycle(self, api):
        """PRD §3.5: "Correction is available only from `DISPUTED`; it requires the movement's `correction_count` to be strictly below 3, with a fourth attempt refused as `ERR_CORRECTION_LIMIT_EXCEEDED`; and it requires the origin premises not to be `QUARANTINED`, else `ERR_PREMISES_UNDER_HOLD`."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."

        Design: Corner/state_machines/movement_correction_cycle_rejects_fourth_correction
        """
        scenario = setup_two_premises_scenario(
            origin_state="OK", destination_state="OK", capacity=10, quantity=10
        )
        set_clock("2026-08-06T00:00:00Z")
        movement = report_departure(
            scenario["producer"]["id"],
            scenario["animal"]["id"],
            scenario["origin"]["id"],
            scenario["destination"]["id"],
            "2026-08-01T00:00:00Z",
        )

        corrected = None
        for corrected_departure in ("2026-08-02", "2026-08-03", "2026-08-04"):
            dispute_movement(movement["id"])
            corrected = validate_success(
                api.correct_movement_event(
                    movement["id"],
                    correct_movement_payload(f"{corrected_departure}T00:00:00Z"),
                    scenario["producer_headers"],
                )
            )
        assert corrected["correction_count"] == 3

        dispute_movement(movement["id"])
        resp = api.correct_movement_event(
            movement["id"],
            correct_movement_payload("2026-08-05T00:00:00Z"),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_LIMIT_EXCEEDED, expected_status=409)

        after = read_movement(movement["id"])
        assert after["status"] == "DISPUTED"
        assert after["correction_count"] == 3
        assert_same_instant(after["departed_at"], "2026-08-04T00:00:00Z", "departed_at")


class TestResidencyOverlapOnCorrection:
    def test_correcting_departure_past_a_recorded_arrival_is_refused(self, api):
        """PRD §3.5: "A corrected `departed_at` may not be later than an `arrived_at` already recorded on that movement, because the animal would then be resident at the origin after it had already arrived at the destination; that contradiction is refused with `ERR_RESIDENCY_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/corrected_departure_after_recorded_arrival_rejected
        """
        scenario = _disputed_after_arrival()
        resp = api.correct_movement_event(
            scenario["movement"]["id"],
            correct_movement_payload("2026-08-11T00:00:00Z"),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_OVERLAP, expected_status=409)

    def test_refused_correction_leaves_the_movement_exactly_as_it_stood(self, api):
        """PRD §3.5: "A corrected `departed_at` may not be later than an `arrived_at` already recorded on that movement, because the animal would then be resident at the origin after it had already arrived at the destination; that contradiction is refused with `ERR_RESIDENCY_OVERLAP`."
        PRD §2.5: "Rules are evaluated **strictly in ascending priority order**, the first failing rule alone decides the response, and no side effect of any kind is applied once a rule has failed."
        PRD §3.5: "Disputing a movement that was merely `REPORTED` reverses no sighting and leaves the animal's `lifecycle_status` untouched — it stays `IN_TRANSIT`. Disputing a movement that had already been `RECEIVED` triggers a conditional cascade: the `ARRIVAL` sighting is marked `reversed`, the animal re-projects from `ACTIVE` back to `IN_TRANSIT`, and the destination premises' `animal_count` falls by one."

        Design: Difficulty/resource_temporal_overlap/corrected_departure_after_recorded_arrival_rejected
        """
        scenario = _disputed_after_arrival()
        resp = api.correct_movement_event(
            scenario["movement"]["id"],
            correct_movement_payload("2026-08-11T00:00:00Z"),
            scenario["producer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENCY_OVERLAP, expected_status=409)

        after = read_movement(scenario["movement"]["id"])
        assert after["status"] == "DISPUTED"
        assert after["correction_count"] == 0
        assert_same_instant(after["departed_at"], "2026-08-09T00:00:00Z", "departed_at")
        assert read_animal(scenario["animal"]["id"])["lifecycle_status"] == "IN_TRANSIT"


class TestVoidedMovementConservesHeadCount:
    def test_voiding_a_disputed_movement_returns_the_animal_to_its_origin(self, api):
        """PRD §3.5: "The movement moves `DISPUTED → VOIDED`; every sighting whose `source_movement_id` is that movement is marked `reversed`; the animal is re-projected from its surviving sightings, returning it to the origin premises with `lifecycle_status` `ACTIVE`; the origin premises' `animal_count` rises by one, restoring the sum of the origin and destination head counts to its pre-departure value; and the movement leaves the origin producer's `on_time_movement_pct` denominator entirely."

        Design: Difficulty/compensating_invariant/premises_head_count_conserved_when_movement_is_voided
        """
        scenario = _disputed_after_arrival(state_code="WY")
        assert read_premises(scenario["destination"]["id"])["animal_count"] == 0

        voided = validate_success(api.void_movement_event(scenario["movement"]["id"], ADMIN))
        assert voided["status"] == "VOIDED"

        animal = read_animal(scenario["animal"]["id"])
        assert animal["lifecycle_status"] == "ACTIVE"
        assert animal["current_premises_id"] == scenario["origin"]["id"]
        assert animal["sighting_count"] == 1, "both movement observations were reversed"

    def test_voiding_conserves_the_two_premises_head_total_and_clears_the_denominator(self, api):
        """PRD §2.8: "Second, compensating actions restore the totals they unwind: voiding a movement returns the animal to its origin so that the sum of origin and destination `animal_count` returns to its pre-departure value, and clawing back an award returns a producer's `incentive_balance_cents` to its pre-payment value."
        PRD §3.5: "A producer with no qualifying movements at all scores 100.00 rather than a zero-over-zero result. Voided movements leave both the numerator and the denominator entirely."

        Design: Difficulty/compensating_invariant/premises_head_count_conserved_when_movement_is_voided
        """
        scenario = _disputed_after_arrival(state_code="WY")

        validate_success(api.void_movement_event(scenario["movement"]["id"], ADMIN))

        origin_count = read_premises(scenario["origin"]["id"])["animal_count"]
        destination_count = read_premises(scenario["destination"]["id"])["animal_count"]
        assert origin_count == 1
        assert destination_count == 0
        assert origin_count + destination_count == 1, (
            "the head total returns to exactly its pre-departure value"
        )
        assert read_producer(scenario["producer"]["id"])["on_time_movement_pct"] == 100.00


class TestSightingHistory:
    def test_sighting_history_is_append_ordered_and_hides_reversed_rows(self, api):
        """PRD §2.3: "The one documented exception is the sighting history, which is ordered by `sequence_no` ascending so that an animal's event log always reads in append order."
        PRD §3.4: "The sighting history may be filtered by `animal_id`, `premises_id`, `source_movement_id` and `sighting_type`, and reversed rows are excluded from it unless `include_reversed` is supplied as true."
        PRD §2.11: "After each replay, `sighting_count` is set to the number of non-reversed rows and `last_sequence_no` is set to the highest `sequence_no` across all of that animal's rows, reversed rows included."

        Design: Corner/endpoints/sighting_history_is_ordered_and_hides_reversed_rows_by_default
        """
        scenario = _disputed_after_arrival(state_code="WY", arrive_same_instant=True)
        validate_success(api.void_movement_event(scenario["movement"]["id"], ADMIN))

        visible = sightings_of_animal(scenario["animal"]["id"])
        assert len(visible) == 1
        assert visible[0]["sequence_no"] == 1
        assert visible[0]["sighting_type"] == "TAG_APPLIED"
        assert visible[0]["reversed"] is False

        everything = sightings_of_animal(scenario["animal"]["id"], include_reversed=True)
        assert [row["sequence_no"] for row in everything] == [1, 2, 3]
        assert [row["sighting_type"] for row in everything] == [
            "TAG_APPLIED",
            "DEPARTURE",
            "ARRIVAL",
        ]
        for row in everything[1:]:
            assert row["reversed"] is True
            assert row["source_movement_id"] == scenario["movement"]["id"]

        by_movement, meta = validate_paginated(
            api.list_sightings(
                ADMIN,
                params={
                    "source_movement_id": scenario["movement"]["id"],
                    "include_reversed": "true",
                },
            )
        )
        assert meta["total_count"] == 2
        assert len(by_movement) == 2

        animal = read_animal(scenario["animal"]["id"])
        assert animal["sighting_count"] == 1
        assert animal["last_sequence_no"] == 3


def _disputed_after_arrival(state_code: str = "MT", arrive_same_instant: bool = False) -> dict:
    """Depart, receive and then dispute one movement, leaving the arrival reversed."""
    scenario = setup_two_premises_scenario(
        origin_state=state_code, destination_state=state_code, capacity=30, quantity=10
    )
    departure_instant = "2026-08-09T00:00:00Z"
    arrival_instant = "2026-08-09T00:00:00Z" if arrive_same_instant else "2026-08-10T00:00:00Z"

    set_clock(departure_instant)
    movement = report_departure(
        scenario["producer"]["id"],
        scenario["animal"]["id"],
        scenario["origin"]["id"],
        scenario["destination"]["id"],
        departure_instant,
    )
    set_clock(arrival_instant)
    receive_arrival(movement["id"], scenario["producer"]["id"], arrival_instant)
    dispute_movement(movement["id"], reason="arrival scan not corroborated")
    set_clock("2026-08-12T00:00:00Z")

    scenario["movement"] = movement
    return scenario
