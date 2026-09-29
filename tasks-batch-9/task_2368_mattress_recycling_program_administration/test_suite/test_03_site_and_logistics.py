"""Collection-site custody, hauler routing, load inspection and route settlement."""

import pytest

from test_helpers import (
    TEST_USERS,
    accept_volume_report,
    assert_custody_buckets,
    certify_recycler,
    create_certified_recycler,
    create_enrolled_site,
    create_hauler,
    create_pickup_order_payload,
    create_program,
    create_recycler,
    create_wa_program,
    dispatch_order,
    finalize_settlement,
    inspect_load,
    make_site_operator_headers,
    pickup_and_deliver,
    read_program,
    reinstate_site,
    set_clock,
    setup_delivered_order,
    setup_logistics_chain,
    setup_quarantined_site,
    setup_site_with_contamination_strikes,
    submit_volume_report,
    suspend_site,
    validate_error,
    validate_paginated,
    validate_success,
    void_order,
)

ADMIN = TEST_USERS["admin_headers"]


def test_delivery_stamps_the_route_estimate_from_the_manifested_units(api):
    """PRD §3.6: "The **route-estimate** variant, stamped at delivery into
    `estimated_payment_cents`, bills the manifest rather than the scale ticket:
    its billable units are `units_manifested`, and because nothing has been
    inspected yet its rejected units are zero, so no handling deduction applies."

    Design: Difficulty/dual_variant_calc/hauler_route_estimate_vs_final_settlement_divergence
    """
    chain = setup_delivered_order(api, units_delivered=240)

    order = chain["order"]

    assert order["fulfillment_status"] == "DELIVERED"
    assert order["settlement_status"] == "ESTIMATED"
    assert order["units_delivered"] == 240
    assert order["estimated_payment_cents"] == 121_750
    assert order["final_payment_cents"] is None


def test_final_settlement_bills_accepted_units_and_deducts_rejected_handling(api):
    """PRD §3.7: "That variant differs from the estimate in two respects: its
    billable units are the `units_accepted` established by the inspection rather
    than the manifest, and its rejected units are the delivered units less the
    accepted units, so the 300-cents-per-unit handling deduction genuinely
    applies."

    Design: Difficulty/dual_variant_calc/hauler_route_estimate_vs_final_settlement_divergence
    """
    chain = setup_delivered_order(api, units_delivered=240)
    inspect_load(api, chain["order_id"], chain["recycler_id"], 12)

    settled = finalize_settlement(api, chain["order_id"])

    assert settled["fulfillment_status"] == "CLOSED"
    assert settled["settlement_status"] == "FINALIZED"
    assert settled["units_accepted"] == 228
    assert settled["estimated_payment_cents"] == 121_750
    assert settled["final_payment_cents"] == 112_750
    hauler = validate_success(api.get_hauler(chain["hauler_id"], ADMIN))
    assert hauler["total_paid_cents"] == 112_750
    program = read_program(api, chain["program_id"])
    assert program["hauler_payment_paid_cents"] == 112_750
    assert program["reserve_balance_cents"] == 4_723_922


def test_a_rejected_inspection_disputes_settlement_while_fulfillment_stays_delivered(api):
    """PRD §3.6: "Recording an inspection can move `settlement_status` from
    `ESTIMATED` to `DISPUTED` while `fulfillment_status` stays at `DELIVERED`;
    finalizing the settlement moves both axes in a single request."

    Design: Difficulty/non_linear_state_machine/pickup_order_fulfillment_and_settlement_axes_advance_independently
    """
    chain = setup_delivered_order(api, units_delivered=240)

    inspection = inspect_load(api, chain["order_id"], chain["recycler_id"], 13)

    assert inspection["contamination_pct"] == pytest.approx(5.42)
    assert inspection["disposition"] == "FULL_REJECT"
    assert inspection["rejection_reason"] == "CONTAMINATION_THRESHOLD"
    order = validate_success(api.get_pickup_order(chain["order_id"], ADMIN))
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["settlement_status"] == "DISPUTED"
    assert order["units_accepted"] == 0


