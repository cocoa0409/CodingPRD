"""Delivery close, allowed-loss boundary, variance cascade, and samples."""
import pytest

from test_helpers import (
    SO_1,
    TEST_USERS,
    check_in,
    close_delivery,
    close_meter,
    confirm_placards,
    create_active_agreement,
    create_driver,
    create_product,
    create_rack,
    create_rule,
    create_shipment_payload,
    create_spill_plan_payload,
    get_retain_sample,
    make_customer_rep_headers,
    make_driver_headers,
    make_safety_officer_headers,
    record_weights,
    set_clock,
    setup_delivered_shipment,
    setup_delivering_shipment,
    start_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_variance_exactly_at_allowance_accepted(api):
    """PRD 3.5: "The comparison decides everything, and equality accepts: a variance
    less than or equal to `allowed_loss_gal` closes the ticket `CLOSED_ACCEPTED` and
    moves the shipment `DELIVERING → DELIVERED`". (500-mile route: allowed = 5.0 +
    0.02*500 = 15.0; variance exactly 15.0.)

    Design: Difficulty/boundary_precision_check/variance_exactly_at_allowance_accepted
    """
    scenario = setup_delivering_shipment(route_miles=500)
    ticket = close_delivery(scenario, delivered_observed_gal=985, delivered_temp_F=60)
    assert ticket["allowed_loss_gal"] == pytest.approx(15.0, abs=0.001)
    assert ticket["variance_gallons"] == pytest.approx(15.0, abs=0.001)
    assert ticket["status"] == "CLOSED_ACCEPTED"
    assert scenario["ship"]["status"] == "DELIVERED"


def test_variance_just_above_allowance_reviews(api):
    """PRD 3.5: "a variance strictly greater closes it `CLOSED_VARIANCE` and moves the
    shipment `DELIVERING → VARIANCE_REVIEW`". (Same 500-mile route, allowance 15.0;
    delivered 984.9 leaves variance 15.1 > 15.0.)

    Design: Difficulty/boundary_precision_check/variance_exactly_at_allowance_accepted
    """
    scenario = setup_delivering_shipment(route_miles=500)
    ticket = close_delivery(scenario, delivered_observed_gal=984.9, delivered_temp_F=60)
    assert ticket["allowed_loss_gal"] == pytest.approx(15.0, abs=0.001)
    assert ticket["variance_gallons"] == pytest.approx(15.1, abs=0.001)
    assert ticket["status"] == "CLOSED_VARIANCE"
    assert scenario["ship"]["status"] == "VARIANCE_REVIEW"


def test_allowed_loss_cap_binds_with_nested_min(api):
    """PRD 3.5: "The allowed in-transit loss is then the smaller of two quantities: a
    flat 50.0-gallon cap, or a base allowance of 5.0 gallons plus 0.02 gallons per mile
    of the shipment's `route_miles`". (3000 miles: uncapped 65.0, cap binds at 50.0;
    60.0-gal shortage goes to VARIANCE_REVIEW.)

    Design: Difficulty/combinatorial_formula/allowed_loss_cap_binds_with_nested_min
    """
    scenario = setup_delivering_shipment(ordered_gallons=1000, route_miles=3000)
    ticket = close_delivery(scenario, delivered_observed_gal=940, delivered_temp_F=60)
    assert ticket["allowed_loss_gal"] == pytest.approx(50.0, abs=0.001)
    assert ticket["variance_gallons"] == pytest.approx(60.0, abs=0.001)
    assert ticket["status"] == "CLOSED_VARIANCE"
    assert scenario["ship"]["status"] == "VARIANCE_REVIEW"


def test_allowed_loss_below_cap_uses_mileage_formula(api):
    """PRD 3.5: "The allowed in-transit loss is then the smaller of two quantities: a
    flat 50.0-gallon cap, or a base allowance of 5.0 gallons plus 0.02 gallons per mile
    of the shipment's `route_miles`". (100 miles: 5.0 + 2.0 = 7.0, below the cap.)

    Design: Difficulty/combinatorial_formula/allowed_loss_cap_binds_with_nested_min
    """
    scenario = setup_delivering_shipment(route_miles=100)
    ticket = close_delivery(scenario, delivered_observed_gal=995, delivered_temp_F=60)
    assert ticket["allowed_loss_gal"] == pytest.approx(7.0, abs=0.001)
    assert ticket["variance_gallons"] == pytest.approx(5.0, abs=0.001)
    assert ticket["status"] == "CLOSED_ACCEPTED"
    assert scenario["ship"]["status"] == "DELIVERED"


def test_variance_close_cascades_to_agreement_flag(api):
    """PRD 3.5: "If a DedicatedTrailerAgreement matching the shipment's
    (`customer_id`, `trailer_id`) is `ACTIVE`, its `flagged_shipment_count` increments
    by one; the moment that counter reaches 2, the agreement itself suspends
    `ACTIVE → SUSPENDED`." (First variance: counter 1, still ACTIVE.)

    Design: Difficulty/transitive_cascade/variance_close_cascades_to_agreement_flag
    """
    dedicated = create_active_agreement()
    prod = create_product()
    create_rule()  # PETROLEUM -> PETROLEUM, no wash required
    drv = create_driver()
    rack = create_rack()
    rep = make_customer_rep_headers(dedicated["cust"]["id"])
    plan = validate_success(
        api.create_spill_plan(create_spill_plan_payload(dedicated["cust"]["id"], prod["id"]), rep), 201)
    validate_success(api.submit_spill_plan(plan["id"], rep), 200)
    validate_success(api.approve_spill_plan(plan["id"], make_safety_officer_headers(SO_1)), 200)

    ship = validate_success(api.create_shipment(
        create_shipment_payload(dedicated["cust"]["id"], prod["id"], ordered_gallons=1000,
                                route_miles=500), DISP), 201)
    set_clock("2026-08-02T10:30:00Z")
    validate_success(api.plan_shipment(ship["id"], {
        "trailer_id": dedicated["trl"]["id"], "driver_id": drv["id"], "rack_id": rack["id"],
        "rack_window_start": "2026-08-02T10:00:00Z", "rack_window_end": "2026-08-02T12:00:00Z"},
        DISP), 200)
    local = {"ship": ship, "trl": dedicated["trl"], "drv": drv, "rack": rack}
    check_in(local)
    close_meter(local, meter_end_gal=1000, observed_temp_F=60)
    record_weights(local)
    confirm_placards(local)
    validate_success(api.depart_shipment(ship["id"], DISP), 200)
    start_delivery(local)
    ticket = validate_success(api.close_delivery_ticket(
        local["delivery_ticket"]["id"],
        {"delivered_observed_gal": 940, "delivered_temp_F": 60, "retain_sample_ml": 250},
        make_driver_headers(drv["id"])), 200)
    assert ticket["status"] == "CLOSED_VARIANCE"  # hop 1

    ship_after = validate_success(api.get_shipment(ship["id"], DISP), 200)
    assert ship_after["status"] == "VARIANCE_REVIEW"  # hop 2

    agr_after = validate_success(api.get_agreement(dedicated["agr"]["id"], ADMIN), 200)
    assert agr_after["flagged_shipment_count"] == 1  # hop 3
    assert agr_after["status"] == "ACTIVE"


def test_accepted_close_does_not_flag_agreement(api):
    """PRD 3.5: "If a DedicatedTrailerAgreement matching the shipment's
    (`customer_id`, `trailer_id`) is `ACTIVE`, its `flagged_shipment_count` increments
    by one; the moment that counter reaches 2, the agreement itself suspends
    `ACTIVE → SUSPENDED`. The accepted branch performs no such increment."

    Design: Difficulty/transitive_cascade/variance_close_cascades_to_agreement_flag
    """
    dedicated = create_active_agreement()
    prod = create_product()
    create_rule()  # PETROLEUM -> PETROLEUM, no wash required
    drv = create_driver()
    rack = create_rack()
    rep = make_customer_rep_headers(dedicated["cust"]["id"])
    plan = validate_success(
        api.create_spill_plan(create_spill_plan_payload(dedicated["cust"]["id"], prod["id"]), rep), 201)
    validate_success(api.submit_spill_plan(plan["id"], rep), 200)
    validate_success(api.approve_spill_plan(plan["id"], make_safety_officer_headers(SO_1)), 200)

    ship = validate_success(api.create_shipment(
        create_shipment_payload(dedicated["cust"]["id"], prod["id"], ordered_gallons=1000,
                                route_miles=500), DISP), 201)
    set_clock("2026-08-02T10:30:00Z")
    validate_success(api.plan_shipment(ship["id"], {
        "trailer_id": dedicated["trl"]["id"], "driver_id": drv["id"], "rack_id": rack["id"],
        "rack_window_start": "2026-08-02T10:00:00Z", "rack_window_end": "2026-08-02T12:00:00Z"},
        DISP), 200)
    local = {"ship": ship, "trl": dedicated["trl"], "drv": drv, "rack": rack}
    check_in(local)
    close_meter(local, meter_end_gal=1000, observed_temp_F=60)
    record_weights(local)
    confirm_placards(local)
    validate_success(api.depart_shipment(ship["id"], DISP), 200)
    start_delivery(local)
    ticket = validate_success(api.close_delivery_ticket(
        local["delivery_ticket"]["id"],
        {"delivered_observed_gal": 1000, "delivered_temp_F": 60, "retain_sample_ml": 250},
        make_driver_headers(drv["id"])), 200)
    assert ticket["status"] == "CLOSED_ACCEPTED"

    agr_after = validate_success(api.get_agreement(dedicated["agr"]["id"], ADMIN), 200)
    assert agr_after["flagged_shipment_count"] == 0
    assert agr_after["status"] == "ACTIVE"


def test_delivery_ticket_double_close_rejected(api):
    """PRD 3.5: "Closing the delivery ticket is likewise reserved to the assigned
    driver, and the ticket must still be `OPEN` (`ERR_DELIVERY_TICKET_NOT_OPEN`
    otherwise)". A successful close creates exactly one RetainSample, and the failed
    second close creates none.

    Design: Corner/errors/delivery_ticket_double_close_rejected
    """
    scenario = setup_delivered_shipment()
    res = api.close_delivery_ticket(
        scenario["delivery_ticket"]["id"],
        {"delivered_observed_gal": 1000, "delivered_temp_F": 60, "retain_sample_ml": 250},
        make_driver_headers(scenario["drv"]["id"]))
    validate_error(res, "ERR_DELIVERY_TICKET_NOT_OPEN", expected_status=409)

    _samples, meta = validate_paginated(
        api.list_retain_samples(DISP, params={"shipment_id": scenario["ship"]["id"]}))
    assert meta["total_count"] == 1


def test_sample_dispose_retention_gate(api):
    """PRD 3.5: "A sample may be disposed by a `SafetyOfficer` only while `RETAINED`
    (else `ERR_SAMPLE_NOT_RETAINED`) and only once the logical clock is strictly later
    than `retain_until` (disposing earlier fails with `ERR_SAMPLE_STILL_IN_RETENTION`)",
    with "`retain_until` computed as `taken_at` plus 90 days" (taken at
    2026-08-02T10:30:00Z, so retention ends 2026-10-31T10:30:00Z).

    Design: Corner/validations/sample_dispose_retention_gate
    """
    scenario = setup_delivered_shipment()
    sample = get_retain_sample(scenario)

    res = api.dispose_retain_sample(sample["id"], make_safety_officer_headers(SO_1))
    validate_error(res, "ERR_SAMPLE_STILL_IN_RETENTION", expected_status=422)

    set_clock("2026-11-01T00:00:00Z")
    disposed = validate_success(
        api.dispose_retain_sample(sample["id"], make_safety_officer_headers(SO_1)), 200)
    assert disposed["status"] == "DISPOSED"


def test_sample_double_dispose_rejected(api):
    """PRD 3.5: "A sample may be disposed by a `SafetyOfficer` only while `RETAINED`
    (else `ERR_SAMPLE_NOT_RETAINED`) and only once the logical clock is strictly later
    than `retain_until` (disposing earlier fails with `ERR_SAMPLE_STILL_IN_RETENTION`);
    disposal moves it `RETAINED → DISPOSED`, and `DISPOSED` is terminal."

    Design: Corner/errors/sample_double_dispose_rejected
    """
    scenario = setup_delivered_shipment()
    sample = get_retain_sample(scenario)
    set_clock("2026-11-01T00:00:00Z")
    validate_success(api.dispose_retain_sample(sample["id"], make_safety_officer_headers(SO_1)), 200)

    res = api.dispose_retain_sample(sample["id"], make_safety_officer_headers(SO_1))
    validate_error(res, "ERR_SAMPLE_NOT_RETAINED", expected_status=409)
