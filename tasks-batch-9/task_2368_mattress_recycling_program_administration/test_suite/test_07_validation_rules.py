"""Quantitative and uniqueness gates: page bounds, duplicate periods, quantities
weighed against the record they must not exceed, and the fiscal exactness rules."""

import pytest

from test_helpers import (
    TEST_USERS,
    adjudicate_claim,
    attach_claim,
    complete_take_back,
    confirm_pickup,
    create_active_rate,
    create_ca_program,
    create_enrolled_site,
    create_hauler,
    create_pickup_order_payload,
    create_registrant,
    create_remittance,
    create_site,
    create_take_back,
    create_wa_program,
    file_remittance,
    make_registrant_headers,
    make_site_operator_headers,
    open_audit,
    pay_remittance,
    read_program,
    set_clock,
    setup_delivered_order,
    setup_draft_remittance,
    setup_filed_remittance,
    setup_logistics_chain,
    setup_paid_remittance,
    setup_scheduled_order,
    submit_volume_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

UNKNOWN_SITE_ID = "00000000-0000-4000-8000-0000000009f1"


def test_a_page_size_outside_the_accepted_bounds_is_refused(api):
    """PRD §2.3: "`limit` caps the number of records returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted value
    is 100. `offset` skips a number of leading records and defaults to 0; its
    minimum accepted value is 0. A `limit` below 1 or above 100, or a negative
    `offset`, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/pagination_limit_above_maximum_rejected
    """
    program = create_ca_program(api)

    over_maximum = api.list_fee_rate_schedules(
        ADMIN, params={"state_program_id": program["id"], "limit": 101}
    )
    below_minimum = api.list_fee_rate_schedules(
        ADMIN, params={"state_program_id": program["id"], "limit": 0}
    )
    at_maximum = api.list_fee_rate_schedules(
        ADMIN, params={"state_program_id": program["id"], "limit": 100, "offset": 0}
    )

    validate_error(over_maximum, "ERR_INVALID_PAGINATION", 400)
    validate_error(below_minimum, "ERR_INVALID_PAGINATION", 400)
    schedules, meta = validate_paginated(at_maximum)
    assert schedules == []
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 0


def test_a_second_original_filing_for_the_same_quarter_is_refused(api):
    """PRD §3.3: "Only one *original* filing may exist per registrant, program and
    quarter: a second attempt where no amendment parent is involved is rejected with
    `ERR_DUPLICATE_REMITTANCE_PERIOD`."

    Design: Corner/validations/duplicate_original_remittance_period_rejected
    """
    chain = setup_draft_remittance(api)

    duplicate = api.create_sales_remittance(
        {
            "registrant_id": chain["registrant_id"],
            "state_program_id": chain["program_id"],
            "period_code": "2026Q2",
            "units_sold_mattress": 10,
            "units_sold_foundation": 0,
        },
        chain["registrant_headers"],
    )
    next_quarter = api.create_sales_remittance(
        {
            "registrant_id": chain["registrant_id"],
            "state_program_id": chain["program_id"],
            "period_code": "2026Q3",
            "units_sold_mattress": 10,
            "units_sold_foundation": 0,
        },
        chain["registrant_headers"],
    )

    validate_error(duplicate, "ERR_DUPLICATE_REMITTANCE_PERIOD", 409)
    validate_success(next_quarter, 201)
    filings, meta = validate_paginated(
        api.list_sales_remittances(
            chain["registrant_headers"], params={"registrant_id": chain["registrant_id"]}
        )
    )
    assert meta["total_count"] == 2
    stored = validate_success(
        api.get_sales_remittance(chain["remittance_id"], chain["registrant_headers"])
    )
    assert stored["units_sold_mattress"] == 500
    assert {row["period_code"] for row in filings} == {"2026Q2", "2026Q3"}


def test_a_second_monthly_report_for_the_same_site_and_month_is_refused(api):
    """PRD §3.5: "Only one report may exist per site and month; a duplicate is
    refused with `ERR_DUPLICATE_VOLUME_PERIOD`."

    Design: Corner/validations/duplicate_volume_report_month_rejected
    """
    program = create_wa_program(api)
    first_site = create_enrolled_site(api, program["id"])
    second_site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Olympic Dropoff",
        site_type="PERMANENT_DROPOFF",
    )
    submit_volume_report(
        api,
        first_site["id"],
        period_month="2026-08",
        units_mattress=320,
        units_foundation=190,
    )

    duplicate = api.create_volume_report(
        first_site["id"],
        {"period_month": "2026-08", "units_mattress": 40, "units_foundation": 10},
        make_site_operator_headers(first_site["id"]),
    )
    other_site_same_month = api.create_volume_report(
        second_site["id"],
        {"period_month": "2026-08", "units_mattress": 40, "units_foundation": 10},
        make_site_operator_headers(second_site["id"]),
    )

    validate_error(duplicate, "ERR_DUPLICATE_VOLUME_PERIOD", 409)
    validate_success(other_site_same_month, 201)
    _, meta = validate_paginated(
        api.list_volume_reports(first_site["id"], make_site_operator_headers(first_site["id"]))
    )
    assert meta["total_count"] == 1


