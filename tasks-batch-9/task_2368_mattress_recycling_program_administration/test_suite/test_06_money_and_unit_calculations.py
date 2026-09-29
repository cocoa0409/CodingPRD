"""Money and unit arithmetic: rate lookup, site credits, hauler selection and
route payments, diversion rates, the recommendation tiers and custody totals."""

import pytest

from test_helpers import (
    TEST_USERS,
    accept_volume_report,
    assert_custody_buckets,
    confirm_pickup,
    create_active_rate,
    create_approved_rate,
    create_ca_program,
    create_certified_recycler,
    create_enrolled_site,
    create_hauler,
    create_program,
    create_registrant,
    create_remittance,
    create_verified_commodity_output,
    deliver_order,
    dispatch_order,
    finalize_settlement,
    inspect_load,
    make_registrant_headers,
    make_site_operator_headers,
    open_audit,
    pay_remittance,
    pickup_and_deliver,
    propose_rate,
    read_fee_adequacy,
    read_program,
    setup_filed_remittance,
    setup_inspected_order,
    setup_logistics_chain,
    setup_paid_remittance,
    submit_commodity_output,
    submit_volume_report,
    suspend_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN_2 = TEST_USERS["admin_2_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_a_rate_left_unactivated_cannot_price_a_filing(api):
    """PRD §3.2: "Whenever a fee rate is needed for a program, a unit class and a
    particular date, the candidate set is every schedule of that program and unit
    class whose `status` is `ACTIVE` or `SUPERSEDED`, whose `effective_from` is at or
    before the date in question, and whose `effective_to` is either null or strictly
    later than that date. Schedules in `PROPOSED` or `APPROVED` are never the rate of
    record. If the candidate set is empty, the lookup fails with
    `ERR_NO_APPLICABLE_RATE`."

    Design: Corner/calculations/applicable_rate_lookup_ignores_proposed_and_approved_schedules
    """
    program = create_ca_program(api)
    schedule = create_approved_rate(
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

    response = api.file_sales_remittance(
        remittance["id"], make_registrant_headers(registrant["id"])
    )

    validate_error(response, "ERR_NO_APPLICABLE_RATE", 422)
    stored = validate_success(api.get_sales_remittance(remittance["id"], ADMIN))
    assert stored["status"] == "DRAFT"
    assert stored["fee_self_assessed_cents"] == 0
    assert stored["filed_at"] is None
    assert (
        validate_success(api.get_fee_rate_schedule(schedule["id"], ADMIN))["status"]
        == "APPROVED"
    )


def test_credited_units_exactly_at_the_threshold_earn_the_five_percent_bonus(api):
    """PRD §3.5: "A volume bonus of five percent applies when the credited units
    reach or exceed the program's `volume_bonus_threshold_units`, and no bonus applies
    below that threshold. The credit in cents is the credited units multiplied by the
    program's `site_credit_cents_per_unit`, multiplied by one plus the bonus
    percentage, with the round-half-up applied once to that bonus-multiplied product."

    Design: Corner/calculations/site_volume_credit_bonus_applies_at_the_exact_threshold
    """
    program = create_program(
        api, state_code="WA", program_name="Washington Mattress Stewardship Program"
    )
    site = create_enrolled_site(api, program["id"])
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=320, units_foundation=180
    )

    accepted = accept_volume_report(api, report["id"])

    assert accepted["credited_units"] == 500
    assert accepted["credit_cents"] == 160_125, (
        "five hundred credited units reach the bonus threshold, so the credit is "
        "500 times 305 cents lifted by five percent, not the unbonused 152,500"
    )
    stored_program = read_program(api, program["id"])
    assert stored_program["site_credit_paid_cents"] == 160_125
    assert stored_program["reserve_balance_cents"] == 4_839_875
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 500
    assert stored_site["units_reported_total"] == 500


def test_a_nil_volume_month_is_accepted_and_credits_nothing(api):
    """PRD §3.5: "A report of zero units is entirely legal: it credits zero cents,
    earns no bonus, and still reaches `ACCEPTED`."

    Design: Corner/calculations/site_volume_credit_zero_unit_report_is_accepted_with_zero_credit
    """
    program = create_program(
        api, state_code="WA", program_name="Washington Mattress Stewardship Program"
    )
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Olympic Dropoff",
        site_type="PERMANENT_DROPOFF",
    )
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=0, units_foundation=0
    )

    accepted = accept_volume_report(api, report["id"])

    assert accepted["status"] == "ACCEPTED"
    assert accepted["credited_units"] == 0
    assert accepted["credit_cents"] == 0
    stored_program = read_program(api, program["id"])
    assert stored_program["site_credit_paid_cents"] == 0
    assert stored_program["reserve_balance_cents"] == 5_000_000
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_reported_total"] == 0