def test_a_disputed_route_still_settles_with_the_payment_floored_at_zero(api):
    """PRD §3.7: "Note that a disputed route is still settleable — a full
    rejection reduces the payment, it does not block it."

    Design: Difficulty/non_linear_state_machine/pickup_order_fulfillment_and_settlement_axes_advance_independently
    """
    chain = setup_delivered_order(api, units_delivered=240)
    inspect_load(api, chain["order_id"], chain["recycler_id"], 13)

    settled = finalize_settlement(api, chain["order_id"])

    assert settled["fulfillment_status"] == "CLOSED"
    assert settled["settlement_status"] == "FINALIZED"
    assert settled["estimated_payment_cents"] == 121_750
    assert settled["final_payment_cents"] == 0
    hauler = validate_success(api.get_hauler(chain["hauler_id"], ADMIN))
    assert hauler["total_paid_cents"] == 0
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["contamination_strike_count"] == 1
    assert site["enrollment_status"] == "ENROLLED"
    assert site["infestation_quarantine_until"] is None


def strike_chain_with_two_open_orders(api):
    """Two rejected loads already on the record, a third delivered load awaiting
    inspection, and a fourth order still scheduled."""
    chain = setup_site_with_contamination_strikes(api, strikes=2)
    third = dispatch_order(
        api,
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        units_manifested=100,
        route_distance_km=40.0,
        pickup_window_start="2026-08-09T09:00:00Z",
        pickup_window_end="2026-08-09T11:00:00Z",
    )
    pickup_and_deliver(api, third["id"], chain["hauler_id"], 100)
    fourth = dispatch_order(
        api,
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        units_manifested=50,
        route_distance_km=40.0,
        pickup_window_start="2026-08-11T09:00:00Z",
        pickup_window_end="2026-08-11T11:00:00Z",
    )
    chain["third_order_id"] = third["id"]
    chain["fourth_order_id"] = fourth["id"]
    return chain


def test_the_third_contamination_strike_suspends_the_site_within_the_same_request(api):
    """PRD §3.7: "The third hop applies when the strike count has thereby reached
    three: the site's `enrollment_status` moves `ENROLLED → SUSPENDED` with
    `suspended_at` set from the logical clock. The threshold is evaluated after
    the second hop's increment has landed, so the third strike suspends within the
    same request that recorded it."

    Design: Difficulty/transitive_cascade/third_contamination_strike_cascades_site_suspension_to_program_and_open_orders
    """
    chain = strike_chain_with_two_open_orders(api)

    inspection = inspect_load(api, chain["third_order_id"], chain["recycler_id"], 6)

    assert inspection["contamination_pct"] == pytest.approx(6.00)
    assert inspection["disposition"] == "FULL_REJECT"
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["contamination_strike_count"] == 3
    assert site["enrollment_status"] == "SUSPENDED"
    assert site["suspended_at"] == "2026-08-01T00:00:00Z"
    assert read_program(api, chain["program_id"])["enrolled_site_count"] == 0


def test_the_suspension_cascade_cancels_open_orders_and_conserves_custody(api):
    """PRD §3.7: "The fourth hop follows from the suspension: the program's
    `enrolled_site_count` decrements by one, and every other pickup order of that
    site whose `fulfillment_status` is `SCHEDULED` or `PICKED_UP` becomes
    `CANCELLED` with `settlement_status` `VOIDED`, its manifested units returning
    from the site's `units_in_transit` to `units_on_hand`."

    Design: Difficulty/transitive_cascade/third_contamination_strike_cascades_site_suspension_to_program_and_open_orders
    """
    chain = strike_chain_with_two_open_orders(api)

    inspect_load(api, chain["third_order_id"], chain["recycler_id"], 6)

    fourth = validate_success(api.get_pickup_order(chain["fourth_order_id"], ADMIN))
    assert fourth["fulfillment_status"] == "CANCELLED"
    assert fourth["settlement_status"] == "VOIDED"
    first = validate_success(
        api.get_pickup_order(chain["strike_orders"][0]["id"], ADMIN)
    )
    assert first["fulfillment_status"] == "DELIVERED"
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert_custody_buckets(site, 210, 0, 0, 0, 300, reported_total=510)
    hauler = validate_success(api.get_hauler(chain["hauler_id"], ADMIN))
    assert hauler["active_route_count"] == 3


