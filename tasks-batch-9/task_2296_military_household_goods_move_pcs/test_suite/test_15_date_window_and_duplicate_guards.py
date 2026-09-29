"""Spread and transit windows, movement-date guards, duplicates and claim windows."""

import pytest

from test_helpers import (
    COUNSELOR,
    COUNSELOR_USER_ID,
    ApiErrorId,
    amend_order,
    amend_order_payload,
    api_client,
    award_shipment,
    complete_counseling,
    complete_counseling_payload,
    create_capacity_block,
    create_claim_payload,
    create_claim_item_payload,
    create_counseling_session,
    create_order,
    create_order_payload,
    create_service_member,
    create_service_member_payload,
    deliver_payload,
    declare_pro_gear,
    get_success_data,
    pack_payload,
    pickup_payload,
    read_entitlement,
    read_shipment,
    record_actual_weight_payload,
    set_clock,
    setup_awarded_shipment,
    setup_booked_shipment,
    setup_delivered_shipment,
    setup_surveyed_shipment,
    survey_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_pro_gear,
    verify_pro_gear_payload,
)

EARLIEST_PACK = "2026-08-14T00:00:00Z"
TOO_EARLY_PACK = "2026-08-13T00:00:00Z"
SPREAD_START = "2026-08-15T00:00:00Z"
SPREAD_END = "2026-08-24T00:00:00Z"
DAY_PAST_SPREAD = "2026-08-25T00:00:00Z"
WEIGH_DATE = "2026-08-17T00:00:00Z"
FILING_CLOCK = "2026-09-01T00:00:00Z"
FAR_FUTURE_CLOCK = "2028-08-25T00:00:00Z"
LATE_NOTICE = "2027-03-01T00:00:00Z"
GOOD_NOTICE = "2026-08-25T00:00:00Z"


def _declaration(declaration_id):
    return get_success_data(
        api_client.get_pro_gear_declaration(declaration_id, COUNSELOR)
    )


def _shipment_claims(shipment_id):
    return validate_paginated(api_client.list_shipment_claims(shipment_id, COUNSELOR))


def _amend(order_id, amendment_reason, report_date):
    return api_client.amend_order(
        order_id,
        amend_order_payload(
            amendment_reason=amendment_reason,
            report_no_later_than_date_override=report_date,
        ),
        COUNSELOR,
    )


def _member_with_one_completed_session():
    """One member, one set of orders, one completed session and a second scheduled one."""
    set_clock()
    member = create_service_member()
    order = create_order(member["id"])
    first = create_counseling_session(order["id"])
    complete_counseling(first["id"])
    second = create_counseling_session(
        order["id"], session_type="VIRTUAL", scheduled_at="2026-08-06T00:00:00Z"
    )
    return member, order, second