def test_auto_selection_prefers_the_cheaper_and_then_the_idler_hauler(api):
    """PRD §3.6: "Otherwise the pool is ranked by `per_unit_rate_cents` ascending —
    cheapest per unit wins — then by `active_route_count` ascending as the first
    tie-break, favouring the less loaded hauler, then by `created_at` ascending as the
    final tie-break, favouring the longer-standing contract. A hauler's `id` is never
    a ranking input. The first hauler in that ranking is chosen."

    Design: Corner/calculations/hauler_selection_ranks_by_rate_then_by_active_route_count
    """
    program = create_program(
        api, state_code="WA", program_name="Washington Mattress Stewardship Program"
    )
    site = create_enrolled_site(api, program["id"])
    recycler = create_certified_recycler(api, program["id"])
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=320, units_foundation=190
    )
    accept_volume_report(api, report["id"])
    busy = create_hauler(
        api, program["id"], company_name="Cheap Busy Hauling", per_unit_rate_cents=450
    )
    expensive = create_hauler(
        api,
        program["id"],
        company_name="Expensive Express Hauling",
        per_unit_rate_cents=500,
        per_km_rate_cents=100,
    )
    idle = create_hauler(
        api, program["id"], company_name="Cheap Idle Hauling", per_unit_rate_cents=450
    )
    dispatch_order(
        api,
        site["id"],
        recycler["id"],
        hauler_id=busy["id"],
        units_manifested=100,
        route_distance_km=40.0,
        pickup_window_start="2026-08-05T06:00:00Z",
        pickup_window_end="2026-08-05T07:00:00Z",
    )

    order = validate_success(
        api.create_pickup_order(
            {
                "collection_site_id": site["id"],
                "recycler_id": recycler["id"],
                "units_manifested": 100,
                "route_distance_km": 40.0,
                "pickup_window_start": "2026-08-05T12:00:00Z",
                "pickup_window_end": "2026-08-05T13:00:00Z",
            },
            make_site_operator_headers(site["id"]),
        ),
        201,
    )

    assert order["hauler_id"] == idle["id"], (
        "the 500-cent hauler loses on rate and the busy 450-cent hauler loses on "
        "active route count"
    )
    assert order["hauler_auto_selected"] is True
    assert validate_success(api.get_hauler(idle["id"], ADMIN))["active_route_count"] == 1
    assert validate_success(api.get_hauler(busy["id"], ADMIN))["active_route_count"] == 1
    assert validate_success(api.get_hauler(expensive["id"], ADMIN))["active_route_count"] == 0
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 310
    assert stored_site["units_in_transit"] == 200


