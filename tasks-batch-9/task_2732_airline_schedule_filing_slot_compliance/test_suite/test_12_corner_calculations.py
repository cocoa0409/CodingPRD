"""Calculation breadth: charges, scores, tiers, thresholds and orderings.

The filing charge is priced once and frozen; the compliance score charges its
weights per leg and filters cancelled legs out of the input set; the
compensation tier flips inclusively at 120 minutes; the connect-time minimum is
inclusive; and utilization credit is order-independent.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_charge_breakdown,
    assert_filing_submission,
    assert_flight_leg,
    assert_notification_obligation,
    assert_score_matches_counters,
    assert_slot_utilization_record,
    assert_timestamp_equals,
    assert_utilization_math,
    cancel_leg,
    create_flight_leg,
    create_flight_leg_payload,
    create_notification_obligation_payload,
    create_schedule_version,
    create_slot_holding,
    create_station,
    file_utilization_record,
    queue_submission,
    raise_obligation,
    read_holding,
    read_leg,
    read_version,
    retime_leg,
    setup_booked_leg,
    setup_monday_series_schedule,
    setup_reference_data,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["filing_agent_headers"]


# ─── The filing charge, priced once and frozen ────────────────────────────

def _two_slot_backed_legs_filed_standard():
    """A validated two-leg version with one STANDARD submission queued."""
    return setup_monday_series_schedule(
        leg_count=2,
        series_weeks=2,
        version_label="W26-F1",
        validate=True,
        submission={"distribution_system": "OAG", "change_window": "STANDARD"},
    )


class TestTwoStandardLegsPriceAtEightThousandFourHundredFifty:
    """Tier one carries no surcharge and STANDARD carries no expedite fee."""

    def test_the_whole_breakdown_falls_out_of_the_two_leg_count(self):
        """8450 raw, 8450 subtotal, no fee, 8450 total.

        PRD §3.8: "Second, a raw amount equal to that count multiplied by 4225
        cents per leg. Third, a volume surcharge chosen by the count: at 5 legs or
        fewer the surcharge is 0.00 percent"

        Design: Corner/calculations/filing_charge_for_two_standard_legs_totals_eight_thousand_four_hundred_fifty
        """
        world = _two_slot_backed_legs_filed_standard()
        submission = world["submission"]

        assert_filing_submission(submission)
        assert submission["changed_leg_count"] == 2
        assert submission["base_charge_subtotal_cents"] == 8450
        assert submission["expedite_rate_pct"] == pytest.approx(0.00, abs=0.01)
        assert submission["expedite_fee_cents"] == 0
        assert submission["total_charge_cents"] == 8450
        assert submission["status"] == "QUEUED"
        assert submission["codeshare_sync_status"] == "NOT_REQUIRED"
        assert submission["submitted_by_user_id"] == "usr-file-1"
        assert_charge_breakdown(submission)

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0

    def test_a_leg_leaving_slot_backed_reprices_only_the_next_submission(self):
        """The frozen count on the queued submission is never recomputed.

        PRD §3.8: "At the instant of creation, `changed_leg_count` is set to the
        number of legs of that schedule version whose `status` is `SLOT_BACKED` or
        `CANCELLED` - the legs that represent a change the distribution system
        needs to hear about, whether an addition or a removal - and it is **never
        recomputed afterwards**."

        Design: Corner/calculations/filing_charge_for_two_standard_legs_totals_eight_thousand_four_hundred_fifty
        """
        world = _two_slot_backed_legs_filed_standard()
        first = world["submission"]

        retimed = retime_leg(
            world["carrier"]["id"],
            world["legs"][1]["id"],
            "2026-11-09T10:00:00.000Z",
            "2026-11-09T11:00:00.000Z",
        )
        # The retime nulled the slot the leg requires at the coordinated hub, so
        # it falls back out of `SLOT_BACKED`.
        assert retimed["status"] == "ASSIGNED"
        assert retimed["departure_slot_holding_id"] is None

        second = queue_submission(
            world["version"]["id"],
            change_window="STANDARD",
            distribution_system="OAG",
        )
        assert second["changed_leg_count"] == 1
        assert second["base_charge_subtotal_cents"] == 4225
        assert second["total_charge_cents"] == 4225
        assert_charge_breakdown(second)

        unchanged = validate_success(
            api_client.get_filing_submission(first["id"], AGENT)
        )
        assert unchanged["changed_leg_count"] == 2
        assert unchanged["total_charge_cents"] == 8450

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0


# ─── The compliance score, charged per leg ────────────────────────────────

def _coordinated_departures_without_slots():
    """A version at the coordinated hub whose legs never get a slot."""
    ref = setup_reference_data(("FRA", "MUC"))
    version = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-C1"
    )
    ref["version"] = version

    def add(flight_number: str, date: str):
        return create_flight_leg(
            ref["carrier"]["id"],
            version["id"],
            ref["stations"]["FRA"]["id"],
            ref["stations"]["MUC"]["id"],
            f"{date}T08:00:00.000Z",
            f"{date}T09:00:00.000Z",
            flight_number=flight_number,
        )

    ref["add"] = add
    return ref


class TestEachUnslottedLegCostsEightPoints:
    """One unslotted leg is 92.00; two are 84.00, not 92.00 again."""

    def test_the_first_unslotted_leg_takes_exactly_eight_points(self):
        """92.00 is still at or above the warning threshold, so `CLEAN`.

        PRD §3.7: "The raw penalty is the sum of `curfew_violation_count` times
        12.00, `mct_violation_count` times 7.00, `gate_overflow_count` times 9.00,
        `unslotted_leg_count` times 8.00 and `at_risk_slot_count` times 15.00."

        Design: Corner/calculations/compliance_score_deducts_eight_points_for_each_unslotted_coordinated_leg
        """
        world = _coordinated_departures_without_slots()
        world["add"]("HX101", "2026-11-02")

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(92.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"
        assert_score_matches_counters(version)

    def test_the_weight_is_charged_once_per_leg_and_not_once_per_version(self):
        """Two unslotted legs cross into the warning band at 84.00.

        PRD §3.7: "Otherwise it is `WARNED` when the score is strictly below
        85.00."

        Design: Corner/calculations/compliance_score_deducts_eight_points_for_each_unslotted_coordinated_leg
        """
        world = _coordinated_departures_without_slots()
        first = world["add"]("HX101", "2026-11-02")
        second = world["add"]("HX103", "2026-11-09")
        assert first["status"] == "DRAFT"
        assert second["status"] == "DRAFT"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 2
        assert version["schedule_compliance_score"] == pytest.approx(84.00, abs=0.01)
        assert version["compliance_state"] == "WARNED"
        assert version["leg_count"] == 2
        assert version["curfew_violation_count"] == 0
        assert version["mct_violation_count"] == 0
        assert version["gate_overflow_count"] == 0
        assert version["at_risk_slot_count"] == 0
        assert_score_matches_counters(version)


class TestCancelledLegsLeaveTheScoreInputSet:
    """The cancelled leg stays on the manifest and leaves every other counter."""

    def test_cancelling_one_of_two_unslotted_legs_repairs_the_score(self):
        """84.00 walks back to 92.00 and `WARNED` back to `CLEAN`.

        PRD §3.4: "`unslotted_leg_count` is the number of non-cancelled legs that
        are not fully slotted, meaning either the leg's `status` is
        `REFILE_REQUIRED` or some slot the leg requires has no holding attached"

        Design: Corner/calculations/cancelled_legs_drop_out_of_the_compliance_score_input_set
        """
        world = _coordinated_departures_without_slots()
        world["add"]("HX101", "2026-11-02")
        second = world["add"]("HX103", "2026-11-09")

        cancelled = cancel_leg(
            world["carrier"]["id"], second["id"], "DEMAND_SHORTFALL"
        )
        assert cancelled["status"] == "CANCELLED"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["unslotted_leg_count"] == 1
        assert version["schedule_compliance_score"] == pytest.approx(92.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"
        assert_score_matches_counters(version)

    def test_the_manifest_counter_keeps_the_cancelled_leg(self):
        """`leg_count` is the one counter that does not filter cancellations.

        PRD §3.4: "That is a deliberate exception: every other counter on the
        version excludes cancelled legs."

        Design: Corner/calculations/cancelled_legs_drop_out_of_the_compliance_score_input_set
        """
        world = _coordinated_departures_without_slots()
        world["add"]("HX101", "2026-11-02")
        second = world["add"]("HX103", "2026-11-09")
        cancel_leg(world["carrier"]["id"], second["id"], "DEMAND_SHORTFALL")

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_flight_legs(
                world["planner"],
                params={
                    "schedule_version_id": world["version"]["id"],
                    "status": "CANCELLED",
                },
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == second["id"]


# ─── The compensation tier, inclusive on the mandatory side ───────────────

def _ten_economy_passengers():
    """One leg carrying exactly ten economy passengers and nothing else."""
    return setup_booked_leg(
        booked_first=0,
        booked_business=0,
        booked_economy=10,
        version_label="W26-N1",
    )


class TestCompensationTierFlipsAtExactlyOneHundredTwentyMinutes:
    """119 minutes is advisory at 37.50 percent; 120 is mandatory at 100.00."""

    def test_one_hundred_nineteen_minutes_is_advisory_at_thirty_seven_and_a_half(self):
        """10 economy at 25124 is 251240, and 37.50 percent of that is 94215.

        PRD §3.9: "`obligation_tier` follows from the magnitude: `ADVISORY` when
        the magnitude is at least 30 and strictly below 120, and
        `MANDATORY_REACCOMMODATION` when it is 120 or more."

        Design: Corner/calculations/compensation_tier_flips_to_mandatory_at_exactly_one_hundred_twenty_minutes
        """
        world = _ten_economy_passengers()

        advisory = raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=119
        )
        assert_notification_obligation(advisory)
        assert advisory["obligation_tier"] == "ADVISORY"
        assert advisory["booked_total"] == 10
        assert advisory["booked_economy"] == 10
        assert advisory["compensation_cents"] == 94215
        assert advisory["status"] == "PENDING"
        assert advisory["dispatched_channel"] is None
        assert advisory["regulator_reference"] is None
        assert advisory["late_dispatch"] is False
        assert_timestamp_equals(
            advisory["notify_deadline_utc"],
            "2026-08-04T00:00:00Z",
            "notify_deadline_utc",
        )

    def test_exactly_one_hundred_twenty_minutes_is_mandatory_at_full_rate(self):
        """The multiplier reaches 100.00 percent, so the raw 251240 stands.

        PRD §3.9: "The tier selects a multiplier: 37.50 percent for `ADVISORY` and
        100.00 percent for `MANDATORY_REACCOMMODATION`."

        Design: Corner/calculations/compensation_tier_flips_to_mandatory_at_exactly_one_hundred_twenty_minutes
        """
        world = _ten_economy_passengers()
        raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=119
        )

        mandatory = raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=120
        )
        assert mandatory["obligation_tier"] == "MANDATORY_REACCOMMODATION"
        assert mandatory["booked_total"] == 10
        assert mandatory["compensation_cents"] == 251240
        assert mandatory["status"] == "PENDING"
        assert mandatory["late_dispatch"] is False

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["open_obligation_count"] == 2

    def test_twenty_nine_minutes_persists_no_obligation_at_all(self):
        """Below the 30-minute floor the manual endpoint refuses outright.

        PRD §3.9: "An obligation exists at all only when two conditions both hold:
        the leg's booked total across all three cabins is greater than zero, and
        `change_magnitude_minutes` is at least 30."

        Design: Corner/calculations/compensation_tier_flips_to_mandatory_at_exactly_one_hundred_twenty_minutes
        """
        world = _ten_economy_passengers()
        raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=119
        )
        raise_obligation(
            world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=120
        )

        validate_error(
            api_client.create_notification_obligation(
                create_notification_obligation_payload(
                    world["leg"]["id"], "RETIME", 29
                ),
                OFFICER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["open_obligation_count"] == 2

        rows, meta = validate_paginated(
            api_client.list_notification_obligations(
                OFFICER, params={"flight_leg_id": world["leg"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


# ─── The connect-time minimum, inclusive at the published figure ──────────

def _inbound_arriving_at_the_forty_minute_station():
    """A TXL->MUC inbound landing at 08:00Z where MUC publishes 40 minutes."""
    carrier_ref = setup_reference_data(("TXL",))
    muc = create_station(
        "MUC", min_connect_domestic_minutes=40, min_connect_international_minutes=75
    )
    carrier_ref["stations"]["MUC"] = muc
    version = create_schedule_version(
        carrier_ref["carrier"]["id"],
        carrier_ref["season"]["id"],
        version_label="W26-M1",
    )
    carrier_ref["version"] = version
    carrier_ref["inbound"] = create_flight_leg(
        carrier_ref["carrier"]["id"],
        version["id"],
        carrier_ref["stations"]["TXL"]["id"],
        muc["id"],
        "2026-11-03T07:00:00.000Z",
        "2026-11-03T08:00:00.000Z",
        flight_number="HX350",
    )
    return carrier_ref


def _onward_payload(world, dep: str, arr: str, flight_number: str):
    return create_flight_leg_payload(
        world["version"]["id"],
        world["stations"]["MUC"]["id"],
        world["stations"]["TXL"]["id"],
        dep,
        arr,
        flight_number=flight_number,
        connects_from_leg_id=world["inbound"]["id"],
    )


class TestConnectTimeMinimumIsInclusive:
    """39 minutes is refused at creation; exactly 40 has a shortfall of zero."""

    def test_one_minute_under_the_published_minimum_is_refused(self):
        """The refusal happens at creation, so nothing lands on the version.

        PRD §3.4: "departing at 10:34 gives a connect of 34, a shortfall of 1, and
        rejection with `ERR_MIN_CONNECT_TIME_VIOLATION`."

        Design: Corner/calculations/mct_shortfall_is_zero_at_exactly_the_station_minimum_connect_time
        """
        world = _inbound_arriving_at_the_forty_minute_station()

        validate_error(
            api_client.create_flight_leg(
                _onward_payload(
                    world,
                    "2026-11-03T08:39:00.000Z",
                    "2026-11-03T09:39:00.000Z",
                    "HX351",
                ),
                world["planner"],
            ),
            ApiErrorId.ERR_MIN_CONNECT_TIME_VIOLATION,
            expected_status=422,
        )

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 1
        assert version["mct_violation_count"] == 0

    def test_exactly_the_published_minimum_gives_a_shortfall_of_zero(self):
        """40 against a required 40 is short by nothing at all.

        PRD §3.4: "`mct_shortfall_minutes` is the amount by which the connect time
        falls short of that minimum, floored at 0 - so a connection meeting or
        exceeding the minimum has a shortfall of 0, since the minimum is
        inclusive."

        Design: Corner/calculations/mct_shortfall_is_zero_at_exactly_the_station_minimum_connect_time
        """
        world = _inbound_arriving_at_the_forty_minute_station()
        validate_error(
            api_client.create_flight_leg(
                _onward_payload(
                    world,
                    "2026-11-03T08:39:00.000Z",
                    "2026-11-03T09:39:00.000Z",
                    "HX351",
                ),
                world["planner"],
            ),
            ApiErrorId.ERR_MIN_CONNECT_TIME_VIOLATION,
        )

        onward = validate_success(
            api_client.create_flight_leg(
                _onward_payload(
                    world,
                    "2026-11-03T08:40:00.000Z",
                    "2026-11-03T09:40:00.000Z",
                    "HX352",
                ),
                world["planner"],
            ),
            expected_status=201,
        )
        assert_flight_leg(onward)
        assert onward["connect_minutes"] == 40
        assert onward["mct_shortfall_minutes"] == 0
        assert onward["is_international"] is False
        assert onward["block_minutes"] == 60
        assert onward["connects_from_leg_id"] == world["inbound"]["id"]

        # The inbound leg starts the itinerary, so it connects from nothing.
        inbound = read_leg(world["inbound"]["id"], world["planner"])
        assert inbound["connects_from_leg_id"] is None
        assert inbound["connect_minutes"] is None
        assert inbound["mct_shortfall_minutes"] == 0

        version = read_version(world["version"]["id"], world["planner"])
        assert version["leg_count"] == 2
        assert version["mct_violation_count"] == 0
        assert version["schedule_compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert version["compliance_state"] == "CLEAN"


# ─── Utilization credit, independent of arrival order ─────────────────────

def _series_filed_out_of_order():
    """Four dated outcomes posted 11-23, 11-02, 11-16, 11-09 in that order."""
    ref = setup_reference_data(("FRA",))
    holding = create_slot_holding(
        ref["stations"]["FRA"]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc="2026-11-02T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
    )
    ref["holding"] = holding
    ref["records"] = [
        file_utilization_record(holding["id"], f"{date}T00:00:00.000Z", outcome)
        for date, outcome in (
            ("2026-11-23", "OPERATED"),
            ("2026-11-02", "OPERATED"),
            ("2026-11-16", "CANCELLED_ATC"),
            ("2026-11-09", "CANCELLED_CARRIER"),
        )
    ]
    return ref


class TestUtilizationCreditIsOrderIndependent:
    """Three crediting outcomes and one carrier cancellation, shuffled."""

    def test_the_crediting_flag_follows_the_outcome_and_not_the_position(self):
        """The first record posted is the last operating day of the four.

        PRD §3.5: "records may legitimately be posted out of chronological order
        and the derived figures must be identical whichever order they arrive in."

        Design: Corner/calculations/utilization_records_posted_out_of_chronological_order_credit_the_same_total
        """
        world = _series_filed_out_of_order()
        records = world["records"]

        for record in records:
            assert_slot_utilization_record(record)
            assert record["recorded_by_user_id"] == "usr-coord-1"

        assert [record["credited"] for record in records] == [
            True,
            True,
            True,
            False,
        ]
        assert records[3]["outcome"] == "CANCELLED_CARRIER"

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["planned_operations"] == 5
        assert holding["credited_operations"] == 3
        assert holding["utilization_pct"] == pytest.approx(60.00, abs=0.01)
        assert_utilization_math(holding)

    def test_posting_records_never_moves_the_as_filed_variant(self):
        """The as-operated figure moved and the as-filed one did not.

        PRD §3.5: "Filing a record recomputes `credited_operations` and
        `utilization_pct` and **only** those: `utilization_pct_as_filed` is
        untouched, because what happened on the day says nothing about what is
        currently attached."

        Design: Corner/calculations/utilization_records_posted_out_of_chronological_order_credit_the_same_total
        """
        world = _series_filed_out_of_order()

        holding = read_holding(world["holding"]["id"], COORDINATOR)
        assert holding["attached_operations"] == 0
        assert holding["utilization_pct_as_filed"] == pytest.approx(0.00, abs=0.01)
        assert holding["at_risk_of_loss"] is False
        # Only the season audit may take a series away.
        assert holding["holding_status"] == "HELD"

        rows, meta = validate_paginated(
            api_client.list_slot_utilization_records(
                COORDINATOR, params={"slot_holding_id": world["holding"]["id"]}
            )
        )
        assert meta["total_count"] == 4
        assert meta["has_more"] is False
        assert sum(1 for row in rows if row["credited"]) == 3

        operated, operated_meta = validate_paginated(
            api_client.list_slot_utilization_records(
                COORDINATOR,
                params={
                    "slot_holding_id": world["holding"]["id"],
                    "outcome": "OPERATED",
                },
            )
        )
        assert operated_meta["total_count"] == 2
        assert all(row["outcome"] == "OPERATED" for row in operated)
