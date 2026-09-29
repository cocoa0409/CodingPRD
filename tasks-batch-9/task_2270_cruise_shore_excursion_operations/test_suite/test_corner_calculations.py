"""Arithmetic corners of the shore-excursion API: the five pinned pricing steps and
their rounding order, the two channel seat buckets and their release, tender-wave
selection with the timing bands it moves, the alternative-offer ranking, operator
safety scoring, the commission waterfall and the guest refund tiers.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS


def test_premium_precruise_party_of_two_walks_all_five_pricing_steps(api):
    """PRD §3.5: "Step one is the tier multiplier: `price_tier` selects 9000 basis points for `VALUE`, 10000 for `STANDARD`, 11500 for `PREMIUM` and 13000 for `SIGNATURE`, and the list price is `base_price_cents` multiplied by that figure, divided by ten thousand, rounded half up to whole cents."
    PRD §3.5: "A `PRE_CRUISE` booking earns a reduction of 500 basis points only when the booking is made at least a full week ahead: take the number of minutes from the logical clock to the departure's `meeting_time_utc`, divide by 1440 and discard the remainder to get whole days to the meeting, and apply the reduction only when that whole-day figure is 7 or more; below 7 the pre-cruise adjustment is zero."
    PRD §3.5: "`quoted_total_cents` is then `per_guest_price_cents` multiplied by `party_size` exactly — an integer multiple of the rounded per-guest figure, never a re-derivation from `base_price_cents`."
    PRD §3.5: "`service_fee_cents` is the smaller of 1500 cents and 300 basis points of `quoted_total_cents` rounded half up; it is retained by the line and is never commissionable."
    PRD §3.5: "`charge_total_cents` is `quoted_total_cents` plus `service_fee_cents`, and it is the amount authorised at booking and captured at ticketing."

    Design: Corner/calculations/booking_quote_walks_all_five_steps_on_a_premium_precruise_party_of_two
    """
    world = fixtures.setup_booked_booking(api)
    booking = world.booking

    # 12000 * 11500 / 10000 = 13800; 45 whole days out earns -500 bps -> 13110.
    assert booking["per_guest_price_cents"] == 13110, booking
    assert booking["quoted_total_cents"] == 26220, booking
    # 26220 * 300 / 10000 = 786.6 -> 787, which is under the 1500-cent cap.
    assert booking["service_fee_cents"] == 787, booking
    assert booking["charge_total_cents"] == 27007, booking
    assert booking["financial_status"] == "AUTHORIZED", booking
    assert booking["commission_accrued_cents"] == 0, booking

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 2, departure
    assert departure["effective_precruise_available"] == 23, departure
    assert departure["seats_available_total"] == 38, departure


def test_value_tier_onboard_booking_applies_the_tier_and_channel_constants(api):
    """PRD §3.5: "Step one is the tier multiplier: `price_tier` selects 9000 basis points for `VALUE`, 10000 for `STANDARD`, 11500 for `PREMIUM` and 13000 for `SIGNATURE`, and the list price is `base_price_cents` multiplied by that figure, divided by ten thousand, rounded half up to whole cents."
    PRD §3.5: "An `ONBOARD` booking always carries an adjustment of plus 800 basis points."
    PRD §3.5: "The channel price is the list price multiplied by ten thousand plus the adjustment in basis points, divided by ten thousand, rounded half up."

    Design: Corner/calculations/value_tier_sold_onboard_applies_the_9000_and_10800_bps_constants
    """
    world = fixtures.setup_booked_booking(
        api,
        excursion={"price_tier": "VALUE"},
        booking={"party_size": 1, "channel": "ONBOARD"},
    )
    booking = world.booking

    # 12000 * 9000 / 10000 = 10800; +800 bps -> 10800 * 10800 / 10000 = 11664.
    assert booking["channel"] == "ONBOARD", booking
    assert booking["per_guest_price_cents"] == 11664, booking
    assert booking["quoted_total_cents"] == 11664, booking
    # 11664 * 300 / 10000 = 349.92 -> 350.
    assert booking["service_fee_cents"] == 350, booking
    assert booking["charge_total_cents"] == 12014, booking

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["onboard_sold_seats"] == 1, departure
    assert departure["precruise_sold_seats"] == 0, departure
    assert departure["effective_onboard_available"] == 14, departure


def test_precruise_reduction_is_earned_at_seven_whole_days_and_lost_at_six(api):
    """PRD §3.5: "A `PRE_CRUISE` booking earns a reduction of 500 basis points only when the booking is made at least a full week ahead: take the number of minutes from the logical clock to the departure's `meeting_time_utc`, divide by 1440 and discard the remainder to get whole days to the meeting, and apply the reduction only when that whole-day figure is 7 or more; below 7 the pre-cruise adjustment is zero."
    PRD §3.5: "The channel price is the list price multiplied by ten thousand plus the adjustment in basis points, divided by ten thousand, rounded half up."

    Design: Corner/calculations/the_precruise_reduction_is_earned_at_exactly_seven_days_and_lost_at_six
    """
    world = fixtures.setup_selling_departure(api)
    voyage_code = world.port_call["voyage_code"]
    guest_at_seven = fixtures.create_guest(api, voyage_code=voyage_code)
    guest_at_six = fixtures.create_guest(
        api, voyage_code=voyage_code, full_name="Bo Lund"
    )

    # Exactly 10080 minutes to the 2026-09-15T09:00:00Z meeting: 7 whole days.
    fixtures.set_clock(api, "2026-09-08T09:00:00Z")
    booking_at_seven = fixtures.create_booking(
        api, world.departure["id"], guest_at_seven["id"], party_size=1
    )
    # 13800 * 9500 / 10000 = 13110; 13110 * 300 / 10000 = 393.3 -> 393.
    assert booking_at_seven["per_guest_price_cents"] == 13110, booking_at_seven
    assert booking_at_seven["service_fee_cents"] == 393, booking_at_seven
    assert booking_at_seven["charge_total_cents"] == 13503, booking_at_seven

    # 8640 minutes is 6 whole days, so the reduction is not earned.
    fixtures.set_clock(api, "2026-09-09T09:00:00Z")
    booking_at_six = fixtures.create_booking(
        api, world.departure["id"], guest_at_six["id"], party_size=1
    )
    # The list price stands at 13800; 13800 * 300 / 10000 = 414.
    assert booking_at_six["per_guest_price_cents"] == 13800, booking_at_six
    assert booking_at_six["service_fee_cents"] == 414, booking_at_six
    assert booking_at_six["charge_total_cents"] == 14214, booking_at_six

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 2, departure


def test_precruise_release_fires_at_exactly_2880_minutes_to_the_meeting(api):
    """PRD §3.5: "Whenever the number of minutes from the logical clock to `meeting_time_utc` has fallen to 2880 or below, the pre-cruise release has happened: the effective pre-cruise allocation collapses to `precruise_sold_seats` exactly, and the effective onboard allocation becomes `total_capacity` less `precruise_sold_seats`, so every unsold pre-cruise seat joins the onboard pool."
    PRD §3.5: "From those, `effective_precruise_available` is the effective pre-cruise allocation less `precruise_sold_seats`, floored at 0, and `effective_onboard_available` is the effective onboard allocation less `onboard_sold_seats`, floored at 0."
    PRD §3.5: "`seats_available_total` is `total_capacity` less both sold counts."

    Design: Corner/calculations/the_precruise_release_fires_at_exactly_2880_minutes_and_moves_the_unsold_seats
    """
    world = fixtures.setup_booked_booking(api, booking={"party_size": 4})

    # 2881 minutes to the meeting: the release has not happened yet.
    fixtures.set_clock(api, "2026-09-13T08:59:00Z")
    before = fixtures.get_departure(api, world.departure["id"])
    assert before["effective_precruise_available"] == 21, before
    assert before["effective_onboard_available"] == 15, before
    assert before["seats_available_total"] == 36, before

    # Exactly 2880 minutes: the 21 unsold pre-cruise seats join the onboard pool.
    fixtures.set_clock(api, "2026-09-13T09:00:00Z")
    after = fixtures.get_departure(api, world.departure["id"])
    assert after["effective_precruise_available"] == 0, after
    assert after["effective_onboard_available"] == 36, after
    assert after["seats_available_total"] == 36, after
    assert after["precruise_sold_seats"] == 4, after
    assert after["status"] == "SELLING", after


def test_tender_assignment_picks_the_latest_eligible_wave_and_lifts_the_band(api):
    """PRD §3.4: "The eligible pool is every wave on the departure's own port call whose `priority_class` is `EXCURSION_PRIORITY`, whose `window_end_utc` is at or before the departure's `meeting_time_utc` (a wave ending exactly at the meeting time is eligible), and whose `assigned_guest_count` plus the departure's whole `total_capacity` is at most its `guest_capacity` (an exact fit is eligible)."
    PRD §3.4: "Among the eligible pool the wave with the latest `window_end_utc` wins, because it keeps the group waiting on the pier for the shortest time; ties are broken by the lower `wave_index`, and then by the earlier `created_at`."
    PRD §3.4: "On success the departure's `tender_wave_id` becomes the winner's identifier, the winner's `assigned_guest_count` grows by the departure's `total_capacity` and its `assigned_departure_count` by 1, and both projections are recomputed — assigning a wave removes the 20-minute penalty and may simultaneously floor the actual-basis start."
    PRD §3.4: "Both slack figures are banded identically into `timing_risk_band_scheduled` and `timing_risk_band_actual`: a slack of 0 or fewer minutes is `RED`, a slack of 45 or fewer minutes but more than 0 is `AMBER`, and anything above 45 minutes is `GREEN`."

    Design: Corner/calculations/tender_assignment_picks_the_latest_eligible_wave_and_lifts_the_band_to_green
    """
    world = fixtures.setup_selling_departure(
        api,
        tender=True,
        meeting_point={"name": "Tender Pontoon 2", "zone": "TENDER_PONTOON"},
        tender_waves=[
            {
                "wave_index": 1,
                "window_start_utc": "2026-09-15T07:30:00Z",
                "window_end_utc": "2026-09-15T08:00:00Z",
                "guest_capacity": 100,
            },
            {
                "wave_index": 2,
                "window_start_utc": "2026-09-15T08:20:00Z",
                "window_end_utc": "2026-09-15T08:50:00Z",
                "guest_capacity": 100,
            },
            {
                "wave_index": 3,
                "window_start_utc": "2026-09-15T09:05:00Z",
                "window_end_utc": "2026-09-15T09:20:00Z",
                "guest_capacity": 100,
            },
        ],
        assign_wave=False,
    )
    wave_two = world.tender_waves[1]

    # Unassigned: 25 egress + 20 penalty + 300 ashore + 30 transfer = 375 minutes
    # from 09:00, so 15:15; 16:30 less 15:15 is 75, less the 30-minute buffer = 45.
    unassigned = fixtures.get_departure(api, world.departure["id"])
    assert unassigned["tender_wave_id"] is None, unassigned
    assert unassigned["slack_minutes_scheduled"] == 45, unassigned
    assert unassigned["timing_risk_band_scheduled"] == "AMBER", unassigned

    assigned = fixtures.assign_tender_wave(api, world.departure["id"])

    # Wave 3 ends after the 09:00 meeting time, so wave 2 is the latest eligible.
    assert assigned["tender_wave_id"] == wave_two["id"], assigned
    # Dropping the 20-minute penalty gives a 355-minute leg: 14:55, slack 65.
    assert assigned["slack_minutes_scheduled"] == 65, assigned
    assert assigned["timing_risk_band_scheduled"] == "GREEN", assigned

    wave = validate_success(
            api.get_tender_wave(wave_two["id"], TEST_USERS["port_agent_headers"])
        )
    
    assert wave["assigned_guest_count"] == 40, wave
    assert wave["assigned_departure_count"] == 1, wave


def test_a_wave_too_small_for_the_whole_departure_leaves_the_pool_empty(api):
    """PRD §3.4: "The eligible pool is every wave on the departure's own port call whose `priority_class` is `EXCURSION_PRIORITY`, whose `window_end_utc` is at or before the departure's `meeting_time_utc` (a wave ending exactly at the meeting time is eligible), and whose `assigned_guest_count` plus the departure's whole `total_capacity` is at most its `guest_capacity` (an exact fit is eligible)."
    PRD §3.4: "If the pool is empty, the assignment is refused with `ERR_NO_ELIGIBLE_TENDER_WAVE` and the departure keeps no wave — and therefore keeps carrying the 20-minute unassigned penalty in both projections."

    Design: Corner/calculations/a_wave_too_small_for_the_departure_empties_the_pool
    """
    world = fixtures.setup_selling_departure(
        api,
        tender=True,
        meeting_point={"name": "Tender Pontoon 2", "zone": "TENDER_PONTOON"},
        tender_waves=[
            {
                "wave_index": 1,
                "window_start_utc": "2026-09-15T08:20:00Z",
                "window_end_utc": "2026-09-15T08:50:00Z",
                "guest_capacity": 20,
            },
        ],
        assign_wave=False,
    )
    small_wave = world.tender_waves[0]

    # 0 assigned guests plus a 40-seat departure exceeds the wave's capacity of 20.
    resp = api.assign_tender_wave(
        world.departure["id"], {}, TEST_USERS["port_agent_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_TENDER_WAVE)

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["tender_wave_id"] is None, departure
    assert departure["slack_minutes_scheduled"] == 45, departure
    assert departure["timing_risk_band_scheduled"] == "AMBER", departure

    wave = validate_success(
            api.get_tender_wave(small_wave["id"], TEST_USERS["port_agent_headers"])
        )
    
    assert wave["assigned_guest_count"] == 0, wave
    assert wave["assigned_departure_count"] == 0, wave


def test_the_nominated_fallback_excursion_wins_over_a_closer_priced_candidate(api):
    """PRD §3.7: "If the cancelled excursion nominated an `alternative_excursion_id` and any sellable candidate belongs to that excursion, the nominated candidates win outright and the price comparison never runs; among them the earliest `meeting_time_utc` wins, then the earliest `created_at`."
    PRD §3.7: "When `offer_alternative` is true, each cancelled booking receives an `alternative_departure_id` and its `alternative_offer_status` becomes `OFFERED`."
    PRD §3.7: "The offer reserves nothing; it merely flips to `EXPIRED` when the port call closes."
    PRD §3.7: "A booking whose `financial_status` was `AUTHORIZED` moves to `VOIDED` with an `AUTH_VOID` entry of `amount_cents` 0."

    Design: Corner/calculations/the_nominated_fallback_wins_over_a_much_closer_priced_candidate
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    meeting_point = fixtures.create_meeting_point(api, port["id"])
    operator = fixtures.create_approved_operator(api, port["id"])

    nominated = fixtures.create_published_excursion(
        api, port["id"], operator["id"],
        title="Mayan Ruins Deluxe", base_price_cents=30000,
    )
    closer_priced = fixtures.create_published_excursion(
        api, port["id"], operator["id"],
        title="Beach Club Day Pass", base_price_cents=12100,
    )
    booked = fixtures.create_published_excursion(
        api, port["id"], operator["id"],
        base_price_cents=12000, alternative_excursion_id=nominated["id"],
    )

    port_call = fixtures.create_port_call(api, port["id"])
    port_call = fixtures.open_port_call_sales(api, port_call["id"])

    departure = fixtures.create_departure(
        api, booked["id"], port_call["id"], meeting_point["id"],
        meeting_time_utc="2026-09-15T09:00:00Z",
    )
    nominated_departure = fixtures.create_departure(
        api, nominated["id"], port_call["id"], meeting_point["id"],
        meeting_time_utc="2026-09-15T11:00:00Z",
    )
    closer_departure = fixtures.create_departure(
        api, closer_priced["id"], port_call["id"], meeting_point["id"],
        meeting_time_utc="2026-09-15T10:00:00Z",
    )

    guest = fixtures.create_guest(api, voyage_code=port_call["voyage_code"])
    booking = fixtures.create_booking(api, departure["id"], guest["id"], party_size=2)

    cancelled = fixtures.cancel_departure(
        api, departure["id"], "WEATHER", offer_alternative=True
    )
    assert cancelled["status"] == "CANCELLED_WEATHER", cancelled

    # The 30000-cent nomination beats the 12100-cent near-price candidate outright.
    settled = fixtures.get_booking(api, booking["id"])
    assert settled["alternative_departure_id"] == nominated_departure["id"], settled
    assert settled["alternative_offer_status"] == "OFFERED", settled
    assert settled["fulfillment_status"] == "CANCELLED_BY_LINE", settled
    assert settled["financial_status"] == "VOIDED", settled

    # The offer reserves nothing on either candidate.
    offered = fixtures.get_departure(api, nominated_departure["id"])
    assert offered["seats_available_total"] == 40, offered
    passed_over = fixtures.get_departure(api, closer_departure["id"])
    assert passed_over["seats_available_total"] == 40, passed_over