def test_a_site_no_hauler_serves_cannot_be_dispatched_automatically(api):
    """PRD §3.6: "**Automatic hauler selection** considers only haulers whose
    `state_program_id` matches the source site's program, whose `service_regions`
    contains the site's `region_code`, and whose count of buffer-conflicting routes
    against the requested window is strictly below their own `max_concurrent_routes`.
    If that pool is empty the dispatch fails with `ERR_NO_ELIGIBLE_HAULER`."

    Design: Corner/calculations/hauler_selection_empty_eligible_pool_returns_no_eligible_hauler
    """
    program = create_program(
        api, state_code="WA", program_name="Washington Mattress Stewardship Program"
    )
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Vancouver South Dropoff",
        site_type="PERMANENT_DROPOFF",
        region_code="SOUTH",
    )
    recycler = create_certified_recycler(api, program["id"])
    hauler = create_hauler(api, program["id"], service_regions=["NORTH"])
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=320, units_foundation=190
    )
    accept_volume_report(api, report["id"])

    response = api.create_pickup_order(
        {
            "collection_site_id": site["id"],
            "recycler_id": recycler["id"],
            "units_manifested": 100,
            "route_distance_km": 40.0,
            "pickup_window_start": "2026-08-05T09:00:00Z",
            "pickup_window_end": "2026-08-05T10:00:00Z",
        },
        make_site_operator_headers(site["id"]),
    )

    validate_error(response, "ERR_NO_ELIGIBLE_HAULER", 422)
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 510
    assert stored_site["units_in_transit"] == 0
    assert validate_success(api.get_hauler(hauler["id"], ADMIN))["active_route_count"] == 0
    _, meta = validate_paginated(
        api.list_pickup_orders(ADMIN, params={"collection_site_id": site["id"]})
    )
    assert meta["total_count"] == 0


def test_the_contractual_cap_is_applied_before_the_handling_deduction(api):
    """PRD §3.6: "The ordering here is deliberate and normative: the contractual cap
    is applied *before* the minimum floor and *before* the rejection deduction, so a
    route that hits its cap still pays the full handling deduction out of the capped
    amount rather than out of the raw one."

    Design: Corner/calculations/hauler_route_payment_cap_precedes_floor_and_rejection_deduction
    """
    chain = setup_logistics_chain(api)
    second_report = submit_volume_report(
        api, chain["site_id"], period_month="2026-09", units_mattress=400, units_foundation=300
    )
    accept_volume_report(api, second_report["id"])
    order = dispatch_order(
        api,
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        units_manifested=600,
        route_distance_km=62.5,
        pickup_window_start="2026-08-05T09:00:00Z",
        pickup_window_end="2026-08-05T13:00:00Z",
    )
    delivered = pickup_and_deliver(api, order["id"], chain["hauler_id"], 600)
    assert delivered["estimated_payment_cents"] == 200_000, (
        "the raw estimate of 283,750 cents exceeds the 200,000-cent contractual cap"
    )
    inspect_load(api, order["id"], chain["recycler_id"], 30)

    settled = finalize_settlement(api, order["id"])

    assert settled["final_payment_cents"] == 191_000, (
        "the capped 200,000 cents less the 9,000-cent handling deduction on thirty "
        "rejected units"
    )
    assert settled["fulfillment_status"] == "CLOSED"
    assert settled["settlement_status"] == "FINALIZED"
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))["total_paid_cents"] == 191_000
    program = read_program(api, chain["program_id"])
    assert program["hauler_payment_paid_cents"] == 191_000
    assert program["site_credit_paid_cents"] == 387_503
    assert program["reserve_balance_cents"] == 4_421_497


