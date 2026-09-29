"""Calculation boundaries: award pricing compounding and per-seat rounding, the
volume-tolerance ceiling, settlement-run eligibility and per-booking rounding,
fraud scoring thresholds, ledger aggregation and reaction-index relief.

Every test builds its own state from an empty database through the endpoints the
PRD declares, and every expected figure is the one the PRD's own arithmetic
produces.
"""
from test_helpers import (
    PROGRAM_ADMIN,
    PARTNER_MANAGER,
    REVENUE_ACCOUNTANT,
    FRAUD_ANALYST,
    assert_award_booking,
    assert_fraud_case,
    assert_member_account,
    assert_mile_purchase_order,
    assert_mile_transaction,
    assert_partner_airline,
    assert_program_change_notice,
    award_booking_payload,
    cancel_booking,
    create_member,
    create_partner,
    create_program,
    create_window,
    draft_notice,
    fraud_case_payload,
    grant_status_match,
    hold_seats,
    is_iso8601_timestamp,
    mile_purchase_order_payload,
    mile_transaction_payload,
    program_with_issuer,
    read_agreement,
    read_member,
    read_window,
    set_clock,
    tier_schedule,
    active_agreement,
    ticket_booking,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_dynamic_passthrough_charges_the_demand_multiplier_twice(api):
    """PRD §3.5: "That pre-booking load factor selects `demand_multiplier_bps_applied` from a four-rung ladder whose lower bounds are inclusive: 9000 basis points below 5000, 10000 from 5000 through 7499, 12500 from 7500 through 8999, and 16000 at 9000 and above."
    PRD §3.5: "`chart_miles_per_seat` is read from the award chart by the window's `cabin` and the requested `fare_class`: `ECONOMY` charges 12500 at `SAVER` and 25000 at `FLEX`; `PREMIUM` charges 25000 and 45000; `BUSINESS` charges 50000 and 85000; `FIRST` charges 90000 and 140000."
    PRD §3.5: "When a partner is named, it is 10000 under `FIXED_CHART`, 11500 under `DISTANCE_BAND`, and — under `DYNAMIC_PASSTHROUGH` — the very `demand_multiplier_bps_applied` from step 2, so the demand multiplier is charged a second time."
    PRD §3.5: "The gross award miles per seat are `chart_miles_per_seat` multiplied by `demand_multiplier_bps_applied` and by `partner_uplift_bps_applied`, divided by 100000000 (that is, both basis-point factors converted to plain multipliers), rounded half up."
    PRD §3.5: "`surcharge_band` is keyed by that gross per-seat figure, pre-discount, against inclusive lower bounds: `SURCHARGE_LOW` below 25000 gross miles, `SURCHARGE_MID` from 25000 through 74999, and `SURCHARGE_HIGH` at 75000 and above, so a gross of exactly 25000 or exactly 75000 takes the higher band."
    PRD §3.5: "The band also fixes the cash side: `cash_surcharge_cents` is 560 cents per seat at `SURCHARGE_LOW`, 1120 at `SURCHARGE_MID` and 2240 at `SURCHARGE_HIGH`, multiplied by `seats`."
    PRD §3.5: "A `BASE` member receives no discount in any band."
    PRD §3.5: "`partner_settlement_cents` is zero for own metal and otherwise `quoted_miles` multiplied by the partner's `settlement_rate_centicents_per_mile`, divided by 100, rounded half up."

    Design: Corner/calculations/dynamic_passthrough_charges_the_demand_multiplier_twice
    """
    program = create_program(name="SkyMiles Passthrough")
    member = create_member(
        program["id"], external_member_ref="MBR-PASS", home_region="APAC"
    )
    partner = create_partner(
        program["id"],
        iata_code="NH",
        settlement_rate_centicents_per_mile=200,
        reciprocity_mode="FULL",
        award_pricing_mode="DYNAMIC_PASSTHROUGH",
    )
    window = create_window(
        program["id"],
        route_code="JFK-HND",
        cabin="BUSINESS",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    response = api.create_award_booking(
        award_booking_payload(
            member["id"],
            window["id"],
            window["version"],
            travel_date="2026-09-12",
            seats=1,
            fare_class="FLEX",
            partner_airline_id=partner["id"],
        ),
        PROGRAM_ADMIN,
    )
    booking = validate_success(response, 201)
    assert_award_booking(booking)

    assert booking["chart_miles_per_seat"] == 85000, (
        "a BUSINESS FLEX award reads 85000 chart miles per seat"
    )
    assert booking["demand_multiplier_bps_applied"] == 9000, (
        "an empty window sits on the lowest demand rung of 9000 bps"
    )
    assert booking["partner_uplift_bps_applied"] == 9000, (
        "a DYNAMIC_PASSTHROUGH partner's uplift is the step-2 demand multiplier"
    )
    assert booking["quoted_miles"] == 68850, (
        "85000 * 9000 * 9000 / 100000000 charges the 9000 bps multiplier twice, "
        f"giving 68850, got {booking['quoted_miles']}"
    )
    assert booking["surcharge_band"] == "SURCHARGE_MID", (
        "a gross of 68850 miles falls in the 25000-74999 band"
    )
    assert booking["cash_surcharge_cents"] == 1120, (
        "SURCHARGE_MID charges 1120 cents for the single seat"
    )
    assert booking["elite_discount_bps_applied"] == 0, (
        "a BASE member receives no elite discount in any band"
    )
    assert booking["partner_settlement_cents"] == 137700, (
        "68850 quoted miles at 200 centicents per mile settle at 137700 cents"
    )
    assert booking["status"] == "HELD", "a freshly created award booking is HELD"


def test_settlement_run_ignores_held_cancelled_and_future_travel_bookings(api):
    """PRD §3.5: "The eligible set is the partner's bookings whose `status` is `TICKETED`, whose `partner_settled` is false, and whose `travel_date` is at or before the logical clock's calendar date — the date bound being inclusive, so a booking travelling today is eligible."
    PRD §3.5: "For each eligible booking in order, an amount equal to that booking's `partner_settlement_cents` multiplied by the factor, divided by 10000, **rounded half up per booking**, is added to `net_settlement_balance_cents`; `settled_booking_count` increases by one; and the booking's `partner_settled` is set true, which makes it permanently ineligible for any later run."
    PRD §3.5: "A run that finds no eligible booking succeeds, changes nothing but `last_settlement_run_at`, and is not an error; a `HELD` or `CANCELLED` booking is never eligible however old its travel date; and refunding a ticketed booking before settlement removes it from the eligible set, which is exactly why refund is blocked once `partner_settled` is true."
    PRD §3.5: "Finally `last_settlement_run_at` is stamped with the clock's now and the partner's `version` increments."
    PRD §3.5: "Otherwise a reciprocity factor is selected — 10000 basis points under `FULL`, 10000 under `INBOUND_ONLY`, and 5000 under `OUTBOUND_ONLY`, which halves the partner's take."

    Design: Corner/calculations/settlement_run_ignores_held_cancelled_and_future_travel_bookings
    """
    program = create_program(name="SkyMiles Filter")
    member = create_member(
        program["id"], external_member_ref="MBR-FILTER", home_region="EMEA"
    )
    validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "CARD_SPEND_EARN", "2026-07-02",
                qualifying_spend_cents=10000000,
            ),
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    partner = create_partner(
        program["id"], iata_code="LH", settlement_rate_centicents_per_mile=100
    )
    window = create_window(
        program["id"],
        route_code="JFK-FRA",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    # B1: ticketed, travel date already past by the time the run happens.
    b1 = hold_seats(
        member["id"], window["id"], window["version"],
        travel_date="2026-09-05", seats=1, fare_class="FLEX",
        partner_airline_id=partner["id"],
    )
    ticket_booking(b1["id"])
    # B4: ticketed but travelling after the run's calendar date.
    b4 = hold_seats(
        member["id"], window["id"], read_window(window["id"])["version"],
        travel_date="2026-09-20", seats=1, fare_class="FLEX",
        partner_airline_id=partner["id"],
    )
    ticket_booking(b4["id"])
    # B2: never ticketed, so never eligible.
    b2 = hold_seats(
        member["id"], window["id"], read_window(window["id"])["version"],
        travel_date="2026-09-05", seats=1, fare_class="FLEX",
        partner_airline_id=partner["id"],
    )
    # B3: cancelled, so never eligible.
    b3 = hold_seats(
        member["id"], window["id"], read_window(window["id"])["version"],
        travel_date="2026-09-05", seats=1, fare_class="FLEX",
        partner_airline_id=partner["id"],
    )
    cancel_booking(b3["id"])

    for candidate in (b1, b2, b3, b4):
        assert candidate["quoted_miles"] == 22500, (
            "every ECONOMY FLEX seat on this empty-to-lightly-loaded window "
            f"quotes 22500 miles, got {candidate['quoted_miles']}"
        )
        assert candidate["partner_settlement_cents"] == 22500, (
            "22500 miles at 100 centicents per mile is a 22500-cent basis"
        )

    set_clock("2026-09-06T00:00:00Z")

    run = api.create_settlement_run(partner["id"], REVENUE_ACCOUNTANT)
    validate_success(run, 200)

    settled_partner = validate_success(
        api.get_partner_airline(partner["id"], PROGRAM_ADMIN)
    )
    assert_partner_airline(settled_partner)
    assert settled_partner["net_settlement_balance_cents"] == 22500, (
        "only the single ticketed booking whose travel date has passed settles, "
        f"so the balance is one booking's 22500 cents, got "
        f"{settled_partner['net_settlement_balance_cents']}"
    )
    assert settled_partner["settled_booking_count"] == 1, (
        "the held, cancelled and future-travel bookings are all ineligible"
    )
    assert is_iso8601_timestamp(settled_partner["last_settlement_run_at"]), (
        "last_settlement_run_at is stamped with the clock's now"
    )
    assert settled_partner["last_settlement_run_at"].startswith(
        "2026-09-06T00:00:00"
    ), (
        "last_settlement_run_at carries the logical clock's instant, "
        f"got {settled_partner['last_settlement_run_at']}"
    )

    for booking_id, expected_settled, expected_status in (
        (b1["id"], True, "TICKETED"),
        (b2["id"], False, "HELD"),
        (b3["id"], False, "CANCELLED"),
        (b4["id"], False, "TICKETED"),
    ):
        row = validate_success(api.get_award_booking(booking_id, PROGRAM_ADMIN))
        assert row["partner_settled"] is expected_settled, (
            f"booking {expected_status} must have partner_settled "
            f"{expected_settled}, got {row['partner_settled']}"
        )
        assert row["status"] == expected_status, (
            f"the run must not move booking status, expected {expected_status}"
        )

    member_after = read_member(member["id"])
    assert_member_account(member_after)
    assert member_after["mile_balance"] == 55000, (
        "two ticketed redemptions of 22500 leave 100000 - 45000 = 55000 miles, "
        f"got {member_after['mile_balance']}"
    )


def test_volume_draw_allowed_up_to_exactly_one_hundred_ten_percent_of_commitment(api):
    """PRD §2.9: "The agreement's `drawn_miles` plus the requested `order_miles` is at most 110% of `committed_volume_miles`, computed as `committed_volume_miles` multiplied by 11000 divided by 10000 and rounded half up — otherwise `ERR_VOLUME_COMMITMENT_EXCEEDED` (409)."
    PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."
    PRD §3.3: "Its effects reach three rows: the agreement's `drawn_miles` increases by `order_miles`, the agreement's `prepayment_balance_miles` increases by the same `order_miles` (these are miles bought but not yet distributed to members), and the programme's `deferred_revenue_cents` increases by `gross_amount_cents`."
    PRD §3.3: "Breaching that ceiling raises `ERR_VOLUME_COMMITMENT_EXCEEDED` and the pricing calculation never runs at all."

    Design: Corner/calculations/volume_draw_allowed_up_to_exactly_one_hundred_ten_percent_of_commitment
    """
    program, issuer = program_with_issuer(
        program_overrides={"name": "SkyMiles Tolerance"},
        issuer_overrides={"annual_mile_purchase_cap_miles": 5000000},
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1000000,
        tier_schedule=tier_schedule((0, 200)),
    )

    at_the_ceiling = validate_success(
        api.create_mile_purchase_order(
            mile_purchase_order_payload(
                agreement["id"], 1100000, agreement["version"]
            ),
            PARTNER_MANAGER,
        ),
        201,
    )
    assert_mile_purchase_order(at_the_ceiling)
    assert at_the_ceiling["gross_amount_cents"] == 2200000, (
        "1100000 miles at 200 centicents each is 2200000 cents, got "
        f"{at_the_ceiling['gross_amount_cents']}"
    )

    validate_success(api.issue_order(at_the_ceiling["id"], PARTNER_MANAGER))
    drawn = read_agreement(agreement["id"])
    assert drawn["drawn_miles"] == 1100000, (
        "issuing advances drawn_miles by the full order, to exactly 110% of the "
        f"1000000-mile commitment, got {drawn['drawn_miles']}"
    )

    one_mile_too_far = api.create_mile_purchase_order(
        mile_purchase_order_payload(agreement["id"], 1, drawn["version"]),
        PARTNER_MANAGER,
    )
    validate_error(one_mile_too_far, "ERR_VOLUME_COMMITMENT_EXCEEDED", 409)

    unchanged = read_agreement(agreement["id"])
    assert unchanged["drawn_miles"] == 1100000, (
        "the rejected order mutates nothing, so drawn_miles stays at 1100000"
    )
    orders, meta = validate_paginated(
        api.list_mile_purchase_orders(
            PARTNER_MANAGER, params={"agreement_id": agreement["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the accepted order exists, got total_count {meta['total_count']}"
    )


def test_award_quote_rounds_per_seat_before_multiplying_by_seats(api):
    """PRD §3.6: "The grant moves `status_match_state` `NONE → TRIAL`, sets both `elite_tier` and `status_match_tier` to `matched_tier`, and sets `status_match_expires_at` to the logical clock's now plus `trial_days` days."
    PRD §3.5: "A `SILVER` member receives 0 basis points at `SURCHARGE_LOW`, 250 at `SURCHARGE_MID` and 500 at `SURCHARGE_HIGH`."
    PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."
    PRD §3.5: "The band also fixes the cash side: `cash_surcharge_cents` is 560 cents per seat at `SURCHARGE_LOW`, 1120 at `SURCHARGE_MID` and 2240 at `SURCHARGE_HIGH`, multiplied by `seats`."
    PRD §3.5: "The window's `seats_held` increases by `seats`, and for a `SAVER` booking `saver_seats_consumed` increases by `seats` as well; `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state` are then recomputed and the window's `version` increments."

    Design: Corner/calculations/award_quote_rounds_per_seat_before_multiplying_by_seats
    """
    program = create_program(name="SkyMiles Precision")
    member = create_member(
        program["id"], external_member_ref="MBR-PREC", home_region="AMER"
    )
    grant_status_match(member["id"], "SILVER", 90)
    window = create_window(
        program["id"],
        route_code="JFK-LHR",
        cabin="PREMIUM",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    matched = read_member(member["id"])
    assert matched["elite_tier"] == "SILVER", (
        "the status match raises the member to SILVER before the quote runs"
    )

    booking = validate_success(
        api.create_award_booking(
            award_booking_payload(
                member["id"], window["id"], window["version"],
                travel_date="2026-09-22", seats=2, fare_class="FLEX",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_award_booking(booking)

    assert booking["chart_miles_per_seat"] == 45000, (
        "a PREMIUM FLEX award reads 45000 chart miles per seat"
    )
    assert booking["demand_multiplier_bps_applied"] == 9000, (
        "the empty window prices on the 9000 bps demand rung"
    )
    assert booking["surcharge_band"] == "SURCHARGE_MID", (
        "a 40500-mile gross per seat falls in the 25000-74999 band"
    )
    assert booking["elite_discount_bps_applied"] == 250, (
        "SILVER receives 250 basis points at SURCHARGE_MID"
    )
    assert booking["quoted_miles"] == 78976, (
        "40500 * 9750 / 10000 is the exact half 39487.5, which rounds half up "
        f"per seat to 39488 before doubling to 78976, got {booking['quoted_miles']}"
    )
    assert booking["quoted_miles"] != 78975, (
        "rounding once after multiplying by the seat count is not the rule"
    )
    assert booking["cash_surcharge_cents"] == 2240, (
        "1120 cents per seat at SURCHARGE_MID across two seats is 2240"
    )
    held = read_window(window["id"])
    assert held["seats_held"] == 2, (
        f"the hold takes both seats, got seats_held {held['seats_held']}"
    )


def test_detection_score_of_exactly_forty_sets_watch_not_frozen(api):
    """PRD §3.7: "Each signal is first converted to a 0-to-100 sub-score and clamped at 100 **before** weighting, so that no single signal can dominate the result: the geo-velocity sub-score is `login_geo_velocity` times 10, capped at 100; the redemption sub-score is `redemption_velocity_24h` times 20, capped at 100; the brokering sub-score is `brokering_pattern_hits` times 25, capped at 100; and the dormancy sub-score is `dormancy_days` divided by 4 and rounded down, capped at 100."
    PRD §3.7: "`detection_score` is then the weighted blend of those four — 3500 basis points on geo velocity, 3000 on redemption velocity, 2500 on brokering pattern and 1000 on dormancy, meaning 35%, 30%, 25% and 10% — with the weighted sum divided by 10000, rounded half up, and capped at 100."
    PRD §3.7: "A `detection_score` of 70 or more drives `security_state` to `FROZEN` and sets the case's `freeze_applied` true."
    PRD §3.7: "A score from 40 through 69 drives `security_state` to `WATCH`."
    PRD §3.7: "In every case, including the last, the member's `risk_score` is set to the new `detection_score`; `risk_score` is by definition the `detection_score` of the member's most recent case, ordered by `created_at` ascending so the newest wins."
    PRD §3.7: "The opener's `X-User-ID` is stamped into `opened_by_user_id`, `adjudicated_by_user_id` starts null, `clawback_miles` starts at zero, `freeze_applied` starts false, and `status` starts `OPEN`."

    Design: Corner/calculations/detection_score_of_exactly_forty_sets_watch_not_frozen
    """
    program = create_program(name="SkyMiles Threshold")
    member = create_member(
        program["id"], external_member_ref="MBR-THRESH", home_region="AMER"
    )
    validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "PARTNER_EARN", "2026-07-15", base_miles=1000
            ),
            REVENUE_ACCOUNTANT,
        ),
        201,
    )

    case = validate_success(
        api.create_fraud_case(
            fraud_case_payload(
                member["id"], "VELOCITY_ANOMALY",
                login_geo_velocity=10,
                redemption_velocity_24h=0,
                brokering_pattern_hits=0,
                dormancy_days=200,
            ),
            FRAUD_ANALYST,
        ),
        201,
    )
    assert_fraud_case(case)

    assert case["detection_score"] == 40, (
        "geo velocity clamps to 100 and contributes 35 while 200 dormancy days "
        "give a sub-score of 50 contributing 5, landing exactly on 40, got "
        f"{case['detection_score']}"
    )
    assert case["freeze_applied"] is False, (
        "40 is below the inclusive freeze bound of 70, so no freeze is applied"
    )
    assert case["status"] == "OPEN", "a newly opened fraud case starts in OPEN"

    watched = read_member(member["id"])
    assert_member_account(watched)
    assert watched["security_state"] == "WATCH", (
        "a score of exactly 40 sits on the inclusive WATCH lower bound, got "
        f"{watched['security_state']}"
    )
    assert watched["risk_score"] == 40, (
        "the member's risk_score is set to the new detection_score"
    )


def test_outstanding_miles_reconciles_across_earn_redeem_and_expiry(api):
    """PRD §3.4: "**Seventh**, elite-qualifying credit is computed entirely independently of every multiplier above: a `FLIGHT_EARN` row credits `qualifying_miles_credited` equal to its base and adds the supplied `segments` to the member's `qualifying_segments_ytd`; a `CARD_SPEND_EARN` row credits the lesser of its base and a per-transaction cap of 15000 qualifying miles, and adds the supplied `qualifying_spend_cents` to the member's `qualifying_spend_cents_ytd`; a `PARTNER_EARN` row credits zero qualifying miles."
    PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."
    PRD §3.4: "Note that `lifetime_miles` counts only the three earning types, whereas `mile_balance` and `outstanding_miles` sum every type with its sign, and `mile_balance` is never negative."
    PRD §3.4: "Their `total_miles` is taken straight from the caller-supplied `base_miles` magnitude, which is always supplied non-negative, with the sign the type dictates: negative for `REDEEM`, `EXPIRY` and `ADJUSTMENT`, positive for `REVERSAL`."
    PRD §3.1: "`outstanding_miles` is the member-held mile liability: the sum of `total_miles` across every mile ledger row belonging to a member of this programme, taking every `txn_type` and respecting the sign of each row, recomputed on every insert."

    Design: Corner/calculations/outstanding_miles_reconciles_across_earn_redeem_and_expiry
    """
    program = create_program(name="SkyMiles Aggregate")
    member = create_member(
        program["id"], external_member_ref="MBR-AGG", home_region="AMER"
    )

    earn = validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "PARTNER_EARN", "2026-07-10", base_miles=10000
            ),
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    redeem = validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "REDEEM", "2026-07-20", base_miles=4000
            ),
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    expiry = validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "EXPIRY", "2026-08-01", base_miles=1000
            ),
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    for row in (earn, redeem, expiry):
        assert_mile_transaction(row)

    assert earn["total_miles"] == 10000, (
        "a BASE PARTNER_EARN takes base_miles verbatim, got "
        f"{earn['total_miles']}"
    )
    assert earn["qualifying_miles_credited"] == 0, (
        "a PARTNER_EARN row credits zero qualifying miles"
    )
    assert redeem["total_miles"] == -4000, (
        f"a REDEEM row carries the negative magnitude, got {redeem['total_miles']}"
    )
    assert expiry["total_miles"] == -1000, (
        f"an EXPIRY row carries the negative magnitude, got {expiry['total_miles']}"
    )

    member_after = read_member(member["id"])
    assert_member_account(member_after)
    assert member_after["mile_balance"] == 5000, (
        "10000 earned less 4000 redeemed less 1000 expired nets to 5000, got "
        f"{member_after['mile_balance']}"
    )
    assert member_after["lifetime_miles"] == 10000, (
        "lifetime_miles counts only the earning row, got "
        f"{member_after['lifetime_miles']}"
    )
    assert member_after["qualifying_miles_ytd"] == 0, (
        "no row credited qualifying miles, got "
        f"{member_after['qualifying_miles_ytd']}"
    )

    program_after = validate_success(
        api.get_loyalty_program(program["id"], PROGRAM_ADMIN)
    )
    assert program_after["outstanding_miles"] == 5000, (
        "programme-wide outstanding miles sum every row with its sign, got "
        f"{program_after['outstanding_miles']}"
    )

    rows, meta = validate_paginated(
        api.list_mile_transactions(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 3, (
        f"all three ledger rows persist, got total_count {meta['total_count']}"
    )


def test_settlement_run_rounds_each_booking_before_accumulating(api):
    """PRD §3.5: "Otherwise a reciprocity factor is selected — 10000 basis points under `FULL`, 10000 under `INBOUND_ONLY`, and 5000 under `OUTBOUND_ONLY`, which halves the partner's take."
    PRD §3.5: "For each eligible booking in order, an amount equal to that booking's `partner_settlement_cents` multiplied by the factor, divided by 10000, **rounded half up per booking**, is added to `net_settlement_balance_cents`; `settled_booking_count` increases by one; and the booking's `partner_settled` is set true, which makes it permanently ineligible for any later run."
    PRD §3.5: "Because rounding is per booking, two bookings of 1121 cents each under `OUTBOUND_ONLY` settle to 561 plus 561, totalling 1122 — not the 1121 that halving the combined 2242 would give."
    PRD §3.5: "A run that finds no eligible booking succeeds, changes nothing but `last_settlement_run_at`, and is not an error; a `HELD` or `CANCELLED` booking is never eligible however old its travel date; and refunding a ticketed booking before settlement removes it from the eligible set, which is exactly why refund is blocked once `partner_settled` is true."
    PRD §3.5: "`partner_settlement_cents` is zero for own metal and otherwise `quoted_miles` multiplied by the partner's `settlement_rate_centicents_per_mile`, divided by 100, rounded half up."

    Design: Corner/calculations/settlement_run_rounds_each_booking_before_accumulating
    """
    program = create_program(name="SkyMiles Chrono")
    member = create_member(
        program["id"], external_member_ref="MBR-CHRONO", home_region="APAC"
    )
    validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "CARD_SPEND_EARN", "2026-07-02",
                qualifying_spend_cents=10000000,
            ),
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    partner = create_partner(
        program["id"],
        iata_code="NH",
        settlement_rate_centicents_per_mile=1,
        reciprocity_mode="OUTBOUND_ONLY",
    )
    window = create_window(
        program["id"],
        route_code="JFK-HND",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    b1 = hold_seats(
        member["id"], window["id"], window["version"],
        travel_date="2026-09-05", seats=1, fare_class="FLEX",
        partner_airline_id=partner["id"],
    )
    ticket_booking(b1["id"])
    b2 = hold_seats(
        member["id"], window["id"], read_window(window["id"])["version"],
        travel_date="2026-09-05", seats=1, fare_class="FLEX",
        partner_airline_id=partner["id"],
    )
    ticket_booking(b2["id"])

    for booking in (b1, b2):
        assert booking["partner_settlement_cents"] == 225, (
            "22500 quoted miles at 1 centicent per mile is a 225-cent basis, got "
            f"{booking['partner_settlement_cents']}"
        )

    set_clock("2026-09-06T00:00:00Z")

    validate_success(api.create_settlement_run(partner["id"], REVENUE_ACCOUNTANT), 200)

    after_first = validate_success(
        api.get_partner_airline(partner["id"], PROGRAM_ADMIN)
    )
    assert_partner_airline(after_first)
    assert after_first["net_settlement_balance_cents"] == 226, (
        "each 225-cent booking is halved and rounded half up on its own to 113, "
        f"totalling 226, got {after_first['net_settlement_balance_cents']}"
    )
    assert after_first["net_settlement_balance_cents"] != 225, (
        "halving the 450-cent aggregate once is not the rule"
    )
    assert after_first["settled_booking_count"] == 2, (
        "both eligible bookings settle, got "
        f"{after_first['settled_booking_count']}"
    )
    for booking in (b1, b2):
        row = validate_success(api.get_award_booking(booking["id"], PROGRAM_ADMIN))
        assert row["partner_settled"] is True, (
            "a settled booking is flagged partner_settled"
        )

    validate_success(api.create_settlement_run(partner["id"], REVENUE_ACCOUNTANT), 200)
    after_second = validate_success(
        api.get_partner_airline(partner["id"], PROGRAM_ADMIN)
    )
    assert after_second["net_settlement_balance_cents"] == 226, (
        "a second run finds nothing eligible and adds nothing, got "
        f"{after_second['net_settlement_balance_cents']}"
    )
    assert after_second["settled_booking_count"] == 2, (
        "already-settled bookings are permanently ineligible"
    )

    member_after = read_member(member["id"])
    assert member_after["mile_balance"] == 55000, (
        "two 22500-mile redemptions leave 55000 miles, got "
        f"{member_after['mile_balance']}"
    )


def test_full_year_grandfathering_relief_drives_reaction_index_to_zero(api):
    """PRD §3.8: "`notice_days` is the whole number of days from `announced_at` to `effective_at`, taking the floor of the difference."
    PRD §3.8: "`exposed_member_count` is the number of member accounts in the programme whose `elite_tier` is anything other than `BASE` and whose `security_state` is either `NORMAL` or `WATCH`, snapshotted at announcement."
    PRD §3.8: "The first ingredient is severity, taken from `change_type`: 40 points for `EARN_STRUCTURE`, 50 for `AWARD_PRICING`, 30 for `ELITE_THRESHOLD` and 20 for `EXPIRY_POLICY` — repricing awards angers members more than tightening expiry."
    PRD §3.8: "The second is a lead-time factor keyed by `notice_days` against inclusive lower bounds: 10000 basis points at 180 days or more, 12500 from 90 through 179 days, 15000 from 30 through 89 days, and 20000 below 30 days, so exactly 180, 90 or 30 days each take the kinder factor."
    PRD §3.8: "The third is grandfathering relief: 30 points when `grandfather_until` is at or after `effective_at` plus 365 days, 15 points when `grandfather_until` is at or after `effective_at` but earlier than that full year (so a `grandfather_until` exactly equal to `effective_at` still earns the partial 15), and 0 points when `grandfather_until` is null."
    PRD §3.8: "Relief points are subtracted from that product and the result is floored at zero — relief can therefore drive the pre-exposure term to zero, in which case the index is zero no matter how many members are exposed."
    PRD §3.8: "A successful announcement moves `status` `DRAFT → ANNOUNCED`."

    Design: Corner/calculations/full_year_grandfathering_relief_drives_reaction_index_to_zero
    """
    program = create_program(name="SkyMiles Relief")
    first = create_member(
        program["id"], external_member_ref="MBR-R1", home_region="AMER"
    )
    grant_status_match(first["id"], "SILVER", 90)
    second = create_member(
        program["id"], external_member_ref="MBR-R2", home_region="EMEA"
    )
    grant_status_match(second["id"], "SILVER", 90)

    notice = draft_notice(
        program["id"], "EXPIRY_POLICY", "2027-03-01T00:00:00Z", program["version"],
        grandfather_until="2028-03-01T00:00:00Z",
    )

    announced = validate_success(
        api.announce_notice(notice["id"], PROGRAM_ADMIN), 200
    )
    assert_program_change_notice(announced)

    assert announced["status"] == "ANNOUNCED", (
        f"a successful announcement lands in ANNOUNCED, got {announced['status']}"
    )
    assert is_iso8601_timestamp(announced["announced_at"]), (
        "announced_at is stamped with the clock's now"
    )
    assert announced["announced_at"].startswith("2026-08-01T00:00:00"), (
        "the logical clock reads 2026-08-01T00:00:00Z at announcement, got "
        f"{announced['announced_at']}"
    )
    assert announced["notice_days"] == 212, (
        "2026-08-01 to 2027-03-01 is 212 whole days, got "
        f"{announced['notice_days']}"
    )
    assert announced["exposed_member_count"] == 2, (
        "both status-matched SILVER members are exposed, got "
        f"{announced['exposed_member_count']}"
    )
    assert announced["member_reaction_index"] == 0, (
        "EXPIRY_POLICY severity 20 at the 10000 bps lead-time factor is 20, and "
        "the 30 points of full-year relief floor the pre-exposure term at zero "
        "before the exposure multiply, so the index is 0, got "
        f"{announced['member_reaction_index']}"
    )
