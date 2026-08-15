"""Dedicated-trailer program: enrollment, period overlap, lifecycle, settlement."""
import pytest

from test_helpers import (
    SO_1,
    TEST_USERS,
    check_in,
    close_delivery,
    close_meter,
    confirm_placards,
    create_active_agreement,
    create_agreement_payload,
    create_customer,
    create_driver,
    create_product,
    create_rack,
    create_rule,
    create_shipment_payload,
    create_spill_plan_payload,
    create_trailer,
    make_customer_rep_headers,
    make_driver_headers,
    make_safety_officer_headers,
    record_weights,
    set_clock,
    start_delivery,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_agreement_requires_program_enrollment(api):
    """PRD 3.8: "A `FleetAdmin` creates a DedicatedTrailerAgreement naming the
    `customer_id` — the customer must have `dedicated_program_enrolled` set to true,
    else `ERR_NOT_PROGRAM_ENROLLED`".

    Design: Corner/errors/agreement_requires_program_enrollment
    """
    cust = create_customer(name="Plain Co")  # not enrolled
    trl = create_trailer()
    res = api.create_agreement(create_agreement_payload(cust["id"], trl["id"]), ADMIN)
    validate_error(res, "ERR_NOT_PROGRAM_ENROLLED", expected_status=422)


def test_agreement_period_overlap_rejected(api):
    """PRD 3.8: "Two agreements on the same trailer may not overlap: if another
    agreement in `PENDING` or `ACTIVE` status has an inclusive period intersecting the
    new one — each agreement's `effective_from` falling on or before the other's
    `effective_to` — creation is rejected with `ERR_AGREEMENT_PERIOD_CONFLICT` (409)."
    (Second period starts 2026-12-31, touching the first's inclusive end.)

    Design: Corner/errors/agreement_period_overlap_rejected
    """
    cust = create_customer(name="Dedicated Co", dedicated_program_enrolled=True)
    trl = create_trailer()
    validate_success(api.create_agreement(create_agreement_payload(cust["id"], trl["id"]), ADMIN), 201)

    res = api.create_agreement(create_agreement_payload(
        cust["id"], trl["id"], committed_loads_per_month=3,
        effective_from="2026-12-31T00:00:00Z", effective_to="2027-06-30T23:59:59Z"), ADMIN)
    validate_error(res, "ERR_AGREEMENT_PERIOD_CONFLICT", expected_status=409)


def test_terminate_pending_agreement_rejected(api):
    """PRD 3.8: "Termination from either `ACTIVE` or `SUSPENDED` (else
    `ERR_AGREEMENT_INVALID_STATE`) moves the agreement to `TERMINATED`".

    Design: Corner/errors/terminate_pending_agreement_rejected
    """
    cust = create_customer(name="Dedicated Co", dedicated_program_enrolled=True)
    trl = create_trailer()
    agr = validate_success(
        api.create_agreement(create_agreement_payload(cust["id"], trl["id"]), ADMIN), 201)

    res = api.terminate_agreement(agr["id"], ADMIN)
    validate_error(res, "ERR_AGREEMENT_INVALID_STATE", expected_status=409)


def test_trailer_dedication_round_trip(api):
    """PRD 3.8: "A successful activation stamps the trailer's `dedicated_customer_id`
    with the agreement's customer" and "Termination from either `ACTIVE` or
    `SUSPENDED` (else `ERR_AGREEMENT_INVALID_STATE`) moves the agreement to
    `TERMINATED` and clears the trailer's `dedicated_customer_id` as a compensating
    release."

    Design: Difficulty/compensating_invariant/trailer_dedication_round_trip
    """
    ctx = create_active_agreement()
    cust, trl, agr = ctx["cust"], ctx["trl"], ctx["agr"]

    mid = validate_success(api.get_trailer(trl["id"], ADMIN), 200)
    assert mid["dedicated_customer_id"] == cust["id"]

    validate_success(api.terminate_agreement(agr["id"], ADMIN), 200)
    end = validate_success(api.get_trailer(trl["id"], ADMIN), 200)
    assert end["dedicated_customer_id"] is None

    _active, meta = validate_paginated(api.list_agreements(
        ADMIN, params={"trailer_id": trl["id"], "status": "ACTIVE"}))
    assert meta["total_count"] == 0


def test_trailer_already_dedicated_blocks_second_activation(api):
    """PRD 3.8: "Activation moves `PENDING → ACTIVE` (again,
    `ERR_AGREEMENT_INVALID_STATE` from elsewhere) and requires the trailer to be
    undedicated — if the trailer's `dedicated_customer_id` is already set, activation
    fails with `ERR_TRAILER_ALREADY_DEDICATED` (409)."

    Design: Difficulty/compensating_invariant/trailer_dedication_round_trip
    """
    ctx = create_active_agreement()
    trl = ctx["trl"]
    cust2 = create_customer(name="Second Co", dedicated_program_enrolled=True)
    agr2 = validate_success(api.create_agreement(create_agreement_payload(
        cust2["id"], trl["id"], committed_loads_per_month=3,
        effective_from="2027-01-01T00:00:00Z", effective_to="2027-06-30T23:59:59Z"), ADMIN), 201)

    res = api.activate_agreement(agr2["id"], ADMIN)
    validate_error(res, "ERR_TRAILER_ALREADY_DEDICATED", expected_status=409)


def test_month_close_shortfall_arithmetic(api):
    """PRD 3.8: "The compliance floor is the agreement's `committed_loads_per_month`
    multiplied by 0.8 and rounded up to a whole load. If the completed count is
    strictly below the floor, a shortfall fee is assessed: the shortfall — floor minus
    completed — times 25000 cents ($250.00) per missing load, added into
    `shortfall_fees_total_cents`, with `shortfall_events` incremented by one. A
    completed count exactly equal to the floor is compliant and draws no fee. Either
    way, `last_settled_month` is set to the settled `settlement_month`." And "The
    month must be strictly before the month containing the current logical clock and
    strictly after the `last_settled_month` when one exists — violations are
    `ERR_MONTH_NOT_CLOSABLE`." (Committed 5 -> floor 4; 0 completed -> fee 100000.)

    Design: Corner/calculations/month_close_shortfall_arithmetic
    """
    ctx = create_active_agreement()
    agr = ctx["agr"]
    set_clock("2026-09-01T00:00:00Z")

    settled = validate_success(
        api.close_agreement_month(agr["id"], {"settlement_month": "2026-08"}, ADMIN), 200)
    assert settled["shortfall_fees_total_cents"] == 100000
    assert settled["shortfall_events"] == 1
    assert settled["last_settled_month"] == "2026-08"

    res = api.close_agreement_month(agr["id"], {"settlement_month": "2026-08"}, ADMIN)
    validate_error(res, "ERR_MONTH_NOT_CLOSABLE", expected_status=422)


def _run_variance_delivery_on_dedicated(api, cust, trl, prod, drv, rack, spill_ready,
                                        route_miles=500):
    """Plan, load, depart, deliver-short on the dedicated trailer. Returns shipment."""
    ship = validate_success(api.create_shipment(
        create_shipment_payload(cust["id"], prod["id"], ordered_gallons=1000,
                                route_miles=route_miles), DISP), 201)
    validate_success(api.plan_shipment(ship["id"], {
        "trailer_id": trl["id"], "driver_id": drv["id"], "rack_id": rack["id"],
        "rack_window_start": "2026-08-02T10:00:00Z", "rack_window_end": "2026-08-02T12:00:00Z"},
        DISP), 200)
    local = {"ship": ship, "trl": trl, "drv": drv, "rack": rack}
    check_in(local)
    close_meter(local, meter_end_gal=1000, observed_temp_F=60)
    record_weights(local)
    confirm_placards(local)
    validate_success(api.depart_shipment(ship["id"], DISP), 200)
    start_delivery(local)
    close_delivery(local, delivered_observed_gal=940, delivered_temp_F=60)
    return local["ship"]


def test_agreement_suspends_on_second_variance(api):
    """PRD 3.5: "If a DedicatedTrailerAgreement matching the shipment's
    (`customer_id`, `trailer_id`) is `ACTIVE`, its `flagged_shipment_count` increments
    by one; the moment that counter reaches 2, the agreement itself suspends
    `ACTIVE → SUSPENDED`."

    Design: Corner/complexity_layers/agreement_suspends_on_second_variance
    """
    ctx = create_active_agreement()
    cust, trl, agr = ctx["cust"], ctx["trl"], ctx["agr"]
    prod = create_product()
    create_rule()  # PETROLEUM -> PETROLEUM
    drv = create_driver()
    rack = create_rack()
    rep = make_customer_rep_headers(cust["id"])
    plan = validate_success(
        api.create_spill_plan(create_spill_plan_payload(cust["id"], prod["id"]), rep), 201)
    validate_success(api.submit_spill_plan(plan["id"], rep), 200)
    validate_success(api.approve_spill_plan(plan["id"], make_safety_officer_headers(SO_1)), 200)

    set_clock("2026-08-02T10:30:00Z")
    s1 = _run_variance_delivery_on_dedicated(api, cust, trl, prod, drv, rack, True)
    mid = validate_success(api.get_agreement(agr["id"], ADMIN), 200)
    assert mid["flagged_shipment_count"] == 1
    assert mid["status"] == "ACTIVE"

    # Second variance load on the same trailer (released to AVAILABLE by the first
    # delivery close, per PRD 3.5).
    set_clock("2026-08-03T10:30:00Z")
    s2 = validate_success(api.create_shipment(
        create_shipment_payload(cust["id"], prod["id"], ordered_gallons=1000,
                                route_miles=500), DISP), 201)
    validate_success(api.plan_shipment(s2["id"], {
        "trailer_id": trl["id"], "driver_id": drv["id"], "rack_id": rack["id"],
        "rack_window_start": "2026-08-03T10:00:00Z", "rack_window_end": "2026-08-03T12:00:00Z"},
        DISP), 200)
    local2 = {"ship": s2, "trl": trl, "drv": drv, "rack": rack}
    check_in(local2, clock_iso="2026-08-03T10:30:00Z")
    close_meter(local2, meter_end_gal=1000, observed_temp_F=60)
    record_weights(local2)
    confirm_placards(local2)
    validate_success(api.depart_shipment(s2["id"], DISP), 200)
    start_delivery(local2)
    close_delivery(local2, delivered_observed_gal=940, delivered_temp_F=60)

    end = validate_success(api.get_agreement(agr["id"], ADMIN), 200)
    assert end["flagged_shipment_count"] == 2
    assert end["status"] == "SUSPENDED"
    assert local2["ship"]["status"] == "VARIANCE_REVIEW"