def test_a_one_unit_route_is_lifted_to_the_minimum_payment(api):
    """PRD §3.6: "The raw payment is then capped at the hauler's
    `max_route_payment_cents` — the lesser of the two is kept — and the capped figure
    is then floored at a minimum route payment of 4,000 cents, the greater of the two
    being kept."

    Design: Corner/calculations/hauler_route_payment_minimum_floor_lifts_a_tiny_route
    """
    chain = setup_logistics_chain(api)
    order = dispatch_order(
        api,
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        units_manifested=1,
        route_distance_km=1.0,
        pickup_window_start="2026-08-05T09:00:00Z",
        pickup_window_end="2026-08-05T09:30:00Z",
    )
    delivered = pickup_and_deliver(api, order["id"], chain["hauler_id"], 1)
    assert delivered["estimated_payment_cents"] == 4_000, (
        "the arithmetic value of 3,130 cents is lifted to the 4,000-cent minimum"
    )
    inspection = inspect_load(api, order["id"], chain["recycler_id"], 0)

    settled = finalize_settlement(api, order["id"])

    assert settled["final_payment_cents"] == 4_000
    assert inspection["contamination_pct"] == pytest.approx(0.00)
    assert inspection["disposition"] == "PARTIAL_ACCEPT"
    assert inspection["units_accepted"] == 1
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_recycled_count"] == 1
    assert site["units_written_off_count"] == 0
    assert read_program(api, chain["program_id"])["hauler_payment_paid_cents"] == 4_000


def diversion_chain(api, third_record_weight_kg):
    """A suspended facility that has processed 228 units and holds three verified
    commodity-output records plus one still-unverified record."""
    chain = setup_inspected_order(api, contaminated_unit_count=12, units_delivered=240)
    recycler_id = chain["recycler_id"]
    create_verified_commodity_output(
        api, recycler_id, commodity="FOAM", output_weight_kg=2600.5, source_period_month="2026-08"
    )
    create_verified_commodity_output(
        api, recycler_id, commodity="STEEL", output_weight_kg=1300.25, source_period_month="2026-08"
    )
    create_verified_commodity_output(
        api,
        recycler_id,
        commodity="FIBER",
        output_weight_kg=third_record_weight_kg,
        source_period_month="2026-08",
    )
    chain["unverified"] = submit_commodity_output(
        api, recycler_id, commodity="WOOD", output_weight_kg=1000.0, source_period_month="2026-08"
    )
    chain["recycler"] = suspend_certification(api, recycler_id, "PERIODIC_OUTPUT_REVIEW")
    return chain


def test_only_verified_output_weight_counts_toward_the_diversion_rate(api):
    """PRD §3.7: "The basis in kilograms is the facility's `units_processed_count` —
    its accepted units — multiplied by an assumed average unit weight of 28.0
    kilograms. When that basis is zero the diversion rate is 0.00; otherwise it is the
    verified output weight divided by the basis, multiplied by one hundred, rounded
    half up to two decimal places. Only `VERIFIED` records contribute weight;
    `SUBMITTED` weight is excluded entirely."

    Design: Corner/calculations/diversion_rate_counts_verified_output_records_only
    """
    chain = diversion_chain(api, 900.0)

    recertified = validate_success(api.recertify_recycler(chain["recycler_id"], ADMIN))

    assert recertified["certification_status"] == "CERTIFIED"
    assert recertified["certified_at"] == "2026-08-01T00:00:00Z"
    assert recertified["units_processed_count"] == 228
    assert recertified["units_rejected_count"] == 12
    assert recertified["verified_output_weight_kg"] == pytest.approx(4800.75), (
        "the still-unverified 1000.0 kg record contributes nothing"
    )
    assert recertified["diversion_rate_pct"] == pytest.approx(75.20)
    records, _ = validate_paginated(
        api.list_commodity_output_records(chain["recycler_id"], chain["recycler_headers"])
    )
    unverified = next(row for row in records if row["id"] == chain["unverified"]["id"])
    assert unverified["record_status"] == "SUBMITTED"
    assert unverified["verified_by_user_id"] is None


