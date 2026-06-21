"""Validation precedence, cross-entity state dependencies, parallel state dimensions,
resource overlap rules, OCC stale-version rejection, and invalid-transition guards.

Sources: difficulty rules priority_pair_validation_conflict, cross_entity_state_dependency,
non_linear_state_machine, resource_temporal_overlap; corner sections state_machines,
cross_cutting_complexity_layers.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    # fixtures
    set_clock,
    setup_shop_with_catalog,
    create_retail_vehicle,
    create_fleet_vehicle,
    create_fleet_account,
    create_direct_work_order,
    create_inspection_item,
    claim,
    claim_start,
    start,
    begin_inspection,
    mark_ready,
    add_line,
    cancel_work_order,
    create_shop,
    create_package,
    create_bay,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_authorize ───

def test_authorize_draft_order_state_error_beats_fiscal(api):
    """PRD §2.6: "then state-legality of the targeted transition (the 409 family such
    as `ERR_INVALID_STATE`, `ERR_BAY_NOT_OPEN`, `ERR_BAY_OCCUPIED`, `ERR_BAY_NOT_READY`,
    and `ERR_PAYMENT_NOT_SETTLED`), then the optimistic-concurrency version check (412),
    then the synthetic-capability safety checks (409), then bay and technician
    scheduling-overlap checks (409), then coupon eligibility (409), and finally the
    fleet-credit fiscal check (`ERR_FLEET_CREDIT_EXCEEDED`, 402)."
    PRD §3.8: "Authorization is permitted only while the service status is `INSPECTION` or
    `READY`, else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_authorize
    """
    set_clock()
    shop = get_success_data(api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM))
    pkg = get_success_data(api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "CONVENTIONAL", "name": "Basic",
         "base_price_cents": 6995, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM))
    fleet = get_success_data(api.create_fleet_account(
        {"shop_id": shop["id"], "company_name": "Acme", "discount_pct": 0.0,
         "credit_limit_cents": 5000}, SM))
    bay = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 1"}, SM))
    veh = get_success_data(api.create_vehicle(
        {"shop_id": shop["id"], "fleet_account_id": fleet["id"], "vin": "VINPRI001",
         "plate": "PRI1", "make": "Ford", "model": "F150", "odometer": 3000},
        {"X-User-ID": fleet["id"], "X-User-Role": "FleetManager", "Content-Type": "application/json"}))
    # Order left in DRAFT (never started): authorize must fail on the state check, not fiscal.
    wo = get_success_data(api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 3000}, SA))
    res = api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    # The fiscal check (ERR_FLEET_CREDIT_EXCEEDED) must NOT be the reported error.
    assert res.json()["data"]["error_id"] != "ERR_FLEET_CREDIT_EXCEEDED"


def test_authorize_draft_order_leaves_payment_unpaid(api):
    """PRD §3.8: "Once an order's total is meaningful, a `ServiceAdvisor` authorizes
    payment, advancing the order's payment dimension from `UNPAID` to `AUTHORIZED`.
    Authorization is permitted only while the service status is `INSPECTION` or `READY`,
    else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_authorize
    """
    set_clock()
    shop = get_success_data(api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM))
    pkg = get_success_data(api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "CONVENTIONAL", "name": "Basic",
         "base_price_cents": 6995, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM))
    fleet = get_success_data(api.create_fleet_account(
        {"shop_id": shop["id"], "company_name": "Acme", "discount_pct": 0.0,
         "credit_limit_cents": 5000}, SM))
    bay = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 1"}, SM))
    veh = get_success_data(api.create_vehicle(
        {"shop_id": shop["id"], "fleet_account_id": fleet["id"], "vin": "VINPRI004",
         "plate": "PRI4", "make": "Ford", "model": "F150", "odometer": 3000},
        {"X-User-ID": fleet["id"], "X-User-Role": "FleetManager", "Content-Type": "application/json"}))
    wo = get_success_data(api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 3000}, SA))
    res = api.authorize_payment(wo["id"], {"payment_method": "FLEET_ACCOUNT"}, SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = get_success_data(api.get_work_order(wo["id"], SA))
    assert after["payment_status"] == "UNPAID"  # rejection left the payment dimension untouched


# ─── priority_pair_validation_conflict / referential_beats_temporal ────────

def test_create_work_order_referential_coupon_error_beats_occupied_bay(api):
    """PRD §2.6: "then referential resolution of foreign keys named in the body (such as a
    coupon code, a package, or a fleet-account requirement, each producing its own 404 as
    described where it applies), then state-legality of the targeted transition (the 409
    family such as `ERR_INVALID_STATE`, `ERR_BAY_NOT_OPEN`, `ERR_BAY_OCCUPIED`,
    `ERR_BAY_NOT_READY`, and `ERR_PAYMENT_NOT_SETTLED`)".
    PRD §3.5: "The code must resolve to a coupon on the same shop, or the request is
    rejected with `ERR_COUPON_NOT_FOUND`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_work_order_create
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh_a = create_retail_vehicle(shop["id"], vin="VINPRI002", plate="PRI2",
                                  make="BMW", model="X3", odometer=22000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINPRI003", plate="PRI3",
                                  make="BMW", model="X1", odometer=23000)
    # First order occupies the bay.
    create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 22000)
    # Second create targets the OCCUPIED bay AND passes a non-existent coupon: the
    # referential coupon check (earlier) must win, so ERR_COUPON_NOT_FOUND not ERR_BAY_NOT_OPEN.
    res = api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh_b["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 23000, "coupon_code": "NOPE_NO_SUCH"}, SA)
    validate_error(res, "ERR_COUPON_NOT_FOUND", expected_status=404)
    # The temporal/state bay error must NOT be the reported error.
    assert res.json()["data"]["error_id"] != "ERR_BAY_NOT_OPEN"


def test_create_work_order_referential_coupon_error_has_no_side_effect(api):
    """PRD §3.5: "The code must resolve to a coupon on the same shop, or the request is
    rejected with `ERR_COUPON_NOT_FOUND`."
    PRD §3.4: "The bay must be `OPEN`; creating against it occupies it, sets its
    `current_work_order_id`, and lowers the open-bay count by one."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_work_order_create
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh_a = create_retail_vehicle(shop["id"], vin="VINPRI005", plate="PRI5",
                                  make="BMW", model="X3", odometer=22000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINPRI006", plate="PRI6",
                                  make="BMW", model="X1", odometer=23000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 22000)
    res = api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh_b["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 23000, "coupon_code": "NOPE_NO_SUCH"}, SA)
    validate_error(res, "ERR_COUPON_NOT_FOUND", expected_status=404)
    # Rejected create has no side effect: the bay still holds WO_A.
    bay_after = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_after["status"] == "OCCUPIED"
    assert bay_after["current_work_order_id"] == wo_a["id"]


# ─── cross_entity_state_dependency / start_requires_bay_occupied ───────────

def test_start_on_cancelled_order_rejected_invalid_state(api):
    """PRD §3.9: "The bay is freed from `OCCUPIED` to `OPEN` with its `current_work_order_id`
    cleared and the open-bay count raised by one."
    PRD §3.7: "Starting requires that the order's bay is `OCCUPIED` by this very order,
    failing which the request is rejected with `ERR_BAY_NOT_READY`".
    PRD §3.9: "An order that is already `READY`, `COMPLETED`, or `CANCELLED` cannot be
    cancelled and the attempt is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/start_requires_bay_occupied_workorder_to_bay
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINCRS001", plate="CRS1",
                                make="Honda", model="Fit", odometer=4000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 4000)
    claim(wo["id"], tech["id"])
    cancel_work_order(wo["id"])  # frees the bay; order is now CANCELLED
    res = api.start_work_order(wo["id"], make_technician_headers(tech["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancelled_order_frees_its_bay(api):
    """PRD §3.9: "The bay is freed from `OCCUPIED` to `OPEN` with its `current_work_order_id`
    cleared and the open-bay count raised by one."
    PRD §3.7: "Starting requires that the order's bay is `OCCUPIED` by this very order,
    failing which the request is rejected with `ERR_BAY_NOT_READY`".

    Design: Difficulty/cross_entity_state_dependency/start_requires_bay_occupied_workorder_to_bay
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINCRS003", plate="CRS3",
                                make="Honda", model="Fit", odometer=4000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 4000)
    claim(wo["id"], tech["id"])
    bay_occupied = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_occupied["status"] == "OCCUPIED"
    cancel_work_order(wo["id"])
    # The cross-entity dependency: the bay no longer holds the order after cancel.
    bay_freed = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_freed["status"] == "OPEN"
    assert bay_freed["current_work_order_id"] is None


# ─── non_linear_state_machine / parallel service x payment ─────────────────

def test_authorize_in_inspection_then_advance_service_keeps_payment(api):
    """PRD §3.8: "Authorization is permitted only while the service status is `INSPECTION`
    or `READY`, else `ERR_INVALID_STATE`."
    PRD §2.1 (entities): payment_status is an "independent dimension from service_status".
    PRD §3.7: "A `Technician` marks the order ready, advancing it from `IN_SERVICE` to
    `READY`".

    Design: Difficulty/non_linear_state_machine/work_order_parallel_service_x_payment_dimensions
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINPAR001", plate="PAR1",
                                make="Mazda", model="3", odometer=10000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 10000)
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    assert in_insp["service_status"] == "INSPECTION"
    # Authorize CASH while still in INSPECTION: payment moves, service does not.
    authd = validate_success(api.authorize_payment(wo["id"], {"payment_method": "CASH"}, SA), 200)
    assert authd["payment_status"] == "AUTHORIZED"
    assert authd["service_status"] == "INSPECTION"


def test_service_dimension_advances_independently_of_authorized_payment(api):
    """PRD §3.7: "A `Technician` marks the order ready, advancing it from `IN_SERVICE` to
    `READY`; this requires the order to be `IN_SERVICE`, else `ERR_INVALID_STATE`."
    PRD §2.1 (entities): payment_status is an "independent dimension from service_status".

    Design: Difficulty/non_linear_state_machine/work_order_parallel_service_x_payment_dimensions
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINPAR002", plate="PAR2",
                                make="Mazda", model="3", odometer=10000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 10000)
    claim_start(wo["id"], tech["id"])
    begin_inspection(wo["id"], tech["id"])
    get_success_data(api.authorize_payment(wo["id"], {"payment_method": "CASH"}, SA))
    # Finish inspection (INSPECTION -> IN_SERVICE), then mark ready.
    get_success_data(api.finish_inspection(wo["id"], make_technician_headers(tech["id"])))
    ready = mark_ready(wo["id"], tech["id"])
    assert ready["service_status"] == "READY"
    assert ready["payment_status"] == "AUTHORIZED"  # unchanged by the service move


# ─── resource_temporal_overlap / bay_occupancy_half_open_overlap ───────────

def test_second_work_order_on_occupied_bay_rejected(api):
    """PRD §3.4: "The bay must be `OPEN`; creating against it occupies it, sets its
    `current_work_order_id`, and lowers the open-bay count by one."
    PRD §3.3 (assignment): "The target bay must be `OPEN`, or the request is rejected with
    `ERR_BAY_NOT_OPEN`".

    Design: Difficulty/resource_temporal_overlap/bay_occupancy_half_open_overlap
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh_a = create_retail_vehicle(shop["id"], vin="VINOVA001", plate="OVA1",
                                  make="Honda", model="Fit", odometer=2000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINOVA002", plate="OVA2",
                                  make="Honda", model="Jazz", odometer=3000)
    create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 2000)
    res = api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh_b["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 3000}, SA)
    validate_error(res, "ERR_BAY_NOT_OPEN", expected_status=409)


def test_occupied_bay_still_holds_first_order_after_rejected_create(api):
    """PRD §2.9: "While occupied, a bay's `current_work_order_id` points at the work order
    filling it; while open or closed it is null."
    PRD §3.4: "The bay must be `OPEN`; creating against it occupies it, sets its
    `current_work_order_id`, and lowers the open-bay count by one."

    Design: Difficulty/resource_temporal_overlap/bay_occupancy_half_open_overlap
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    veh_a = create_retail_vehicle(shop["id"], vin="VINOVA003", plate="OVA3",
                                  make="Honda", model="Fit", odometer=2000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINOVA004", plate="OVA4",
                                  make="Honda", model="Jazz", odometer=3000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 2000)
    res = api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh_b["id"], "bay_id": bay["id"],
         "package_id": pkg["id"], "odometer_in": 3000}, SA)
    validate_error(res, "ERR_BAY_NOT_OPEN", expected_status=409)
    # The live occupancy is unchanged: the bay still points at WO_A.
    bay_after = get_success_data(api.get_bay(bay["id"], SA))
    assert bay_after["status"] == "OCCUPIED"
    assert bay_after["current_work_order_id"] == wo_a["id"]


# ─── resource_temporal_overlap / technician_buffered_double_booking ────────

def test_technician_double_booked_on_second_live_claim(api):
    """PRD §3.4: "Claiming also enforces that the technician is not double-booked: a
    technician's job intervals, each extended by that technician's `cleanup_buffer_seconds`,
    must not overlap one another; an overlap once the buffer is added is rejected with
    `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_double_booking
    """
    set_clock()
    shop = get_success_data(api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM))
    pkg = get_success_data(api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "CONVENTIONAL", "name": "Basic",
         "base_price_cents": 6995, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM))
    bay_a = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 1"}, SM))
    bay_b = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 2"}, SM))
    tech = get_success_data(api.create_technician(
        {"shop_id": shop["id"], "full_name": "Tess", "cleanup_buffer_seconds": 300}, SM))
    veh_a = create_retail_vehicle(shop["id"], vin="VINTDB001", plate="TDB1",
                                  make="Honda", model="Fit", odometer=2000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINTDB002", plate="TDB2",
                                  make="Honda", model="Jazz", odometer=3000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay_a["id"], pkg["id"], 2000)
    claim_start(wo_a["id"], tech["id"])  # technician now on a live order
    wo_b = create_direct_work_order(shop["id"], veh_b["id"], bay_b["id"], pkg["id"], 3000)
    res = api.claim_work_order(
        wo_b["id"], {"technician_id": tech["id"]}, make_technician_headers(tech["id"]))
    validate_error(res, "ERR_TECHNICIAN_DOUBLE_BOOKED", expected_status=409)


def test_rejected_double_booking_leaves_second_order_unclaimed(api):
    """PRD §3.4: "Until an order is claimed its `technician_id` is null."
    PRD §3.4: "Claiming also enforces that the technician is not double-booked: a
    technician's job intervals, each extended by that technician's `cleanup_buffer_seconds`,
    must not overlap one another; an overlap once the buffer is added is rejected with
    `ERR_TECHNICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/technician_buffered_double_booking
    """
    set_clock()
    shop = get_success_data(api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM))
    pkg = get_success_data(api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "CONVENTIONAL", "name": "Basic",
         "base_price_cents": 6995, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM))
    bay_a = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 1"}, SM))
    bay_b = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 2"}, SM))
    tech = get_success_data(api.create_technician(
        {"shop_id": shop["id"], "full_name": "Tess", "cleanup_buffer_seconds": 300}, SM))
    veh_a = create_retail_vehicle(shop["id"], vin="VINTDB003", plate="TDB3",
                                  make="Honda", model="Fit", odometer=2000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINTDB004", plate="TDB4",
                                  make="Honda", model="Jazz", odometer=3000)
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay_a["id"], pkg["id"], 2000)
    claim_start(wo_a["id"], tech["id"])
    wo_b = create_direct_work_order(shop["id"], veh_b["id"], bay_b["id"], pkg["id"], 3000)
    res = api.claim_work_order(
        wo_b["id"], {"technician_id": tech["id"]}, make_technician_headers(tech["id"]))
    validate_error(res, "ERR_TECHNICIAN_DOUBLE_BOOKED", expected_status=409)
    after = get_success_data(api.get_work_order(wo_b["id"], SA))
    assert after["technician_id"] is None  # rejected claim left the order unclaimed


# ─── corner: cross_cutting / occ_stale_work_order_version_on_add_line ──────

def test_add_line_with_stale_work_order_version_rejected(api):
    """PRD §2.8: "If a prior line add has since recomputed the order's pricing and bumped
    its `version`, the echoed value is stale, the request does not match the order's
    current `version`, and it is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412).
    This field is mandatory on the add-line request."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_work_order_version_on_add_line
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    item_a = create_inspection_item(shop["id"], code="AIR_FILTER", name="Air Filter",
                                    price_cents=4495, labor_minutes=5)
    item_b = create_inspection_item(shop["id"], code="CABIN_FILTER", name="Cabin Filter",
                                    price_cents=2895, labor_minutes=5)
    veh = create_retail_vehicle(shop["id"], vin="VINOCC001", plate="OCC1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    claim_start(wo["id"], tech["id"])
    in_insp = begin_inspection(wo["id"], tech["id"])
    stale_version = in_insp["version"]
    # First add bumps the version.
    add_line(wo["id"], tech["id"], item_a["id"], stale_version)
    # Second add reuses the now-stale version.
    res = api.add_line(
        wo["id"],
        {"inspection_item_id": item_b["id"], "expected_work_order_version": stale_version},
        make_technician_headers(tech["id"]))
    validate_error(res, "ERR_STALE_WORK_ORDER_VERSION", expected_status=412)