def test_cancelling_the_only_departure_with_an_offer_finds_no_alternative(api):
    """PRD §3.7: "A candidate departure is sellable for a given booking when it is not the cancelled departure itself, sits on the same port call, has `status` `SELLING`, belongs to an excursion whose `catalog_status` is `PUBLISHED`, has `seats_available_total` at least the booking's `party_size`, has a `meeting_time_utc` at least 15 minutes ahead of the logical clock so the group can be re-briefed, and passes every hard gate of the eligibility screen in §3.5 for that booking's guest."
    PRD §3.7: "If the sellable pool is empty, the whole cancellation is refused with `ERR_NO_ALTERNATIVE_AVAILABLE` rather than half-applied, so the caller can retry without asking for an alternative."

    Design: Corner/calculations/cancelling_the_only_departure_with_an_offer_finds_no_alternative
    """
    world = fixtures.setup_booked_booking(api)

    # The only departure on the call is the one being cancelled, so it is excluded.
    resp = api.cancel_departure(
        world.departure["id"],
        {"cause": "WEATHER", "offer_alternative": True},
        TEST_USERS["manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NO_ALTERNATIVE_AVAILABLE)

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["status"] == "SELLING", departure
    assert departure.get("cancellation_cause") is None, departure

    booking = fixtures.get_booking(api, world.booking["id"])
    assert booking["fulfillment_status"] == "BOOKED", booking
    assert booking["financial_status"] == "AUTHORIZED", booking
    assert booking["alternative_offer_status"] == "NONE", booking


def test_two_audits_renormalise_their_weights_to_0_625_and_0_375(api):
    """PRD §3.2: "Order the operator's audits by `conducted_on` descending and then `created_at` descending, and take at most the first three; if there are none, `safety_score` is 0 and nothing further is computed."
    PRD §3.2: "Assign base weights of 0.5, 0.3 and 0.2 to the audits in that order, truncated to however many audits are in the window, then divide each base weight by the sum of the base weights actually used, so that with three audits the weights stay 0.5, 0.3 and 0.2, with two they become 0.625 and 0.375, and with one it becomes 1.0."
    PRD §3.2: "The weighted average is the sum of each audit's `raw_score` multiplied by its renormalised weight."
    PRD §2.10: "The operator tracks this as `latest_audit_auditor_user_id`, which holds the `auditor_user_id` of the operator's most recent audit ordered by `conducted_on` descending and then `created_at` descending, and is null while no audit exists."

    Design: Corner/calculations/two_audits_renormalise_their_weights_to_0_625_and_0_375
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    port = fixtures.create_port(api)
    operator = fixtures.create_operator(api, port["id"])

    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_1",
        conducted_on="2026-07-10T00:00:00Z", raw_score=82, critical_finding_count=0,
    )
    fixtures.record_safety_audit(
        api, operator["id"], auditor_user_id="u_aud_2", audit_type="ANNUAL",
        conducted_on="2026-07-20T00:00:00Z", raw_score=90, critical_finding_count=0,
    )

    submitted = fixtures.vetting_action(api, operator["id"], "SUBMIT")

    assert submitted["vetting_status"] == "SUBMITTED", submitted
    # 90 * 0.625 + 82 * 0.375 = 56.25 + 30.75 = 87 exactly.
    assert submitted["safety_score"] == 87, submitted
    assert submitted["latest_audit_auditor_user_id"] == "u_aud_2", submitted
    assert submitted["liability_reserve_cents"] == 0, submitted


def test_provisional_statement_counts_only_the_charged_booking_line(api):
    """PRD §3.9: "Step one aggregates gross: with a `PROVISIONAL` `basis`, the lines in scope are the in-scope bookings whose `financial_status` is `CHARGED` or `PARTIALLY_REFUNDED` and `gross_ticket_cents` is the exact sum of their `quoted_total_cents`; with a `FINAL` `basis`, the lines are the in-scope bookings whose `fulfillment_status` is `COMPLETED` or `NO_SHOW` and `gross_ticket_cents` is the exact sum of each one's `quoted_total_cents` less its `refunded_cents`, each term floored at zero."
    PRD §3.9: "`booking_line_count` is the number of lines that entered the gross, and `refunds_cents` is the sum of `amount_cents` over those lines' `REFUND` ledger entries."
    PRD §3.9: "Step two charges the port infrastructure fee on gross, before any commission is deducted: `port_fee_cents` is 250 basis points of `gross_ticket_cents` rounded half up."
    PRD §3.9: "Step six computes `payable_pre_rebate_cents` as `gross_ticket_cents` less `port_fee_cents`, less `line_commission_cents`, less `claim_offset_cents`, less `operational_penalty_cents`, floored at zero — all exact integer arithmetic."
    PRD §3.9: "Step seven selects the volume rebate rate from that figure, exactly once: `rebate_bps` is 150 when `payable_pre_rebate_cents` is 500000 or more, 75 when it is 200000 or more but below 500000, and 0 below 200000."
    PRD §3.9: "Step nine sets `operator_payable_cents` to `payable_pre_rebate_cents` plus `rebate_cents` plus `adjustment_cents`, exactly."

    Design: Corner/calculations/the_provisional_statement_counts_only_the_charged_line
    """
    world = fixtures.setup_booked_booking(api)
    charged = fixtures.ticket_booking(api, world.booking["id"])
    assert charged["financial_status"] == "CHARGED", charged

    _, authorised = fixtures.create_guest_and_booking(
        api, world, guest={"full_name": "Nils Berg"}
    )
    assert authorised["financial_status"] == "AUTHORIZED", authorised

    statement = fixtures.create_statement(
        api, world.operator["id"], world.port_call["id"], basis="PROVISIONAL"
    )

    assert statement["status"] == "DRAFT", statement
    assert statement["booking_line_count"] == 1, statement
    assert statement["gross_ticket_cents"] == 26220, statement
    # 26220 * 250 / 10000 = 655.5 -> 656 half up.
    assert statement["port_fee_cents"] == 656, statement
    # 26220 * 1800 / 10000 = 4719.6 -> 4720 half up.
    assert statement["line_commission_cents"] == 4720, statement
    assert statement["claim_offset_cents"] == 0, statement
    assert statement["operational_penalty_cents"] == 0, statement
    # 26220 - 656 - 4720 = 20844, which is below the 200000 rebate floor.
    assert statement["payable_pre_rebate_cents"] == 20844, statement
    assert statement["rebate_bps"] == 0, statement
    assert statement["rebate_cents"] == 0, statement
    assert statement["operator_payable_cents"] == 20844, statement

    assert fixtures.get_booking(api, charged["id"])["commission_accrued_cents"] == 4720
    assert fixtures.get_booking(api, authorised["id"])["commission_accrued_cents"] == 0


def test_guest_cancellation_at_exactly_1440_minutes_refunds_7500_bps(api):
    """PRD §3.7: "Below that but at 1440 minutes or more, the refund is 7500 basis points of `quoted_total_cents`."
    PRD §3.7: "A refund of more than zero writes a `REFUND` entry for the computed amount; a refund of zero instead writes a `RETENTION` entry whose `amount_cents` is the whole `charge_total_cents`."
    PRD §3.7: "`financial_status` then follows from the arithmetic: add the refund to the booking's existing `refunded_cents`, and if the new total is zero the status is `RETAINED`, if it is at least `charge_total_cents` the status is `REFUNDED`, and otherwise it is `PARTIALLY_REFUNDED`, with `retained_cents` set to `charge_total_cents` less the new refunded total."
    PRD §3.5: "A cancellation always reduces the sold count of the booking's own `channel` by the booking's `party_size`."
    PRD §3.5: "If the pre-cruise release has already happened and the cancelled booking was `PRE_CRUISE`, the freed seat also changes bucket: `precruise_allocation` falls by the party size and `onboard_allocation` rises by it, so `effective_precruise_available` stays 0 and the two buckets still sum to `total_capacity`."

    Design: Corner/calculations/a_guest_cancellation_at_exactly_1440_minutes_keeps_the_three_quarter_tier
    """
    world = fixtures.setup_ticketed_booking(api)
    assert world.booking["charge_total_cents"] == 27007, world.booking

    # Exactly 1440 minutes to the 2026-09-15T09:00:00Z meeting time.
    fixtures.set_clock(api, "2026-09-14T09:00:00Z")
    cancelled = fixtures.cancel_booking(
        api, world.booking["id"], reason_code="GUEST_CHANGE_OF_PLAN"
    )

    assert cancelled["fulfillment_status"] == "CANCELLED_BY_GUEST", cancelled
    assert cancelled["financial_status"] == "PARTIALLY_REFUNDED", cancelled
    # 26220 * 7500 / 10000 = 19665 exactly; 27007 - 19665 = 7342 retained.
    assert cancelled["refunded_cents"] == 19665, cancelled
    assert cancelled["retained_cents"] == 7342, cancelled
    assert cancelled["goodwill_credit_cents"] == 0, cancelled

    entries = fixtures.ledger_entries_for_booking(api, world.booking["id"])
    assert len(entries) == 1, entries
    assert entries[0]["entry_kind"] == "REFUND", entries[0]
    assert entries[0]["amount_cents"] == 19665, entries[0]
    assert entries[0]["refund_pct_bps"] == 7500, entries[0]
    assert entries[0]["basis"] == "GUEST_INITIATED", entries[0]

    departure = fixtures.get_departure(api, world.departure["id"])
    assert departure["precruise_sold_seats"] == 0, departure
    # The release has already happened, so the two freed seats change bucket.
    assert departure["precruise_allocation"] == 23, departure
    assert departure["onboard_allocation"] == 17, departure
    assert departure["effective_precruise_available"] == 0, departure
    assert departure["seats_available_total"] == 40, departure