def test_claims_may_exhaust_a_sales_line_but_never_over_claim_it(api):
    """PRD §3.4: "Claims cannot over-claim a line: for a given unit class, the total
    `units` across this remittance's `PENDING` and `SUBSTANTIATED` claims may not
    exceed that class's reported units sold, and a claim that would breach that
    ceiling is refused with `ERR_EXEMPT_UNITS_EXCEED_SALES`."

    Design: Corner/validations/aggregate_exempt_units_above_reported_sales_rejected
    """
    program = create_ca_program(api)
    registrant = create_registrant(api)
    registrant_headers = make_registrant_headers(registrant["id"])
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=300,
        units_sold_foundation=0,
    )
    attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="OUT_OF_STATE_SHIPMENT",
        unit_class="MATTRESS",
        units=200,
        documentation_reference="BOL-2026-0501",
    )

    over_ceiling = api.create_exemption_claim(
        remittance["id"],
        {"claim_type": "EXEMPT_SALE", "unit_class": "MATTRESS", "units": 150},
        registrant_headers,
    )
    exactly_to_ceiling = api.create_exemption_claim(
        remittance["id"],
        {"claim_type": "EXEMPT_SALE", "unit_class": "MATTRESS", "units": 100},
        registrant_headers,
    )

    validate_error(over_ceiling, "ERR_EXEMPT_UNITS_EXCEED_SALES", 422)
    validate_success(exactly_to_ceiling, 201)
    _, meta = validate_paginated(
        api.list_exemption_claims(remittance["id"], registrant_headers)
    )
    assert meta["total_count"] == 2, (
        "two hundred plus one hundred units exactly exhausts the three hundred "
        "mattress units reported on the filing"
    )


def test_a_manifest_larger_than_the_stock_on_hand_is_refused(api):
    """PRD §3.6: "The manifested quantity must not exceed the site's
    `units_on_hand`, or the dispatch is refused with `ERR_INSUFFICIENT_SITE_UNITS`."

    Design: Corner/validations/pickup_manifest_above_units_on_hand_rejected
    """
    chain = setup_logistics_chain(api)
    site_headers = make_site_operator_headers(chain["site_id"])

    one_unit_too_many = api.create_pickup_order(
        create_pickup_order_payload(
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=chain["hauler_id"],
            units_manifested=511,
        ),
        site_headers,
    )
    whole_stock = api.create_pickup_order(
        create_pickup_order_payload(
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=chain["hauler_id"],
            units_manifested=510,
        ),
        site_headers,
    )

    validate_error(one_unit_too_many, "ERR_INSUFFICIENT_SITE_UNITS", 422)
    validate_success(whole_stock, 201)
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 0
    assert site["units_in_transit"] == 510
    hauler = validate_success(api.get_hauler(chain["hauler_id"], ADMIN))
    assert hauler["active_route_count"] == 1