def quarantined_site_and_foreign_recycler(api):
    """A quarantined Washington site plus a certified recycler belonging to a
    different state program."""
    chain = setup_quarantined_site(api)
    other_program = create_program(
        api, state_code="OR", program_name="Oregon Mattress Recycling Program"
    )
    other_recycler = create_certified_recycler(
        api,
        other_program["id"],
        facility_name="Willamette Foam Recovery",
    )
    chain["other_program_id"] = other_program["id"]
    chain["other_recycler_id"] = other_recycler["id"]
    chain["dispatch_payload"] = create_pickup_order_payload(
        chain["site_id"],
        other_recycler["id"],
        hauler_id=chain["hauler_id"],
        units_manifested=100,
        route_distance_km=40.0,
        pickup_window_start="2026-08-20T09:00:00Z",
        pickup_window_end="2026-08-20T11:00:00Z",
    )
    return chain


def test_site_quarantine_is_reported_before_the_recycler_program_mismatch(api):
    """PRD §2.10: "11. Safety interlocks: site infestation quarantine
    (`ERR_SITE_QUARANTINED`), then program enforcement posture
    (`ERR_PROGRAM_POSTURE_ELEVATED`)."

    Design: Difficulty/priority_pair_validation_conflict/site_quarantine_safety_precedes_recycler_program_mismatch_referential
    """
    chain = quarantined_site_and_foreign_recycler(api)
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["infestation_quarantine_until"] == "2026-08-15T00:00:00Z"
    assert site["contamination_strike_count"] == 1
    assert site["enrollment_status"] == "ENROLLED"

    response = api.create_pickup_order(
        chain["dispatch_payload"], make_site_operator_headers(chain["site_id"])
    )

    validate_error(response, "ERR_SITE_QUARANTINED", 422)


def test_once_the_quarantine_elapses_the_program_mismatch_surfaces(api):
    """PRD §3.6: "The named recycler's `state_program_id` must equal the source
    site's `state_program_id`, or the dispatch is refused with
    `ERR_RECYCLER_PROGRAM_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/site_quarantine_safety_precedes_recycler_program_mismatch_referential
    """
    chain = quarantined_site_and_foreign_recycler(api)
    api.create_pickup_order(
        chain["dispatch_payload"], make_site_operator_headers(chain["site_id"])
    )
    set_clock(api, "2026-08-15T00:00:00Z")

    response = api.create_pickup_order(
        chain["dispatch_payload"], make_site_operator_headers(chain["site_id"])
    )

    validate_error(response, "ERR_RECYCLER_PROGRAM_MISMATCH", 422)
    orders, meta = validate_paginated(
        api.list_pickup_orders(ADMIN, params={"collection_site_id": chain["site_id"]})
    )
    assert meta["total_count"] == 1
    assert validate_success(api.get_collection_site(chain["site_id"], ADMIN))[
        "units_on_hand"
    ] == 410


