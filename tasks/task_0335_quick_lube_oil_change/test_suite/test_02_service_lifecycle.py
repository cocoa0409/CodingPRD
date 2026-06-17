"""Work-order and bay state-machine guards: invalid transitions, terminal lockdown,
payment-ordering, and the service-start preconditions (technician assignment, capability
gating, bay occupancy).

Source: corner section state_machines.
"""
import pytest

from test_helpers import (
    validate_error,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    # fixtures
    setup_shop_with_catalog,
    create_retail_vehicle,
    create_direct_work_order,
    claim,
    claim_start,
    mark_ready,
    drive_to_completed,
    create_shop,
    create_package,
    create_bay,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["shop_manager_headers"]


def test_complete_from_draft_returns_invalid_state(api):
    """PRD §3.9: "A `ServiceAdvisor` completes a ready order, advancing its service status
    from `READY` to `COMPLETED`. Completion requires the order to be `READY`, else
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/complete_from_draft_returns_invalid_state
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh = create_retail_vehicle(shop["id"], vin="VININS001", plate="INS1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    res = api.complete_work_order(wo["id"], SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_success_data(api.get_work_order(wo["id"], SA))
    assert after["service_status"] == "DRAFT"


def test_cancel_completed_order_returns_invalid_state(api):
    """PRD §3.9: "An order that is already `READY`, `COMPLETED`, or `CANCELLED` cannot be
    cancelled and the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_completed_cannot_cancel
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINTRM001", plate="TRM1",
                                make="Honda", model="Fit", odometer=30000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 30000)
    completed = drive_to_completed(wo["id"], tech["id"], payment_method="CASH")
    assert completed["service_status"] == "COMPLETED"
    res = api.cancel_work_order(wo["id"], SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_success_data(api.get_work_order(wo["id"], SA))
    assert after["service_status"] == "COMPLETED"


def test_capture_before_authorize_returns_invalid_state(api):
    """PRD §3.8: "A `ServiceAdvisor` then captures the payment, advancing it from
    `AUTHORIZED` to `PAID`; capture requires the payment to be `AUTHORIZED` and the service
    status to be `READY`, and a violation of either is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/capture_before_authorize_returns_invalid_state
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINCAP001", plate="CAP1",
                                make="Honda", model="Fit", odometer=5000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 5000)
    claim_start(wo["id"], tech["id"])
    mark_ready(wo["id"], tech["id"])  # READY but payment still UNPAID
    res = api.capture_payment(wo["id"], SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_close_occupied_bay_returns_bay_occupied(api):
    """PRD §3.11: "an occupied bay cannot be closed, and the attempt is rejected with
    `ERR_BAY_OCCUPIED`."

    Design: Corner/state_machines/close_occupied_bay_returns_bay_occupied
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh = create_retail_vehicle(shop["id"], vin="VINBOC001", plate="BOC1",
                                make="Honda", model="Fit", odometer=1000)
    create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)  # bay OCCUPIED
    res = api.close_bay(bay["id"], SM)
    validate_error(res, "ERR_BAY_OCCUPIED", expected_status=409)
    after = get_success_data(api.get_bay(bay["id"], SM))
    assert after["status"] == "OCCUPIED"


def test_start_synthetic_package_with_uncertified_technician_rejected(api):
    """PRD §3.7: "when the order's package requires synthetic certification, that the bay
    is `synthetic_certified`, failing which it is rejected with `ERR_BAY_CAPABILITY_MISMATCH`,
    and that the technician is `synthetic_certified`, failing which it is rejected with
    `ERR_TECHNICIAN_CAPABILITY_MISMATCH`."

    Design: Corner/state_machines/error_technician_capability_mismatch_on_start
    """
    base = setup_shop_with_catalog(
        package_overrides={"oil_grade": "FULL_SYNTHETIC", "name": "Full Syn",
                           "base_price_cents": 9995, "included_quarts": 6, "labor_minutes": 30,
                           "interval_miles": 7500, "interval_days": 365},
        bay_overrides={"synthetic_certified": True},
        tech_overrides={"synthetic_certified": False})
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINTCM001", plate="TCM1",
                                make="BMW", model="X3", odometer=22000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 22000)
    claim(wo["id"], tech["id"])  # certified bay passes; uncertified technician fails at start
    res = api.start_work_order(wo["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_TECHNICIAN_CAPABILITY_MISMATCH", expected_status=409)


def test_start_without_technician_returns_not_assigned(api):
    """PRD §3.7: "that the order has been claimed, i.e. its `technician_id` is set, failing
    which it is rejected with `ERR_TECHNICIAN_NOT_ASSIGNED`".

    Design: Corner/state_machines/start_without_technician_returns_not_assigned
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINTNA001", plate="TNA1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    # No claim: technician_id is still null.
    res = api.start_work_order(wo["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_TECHNICIAN_NOT_ASSIGNED", expected_status=409)


def test_complete_before_payment_settled_returns_not_settled(api):
    """PRD §3.9: "Completion requires the order to be `READY`, else `ERR_INVALID_STATE`, and
    the payment to have settled — its `payment_status` must be `PAID`, else
    `ERR_PAYMENT_NOT_SETTLED`."

    Design: Corner/state_machines/complete_before_payment_settled_returns_not_settled
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINPNS001", plate="PNS1",
                                make="Honda", model="Fit", odometer=5000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 5000)
    claim_start(wo["id"], tech["id"])
    mark_ready(wo["id"], tech["id"])  # READY but never authorized/captured
    res = api.complete_work_order(wo["id"], SA)
    validate_error(res, "ERR_PAYMENT_NOT_SETTLED", expected_status=409)