def test_a_named_hauler_that_does_not_serve_the_region_is_refused(api):
    """PRD §3.6: "An explicitly supplied hauler must belong to the site's program
    and its `service_regions` must contain the site's `region_code`, or the dispatch
    is refused with `ERR_HAULER_REGION_MISMATCH`."

    Design: Corner/validations/explicitly_named_hauler_outside_site_region_rejected
    """
    chain = setup_logistics_chain(api)
    southern_hauler = create_hauler(
        api,
        chain["program_id"],
        company_name="Columbia South Hauling",
        service_regions=["SOUTH"],
        per_unit_rate_cents=400,
        per_km_rate_cents=150,
    )

    response = api.create_pickup_order(
        create_pickup_order_payload(
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=southern_hauler["id"],
            units_manifested=240,
        ),
        make_site_operator_headers(chain["site_id"]),
    )

    validate_error(response, "ERR_HAULER_REGION_MISMATCH", 422)
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 510
    assert site["units_in_transit"] == 0
    stored_hauler = validate_success(api.get_hauler(southern_hauler["id"], ADMIN))
    assert stored_hauler["active_route_count"] == 0


def test_delivering_more_units_than_the_manifest_carried_is_refused(api):
    """PRD §3.6: "The hauler then reports delivery, moving `PICKED_UP → DELIVERED`
    and supplying `units_delivered`, which may not exceed the order's
    `units_manifested`; an over-report is refused with `ERR_UNITS_EXCEED_MANIFEST`."

    Design: Corner/validations/units_delivered_above_manifest_rejected
    """
    chain = setup_scheduled_order(api)
    confirm_pickup(api, chain["order_id"], chain["hauler_id"])

    over_manifest = api.deliver_pickup_order(
        chain["order_id"], {"units_delivered": 241}, chain["hauler_headers"]
    )
    validate_error(over_manifest, "ERR_UNITS_EXCEED_MANIFEST", 422)
    still_in_transit = validate_success(api.get_pickup_order(chain["order_id"], ADMIN))
    assert still_in_transit["fulfillment_status"] == "PICKED_UP"

    delivered = validate_success(
        api.deliver_pickup_order(
            chain["order_id"], {"units_delivered": 240}, chain["hauler_headers"]
        )
    )

    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["settlement_status"] == "ESTIMATED"
    assert delivered["estimated_payment_cents"] == 121_750, (
        "the estimate bills the 240 manifested units at 450 cents, the 62.5 km at "
        "180 cents per km and one 2,500-cent stop fee"
    )
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_at_recycler_count"] == 240
    assert site["units_written_off_count"] == 0


def test_counting_more_contaminated_units_than_were_delivered_is_refused(api):
    """PRD §3.7: "The request supplies `contaminated_unit_count`, the number of units
    found wet, soiled or otherwise unprocessable, which must be zero or greater and
    may not exceed the order's `units_delivered` — an over-count is refused with
    `ERR_UNITS_EXCEED_MANIFEST` — and an `infestation_finding` of `NONE`, `BED_BUG`
    or `MOLD`."

    Design: Corner/validations/contaminated_count_above_units_delivered_rejected
    """
    chain = setup_delivered_order(api, units_delivered=240)

    over_count = api.create_load_inspection(
        chain["order_id"],
        {"contaminated_unit_count": 241, "infestation_finding": "NONE"},
        chain["recycler_headers"],
    )
    validate_error(over_count, "ERR_UNITS_EXCEED_MANIFEST", 422)

    inspection = validate_success(
        api.create_load_inspection(
            chain["order_id"],
            {"contaminated_unit_count": 240, "infestation_finding": "NONE"},
            chain["recycler_headers"],
        ),
        201,
    )

    assert inspection["contamination_pct"] == pytest.approx(100.00)
    assert inspection["disposition"] == "FULL_REJECT"
    assert inspection["rejection_reason"] == "CONTAMINATION_THRESHOLD"
    assert inspection["units_accepted"] == 0
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["contamination_strike_count"] == 1
    assert site["units_written_off_count"] == 240
    order = validate_success(api.get_pickup_order(chain["order_id"], ADMIN))
    assert order["settlement_status"] == "DISPUTED"