def test_contamination_of_exactly_five_percent_is_a_partial_acceptance(api):
    """PRD §3.7: "The comparison is against the *rounded* two-decimal percentage
    and it is strict: exactly 5.00 percent is a partial acceptance and 5.01 percent
    is a full rejection, so twelve contaminated units out of two hundred and forty
    is accepted while thirteen out of two hundred and forty is rejected."

    Design: Difficulty/boundary_precision_check/contamination_pct_exactly_five_percent_partially_accepted
    """
    chain = setup_delivered_order(api, units_delivered=240)

    inspection = inspect_load(api, chain["order_id"], chain["recycler_id"], 12)

    assert inspection["contamination_pct"] == pytest.approx(5.00)
    assert inspection["disposition"] == "PARTIAL_ACCEPT"
    assert inspection["rejection_reason"] is None
    assert inspection["units_accepted"] == 228
    order = validate_success(api.get_pickup_order(chain["order_id"], ADMIN))
    assert order["units_accepted"] == 228
    assert order["settlement_status"] == "ESTIMATED"


def test_a_partial_acceptance_accrues_no_strike_and_moves_custody_to_recycled(api):
    """PRD §3.7: "A `PARTIAL_ACCEPT` triggers none of these four hops; its
    settlement stays at `ESTIMATED` and the site accrues no strike."

    Design: Difficulty/boundary_precision_check/contamination_pct_exactly_five_percent_partially_accepted
    """
    chain = setup_delivered_order(api, units_delivered=240)

    inspect_load(api, chain["order_id"], chain["recycler_id"], 12)

    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["contamination_strike_count"] == 0
    assert_custody_buckets(site, 270, 0, 0, 228, 12, reported_total=510)
    recycler = validate_success(api.get_recycler(chain["recycler_id"], ADMIN))
    assert recycler["units_processed_count"] == 228
    assert recycler["units_rejected_count"] == 12


def single_route_hauler_chain(api):
    """A Washington chain whose only hauler may hold one concurrent route, with one
    scheduled 09:00 to 11:00 window already on its books."""
    program = create_wa_program(api)
    site = create_enrolled_site(api, program["id"])
    hauler = create_hauler(
        api,
        program["id"],
        company_name="Single Truck Hauling",
        per_unit_rate_cents=500,
        per_km_rate_cents=200,
        max_concurrent_routes=1,
    )
    recycler = create_certified_recycler(api, program["id"])
    report = submit_volume_report(api, site["id"], period_month="2026-08")
    accept_volume_report(api, report["id"])
    first = dispatch_order(
        api,
        site["id"],
        recycler["id"],
        hauler_id=hauler["id"],
        units_manifested=100,
        route_distance_km=40.0,
        pickup_window_start="2026-08-05T09:00:00Z",
        pickup_window_end="2026-08-05T11:00:00Z",
    )
    return {
        "program_id": program["id"],
        "site_id": site["id"],
        "hauler_id": hauler["id"],
        "recycler_id": recycler["id"],
        "first_order_id": first["id"],
    }


def test_a_window_touching_the_turnaround_buffer_exhausts_hauler_capacity(api):
    """PRD §3.6: "Both ends of a pickup window are inclusive, and a symmetric
    turnaround buffer of sixty minutes is applied to the *new* window only: the
    padded start is the requested `pickup_window_start` one hour earlier and the
    padded end is the requested `pickup_window_end` one hour later."

    Design: Difficulty/resource_temporal_overlap/hauler_window_turnaround_buffer_capacity_boundary
    """
    chain = single_route_hauler_chain(api)

    response = api.create_pickup_order(
        create_pickup_order_payload(
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=chain["hauler_id"],
            units_manifested=100,
            route_distance_km=40.0,
            pickup_window_start="2026-08-05T12:00:00Z",
            pickup_window_end="2026-08-05T13:00:00Z",
        ),
        make_site_operator_headers(chain["site_id"]),
    )

    validate_error(response, "ERR_HAULER_WINDOW_CAPACITY_EXCEEDED", 409)
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))[
        "active_route_count"
    ] == 1