def test_a_diversion_rate_a_hundredth_below_the_gate_blocks_recertification(api):
    """PRD §3.7: "Recertification moves it `SUSPENDED → CERTIFIED` and stamps
    `certified_at` afresh, but only once the facility's verified diversion rate has
    recovered: `diversion_rate_pct` must be at least 75.00, and a facility below that
    is refused with `ERR_DIVERSION_RATE_BELOW_MINIMUM`."

    Design: Corner/calculations/diversion_rate_below_minimum_blocks_recertification
    """
    chain = diversion_chain(api, 879.25)

    response = api.recertify_recycler(chain["recycler_id"], ADMIN)

    validate_error(response, "ERR_DIVERSION_RATE_BELOW_MINIMUM", 422)
    stored = validate_success(api.get_recycler(chain["recycler_id"], ADMIN))
    assert stored["verified_output_weight_kg"] == pytest.approx(4780.0)
    assert stored["diversion_rate_pct"] == pytest.approx(74.87)
    assert stored["certification_status"] == "SUSPENDED"
    assert stored["certified_at"] is None


def test_a_low_base_rate_takes_the_six_percent_surcharge_tier(api):
    """PRD §3.1: "Fifth, an administrative surcharge percentage is selected from that
    base rate: six percent when the base rate is 800 cents or less, four percent when
    the base rate is from 801 through 1600 cents, and two percent when the base rate
    is 1601 cents or more."

    Design: Corner/calculations/fee_recommendation_low_tier_applies_six_percent_surcharge
    """
    program = create_program(
        api,
        state_code="OR",
        program_name="Oregon Mattress Stewardship Program",
        forecast_annual_cost_cents=24_000_000,
        forecast_annual_units=60_000,
        forecast_other_revenue_cents=0,
        reserve_target_months=3,
        reserve_opening_cents=6_000_000,
    )

    adequacy = read_fee_adequacy(api, program["id"])

    assert adequacy["reserve_target_cents"] == 6_000_000
    assert adequacy["reserve_gap_cents"] == 0
    assert adequacy["reserve_balance_cents"] == 6_000_000
    assert adequacy["base_rate_cents"] == 400
    assert adequacy["admin_surcharge_pct"] == pytest.approx(0.06)
    assert adequacy["recommended_rate_cents"] == 424
    assert adequacy["band_low_cents"] == 339
    assert adequacy["band_high_cents"] == 509
    assert adequacy["reserve_coverage_months"] == pytest.approx(3.00)
    assert read_program(api, program["id"])["recommended_rate_cents"] == 424


def test_coverage_just_below_three_months_lets_an_increase_through(api):
    """PRD §3.2: "If an `ACTIVE` schedule already exists for the same program and unit
    class and this schedule's `fee_cents_per_unit` is greater than that active
    schedule's `fee_cents_per_unit` — that is, if the proposal is a rate *increase* —
    then the program's `reserve_coverage_months` must be strictly less than three
    months."

    Design: Corner/calculations/reserve_coverage_just_below_ceiling_permits_a_rate_increase
    """
    program = create_program(
        api,
        state_code="NV",
        program_name="Nevada Mattress Recycling Program",
        reserve_opening_cents=14_900_000,
    )
    predecessor = create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1000,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    successor = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-09-01T00:00:00Z",
    )

    approved = validate_success(api.approve_fee_rate_schedule(successor["id"], ADMIN_2))

    assert approved["status"] == "APPROVED"
    assert successor["band_low_cents"] == 791
    assert successor["band_high_cents"] == 1187
    stored_program = read_program(api, program["id"])
    assert stored_program["reserve_coverage_months"] == pytest.approx(2.98)
    assert stored_program["recommended_rate_cents"] == 989
    assert (
        validate_success(api.get_fee_rate_schedule(predecessor["id"], ADMIN))["status"]
        == "ACTIVE"
    )


