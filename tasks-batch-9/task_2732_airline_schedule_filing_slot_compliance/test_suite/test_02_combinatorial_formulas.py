"""Two formulas whose evaluation order is outcome-changing.

Passenger compensation rounds each cabin before summing; the filing charge
keys its expedite fee on the post-surcharge subtotal. Both have a wrong answer
that a plausible reordering produces, and both wrong answers are pinned here.
"""

import pytest

from test_helpers import (
    api_client,
    assert_charge_breakdown,
    assert_compensation,
    assert_integer_cents,
    assert_notification_obligation,
    assert_timestamp_equals,
    assign_aircraft,
    create_aircraft,
    create_carrier,
    create_flight_leg,
    create_notification_obligation_payload,
    create_open_season,
    create_schedule_version,
    create_station,
    make_network_planner_headers,
    read_leg,
    read_version,
    snapshot_bookings,
    validate_success,
    validate_version,
    TEST_USERS,
)

OFFICER = TEST_USERS["compliance_officer_headers"]
AGENT = TEST_USERS["filing_agent_headers"]


def _booked_leg_at_facilitated_stations():
    """One MUC->TXL leg carrying 3 first, 7 business and 41 economy.

    Neither station is fully coordinated, so the leg needs no slot and no tail
    for the passenger-impact rules to apply.
    """
    carrier = create_carrier()
    muc = create_station("MUC")
    txl = create_station("TXL", maintenance_capable=False)
    season = create_open_season()
    version = create_schedule_version(
        carrier["id"], season["id"], version_label="W26-N1"
    )
    leg = create_flight_leg(
        carrier["id"],
        version["id"],
        muc["id"],
        txl["id"],
        "2026-11-03T06:00:00.000Z",
        "2026-11-03T07:00:00.000Z",
        flight_number="HX301",
    )
    snapshot_bookings(carrier["id"], leg["id"], 3, 7, 41)
    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "version": version,
        "leg": leg,
    }


class TestCompensationRoundsEachCabinFirst:
    """The per-cabin rounding order is worth exactly one cent, and the contract
    names which cent."""

    def test_advisory_compensation_is_five_six_one_one_three_two(self):
        """Rounding each cabin first gives 561132, not 561131.

        PRD §3.9: "First class is 3 times 61500, which is 184500, times 0.375,
        which is 69187.5, rounding to 69188. Business is 7 times 40252, which is
        281764, times 0.375, which is 105661.5, rounding to 105662. Economy is
        41 times 25124, which is 1030084, times 0.375, which is 386281.5,
        rounding to 386282. The sum is 69188 plus 105662 plus 386282, so
        `compensation_cents` is 561132, and `booked_total` is 51."

        Design: Difficulty/combinatorial_formula/notification_compensation_rounds_each_cabin_before_summing
        """
        world = _booked_leg_at_facilitated_stations()

        response = api_client.create_notification_obligation(
            create_notification_obligation_payload(
                world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=45
            ),
            OFFICER,
        )
        obligation = validate_success(response, expected_status=201)
        assert_notification_obligation(obligation)

        assert obligation["booked_total"] == 51
        assert obligation["obligation_tier"] == "ADVISORY"
        assert_integer_cents(obligation["compensation_cents"], "compensation_cents")
        assert obligation["compensation_cents"] == 561132
        # 69187.5 + 105661.5 + 386281.5 = 561130.5, which rounds to 561131.
        assert obligation["compensation_cents"] != 561131
        assert 69188 + 105662 + 386282 == obligation["compensation_cents"]
        assert_compensation(obligation)

    def test_obligation_starts_pending_with_a_frozen_seventy_two_hour_deadline(self):
        """The deadline is the clock plus 72 hours and the leg's open counter
        rises.

        PRD §3.9: "`notify_deadline_utc` is the logical clock's `current_utc` at
        creation plus 72 hours. It is **frozen** on the row and never
        recomputed, so advancing the clock afterwards moves the world past a
        fixed deadline rather than pushing the deadline along."

        Design: Difficulty/combinatorial_formula/notification_compensation_rounds_each_cabin_before_summing
        """
        world = _booked_leg_at_facilitated_stations()

        obligation = validate_success(
            api_client.create_notification_obligation(
                create_notification_obligation_payload(
                    world["leg"]["id"],
                    trigger_kind="RETIME",
                    change_magnitude_minutes=45,
                ),
                OFFICER,
            ),
            expected_status=201,
        )

        assert obligation["status"] == "PENDING"
        assert_timestamp_equals(
            obligation["notify_deadline_utc"],
            "2026-08-04T00:00:00Z",
            "notify_deadline_utc",
        )
        assert obligation["late_dispatch"] is False

        leg = read_leg(world["leg"]["id"], world["planner"])
        assert leg["open_obligation_count"] == 1

    def test_tier_below_one_twenty_selects_the_advisory_multiplier(self):
        """A 45-minute change is advisory, which is what makes the multiplier
        37.50 percent.

        PRD §3.9: "`obligation_tier` follows from the magnitude: `ADVISORY` when
        the magnitude is at least 30 and strictly below 120, and
        `MANDATORY_REACCOMMODATION` when it is 120 or more."

        Design: Difficulty/combinatorial_formula/notification_compensation_rounds_each_cabin_before_summing
        """
        world = _booked_leg_at_facilitated_stations()

        obligation = validate_success(
            api_client.create_notification_obligation(
                create_notification_obligation_payload(
                    world["leg"]["id"],
                    trigger_kind="RETIME",
                    change_magnitude_minutes=45,
                ),
                OFFICER,
            ),
            expected_status=201,
        )

        assert obligation["change_magnitude_minutes"] == 45
        assert obligation["obligation_tier"] == "ADVISORY"
        assert obligation["booked_first"] == 3
        assert obligation["booked_business"] == 7
        assert obligation["booked_economy"] == 41
        assert obligation["compensation_cents"] == 561132