def test_one_minute_beyond_the_buffer_clears_the_capacity_test(api):
    """PRD §3.6: "The server then counts the resolved hauler's existing pickup
    orders whose `fulfillment_status` is `SCHEDULED`, `PICKED_UP` or `DELIVERED`
    and whose own window overlaps the padded window — meaning the padded start is
    at or before the existing window's end and the existing window's start is at or
    before the padded end."

    Design: Difficulty/resource_temporal_overlap/hauler_window_turnaround_buffer_capacity_boundary
    """
    chain = single_route_hauler_chain(api)

    response = api.create_pickup_order(
        create_pickup_order_payload(
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=chain["hauler_id"],
            units_manifested=100,
            route_distance_km=40.0,
            pickup_window_start="2026-08-05T12:01:00Z",
            pickup_window_end="2026-08-05T13:00:00Z",
        ),
        make_site_operator_headers(chain["site_id"]),
    )

    second = validate_success(response, 201)
    assert second["pickup_window_start"] == "2026-08-05T12:01:00Z"
    assert second["fulfillment_status"] == "SCHEDULED"
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))[
        "active_route_count"
    ] == 2
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 310
    assert site["units_in_transit"] == 200
    assert validate_success(api.get_pickup_order(chain["first_order_id"], ADMIN))[
        "fulfillment_status"
    ] == "SCHEDULED"


def provisional_recycler_chain(api):
    """A Washington chain whose recycler has never been certified."""
    program = create_wa_program(api)
    site = create_enrolled_site(api, program["id"])
    hauler = create_hauler(api, program["id"])
    recycler = create_recycler(
        api, program["id"], facility_name="Olympic Steel Reclaim"
    )
    report = submit_volume_report(api, site["id"], period_month="2026-08")
    accept_volume_report(api, report["id"])
    payload = create_pickup_order_payload(
        site["id"],
        recycler["id"],
        hauler_id=hauler["id"],
        units_manifested=100,
        route_distance_km=40.0,
    )
    return {
        "program_id": program["id"],
        "site_id": site["id"],
        "hauler_id": hauler["id"],
        "recycler_id": recycler["id"],
        "payload": payload,
    }


def test_dispatch_to_an_uncertified_facility_is_refused(api):
    """PRD §3.6: "The named recycler must be `CERTIFIED`, or the dispatch is
    refused with `ERR_RECYCLER_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/pickup_order_requires_certified_recycler
    """
    chain = provisional_recycler_chain(api)

    response = api.create_pickup_order(
        chain["payload"], make_site_operator_headers(chain["site_id"])
    )

    validate_error(response, "ERR_RECYCLER_NOT_CERTIFIED", 409)
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 510
    assert site["units_in_transit"] == 0


def test_the_same_dispatch_succeeds_once_the_facility_is_certified(api):
    """PRD §3.7: "Certification moves it `PROVISIONAL → CERTIFIED` and stamps
    `certified_at` from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/pickup_order_requires_certified_recycler
    """
    chain = provisional_recycler_chain(api)
    api.create_pickup_order(chain["payload"], make_site_operator_headers(chain["site_id"]))
    certify_recycler(api, chain["recycler_id"])

    response = api.create_pickup_order(
        chain["payload"], make_site_operator_headers(chain["site_id"])
    )

    order = validate_success(response, 201)
    assert order["fulfillment_status"] == "SCHEDULED"
    assert order["settlement_status"] == "UNSETTLED"
    assert order["hauler_auto_selected"] is False
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 410
    assert site["units_in_transit"] == 100
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))[
        "active_route_count"
    ] == 1


def suspended_site_with_submitted_report(api):
    """A Washington site suspended after submitting a 499-unit monthly report, one
    unit below the volume-bonus threshold."""
    program = create_wa_program(api)
    site = create_enrolled_site(
        api,
        program["id"],
        operator_name="Chinook Collection Site",
        site_type="COLLECTION_SITE",
        region_code="NORTH",
    )
    report = submit_volume_report(
        api,
        site["id"],
        period_month="2026-09",
        units_mattress=300,
        units_foundation=199,
    )
    suspend_site(api, site["id"], "Unresolved site audit findings")
    return {
        "program_id": program["id"],
        "site_id": site["id"],
        "report_id": report["id"],
    }