def test_an_offer_below_the_new_units_delivered_is_refused_outright(api):
    """PRD §3.8: "`units_takeback_offered`, the units the retailer offered to remove,
    which must be zero or greater and must be at least as large as
    `units_delivered_new`. An offer below the obligation is refused outright with
    `ERR_TAKEBACK_OFFER_BELOW_DELIVERY`."

    Design: Corner/validations/takeback_offer_below_units_delivered_new_rejected
    """
    program = create_ca_program(api)
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    registrant = create_registrant(api)
    registrant_headers = make_registrant_headers(registrant["id"])

    short_offer = api.create_take_back_delivery(
        {
            "registrant_id": registrant["id"],
            "collection_site_id": site["id"],
            "delivery_reference": "DEL-2001",
            "units_delivered_new": 10,
            "units_takeback_offered": 9,
        },
        registrant_headers,
    )
    matching_offer = api.create_take_back_delivery(
        {
            "registrant_id": registrant["id"],
            "collection_site_id": site["id"],
            "delivery_reference": "DEL-2002",
            "units_delivered_new": 10,
            "units_takeback_offered": 10,
        },
        registrant_headers,
    )

    validate_error(short_offer, "ERR_TAKEBACK_OFFER_BELOW_DELIVERY", 422)
    scheduled = validate_success(matching_offer, 201)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["units_takeback_collected"] is None
    assert scheduled["breach_units"] == 0
    assert scheduled["breach_penalty_cents"] == 0
    _, meta = validate_paginated(
        api.list_take_back_deliveries(
            registrant_headers, params={"registrant_id": registrant["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_collecting_more_units_than_were_offered_is_refused(api):
    """PRD §3.8: "Reporting the actual removal supplies `units_takeback_collected`.
    That figure may not exceed `units_takeback_offered`, or the report is refused
    with `ERR_TAKEBACK_COLLECTED_ABOVE_OFFER`, and the receiving collection site must
    be `ENROLLED`, or the report is refused with `ERR_SITE_NOT_ENROLLED`."

    Design: Corner/validations/takeback_collected_above_offer_rejected
    """
    program = create_ca_program(api)
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    registrant = create_registrant(api)
    delivery = create_take_back(
        api,
        registrant["id"],
        site["id"],
        delivery_reference="DEL-2003",
        units_delivered_new=10,
        units_takeback_offered=10,
    )

    response = api.complete_takeback(
        delivery["id"],
        {"units_takeback_collected": 11},
        make_registrant_headers(registrant["id"]),
    )

    validate_error(response, "ERR_TAKEBACK_COLLECTED_ABOVE_OFFER", 422)
    stored = validate_success(
        api.get_take_back_delivery(delivery["id"], make_registrant_headers(registrant["id"]))
    )
    assert stored["status"] == "SCHEDULED"
    assert stored["units_takeback_collected"] is None
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 0
    assert stored_site["units_reported_total"] == 0


def test_a_rate_one_cent_under_the_band_is_refused_and_the_edge_passes(api):
    """PRD §3.2: "The proposed `fee_cents_per_unit` must be at least `band_low_cents`
    and at most `band_high_cents` as snapshotted on this proposal; a value outside
    that inclusive range is rejected with `ERR_RATE_OUTSIDE_RECOMMENDED_BAND`."

    PRD §3.1: "`band_low_cents` is eighty percent of the recommended rate rounded
    *down* to a whole cent, and `band_high_cents` is one hundred and twenty percent
    of the recommended rate rounded *up* to a whole cent."

    Design: Corner/validations/rate_proposal_outside_recommended_band_rejected
    """
    program = create_ca_program(api)

    below_band = api.create_fee_rate_schedule(
        {
            "state_program_id": program["id"],
            "unit_class": "MATTRESS",
            "fee_cents_per_unit": 859,
            "effective_from": "2026-01-01T00:00:00Z",
            "expected_state_program_version": program["version"],
        },
        ADMIN,
    )
    validate_error(below_band, "ERR_RATE_OUTSIDE_RECOMMENDED_BAND", 422)
    assert read_program(api, program["id"])["version"] == 1

    at_band_low = api.create_fee_rate_schedule(
        {
            "state_program_id": program["id"],
            "unit_class": "MATTRESS",
            "fee_cents_per_unit": 860,
            "effective_from": "2026-01-01T00:00:00Z",
            "expected_state_program_version": program["version"],
        },
        ADMIN,
    )

    proposal = validate_success(at_band_low, 201)
    assert proposal["status"] == "PROPOSED"
    assert proposal["band_low_cents"] == 860
    assert proposal["band_high_cents"] == 1290
    assert read_program(api, program["id"])["version"] == 2


def test_a_refund_one_cent_above_the_net_cash_held_is_refused(api):
    """PRD §3.3: "The amount must also not exceed the net cash the program is
    actually holding against this remittance — `fee_paid_cents` less
    `fee_refunded_cents` — or it is refused with `ERR_REFUND_EXCEEDS_PAYMENT`."

    Design: Corner/validations/refund_above_net_payment_rejected
    """
    chain = setup_paid_remittance(api)

    over_refund = api.refund_sales_remittance(
        chain["remittance_id"],
        {"amount_cents": 550_001, "reason": "OVERSTATED_UNITS"},
        ADMIN,
    )
    validate_error(over_refund, "ERR_REFUND_EXCEEDS_PAYMENT", 422)
    assert (
        validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))["status"]
        == "PAID"
    )

    refunded = validate_success(
        api.refund_sales_remittance(
            chain["remittance_id"],
            {"amount_cents": 550_000, "reason": "OVERSTATED_UNITS"},
            ADMIN,
        )
    )

    assert refunded["status"] == "REFUNDED"
    assert refunded["fee_refunded_cents"] == 550_000
    program = read_program(api, chain["program_id"])
    assert program["fee_collected_cents"] == 0
    assert program["reserve_balance_cents"] == 5_000_000


def test_an_unadjudicated_claim_blocks_the_audit_from_closing(api):
    """PRD §3.4: "It additionally requires that no exemption claim of this remittance
    is still `PENDING`; an unadjudicated claim blocks closure with
    `ERR_PENDING_EXEMPTION_CLAIMS`."

    Design: Corner/validations/audit_close_with_a_pending_exemption_claim_rejected
    """
    program = create_ca_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    claim = attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="OUT_OF_STATE_SHIPMENT",
        unit_class="MATTRESS",
        units=50,
        documentation_reference="BOL-2026-0630",
    )
    file_remittance(api, remittance["id"], registrant["id"])
    pay_remittance(api, remittance["id"], registrant["id"], 495_000)
    open_audit(api, remittance["id"])

    blocked = api.close_remittance_audit(remittance["id"], AUDITOR)
    validate_error(blocked, "ERR_PENDING_EXEMPTION_CLAIMS", 409)
    assert (
        validate_success(api.get_sales_remittance(remittance["id"], AUDITOR))["status"]
        == "UNDER_AUDIT"
    )
    adjudicate_claim(api, claim["id"], "SUBSTANTIATE")

    closed = validate_success(api.close_remittance_audit(remittance["id"], AUDITOR))

    assert closed["status"] == "AUDIT_CLOSED"
    assert closed["fee_reconciled_cents"] == 495_000
    assert closed["balance_due_cents"] == 0
    registrant_after = validate_success(api.get_registrant(registrant["id"], ADMIN))
    assert registrant_after["compliance_status"] == "COMPLIANT"


def test_payment_must_match_the_self_assessed_fee_to_the_cent(api):
    """PRD §3.3: "The request carries `amount_cents`, which must equal
    `fee_self_assessed_cents` precisely; anything else is rejected with
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/payment_amount_mismatch_rejected_then_exact_amount_passes
    """
    chain = setup_filed_remittance(api)

    one_cent_short = api.pay_sales_remittance(
        chain["remittance_id"], {"amount_cents": 549_999}, chain["registrant_headers"]
    )
    validate_error(one_cent_short, "ERR_PAYMENT_AMOUNT_MISMATCH", 422)
    unpaid = validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))
    assert unpaid["status"] == "FILED"
    assert unpaid["fee_paid_cents"] == 0

    paid = validate_success(
        api.pay_sales_remittance(
            chain["remittance_id"], {"amount_cents": 550_000}, chain["registrant_headers"]
        )
    )

    assert paid["status"] == "PAID"
    assert paid["fee_paid_cents"] == 550_000
    assert paid["early_filing_qualified"] is False
    assert paid["filed_at"].startswith("2026-08-01T00:00:00")
    assert read_program(api, chain["program_id"])["fee_collected_cents"] == 550_000