def _six_leg_validated_version():
    """Six legs on one UTC date, every turn exactly 45 minutes, validated."""
    carrier = create_carrier()
    muc = create_station("MUC")
    txl = create_station("TXL", maintenance_capable=False)
    season = create_open_season()
    aircraft = create_aircraft(
        carrier["id"], muc["id"], registration="D-AHXC", maintenance_check_required=False
    )
    version = create_schedule_version(
        carrier["id"], season["id"], version_label="W26-F1"
    )

    rotation = (
        ("HX401", muc, txl, "06:00", "07:00"),
        ("HX402", txl, muc, "07:45", "08:45"),
        ("HX403", muc, txl, "09:30", "10:30"),
        ("HX404", txl, muc, "11:15", "12:15"),
        ("HX405", muc, txl, "13:00", "14:00"),
        ("HX406", txl, muc, "14:45", "15:45"),
    )
    for flight_number, origin, dest, dep, arr in rotation:
        leg = create_flight_leg(
            carrier["id"],
            version["id"],
            origin["id"],
            dest["id"],
            f"2026-11-03T{dep}:00.000Z",
            f"2026-11-03T{arr}:00.000Z",
            flight_number=flight_number,
        )
        assign_aircraft(carrier["id"], leg["id"], aircraft["id"])

    validate_version(version["id"])
    return {
        "carrier": carrier,
        "planner": make_network_planner_headers(carrier["id"]),
        "aircraft": aircraft,
        "version": version,
    }


class TestExpediteFeeKeyedOnSubtotal:
    """Six legs expedited: the fee is a percentage of the post-surcharge
    subtotal."""

    def test_six_expedited_legs_total_thirty_eight_thousand_five_hundred_one(self):
        """Every step of the five-step breakdown is pinned.

        PRD §3.8: "At the tier edges: 5 legs is tier one, giving a subtotal of
        21125, while 6 legs is tier two, raw 25350 becoming 28518.75 and
        rounding to 28519"

        Design: Difficulty/combinatorial_formula/filing_charge_expedite_fee_keyed_on_post_surcharge_subtotal_not_raw
        """
        world = _six_leg_validated_version()

        submission = validate_success(
            api_client.create_filing_submission(
                {
                    "schedule_version_id": world["version"]["id"],
                    "distribution_system": "IATA_SSIM",
                    "change_window": "EXPEDITED",
                },
                AGENT,
            ),
            expected_status=201,
        )

        assert submission["changed_leg_count"] == 6
        assert submission["base_charge_subtotal_cents"] == 28519
        assert submission["expedite_rate_pct"] == pytest.approx(35.00, abs=0.01)
        assert submission["expedite_fee_cents"] == 9982
        assert submission["total_charge_cents"] == 38501
        assert_charge_breakdown(submission)

    def test_the_fee_is_not_keyed_on_the_raw_amount(self):
        """Keying the fee on the raw amount would give 8873 and a total of
        37392.

        PRD §3.8: "The expedite fee is keyed on the **post-surcharge
        subtotal**, never on the raw amount and never on a total that already
        contains the fee."

        Design: Difficulty/combinatorial_formula/filing_charge_expedite_fee_keyed_on_post_surcharge_subtotal_not_raw
        """
        world = _six_leg_validated_version()

        submission = validate_success(
            api_client.create_filing_submission(
                {
                    "schedule_version_id": world["version"]["id"],
                    "distribution_system": "IATA_SSIM",
                    "change_window": "EXPEDITED",
                },
                AGENT,
            ),
            expected_status=201,
        )

        # 25350 raw * 0.35 = 8872.5 -> 8873, and 25350 + ... -> 37392.
        assert submission["expedite_fee_cents"] != 8873
        assert submission["total_charge_cents"] != 37392
        assert (
            submission["base_charge_subtotal_cents"] + submission["expedite_fee_cents"]
            == submission["total_charge_cents"]
        )

    def test_queueing_a_submission_accrues_nothing_yet(self):
        """The frozen price is not a charge until the filing is transmitted.

        PRD §2.6: "`filing_charge_accrued_cents` on a schedule version always
        equals the sum of `total_charge_cents` over that version's filing
        submissions whose `status` is `TRANSMITTED` or `ACKNOWLEDGED`."

        Design: Difficulty/combinatorial_formula/filing_charge_expedite_fee_keyed_on_post_surcharge_subtotal_not_raw
        """
        world = _six_leg_validated_version()

        submission = validate_success(
            api_client.create_filing_submission(
                {
                    "schedule_version_id": world["version"]["id"],
                    "distribution_system": "IATA_SSIM",
                    "change_window": "EXPEDITED",
                },
                AGENT,
            ),
            expected_status=201,
        )
        assert submission["status"] == "QUEUED"

        version = read_version(world["version"]["id"], world["planner"])
        assert version["filing_charge_accrued_cents"] == 0
        assert version["filing_status"] == "VALIDATED"