def test_a_report_cannot_be_accepted_while_its_site_is_suspended(api):
    """PRD §3.5: "It requires the report to be in `SUBMITTED`, refusing otherwise
    with `ERR_VOLUME_REPORT_NOT_SUBMITTED`, and it requires the owning site to
    still be `ENROLLED`, refusing otherwise with `ERR_SITE_NOT_ENROLLED` — a
    report submitted before a suspension cannot be accepted after it."

    Design: Difficulty/cross_entity_state_dependency/volume_report_acceptance_requires_enrolled_site
    """
    chain = suspended_site_with_submitted_report(api)

    response = api.accept_volume_report(chain["report_id"], ADMIN)

    validate_error(response, "ERR_SITE_NOT_ENROLLED", 409)
    reports, _ = validate_paginated(api.list_volume_reports(chain["site_id"], ADMIN))
    assert reports[0]["status"] == "SUBMITTED"
    assert reports[0]["credit_cents"] == 0
    assert read_program(api, chain["program_id"])["site_credit_paid_cents"] == 0


def test_reinstatement_lets_the_same_report_be_accepted_and_credited(api):
    """PRD §3.5: "A volume bonus of five percent applies when the credited units
    reach or exceed the program's `volume_bonus_threshold_units`, and no bonus
    applies below that threshold."

    Design: Difficulty/cross_entity_state_dependency/volume_report_acceptance_requires_enrolled_site
    """
    chain = suspended_site_with_submitted_report(api)
    api.accept_volume_report(chain["report_id"], ADMIN)
    reinstated = reinstate_site(api, chain["site_id"])
    assert reinstated["enrollment_status"] == "ENROLLED"
    assert read_program(api, chain["program_id"])["enrolled_site_count"] == 1

    accepted = validate_success(api.accept_volume_report(chain["report_id"], ADMIN))

    assert accepted["status"] == "ACCEPTED"
    assert accepted["credited_units"] == 499
    assert accepted["credit_cents"] == 152_195
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 499
    assert site["units_reported_total"] == 499
    program = read_program(api, chain["program_id"])
    assert program["site_credit_paid_cents"] == 152_195
    assert program["reserve_balance_cents"] == 4_847_805


def test_dispatch_moves_manifested_units_from_on_hand_into_transit(api):
    """PRD §2.8: "Creating a pickup order moves its manifested units from
    `units_on_hand` to `units_in_transit`."

    Design: Difficulty/compensating_invariant/dispatch_then_void_restores_site_unit_custody_buckets
    """
    chain = setup_logistics_chain(api)

    order = dispatch_order(
        api, chain["site_id"], chain["recycler_id"], hauler_id=chain["hauler_id"]
    )

    assert order["units_manifested"] == 240
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert_custody_buckets(site, 270, 240, 0, 0, 0, reported_total=510)
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))[
        "active_route_count"
    ] == 1


def test_voiding_a_scheduled_order_restores_every_custody_bucket(api):
    """PRD §3.6: "It is the exact compensating action of dispatch, and it restores
    both the site's custody buckets and the hauler's load to their pre-dispatch
    values."

    Design: Difficulty/compensating_invariant/dispatch_then_void_restores_site_unit_custody_buckets
    """
    chain = setup_logistics_chain(api)
    order = dispatch_order(
        api, chain["site_id"], chain["recycler_id"], hauler_id=chain["hauler_id"]
    )

    voided = void_order(
        api, order["id"], chain["site_id"], "Truck breakdown; load rescheduled"
    )

    assert voided["fulfillment_status"] == "CANCELLED"
    assert voided["settlement_status"] == "VOIDED"
    assert voided["estimated_payment_cents"] is None
    assert voided["final_payment_cents"] is None
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert_custody_buckets(site, 510, 0, 0, 0, 0, reported_total=510)
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))[
        "active_route_count"
    ] == 0
    assert read_program(api, chain["program_id"])["hauler_payment_paid_cents"] == 0