def test_filing_inside_the_twenty_day_window_earns_the_discount(api):
    """PRD §3.3: "First, the filing is early when `filed_at` falls at or before
    twenty days after `period_end`; `early_filing_qualified` records that
    determination. The discount percentage is one and a half percent when the filing
    is early and the discount has not been forfeited, and zero otherwise."

    Design: Corner/validations/early_filing_inside_twenty_day_window_earns_the_discount
    """
    program = create_ca_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q3",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    set_clock(api, "2026-10-05T00:00:00Z")

    filed = file_remittance(api, remittance["id"], registrant["id"])

    assert filed["early_filing_qualified"] is True
    assert filed["filed_at"].startswith("2026-10-05T00:00:00")
    assert filed["fee_self_assessed_cents"] == 541_750, (
        "the 550,000-cent gross line loses a 8,250-cent discount, one and a half "
        "percent rounded half up to whole cents"
    )

    paid = pay_remittance(api, remittance["id"], registrant["id"], 541_750)

    assert paid["status"] == "PAID"
    program_after = read_program(api, program["id"])
    assert program_after["fee_collected_cents"] == 541_750
    assert program_after["reserve_balance_cents"] == 5_541_750


def test_a_suspended_registrant_is_locked_out_of_filing(api):
    """PRD §3.3: "A registrant whose `compliance_status` is `SUSPENDED` may not file
    at all, and is refused with `ERR_REGISTRANT_SUSPENDED`."

    PRD §3.8: "`breach_units` is set to the obligation less the collected count, and
    `breach_penalty_cents` is set to 2,500 cents — twenty-five dollars — for each
    breached unit."

    Design: Corner/validations/suspended_registrant_cannot_file_a_new_remittance
    """
    program = create_ca_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    delivery = create_take_back(
        api,
        registrant["id"],
        site["id"],
        delivery_reference="DEL-3001",
        units_delivered_new=400,
        units_takeback_offered=400,
    )

    breached = complete_take_back(api, delivery["id"], registrant["id"], 0)

    assert breached["status"] == "OBLIGATION_BREACHED"
    assert breached["breach_units"] == 400
    assert breached["breach_penalty_cents"] == 1_000_000
    suspended = validate_success(api.get_registrant(registrant["id"], ADMIN))
    assert suspended["delinquent_balance_cents"] == 1_000_000
    assert suspended["compliance_status"] == "SUSPENDED"

    response = api.file_sales_remittance(
        remittance["id"], make_registrant_headers(registrant["id"])
    )

    validate_error(response, "ERR_REGISTRANT_SUSPENDED", 409)
    stored = validate_success(api.get_sales_remittance(remittance["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["filed_at"] is None


def test_a_role_denial_answers_before_the_site_lookup_runs(api):
    """PRD §2.10: "When more than one rule would reject a request, the response
    reports the rule that comes first in the following ladder. The ordering is
    normative: a later check must never mask an earlier one, and a request that
    violates several rules is diagnosed by the earliest violated rule only."

    PRD §2.10: "2. Role authorization for the operation (`ERR_UNAUTHORIZED`)."

    Design: Corner/validations/unauthorized_role_on_unknown_site_returns_403_not_404
    """
    program = create_ca_program(api)
    site = create_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    registrant = create_registrant(api)

    wrong_role = api.enroll_collection_site(
        UNKNOWN_SITE_ID, make_registrant_headers(registrant["id"])
    )
    right_role = api.enroll_collection_site(UNKNOWN_SITE_ID, ADMIN)

    validate_error(wrong_role, "ERR_UNAUTHORIZED", 403)
    validate_error(right_role, "ERR_COLLECTION_SITE_NOT_FOUND", 404)
    stored = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored["enrollment_status"] == "APPLIED"