def test_the_reconciled_fee_is_stamped_only_when_the_audit_closes(api):
    """PRD §3.4: "Closure stamps `fee_reconciled_cents` using the **audit-reconciled
    variant** of the fee assessment."

    PRD §3.4: "Closure then stamps `balance_due_cents` as the reconciled fee less the
    net cash actually received, that is less `fee_paid_cents` minus
    `fee_refunded_cents`, with the result floored at zero: an over-collected
    remittance closes with a balance due of zero rather than a negative one."

    Design: Corner/calculations/reconciled_fee_variant_is_not_computed_before_audit_close
    """
    chain = setup_paid_remittance(api)
    open_audit(api, chain["remittance_id"])

    under_audit = validate_success(api.get_sales_remittance(chain["remittance_id"], AUDITOR))

    assert under_audit["status"] == "UNDER_AUDIT"
    assert under_audit["fee_self_assessed_cents"] == 550_000
    assert under_audit["fee_reconciled_cents"] is None
    assert under_audit["early_filing_qualified"] is False

    closed = validate_success(api.close_remittance_audit(chain["remittance_id"], AUDITOR))

    assert closed["fee_reconciled_cents"] == 550_000
    assert closed["balance_due_cents"] == 0
    assert closed["status"] == "AUDIT_CLOSED"
    registrant = validate_success(api.get_registrant(chain["registrant_id"], ADMIN))
    assert registrant["compliance_status"] == "COMPLIANT"
    assert registrant["delinquent_balance_cents"] == 0


def test_a_filed_but_unpaid_remittance_leaves_the_reserve_alone(api):
    """PRD §2.7: "Fees collected (`fee_collected_cents`) is the sum of
    `fee_paid_cents` across the program's remittances minus the sum of
    `fee_refunded_cents` across the same set, counting only remittances whose `status`
    is one of `PAID`, `UNDER_AUDIT`, `AMENDMENT_REQUIRED`, `AUDIT_CLOSED` or
    `REFUNDED`; remittances still in `DRAFT` or `FILED` contribute nothing."

    Design: Corner/calculations/program_ledger_counts_paid_remittances_only
    """
    chain = setup_filed_remittance(api)

    while_filed = read_program(api, chain["program_id"])

    assert while_filed["fee_collected_cents"] == 0
    assert while_filed["reserve_balance_cents"] == 5_000_000
    assert while_filed["receivable_cents"] == 0
    assert while_filed["reserve_coverage_months"] == pytest.approx(1.00)
    assert chain["remittance"]["fee_self_assessed_cents"] == 550_000

    pay_remittance(api, chain["remittance_id"], chain["registrant_id"], 550_000)

    after_payment = read_program(api, chain["program_id"])
    assert after_payment["fee_collected_cents"] == 550_000
    assert after_payment["reserve_balance_cents"] == 5_550_000
    assert after_payment["reserve_coverage_months"] == pytest.approx(1.11)
    assert after_payment["recommended_rate_cents"] == 1070


def test_road_shrinkage_is_written_off_while_the_estimate_bills_the_manifest(api):
    """PRD §3.6: "Delivery settles the custody arithmetic for the leg: the full
    manifested quantity leaves the site's `units_in_transit`, the delivered quantity
    lands in `units_at_recycler_count`, and any shortfall between manifest and
    delivery — shrinkage on the road — lands in `units_written_off_count`."

    PRD §3.6: "The **route-estimate** variant, stamped at delivery into
    `estimated_payment_cents`, bills the manifest rather than the scale ticket: its
    billable units are `units_manifested`, and because nothing has been inspected yet
    its rejected units are zero, so no handling deduction applies."

    Design: Corner/calculations/custody_conservation_holds_under_manifest_shrinkage
    """
    chain = setup_logistics_chain(api)
    order = dispatch_order(
        api, chain["site_id"], chain["recycler_id"], hauler_id=chain["hauler_id"]
    )
    confirm_pickup(api, order["id"], chain["hauler_id"])

    delivered = deliver_order(api, order["id"], chain["hauler_id"], 230)

    assert delivered["units_delivered"] == 230
    assert delivered["estimated_payment_cents"] == 121_750
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert_custody_buckets(site, 270, 0, 230, 0, 10, reported_total=510)
    assert validate_success(api.get_recycler(chain["recycler_id"], ADMIN))[
        "units_received_count"
    ] == 230