class TestMovementDateWindows:
    """The spread window, the transit allowance and the four movement-date guards."""

    def test_the_first_spread_day_is_a_legal_pickup_day(self):
        """A peak-season booking spreads 15 to 24 August, packs on the fourteenth and lifts on the fifteenth.

        "a short-notice booking receives a spread of zero days before and two days after the
        requested pickup date; failing that, a peak-season booking receives two days before
        and seven days after; and an ordinary booking receives one day before and four days
        after. `spread_start_date` is `requested_pickup_date` moved back by the before-days
        and `spread_end_date` is `requested_pickup_date` moved forward by the after-days, the
        latter being an inclusive endpoint."

        "`transit_days_allowed` is the mileage-based figure — the orders' `distance_miles`
        divided by 300 miles per transit day and rounded **up** to a whole day — plus two
        extra days when `peak_season` is true, with the whole result then raised to a floor of
        five days if it came out lower."

        Design: Corner/validations/spread_window_and_transit_dates_accept_the_first_spread_day
        """
        scenario = setup_awarded_shipment()
        shipment = scenario["shipment"]
        shipment_id = shipment["id"]

        assert shipment["is_short_notice"] is False
        assert shipment["peak_season"] is True
        assert shipment["spread_start_date"] == SPREAD_START
        assert shipment["spread_end_date"] == SPREAD_END
        assert shipment["transit_days_allowed"] == 6

        packed = validate_success(
            api_client.pack_shipment(
                shipment_id, pack_payload(EARLIEST_PACK), scenario["tsp_headers"]
            ),
            200,
        )
        assert packed["movement_status"] == "PACKED"
        assert packed["pack_date"] == EARLIEST_PACK

        picked_up = validate_success(
            api_client.pickup_shipment(
                shipment_id, pickup_payload(SPREAD_START), scenario["tsp_headers"]
            ),
            200,
        )
        assert picked_up["movement_status"] == "PICKED_UP"
        assert picked_up["actual_pickup_date"] == SPREAD_START
        assert picked_up["required_delivery_by"] == "2026-08-21T00:00:00Z"

    def test_each_movement_date_guard_returns_its_own_code(self):
        """An empty survey, an early pack, an uncertified scale, a late pickup and an early delivery.

        "An empty array is refused with `ERR_SURVEY_ROOM_ESTIMATES_EMPTY`."

        "The request supplies `pack_date`, which may be no earlier than one day before
        `spread_start_date`; an earlier date is refused with `ERR_PACK_BEFORE_SPREAD`."

        "`scale_certified`, which must be true — an uncertified weight of record is refused
        with `ERR_UNCERTIFIED_SCALE`."

        "The coordinator supplies `actual_pickup_date`, which must fall inside the closed
        spread window — on or after `spread_start_date` and on or before `spread_end_date`. A
        date outside those bounds is refused with `ERR_PICKUP_OUTSIDE_SPREAD`."

        "the supplied `delivery_date` to be no earlier than `actual_pickup_date`, on pain of
        `ERR_DELIVERY_BEFORE_PICKUP`"

        Design: Corner/validations/pack_pickup_delivery_and_scale_guards_return_their_own_codes
        """
        scenario = setup_booked_shipment()
        shipment_id = scenario["shipment"]["id"]
        tsp_headers = scenario["tsp_headers"]

        validate_error(
            api_client.survey_shipment(
                shipment_id, survey_payload(room_estimates=[]), tsp_headers
            ),
            ApiErrorId.ERR_SURVEY_ROOM_ESTIMATES_EMPTY.value,
            422,
        )
        blank = read_shipment(shipment_id)
        assert blank["movement_status"] == "AWARDED"
        assert blank["weight_recon_status"] == "PENDING"

        surveyed = validate_success(
            api_client.survey_shipment(shipment_id, survey_payload(), tsp_headers), 200
        )
        assert surveyed["estimated_gross_lbs"] == 5286

        block = create_capacity_block(scenario["tsp"]["id"])
        award_shipment(block["id"], shipment_id)

        validate_error(
            api_client.pack_shipment(
                shipment_id, pack_payload(TOO_EARLY_PACK), tsp_headers
            ),
            ApiErrorId.ERR_PACK_BEFORE_SPREAD.value,
            422,
        )
        packed = validate_success(
            api_client.pack_shipment(
                shipment_id, pack_payload(EARLIEST_PACK), tsp_headers
            ),
            200,
        )
        assert packed["movement_status"] == "PACKED"
        assert packed["pack_date"] == EARLIEST_PACK

        validate_error(
            api_client.record_actual_weight(
                shipment_id,
                record_actual_weight_payload(
                    6200, 1500, WEIGH_DATE, scale_certified=False
                ),
                tsp_headers,
            ),
            ApiErrorId.ERR_UNCERTIFIED_SCALE.value,
            422,
        )
        unweighed = read_shipment(shipment_id)
        assert unweighed["actual_gross_lbs"] is None
        assert unweighed["weight_recon_status"] == "ESTIMATED"

        weighed = validate_success(
            api_client.record_actual_weight(
                shipment_id, record_actual_weight_payload(6200, 1500, WEIGH_DATE), tsp_headers
            ),
            200,
        )
        assert weighed["net_actual_lbs"] == 4700
        assert weighed["billable_basis"] == "ACTUAL"

        validate_error(
            api_client.pickup_shipment(
                shipment_id, pickup_payload(DAY_PAST_SPREAD), tsp_headers
            ),
            ApiErrorId.ERR_PICKUP_OUTSIDE_SPREAD.value,
            422,
        )
        picked_up = validate_success(
            api_client.pickup_shipment(
                shipment_id, pickup_payload(SPREAD_END), tsp_headers
            ),
            200,
        )
        assert picked_up["required_delivery_by"] == "2026-08-30T00:00:00Z"

        validate_error(
            api_client.deliver_shipment(
                shipment_id, deliver_payload("2026-08-23T00:00:00Z"), tsp_headers
            ),
            ApiErrorId.ERR_DELIVERY_BEFORE_PICKUP.value,
            422,
        )
        delivered = validate_success(
            api_client.deliver_shipment(
                shipment_id, deliver_payload(SPREAD_END), tsp_headers
            ),
            200,
        )
        assert delivered["movement_status"] == "DELIVERED"
        assert delivered["delivery_date"] == SPREAD_END


