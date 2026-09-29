"""Validation-ladder rungs at their exact boundaries: the 90-day agreement term
on both sides of the floor, the closed travel-date interval, the issuer cap in
aggregate, the saver allotment against raw availability, and the partner
reciprocity gate short-circuiting the capacity checks below it.
"""
from test_helpers import (
    CONTRACTS_OFFICER,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    assert_award_booking,
    assert_award_inventory_window,
    assert_co_brand_issuer,
    assert_mile_sale_agreement,
    award_booking_payload,
    create_member,
    create_partner,
    create_program,
    create_window,
    draft_agreement,
    hold_seats,
    mile_sale_agreement_payload,
    program_with_issuer,
    ratify_agreement,
    read_agreement,
    read_window,
    submit_agreement,
    tier_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_agreement_term_one_day_short_of_ninety_returns_invalid_term(api):
    """PRD §2.9: "An agreement term is at least 90 whole days long, measured from `term_start_date` to `term_end_date`, and `term_start_date` is not earlier than the logical clock's calendar date — otherwise `ERR_INVALID_TERM` (422)."
    PRD §2.9: "Every date interval is correctly ordered: `term_start_date` is not after `term_end_date`, `window_start_date` is not after `window_end_date`, and `window_start` is strictly before `window_end` — otherwise `ERR_INVALID_INTERVAL` (422)."
    PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."

    Design: Corner/validations/agreement_term_one_day_short_of_ninety_returns_invalid_term
    """
    program, issuer = program_with_issuer(
        program_overrides={"name": "SkyMiles Term"},
        issuer_overrides={"annual_mile_purchase_cap_miles": 5000000},
    )

    response = api.create_mile_sale_agreement(
        mile_sale_agreement_payload(
            issuer["id"],
            term_start_date="2026-09-01",
            term_end_date="2026-11-29",
            committed_volume_miles=1000000,
            tier_schedule=tier_schedule((0, 200)),
        ),
        PARTNER_MANAGER,
    )
    validate_error(response, "ERR_INVALID_TERM", 422)
    assert response.json()["data"]["error_id"] != "ERR_INVALID_INTERVAL", (
        "the interval is correctly ordered, so the term floor must be reported "
        "rather than an inverted-interval error"
    )

    agreements, meta = validate_paginated(
        api.list_mile_sale_agreements(
            PARTNER_MANAGER, params={"issuer_id": issuer["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "the rejected draft leaves no agreement row behind, got total_count "
        f"{meta['total_count']}"
    )

    issuer_after = validate_success(
        api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN)
    )
    assert_co_brand_issuer(issuer_after)
    assert issuer_after["aggregate_committed_miles"] == 0, (
        "no committed miles accrue from a rejected draft, got "
        f"{issuer_after['aggregate_committed_miles']}"
    )


def test_agreement_term_of_exactly_ninety_days_is_accepted(api):
    """PRD §2.9: "An agreement term is at least 90 whole days long, measured from `term_start_date` to `term_end_date`, and `term_start_date` is not earlier than the logical clock's calendar date — otherwise `ERR_INVALID_TERM` (422)."
    PRD §3.2: "A drafted agreement starts in `DRAFT` with `negotiation_round` at 1, both counter fields (`countered_price_per_mile_centicents` and `countered_committed_volume_miles`) null, `ratified_by_user_id` null, and `drawn_miles` and `prepayment_balance_miles` at zero."
    PRD §3.2: "Crucially, a `DRAFT` agreement does not yet count toward the issuer's aggregate."

    Design: Corner/validations/agreement_term_of_exactly_ninety_days_is_accepted
    """
    program, issuer = program_with_issuer(
        program_overrides={"name": "SkyMiles Term Pass"},
        issuer_overrides={"annual_mile_purchase_cap_miles": 5000000},
    )

    agreement = validate_success(
        api.create_mile_sale_agreement(
            mile_sale_agreement_payload(
                issuer["id"],
                term_start_date="2026-09-01",
                term_end_date="2026-11-30",
                committed_volume_miles=1000000,
                tier_schedule=tier_schedule((0, 200)),
            ),
            PARTNER_MANAGER,
        ),
        201,
    )
    assert_mile_sale_agreement(agreement)

    assert agreement["status"] == "DRAFT", (
        f"a freshly drafted agreement sits in DRAFT, got {agreement['status']}"
    )
    assert agreement["negotiation_round"] == 1, (
        "a drafted agreement starts with negotiation_round at 1, got "
        f"{agreement['negotiation_round']}"
    )
    assert agreement["drawn_miles"] == 0, (
        f"nothing has been drawn yet, got {agreement['drawn_miles']}"
    )
    assert agreement["prepayment_balance_miles"] == 0, (
        "no miles have been prepaid yet, got "
        f"{agreement['prepayment_balance_miles']}"
    )
    assert agreement["countered_price_per_mile_centicents"] is None, (
        "both counter fields are null on a fresh draft"
    )
    assert agreement["countered_committed_volume_miles"] is None, (
        "both counter fields are null on a fresh draft"
    )
    assert agreement["ratified_by_user_id"] is None, (
        "ratified_by_user_id is null until a ContractsOfficer ratifies"
    )

    issuer_after = validate_success(
        api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN)
    )
    assert issuer_after["aggregate_committed_miles"] == 0, (
        "a DRAFT agreement does not count toward the issuer aggregate, got "
        f"{issuer_after['aggregate_committed_miles']}"
    )


def test_travel_date_one_day_past_the_window_returns_travel_date_out_of_window(api):
    """PRD §2.9: "An award booking's `travel_date` falls inside the window's closed date interval, meaning at or after `window_start_date` and at or before `window_end_date` — otherwise `ERR_TRAVEL_DATE_OUT_OF_WINDOW` (422)."
    PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
    PRD §3.5: "`load_factor_bps` is `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up, and defined as zero when `authorized_seats` is zero."

    Design: Corner/validations/travel_date_one_day_past_the_window_returns_travel_date_out_of_window
    """
    program = create_program(name="SkyMiles Travel Date")
    member = create_member(
        program["id"], external_member_ref="MBR-TD", home_region="AMER"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    on_the_last_day = validate_success(
        api.create_award_booking(
            award_booking_payload(
                member["id"], window["id"], window["version"],
                travel_date="2026-09-30", seats=1, fare_class="FLEX",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_award_booking(on_the_last_day)
    assert on_the_last_day["travel_date"] == "2026-09-30", (
        "the closed interval includes its own end date, got "
        f"{on_the_last_day['travel_date']}"
    )
    assert on_the_last_day["quoted_miles"] == 22500, (
        "an ECONOMY FLEX seat on an empty window quotes 25000 * 0.9 = 22500, got "
        f"{on_the_last_day['quoted_miles']}"
    )

    refreshed = read_window(window["id"])
    one_day_past = api.create_award_booking(
        award_booking_payload(
            member["id"], window["id"], refreshed["version"],
            travel_date="2026-10-01", seats=1, fare_class="FLEX",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(one_day_past, "ERR_TRAVEL_DATE_OUT_OF_WINDOW", 422)

    window_after = read_window(window["id"])
    assert_award_inventory_window(window_after)
    assert window_after["seats_held"] == 1, (
        "the rejected booking retains no partial mutation, so only the accepted "
        f"seat is held, got {window_after['seats_held']}"
    )
    assert window_after["load_factor_bps"] == 1000, (
        "one held seat of ten authorised is 1000 basis points, got "
        f"{window_after['load_factor_bps']}"
    )

    bookings, meta = validate_paginated(
        api.list_award_bookings(PROGRAM_ADMIN, params={"window_id": window["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the accepted booking exists, got total_count {meta['total_count']}"
    )


def test_individually_legal_commitments_breach_the_issuer_cap_in_aggregate(api):
    """PRD §3.2: "Second, the issuer's `aggregate_committed_miles` — computed net of any agreement this one supersedes, so a straight renewal does not double-count — plus this agreement's `committed_volume_miles` must not exceed `annual_mile_purchase_cap_miles`, or the ratification is refused with `ERR_ISSUER_CAP_EXCEEDED`."
    PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."
    PRD §3.2: "The third hop, caused by the second, tests the newly recomputed aggregate against a utilisation alarm set at 9000 basis points of the cap, that is at ninety percent of `annual_mile_purchase_cap_miles` after rounding half up, with the boundary inclusive: when the recomputed `aggregate_committed_miles` reaches or exceeds that figure, the issuer's `status` becomes `SUSPENDED` and its `suspension_reason` becomes `CAP_BREACH`."

    Design: Corner/validations/individually_legal_commitments_breach_the_issuer_cap_in_aggregate
    """
    program, issuer = program_with_issuer(
        program_overrides={"name": "SkyMiles Aggregate Cap"},
        issuer_overrides={"annual_mile_purchase_cap_miles": 5000000},
    )

    first = draft_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=3000000,
        tier_schedule=tier_schedule((0, 200)),
    )
    submit_agreement(first["id"])
    ratify_agreement(first["id"])

    second = draft_agreement(
        issuer["id"],
        term_start_date="2027-09-01",
        term_end_date="2028-08-31",
        committed_volume_miles=2000001,
        tier_schedule=tier_schedule((0, 200)),
    )
    submit_agreement(second["id"])

    third = draft_agreement(
        issuer["id"],
        term_start_date="2028-09-01",
        term_end_date="2029-08-31",
        committed_volume_miles=2000000,
        tier_schedule=tier_schedule((0, 200)),
    )
    submit_agreement(third["id"])

    before = validate_success(api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN))
    assert before["aggregate_committed_miles"] == 3000000, (
        "only the ratified agreement counts toward the aggregate, got "
        f"{before['aggregate_committed_miles']}"
    )
    assert before["status"] == "ACTIVE", (
        "3000000 is below the 4500000 utilisation alarm, so the issuer stays "
        f"ACTIVE, got {before['status']}"
    )

    over_the_cap = api.ratify_agreement(second["id"], CONTRACTS_OFFICER)
    validate_error(over_the_cap, "ERR_ISSUER_CAP_EXCEEDED", 409)

    rejected = read_agreement(second["id"])
    assert rejected["status"] == "ISSUER_REVIEW", (
        "the refused ratification leaves the agreement under issuer review, got "
        f"{rejected['status']}"
    )
    assert rejected["ratified_by_user_id"] is None, (
        "a refused ratification stamps no ratifier"
    )

    onto_the_cap = validate_success(
        api.ratify_agreement(third["id"], CONTRACTS_OFFICER), 200
    )
    assert_mile_sale_agreement(onto_the_cap)
    assert onto_the_cap["status"] == "RATIFIED", (
        "3000000 plus 2000000 lands exactly on the 5000000 cap and ratifies, got "
        f"{onto_the_cap['status']}"
    )

    after = validate_success(api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN))
    assert_co_brand_issuer(after)
    assert after["aggregate_committed_miles"] == 5000000, (
        "the aggregate now sums both ratified agreements, got "
        f"{after['aggregate_committed_miles']}"
    )
    assert after["status"] == "SUSPENDED", (
        "5000000 reaches the inclusive 4500000 utilisation alarm, so the issuer "
        f"is suspended, got {after['status']}"
    )
    assert after["suspension_reason"] == "CAP_BREACH", (
        "an automatic suspension records CAP_BREACH, got "
        f"{after['suspension_reason']}"
    )


def test_saver_allotment_blocks_a_fourth_saver_seat_while_flex_still_books(api):
    """PRD §2.9: "For a `SAVER` booking, `saver_seats_consumed` plus the requested `seats` is at most the window's saver allotment, which is `authorized_seats` multiplied by `saver_seat_share_bps` divided by 10000 and rounded half up — otherwise `ERR_SAVER_ALLOTMENT_EXHAUSTED` (409)."
    PRD §3.5: "Note that raw availability and saver allotment are separate ceilings: a `SAVER` request can be refused with `ERR_SAVER_ALLOTMENT_EXHAUSTED` while ordinary seats plainly remain."
    PRD §3.5: "The window's `seats_held` increases by `seats`, and for a `SAVER` booking `saver_seats_consumed` increases by `seats` as well; `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state` are then recomputed and the window's `version` increments."
    PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."
    PRD §3.5: "The band also fixes the cash side: `cash_surcharge_cents` is 560 cents per seat at `SURCHARGE_LOW`, 1120 at `SURCHARGE_MID` and 2240 at `SURCHARGE_HIGH`, multiplied by `seats`."

    Design: Corner/validations/saver_allotment_blocks_a_fourth_saver_seat_while_flex_still_books
    """
    program = create_program(name="SkyMiles Saver")
    member = create_member(
        program["id"], external_member_ref="MBR-SAVER", home_region="AMER"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
        saver_seat_share_bps=3000,
    )

    saver = hold_seats(
        member["id"], window["id"], window["version"],
        travel_date="2026-09-10", seats=3, fare_class="SAVER",
    )
    assert_award_booking(saver)
    assert saver["chart_miles_per_seat"] == 12500, (
        "an ECONOMY SAVER award reads 12500 chart miles per seat, got "
        f"{saver['chart_miles_per_seat']}"
    )
    assert saver["quoted_miles"] == 33750, (
        "12500 * 0.9 is 11250 per seat across three seats, got "
        f"{saver['quoted_miles']}"
    )
    assert saver["cash_surcharge_cents"] == 1680, (
        "560 cents per seat at SURCHARGE_LOW across three seats is 1680, got "
        f"{saver['cash_surcharge_cents']}"
    )

    consumed = read_window(window["id"])
    assert consumed["saver_seats_consumed"] == 3, (
        "the SAVER hold consumes the whole 3-seat allotment, got "
        f"{consumed['saver_seats_consumed']}"
    )

    fourth_saver = api.create_award_booking(
        award_booking_payload(
            member["id"], window["id"], consumed["version"],
            travel_date="2026-09-11", seats=1, fare_class="SAVER",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(fourth_saver, "ERR_SAVER_ALLOTMENT_EXHAUSTED", 409)

    flex = validate_success(
        api.create_award_booking(
            award_booking_payload(
                member["id"], window["id"], consumed["version"],
                travel_date="2026-09-11", seats=1, fare_class="FLEX",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert flex["quoted_miles"] == 22500, (
        "the FLEX seat prices off the 25000-mile chart at the 9000 bps rung, got "
        f"{flex['quoted_miles']}"
    )

    window_after = read_window(window["id"])
    assert_award_inventory_window(window_after)
    assert window_after["saver_seats_consumed"] == 3, (
        "a FLEX booking never touches saver_seats_consumed, got "
        f"{window_after['saver_seats_consumed']}"
    )
    assert window_after["seats_held"] == 4, (
        "three SAVER seats plus one FLEX seat are held, got "
        f"{window_after['seats_held']}"
    )
    assert window_after["load_factor_bps"] == 4000, (
        "four of ten authorised seats is 4000 basis points, got "
        f"{window_after['load_factor_bps']}"
    )
    assert window_after["capacity_control_state"] == "OPEN", (
        "4000 basis points is below the 7500 CONSTRAINED bound, got "
        f"{window_after['capacity_control_state']}"
    )


def test_suspended_reciprocity_short_circuits_before_any_capacity_arithmetic(api):
    """PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
    PRD §2.9: "The partner airline's `reciprocity_mode` is not `SUSPENDED` — otherwise `ERR_RECIPROCITY_SUSPENDED` (409). Applies both to requesting a settlement run and to creating an award booking that names that airline."
    PRD §2.9: "The award window's `capacity_control_state` is not `CLOSED` — otherwise `ERR_AWARD_WINDOW_CLOSED` (409)."
    PRD §2.9: "The window has raw capacity: `seats_held` plus `seats_confirmed` plus the requested `seats` is at most `authorized_seats` — otherwise `ERR_AWARD_SEATS_UNAVAILABLE` (409)."
    PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."

    Design: Corner/validations/suspended_reciprocity_short_circuits_before_any_capacity_arithmetic
    """
    program = create_program(name="SkyMiles Cascade Validation")
    member = create_member(
        program["id"], external_member_ref="MBR-CASC", home_region="EMEA"
    )
    partner = create_partner(
        program["id"],
        iata_code="LH",
        settlement_rate_centicents_per_mile=100,
        reciprocity_mode="SUSPENDED",
    )
    window = create_window(
        program["id"],
        route_code="JFK-FRA",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=1,
    )

    hold_seats(
        member["id"], window["id"], window["version"],
        travel_date="2026-09-10", seats=1, fare_class="FLEX",
    )

    filled = read_window(window["id"])
    assert_award_inventory_window(filled)
    assert filled["load_factor_bps"] == 10000, (
        "the single authorised seat is held, so the load factor is 10000 basis "
        f"points, got {filled['load_factor_bps']}"
    )
    assert filled["capacity_control_state"] == "CLOSED", (
        "a load factor of 10000 or more is CLOSED, got "
        f"{filled['capacity_control_state']}"
    )

    triple_violation = api.create_award_booking(
        award_booking_payload(
            member["id"], window["id"], filled["version"],
            travel_date="2026-09-11", seats=1, fare_class="FLEX",
            partner_airline_id=partner["id"],
        ),
        PROGRAM_ADMIN,
    )
    validate_error(triple_violation, "ERR_RECIPROCITY_SUSPENDED", 409)
    reported = triple_violation.json()["data"]["error_id"]
    assert reported != "ERR_AWARD_WINDOW_CLOSED", (
        "the partner reciprocity gate precedes the closed-window check"
    )
    assert reported != "ERR_AWARD_SEATS_UNAVAILABLE", (
        "the partner reciprocity gate precedes the raw-capacity check"
    )

    window_after = read_window(window["id"])
    assert window_after["seats_held"] == 1, (
        "the refused booking holds no seat, got "
        f"{window_after['seats_held']}"
    )

    bookings, meta = validate_paginated(
        api.list_award_bookings(PROGRAM_ADMIN, params={"window_id": window["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the first booking exists, got total_count {meta['total_count']}"
    )
