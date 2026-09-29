"""Money and timing calculations on departures, bookings and commission statements.

Each test drives the pinned arithmetic of one calculation — the two timing-risk
bases, the five pricing steps, the two commission bases and the nine-step
settlement waterfall — and asserts the exact cents, minutes and bands the PRD
derives.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions, fixtures
from test_helpers.test_users import TEST_USERS


# ==========================================================================
# The two timing-risk bases on one departure
# ==========================================================================

def test_scheduled_basis_ignores_the_delay_and_stays_green(api):
    """PRD §3.4: "On the **scheduled basis**, the group is assumed to start at its ticketed `meeting_time_utc`, ignoring both the call's accumulated `delay_minutes` and the assigned wave's landing window entirely."

    PRD §3.4: "`slack_minutes_scheduled` is the number of minutes from `projected_return_scheduled_utc` to the call's `all_aboard_utc`, less the port's `risk_buffer_minutes`; it may be negative."

    Design: Difficulty/dual_variant_calc/timing_risk_scheduled_green_versus_actual_red_on_the_same_departure
    """
    world = fixtures.setup_selling_departure(api, tender=True)

    fixtures.record_delay(api, world.port_call["id"], 75, reason_code="PILOT_DELAY")

    departure = fixtures.get_departure(api, world.departure["id"])
    # Ashore leg = 300 duration + 30 transfer + 25 tender egress = 355 minutes
    # from the ticketed 09:00Z meeting time, so the group is back at 14:55Z.
    assert datetime.fromisoformat(
        departure["projected_return_scheduled_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 14, 55, tzinfo=timezone.utc)
    assertions.assert_field_values(
        departure,
        slack_minutes_scheduled=65,
        timing_risk_band_scheduled="GREEN",
    )
    assert datetime.fromisoformat(
        departure["meeting_time_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)


def test_actual_basis_floors_on_the_delayed_wave_landing_and_turns_red(api):
    """PRD §3.4: "So when a wave is assigned, the start is the later of `meeting_time_utc` and the wave's `window_end_utc` advanced by the call's `delay_minutes`; when no wave is assigned, the start is `meeting_time_utc` advanced by `delay_minutes`."

    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Difficulty/dual_variant_calc/timing_risk_scheduled_green_versus_actual_red_on_the_same_departure
    """
    world = fixtures.setup_selling_departure(api, tender=True)

    fixtures.record_delay(api, world.port_call["id"], 75, reason_code="PILOT_DELAY")

    departure = fixtures.get_departure(api, world.departure["id"])
    # The wave lands 08:50Z + 75 minutes of delay = 10:05Z, which is later than
    # the 09:00Z meeting time, so the 355-minute ashore leg ends at 16:00Z and
    # the whole 30-minute risk buffer is consumed.
    assert datetime.fromisoformat(
        departure["projected_return_actual_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 16, 0, tzinfo=timezone.utc)
    assertions.assert_field_values(
        departure,
        slack_minutes_actual=0,
        timing_risk_band_actual="RED",
    )


def test_delay_burns_slack_and_closes_the_selling_departure(api):
    """PRD §3.1: "Each report adds to `delay_minutes`, which may never be negative, and `effective_arrival_utc` is recomputed as `arrival_utc` shifted later by `delay_minutes`."

    PRD §3.1: "Every departure on the call has its actual-basis projection and `timing_risk_band_actual` recomputed on the spot, and the recomputation can cascade: each departure that is `SELLING` and whose `timing_risk_band_actual` has just become `RED` moves `SELLING → CLOSED`, and each of that departure's never-charged bookings — those still in `BOOKED` with `financial_status` `AUTHORIZED` — moves to `CANCELLED_BY_LINE` with `financial_status` `VOIDED`, an `AUTH_VOID` ledger entry of `amount_cents` 0 on the `LINE_CANCELLED_OPERATIONAL` `basis`, and its seats returned to its own channel bucket."

    Design: Difficulty/dual_variant_calc/timing_risk_scheduled_green_versus_actual_red_on_the_same_departure
    """
    world = fixtures.setup_selling_departure(api, tender=True)
    assert world.departure["status"] == "SELLING"

    fixtures.record_delay(api, world.port_call["id"], 75, reason_code="PILOT_DELAY")

    port_call = validate_success(
            api.get_port_call(world.port_call["id"], TEST_USERS["port_agent_headers"])
        )
    
    assert port_call["delay_minutes"] == 75
    assert datetime.fromisoformat(
        port_call["effective_arrival_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 9, 15, tzinfo=timezone.utc)
    assert datetime.fromisoformat(
        port_call["all_aboard_utc"].replace("Z", "+00:00")
    ) == datetime(2026, 9, 15, 16, 30, tzinfo=timezone.utc)

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "CLOSED"


# ==========================================================================
# The four-axis booking quote
# ==========================================================================

def test_platinum_group_onboard_quote_clamps_the_blended_discount(api):
    """PRD §3.5: "The blended discount is the larger of the two components plus half of the smaller with any fraction discarded, and the result is then capped at 1200 basis points — twelve percent is the most any booking may ever be discounted."

    PRD §3.5: "`per_guest_price_cents` is the channel price multiplied by ten thousand minus the blended discount in basis points, divided by ten thousand, rounded half up."

    Design: Difficulty/combinatorial_formula/booking_quote_four_axis_blend_where_the_discount_cap_binds
    """
    world = fixtures.setup_selling_departure(
        api,
        excursion={
            "title": "Private Cenote Signature",
            "base_price_cents": 20000,
            "price_tier": "SIGNATURE",
        },
        departure={"precruise_allocation": 20, "onboard_allocation": 20},
    )
    guest = fixtures.create_guest(
        api,
        full_name="Vera Lindqvist",
        birth_date="1968-05-09T00:00:00Z",
        loyalty_tier="PLATINUM",
    )

    booking = fixtures.create_booking(
        api, world.departure["id"], guest["id"], party_size=6, channel="ONBOARD",
    )

    # 20000 * 13000 bps = 26000 list; * 10800 bps ONBOARD = 28080 channel price.
    # PLATINUM 800 bps blends with the 1000 bps six-guest group discount to an
    # uncapped 1400 bps, clamped to 1200: 28080 * 8800 bps = 24710.4 -> 24710.
    assertions.assert_field_values(
        booking,
        per_guest_price_cents=24710,
        quoted_total_cents=148260,
    )
    assertions.assert_quote_is_per_guest_times_party(booking)


def test_service_fee_cap_binds_on_the_signature_group_quote(api):
    """PRD §3.5: "`service_fee_cents` is the smaller of 1500 cents and 300 basis points of `quoted_total_cents` rounded half up; it is retained by the line and is never commissionable."

    PRD §3.5: "`charge_total_cents` is `quoted_total_cents` plus `service_fee_cents`, and it is the amount authorised at booking and captured at ticketing."

    Design: Difficulty/combinatorial_formula/booking_quote_four_axis_blend_where_the_discount_cap_binds
    """
    world = fixtures.setup_selling_departure(
        api,
        excursion={
            "title": "Private Cenote Signature",
            "base_price_cents": 20000,
            "price_tier": "SIGNATURE",
        },
        departure={"precruise_allocation": 20, "onboard_allocation": 20},
    )
    guest = fixtures.create_guest(
        api,
        full_name="Vera Lindqvist",
        birth_date="1968-05-09T00:00:00Z",
        loyalty_tier="PLATINUM",
    )

    booking = fixtures.create_booking(
        api, world.departure["id"], guest["id"], party_size=6, channel="ONBOARD",
    )

    # 300 bps of 148260 is 4447.8 -> 4448, above the 1500-cent ceiling.
    assertions.assert_field_values(
        booking,
        service_fee_cents=1500,
        charge_total_cents=149760,
        financial_status="AUTHORIZED",
    )
    assertions.assert_charge_total_is_quote_plus_fee(booking)


# ==========================================================================
# Commission rounding: per line, then summed
# ==========================================================================

def test_ticketing_rounds_each_line_commission_half_up(api):
    """PRD §3.6: "Ticketing simultaneously moves `financial_status` `AUTHORIZED → CHARGED`, capturing `charge_total_cents` — a transition that presupposes `charge_total_cents` is greater than zero — and sets `commission_accrued_cents` on the provisional basis described in §3.9."

    PRD §3.9: "**On the provisional basis**, the lines in scope are the bookings whose `financial_status` is `CHARGED` or `PARTIALLY_REFUNDED`, and each line's commission is the booking's full `quoted_total_cents` multiplied by the operator's `commission_rate_bps`, divided by ten thousand, rounded half up, with no deduction for refunds."

    Design: Difficulty/combinatorial_formula/commission_per_line_rounding_pinned_over_sum_then_round
    """
    world = fixtures.setup_selling_departure(api)
    guests = [
        fixtures.create_guest(api, full_name="Ada Reyes",
                              birth_date="1985-04-02T00:00:00Z", loyalty_tier="GOLD"),
        fixtures.create_guest(api, full_name="Ben Ortiz",
                              birth_date="1979-11-20T00:00:00Z", loyalty_tier="GOLD"),
        fixtures.create_guest(api, full_name="Cleo Marsh",
                              birth_date="1990-02-14T00:00:00Z", loyalty_tier="GOLD"),
    ]
    bookings = [
        fixtures.create_booking(api, world.departure["id"], guest["id"],
                                party_size=4, channel="PRE_CRUISE")
        for guest in guests
    ]

    ticketed = [fixtures.ticket_booking(api, booking["id"]) for booking in bookings]

    for booking in ticketed:
        # 48508 * 1800 bps = 8731.44, rounded half up to 8731 on every line.
        assertions.assert_field_values(
            booking,
            quoted_total_cents=48508,
            financial_status="CHARGED",
            commission_accrued_cents=8731,
        )


def test_statement_adds_rounded_lines_instead_of_rounding_the_summed_basis(api):
    """PRD §3.9: "Either way the rounding order is pinned: round each booking line to whole cents first, then add the rounded lines exactly."

    PRD §3.9: "Summing the raw bases and rounding once at the end is a different number and is wrong."

    Design: Difficulty/combinatorial_formula/commission_per_line_rounding_pinned_over_sum_then_round
    """
    world = fixtures.setup_selling_departure(api)
    for full_name, birth_date in (
        ("Ada Reyes", "1985-04-02T00:00:00Z"),
        ("Ben Ortiz", "1979-11-20T00:00:00Z"),
        ("Cleo Marsh", "1990-02-14T00:00:00Z"),
    ):
        guest = fixtures.create_guest(api, full_name=full_name, birth_date=birth_date,
                                      loyalty_tier="GOLD")
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=4, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL",
    )

    # Three rounded lines of 8731 sum to 26193; rounding the summed raw basis
    # (145524 * 1800 bps = 26194.32) would give 26194 instead.
    assertions.assert_field_values(
        statement,
        basis="PROVISIONAL",
        gross_ticket_cents=145524,
        line_commission_cents=26193,
        booking_line_count=3,
    )
    assert statement["line_commission_cents"] != 26194


def test_provisional_payable_follows_the_per_line_commission(api):
    """PRD §3.9: "Step two charges the port infrastructure fee on gross, before any commission is deducted: `port_fee_cents` is 250 basis points of `gross_ticket_cents` rounded half up."

    PRD §3.9: "Step six computes `payable_pre_rebate_cents` as `gross_ticket_cents` less `port_fee_cents`, less `line_commission_cents`, less `claim_offset_cents`, less `operational_penalty_cents`, floored at zero — all exact integer arithmetic."

    Design: Difficulty/combinatorial_formula/commission_per_line_rounding_pinned_over_sum_then_round
    """
    world = fixtures.setup_selling_departure(api)
    for full_name, birth_date in (
        ("Ada Reyes", "1985-04-02T00:00:00Z"),
        ("Ben Ortiz", "1979-11-20T00:00:00Z"),
        ("Cleo Marsh", "1990-02-14T00:00:00Z"),
    ):
        guest = fixtures.create_guest(api, full_name=full_name, birth_date=birth_date,
                                      loyalty_tier="GOLD")
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=4, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL",
    )

    # 250 bps of 145524 is 3638.1 -> 3638; 145524 - 3638 - 26193 = 115693.
    assertions.assert_field_values(
        statement,
        port_fee_cents=3638,
        claim_offset_cents=0,
        operational_penalty_cents=0,
        payable_pre_rebate_cents=115693,
        rebate_bps=0,
    )


# ==========================================================================
# The provisional and final commission bases over the same three lines
# ==========================================================================

def test_provisional_basis_commissions_the_three_charged_lines(api):
    """PRD §3.9: "Step one aggregates gross: with a `PROVISIONAL` `basis`, the lines in scope are the in-scope bookings whose `financial_status` is `CHARGED` or `PARTIALLY_REFUNDED` and `gross_ticket_cents` is the exact sum of their `quoted_total_cents`; with a `FINAL` `basis`, the lines are the in-scope bookings whose `fulfillment_status` is `COMPLETED` or `NO_SHOW` and `gross_ticket_cents` is the exact sum of each one's `quoted_total_cents` less its `refunded_cents`, each term floored at zero."

    PRD §3.9: "`booking_line_count` is the number of lines that entered the gross, and `refunds_cents` is the sum of `amount_cents` over those lines' `REFUND` ledger entries."

    Design: Difficulty/dual_variant_calc/commission_provisional_versus_final_on_the_same_three_booking_lines
    """
    world = fixtures.setup_selling_departure(api)
    for full_name, birth_date in (
        ("Ada Reyes", "1985-04-02T00:00:00Z"),
        ("Ben Ortiz", "1979-11-20T00:00:00Z"),
        ("Cleo Marsh", "1990-02-14T00:00:00Z"),
    ):
        guest = fixtures.create_guest(api, full_name=full_name, birth_date=birth_date,
                                      loyalty_tier="GOLD")
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=4, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL",
    )

    # All three lines are CHARGED, so the gross is 3 * 48508 and the commission
    # is 3 * 8731 at the operator's 1800 bps.
    assertions.assert_field_values(
        statement,
        basis="PROVISIONAL",
        status="DRAFT",
        gross_ticket_cents=145524,
        line_commission_cents=26193,
        booking_line_count=3,
    )


def test_final_basis_reprices_the_same_three_lines_by_fulfillment(api):
    """PRD §3.9: "**On the final basis**, the lines in scope are instead the bookings whose `fulfillment_status` is `COMPLETED` or `NO_SHOW`, and each line's basis is `quoted_total_cents` less `refunded_cents`, floored at zero; a `COMPLETED` line is rated at the operator's `commission_rate_bps` while a `NO_SHOW` line is rated at the smaller of `commission_rate_bps` and 500 basis points, since the line performed no service."

    PRD §3.9: "Step nine sets `operator_payable_cents` to `payable_pre_rebate_cents` plus `rebate_cents` plus `adjustment_cents`, exactly."

    Design: Difficulty/dual_variant_calc/commission_provisional_versus_final_on_the_same_three_booking_lines
    """
    world = fixtures.setup_selling_departure(api)
    bookings = []
    for full_name, birth_date in (
        ("Ada Reyes", "1985-04-02T00:00:00Z"),
        ("Ben Ortiz", "1979-11-20T00:00:00Z"),
        ("Cleo Marsh", "1990-02-14T00:00:00Z"),
    ):
        guest = fixtures.create_guest(api, full_name=full_name, birth_date=birth_date,
                                      loyalty_tier="GOLD")
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=4, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])
        bookings.append(booking)
    booking_a, booking_b, booking_c = bookings
    fixtures.create_statement(api, world.operator["id"], world.port_call["id"],
                              basis="PROVISIONAL")

    # Booking C walks away 4319 minutes out, booking A completes and booking B
    # is swept into NO_SHOW by the dispatch.
    fixtures.set_clock(api, "2026-09-12T09:01:00Z")
    fixtures.cancel_booking(api, booking_c["id"], reason_code="GUEST_CHANGED_PLANS")
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.check_in_booking(api, booking_a["id"])
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:35:00Z")
    fixtures.complete_departure(api, world.departure["id"], "2026-09-15T14:30:00Z")

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL",
    )

    # Two lines survive: A COMPLETED at 1800 bps (8731) and B NO_SHOW at the
    # 500 bps floor (2425), on a gross of 2 * 48508 = 97016.  250 bps of that
    # gross is 2425.4 -> 2425, leaving 97016 - 2425 - 11156 = 83435, below the
    # 200000-cent rebate tier.
    assertions.assert_field_values(
        statement,
        basis="FINAL",
        gross_ticket_cents=97016,
        booking_line_count=2,
        port_fee_cents=2425,
        line_commission_cents=11156,
        payable_pre_rebate_cents=83435,
        rebate_bps=0,
        rebate_cents=0,
        adjustment_cents=0,
        operator_payable_cents=83435,
    )
    assert fixtures.get_booking(api, booking_a["id"])["commission_accrued_cents"] == 8731
    assert fixtures.get_booking(api, booking_b["id"])["commission_accrued_cents"] == 2425


def test_guest_cancelled_line_is_refunded_and_leaves_the_final_basis(api):
    """PRD §3.7: "Below that but at 1440 minutes or more, the refund is 7500 basis points of `quoted_total_cents`."

    PRD §3.9: "Creating a statement supersedes rather than accumulates: any existing statement for the same operator and port call that is still in `DRAFT` moves `DRAFT → VOIDED`."

    Design: Difficulty/dual_variant_calc/commission_provisional_versus_final_on_the_same_three_booking_lines
    """
    world = fixtures.setup_selling_departure(api)
    bookings = []
    for full_name, birth_date in (
        ("Ada Reyes", "1985-04-02T00:00:00Z"),
        ("Ben Ortiz", "1979-11-20T00:00:00Z"),
        ("Cleo Marsh", "1990-02-14T00:00:00Z"),
    ):
        guest = fixtures.create_guest(api, full_name=full_name, birth_date=birth_date,
                                      loyalty_tier="GOLD")
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=4, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])
        bookings.append(booking)
    booking_a, booking_b, booking_c = bookings
    provisional = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL",
    )

    fixtures.set_clock(api, "2026-09-12T09:01:00Z")
    fixtures.cancel_booking(api, booking_c["id"], reason_code="GUEST_CHANGED_PLANS")
    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    fixtures.check_in_booking(api, booking_a["id"])
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:35:00Z")
    fixtures.complete_departure(api, world.departure["id"], "2026-09-15T14:30:00Z")

    fixtures.create_statement(api, world.operator["id"], world.port_call["id"],
                              basis="FINAL")

    # 4319 minutes out is the 7500 bps tier: 48508 * 7500 bps = 36381.
    assertions.assert_field_values(
        fixtures.get_booking(api, booking_c["id"]),
        fulfillment_status="CANCELLED_BY_GUEST",
        refunded_cents=36381,
        financial_status="PARTIALLY_REFUNDED",
    )
    assert fixtures.get_booking(api, booking_a["id"])["fulfillment_status"] == "COMPLETED"
    assert fixtures.get_booking(api, booking_b["id"])["fulfillment_status"] == "NO_SHOW"

    superseded = validate_success(
            api.get_commission_statement(provisional["id"],
                                         TEST_USERS["finance_headers"])
        )
    
    assert superseded["status"] == "VOIDED"


# ==========================================================================
# The nine-step settlement waterfall
# ==========================================================================

def test_port_fee_is_charged_on_gross_and_not_on_gross_less_commission(api):
    """PRD §3.9: "Step two charges the port infrastructure fee on gross, before any commission is deducted: `port_fee_cents` is 250 basis points of `gross_ticket_cents` rounded half up."

    PRD §3.9: "Charging it on a post-commission net instead would produce a smaller fee and a different payable, and is wrong."

    Design: Difficulty/combinatorial_formula/statement_waterfall_pins_fee_on_gross_and_selects_the_rebate_tier_once
    """
    world = fixtures.setup_selling_departure(
        api,
        clock="2026-09-12T09:00:00Z",
        excursion={
            "title": "Chankanaab Beach Day",
            "base_price_cents": 50000,
            "price_tier": "STANDARD",
            "languages": ["EN"],
        },
        departure={"total_capacity": 10, "precruise_allocation": 10,
                   "onboard_allocation": 0},
    )
    bookings = []
    for index in range(1, 7):
        guest = fixtures.create_guest(
            api, full_name=f"Guest {index}",
            birth_date=f"1980-01-0{index}T00:00:00Z",
        )
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=1, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])
        bookings.append(booking)

    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    for booking in bookings:
        fixtures.check_in_booking(api, booking["id"])
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:35:00Z")
    fixtures.complete_departure(api, world.departure["id"], "2026-09-15T14:30:00Z")

    incident = fixtures.file_incident(
        api, bookings[0]["id"], category="PROPERTY_LOSS", severity="MODERATE",
        occurred_utc="2026-09-15T12:00:00Z",
        narrative="Guest camera bag lost from the tour vehicle.",
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=90000,
                               basis_code="GUIDE_CONDUCT")
    fixtures.claim_action(api, claim["id"], "SEND_TO_OPERATOR",
                          headers=TEST_USERS["risk_officer_headers"])
    upheld = fixtures.adjudicate_upheld(api, claim["id"], liability_share_bps=5000,
                                        settlement_amount_cents=77000)
    fixtures.set_clock(api, "2026-09-15T16:35:00Z")
    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL",
    )

    # 77000 * 5000 bps = 38500 charged to the operator.  Gross is 6 * 50000, so
    # the fee is 250 bps of 300000 = 7500 — not 250 bps of the post-commission
    # 246000, which would be 6150.
    assert upheld["operator_charge_cents"] == 38500
    assertions.assert_field_values(
        statement,
        gross_ticket_cents=300000,
        booking_line_count=6,
        port_fee_cents=7500,
        line_commission_cents=54000,
        claim_offset_cents=38500,
        operational_penalty_cents=0,
        payable_pre_rebate_cents=200000,
    )
    assert statement["port_fee_cents"] != 6150


def test_rebate_tier_is_selected_once_from_the_pre_rebate_payable(api):
    """PRD §3.9: "Step seven selects the volume rebate rate from that figure, exactly once: `rebate_bps` is 150 when `payable_pre_rebate_cents` is 500000 or more, 75 when it is 200000 or more but below 500000, and 0 below 200000."

    PRD §3.9: "Step eight computes `rebate_cents` as the negation of the half-up rounding of `payable_pre_rebate_cents` multiplied by `rebate_bps` divided by ten thousand — it is stored as a negative amount, because the rebate is a deduction the operator grants the line."

    Design: Difficulty/combinatorial_formula/statement_waterfall_pins_fee_on_gross_and_selects_the_rebate_tier_once
    """
    world = fixtures.setup_selling_departure(
        api,
        clock="2026-09-12T09:00:00Z",
        excursion={
            "title": "Chankanaab Beach Day",
            "base_price_cents": 50000,
            "price_tier": "STANDARD",
            "languages": ["EN"],
        },
        departure={"total_capacity": 10, "precruise_allocation": 10,
                   "onboard_allocation": 0},
    )
    bookings = []
    for index in range(1, 7):
        guest = fixtures.create_guest(
            api, full_name=f"Guest {index}",
            birth_date=f"1980-01-0{index}T00:00:00Z",
        )
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=1, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])
        bookings.append(booking)

    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    for booking in bookings:
        fixtures.check_in_booking(api, booking["id"])
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:35:00Z")
    fixtures.complete_departure(api, world.departure["id"], "2026-09-15T14:30:00Z")

    incident = fixtures.file_incident(
        api, bookings[0]["id"], category="PROPERTY_LOSS", severity="MODERATE",
        occurred_utc="2026-09-15T12:00:00Z",
        narrative="Guest camera bag lost from the tour vehicle.",
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=90000,
                               basis_code="GUIDE_CONDUCT")
    fixtures.claim_action(api, claim["id"], "SEND_TO_OPERATOR",
                          headers=TEST_USERS["risk_officer_headers"])
    fixtures.adjudicate_upheld(api, claim["id"], liability_share_bps=5000,
                               settlement_amount_cents=77000)
    fixtures.set_clock(api, "2026-09-15T16:35:00Z")
    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL",
    )
    issued = fixtures.statement_transition(api, statement["id"], "ISSUE")

    # A payable of exactly 200000 sits in the 75 bps band, and 75 bps of 200000
    # is 1500, stored negative.
    assertions.assert_field_values(
        issued,
        status="ISSUED",
        payable_pre_rebate_cents=200000,
        rebate_bps=75,
        rebate_cents=-1500,
        adjustment_cents=0,
        operator_payable_cents=198500,
    )


def test_adjustment_does_not_reselect_the_rebate_tier(api):
    """PRD §3.9: "An adjustment rewrites `adjustment_cents` and recomputes `operator_payable_cents` as step nine only: `payable_pre_rebate_cents`, `rebate_bps` and `rebate_cents` are left exactly as issued, and in particular the rebate tier is **not** re-selected from the new, smaller payable."

    PRD §3.9: "Because the rate is chosen from the pre-rebate figure, the rebate never re-enters its own tier test."

    Design: Difficulty/combinatorial_formula/statement_waterfall_pins_fee_on_gross_and_selects_the_rebate_tier_once
    """
    world = fixtures.setup_selling_departure(
        api,
        clock="2026-09-12T09:00:00Z",
        excursion={
            "title": "Chankanaab Beach Day",
            "base_price_cents": 50000,
            "price_tier": "STANDARD",
            "languages": ["EN"],
        },
        departure={"total_capacity": 10, "precruise_allocation": 10,
                   "onboard_allocation": 0},
    )
    bookings = []
    for index in range(1, 7):
        guest = fixtures.create_guest(
            api, full_name=f"Guest {index}",
            birth_date=f"1980-01-0{index}T00:00:00Z",
        )
        booking = fixtures.create_booking(api, world.departure["id"], guest["id"],
                                          party_size=1, channel="PRE_CRUISE")
        fixtures.ticket_booking(api, booking["id"])
        bookings.append(booking)

    fixtures.set_clock(api, "2026-09-15T08:30:00Z")
    fixtures.arrive_port_call(api, world.port_call["id"])
    for booking in bookings:
        fixtures.check_in_booking(api, booking["id"])
    fixtures.dispatch_departure(api, world.departure["id"])
    fixtures.set_clock(api, "2026-09-15T14:35:00Z")
    fixtures.complete_departure(api, world.departure["id"], "2026-09-15T14:30:00Z")

    incident = fixtures.file_incident(
        api, bookings[0]["id"], category="PROPERTY_LOSS", severity="MODERATE",
        occurred_utc="2026-09-15T12:00:00Z",
        narrative="Guest camera bag lost from the tour vehicle.",
    )
    claim = fixtures.open_claim(api, incident["id"], claimed_amount_cents=90000,
                               basis_code="GUIDE_CONDUCT")
    fixtures.claim_action(api, claim["id"], "SEND_TO_OPERATOR",
                          headers=TEST_USERS["risk_officer_headers"])
    fixtures.adjudicate_upheld(api, claim["id"], liability_share_bps=5000,
                               settlement_amount_cents=77000)
    fixtures.set_clock(api, "2026-09-15T16:35:00Z")
    fixtures.port_call_transition(api, world.port_call["id"], "CLOSE_ALL_ABOARD")
    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="FINAL",
    )
    fixtures.statement_transition(api, statement["id"], "ISSUE")
    fixtures.statement_transition(api, statement["id"], "DISPUTE")

    adjusted = fixtures.statement_transition(api, statement["id"], "ADJUST",
                                             adjustment_cents=-100000)

    # 200000 - 1500 - 100000 = 98500.  Re-selecting the tier from the adjusted
    # figure would drop the rebate to 0 bps and pay 100000 instead.
    assertions.assert_field_values(
        adjusted,
        status="ADJUSTED",
        payable_pre_rebate_cents=200000,
        rebate_bps=75,
        rebate_cents=-1500,
        adjustment_cents=-100000,
        operator_payable_cents=98500,
    )
    assert adjusted["operator_payable_cents"] != 100000