class TestUniquenessAndLimits:
    """Three uniqueness rules and the three-amendment ceiling."""

    def test_a_repeat_identifier_is_refused_on_all_three_records(self):
        """The same DoD number, the same order number and a second entitlement are each refused.

        "the member's ten-digit `dod_id` (exactly ten digits, and unique across all members —
        a repeat registration is refused with `ERR_DUPLICATE_DOD_ID`)"

        "the printed `order_number` (4 to 32 characters, unique across all orders — a
        collision yields `ERR_DUPLICATE_ORDER_NUMBER`)"

        "Completion also requires that no `EntitlementAuthorization` yet exists for these
        orders; a second session attempting to create a second entitlement for the same orders
        is refused with `ERR_DUPLICATE_ENTITLEMENT`."

        Design: Corner/validations/duplicate_dod_id_and_order_number_and_entitlement_are_rejected
        """
        member, order, second_session = _member_with_one_completed_session()

        validate_error(
            api_client.create_service_member(
                create_service_member_payload(
                    rank_code="E5", branch="NAVY", dependents_count=0, spouse_present=False
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_DUPLICATE_DOD_ID.value,
            409,
        )

        validate_error(
            api_client.create_order(
                create_order_payload(
                    member["id"], move_type="PCS_OCONUS", distance_miles=900
                ),
                COUNSELOR,
            ),
            ApiErrorId.ERR_DUPLICATE_ORDER_NUMBER.value,
            409,
        )
        _, order_meta = validate_paginated(
            api_client.list_service_member_orders(member["id"], COUNSELOR)
        )
        assert order_meta["total_count"] == 1

        validate_error(
            api_client.complete_counseling_session(
                second_session["id"], complete_counseling_payload(), COUNSELOR
            ),
            ApiErrorId.ERR_DUPLICATE_ENTITLEMENT.value,
            409,
        )
        assert (
            get_success_data(
                api_client.get_counseling_session(second_session["id"], COUNSELOR)
            )["status"]
            == "SCHEDULED"
        )
        _, entitlement_meta = validate_paginated(
            api_client.list_order_entitlements(order["id"], COUNSELOR)
        )
        assert entitlement_meta["total_count"] == 1

    def test_the_fourth_amendment_hits_the_ceiling(self):
        """Three revisions are accepted and the fourth leaves the orders exactly as they were.

        "At most three amendments are accepted per set of orders: the fourth attempt, made
        when `amendment_count` has already reached 3, is refused with
        `ERR_ORDER_AMENDMENT_LIMIT`. On acceptance, `amendment_count` increases by one and
        `last_amendment_reason` is set to the supplied reason"

        Design: Corner/validations/fourth_order_amendment_returns_amendment_limit
        """
        set_clock()
        member = create_service_member()
        order = create_order(member["id"])

        first = amend_order(
            order["id"],
            amendment_reason="FIRST REVISION",
            report_no_later_than_date_override="2026-10-05T00:00:00Z",
        )
        assert first["status"] == "AMENDED"
        assert first["amendment_count"] == 1

        amend_order(
            order["id"],
            amendment_reason="SECOND REVISION",
            report_no_later_than_date_override="2026-10-10T00:00:00Z",
        )
        third = amend_order(
            order["id"],
            amendment_reason="THIRD REVISION",
            report_no_later_than_date_override="2026-10-15T00:00:00Z",
        )
        assert third["amendment_count"] == 3
        assert third["status"] == "AMENDED"

        validate_error(
            _amend(order["id"], "FOURTH REVISION", "2026-10-20T00:00:00Z"),
            ApiErrorId.ERR_ORDER_AMENDMENT_LIMIT.value,
            409,
        )

        stored = get_success_data(api_client.get_order(order["id"], COUNSELOR))
        assert stored["amendment_count"] == 3
        assert stored["status"] == "AMENDED"
        assert stored["last_amendment_reason"] == "THIRD REVISION"


class TestAllowanceAndWindowCeilings:
    """The professional-gear allowance ceiling and the two loss-and-damage windows."""

    def test_verified_gear_may_not_break_the_member_allowance(self):
        """2,500 verified pounds are refused against a 2,000 pound allowance; 2,000 land.

        "both require that the verified figure not exceed `claimed_weight_lbs` and that the
        running total of verified weight for that shipment and that owner, this declaration
        included, stay within the owner's allowance — 2,000 pounds for `MEMBER`, and the
        entitlement's `pro_gear_spouse_allowance_lbs` for `SPOUSE`, which is 500 pounds only
        where a spouse is present on a with-dependents move and 0 otherwise. A breach of
        either bound is refused with `ERR_PRO_GEAR_CAP_EXCEEDED`."

        "when it is greater than zero but strictly less than the claimed figure, it moves
        `SUBMITTED → PARTIALLY_VERIFIED`"

        Design: Corner/validations/pro_gear_verified_weight_above_member_cap_returns_cap_exceeded
        """
        scenario = setup_surveyed_shipment()
        entitlement = read_entitlement(scenario["entitlement"]["id"])
        assert entitlement["pro_gear_member_allowance_lbs"] == 2000
        assert entitlement["pro_gear_spouse_allowance_lbs"] == 500

        declaration = declare_pro_gear(
            scenario,
            owner="MEMBER",
            claimed_weight_lbs=2500,
            documentation_type="ITEMIZED_INVENTORY",
        )

        validate_error(
            api_client.verify_pro_gear_declaration(
                declaration["id"], verify_pro_gear_payload(2500), COUNSELOR
            ),
            ApiErrorId.ERR_PRO_GEAR_CAP_EXCEEDED.value,
            422,
        )
        refused = _declaration(declaration["id"])
        assert refused["status"] == "SUBMITTED"
        assert refused["verified_weight_lbs"] == 0
        assert read_shipment(scenario["shipment"]["id"])["billable_weight_lbs"] == 5286

        verified = verify_pro_gear(declaration["id"], 2000)
        assert verified["status"] == "PARTIALLY_VERIFIED"
        assert verified["verified_weight_lbs"] == 2000
        assert verified["verified_by_user_id"] == COUNSELOR_USER_ID

        shipment = read_shipment(scenario["shipment"]["id"])
        assert shipment["pro_gear_excluded_lbs"] == 2000
        assert shipment["billable_weight_lbs"] == 3286

        ledger = read_entitlement(scenario["entitlement"]["id"])
        assert ledger["charged_billable_weight_lbs"] == 3286
        assert ledger["pro_gear_excluded_total_lbs"] == 2000

    def test_the_notice_and_filing_windows_both_close(self):
        """Notice given 193 days after delivery is refused, and filing two years later too.

        "The notice date must fall no later than 180 days — roughly six months — after the
        shipment's `delivery_date`; later notice is refused with
        `ERR_LOSS_NOTICE_WINDOW_EXPIRED`."

        "the logical clock must be no later than 730 days — two years — after the shipment's
        `delivery_date`, a later filing being refused with
        `ERR_CLAIM_FILING_WINDOW_EXPIRED`"

        Design: Corner/validations/claim_notice_and_filing_windows_are_enforced
        """
        scenario = setup_delivered_shipment(
            weigh_date=WEIGH_DATE, actual_pickup_date=WEIGH_DATE
        )
        shipment_id = scenario["shipment"]["id"]
        assert scenario["shipment"]["delivery_date"] == "2026-08-20T00:00:00Z"
        set_clock(FILING_CLOCK)

        validate_error(
            api_client.create_claim(
                shipment_id, create_claim_payload(LATE_NOTICE), COUNSELOR
            ),
            ApiErrorId.ERR_LOSS_NOTICE_WINDOW_EXPIRED.value,
            422,
        )
        _, empty = _shipment_claims(shipment_id)
        assert empty["total_count"] == 0

        claim = validate_success(
            api_client.create_claim(
                shipment_id, create_claim_payload(GOOD_NOTICE), COUNSELOR
            ),
            201,
        )
        assert claim["status"] == "DRAFT"
        assert claim["filed_date"] is None
        assert claim["filing_window_days"] is None
        assert claim["settlement_basis"] == "UNDETERMINED"

        get_success_data(
            api_client.create_claim_item(
                claim["id"],
                create_claim_item_payload(
                    1800.00, category="FURNITURE", age_years=6.0
                ),
                COUNSELOR,
            )
        )

        set_clock(FAR_FUTURE_CLOCK)
        validate_error(
            api_client.submit_claim(
                claim["id"], {"filing_note": "VERY LATE FILING"}, COUNSELOR
            ),
            ApiErrorId.ERR_CLAIM_FILING_WINDOW_EXPIRED.value,
            422,
        )

        stored = get_success_data(api_client.get_claim(claim["id"], COUNSELOR))
        assert stored["status"] == "DRAFT"
        assert stored["filed_date"] is None
        assert stored["settlement_basis"] == "UNDETERMINED"
        assert stored["item_count"] == 1
        assert stored["claimed_total_usd"] == pytest.approx(1800.00, abs=0.01)
