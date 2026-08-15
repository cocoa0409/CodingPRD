"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

Identity threading: the Customer role is entity-backed — quote approval,
request-revision, decline, own-order intake/cancel, and own-pool withdraw use
headers built from the real Customer.id via make_customer_headers(...). Opaque
staff roles use shared headers, except where a workflow records X-User-ID
(assembly logging vs. certification segregation of duties), where a stable
operator id is threaded via make_technician_headers / make_certifier_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import POINT_ZERO_DEVIATION
from .factories import (
    create_asset_payload,
    create_capacity_window_payload,
    create_certification_payload,
    create_customer_payload,
    create_inspection_report_payload,
    create_part_payload,
    create_pool_unit_payload,
    create_quote_payload,
    create_repair_order_payload,
    create_test_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_certifier_headers,
    make_customer_headers,
    make_technician_headers,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
PLANNER = TEST_USERS["planner_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and simple reads
# ---------------------------------------------------------------------------

def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SM))


def create_asset(customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_asset(create_asset_payload(customer_id, **overrides), IC))


def create_capacity_window(**overrides) -> dict:
    return get_success_data(api_client.create_capacity_window(create_capacity_window_payload(**overrides), PLANNER))


def create_part(**overrides) -> dict:
    return get_success_data(api_client.create_part(create_part_payload(**overrides), SM))


def create_repair_order(customer_id: str, asset_id: str, **overrides) -> dict:
    payload = create_repair_order_payload(customer_id, asset_id, **overrides)
    return get_success_data(api_client.create_repair_order(payload, IC))


def create_pool_unit(customer_id: str, asset_id: str) -> dict:
    return get_success_data(api_client.create_pool_unit(create_pool_unit_payload(customer_id, asset_id), IC))


def get_repair_order(ro_id: str) -> dict:
    return get_success_data(api_client.get_repair_order(ro_id, SM))


def get_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, SM))


def get_window(window_id: str) -> dict:
    return get_success_data(api_client.get_capacity_window(window_id, SM))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SM))


def get_pool_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_pool_unit(unit_id, SM))


def get_part(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, SM))


def start_teardown(ro_id: str) -> dict:
    return get_success_data(api_client.start_teardown(ro_id, IC))


def author_and_finalize_report(ro_id: str, part_lines=None, **overrides) -> dict:
    """Author the teardown report and finalize it, driving the order
    IN_INSPECTION -> QUOTE_IN_PROGRESS. Returns the FINALIZED report."""
    payload = create_inspection_report_payload(part_lines=part_lines if part_lines is not None else [], **overrides)
    report = get_success_data(api_client.create_inspection_report(ro_id, payload, INSPECTOR))
    return get_success_data(api_client.finalize_inspection_report(report["id"], INSPECTOR))


def create_quote_for_ro(ro_id: str, window_id: str, expected_version: int = None,
                        **overrides) -> dict:
    """Create a DRAFT quote against the order's CURRENT version (refetched
    unless the caller pins expected_version explicitly). Returns the quote."""
    if expected_version is None:
        expected_version = get_repair_order(ro_id)["version"]
    payload = create_quote_payload(ro_id, window_id, expected_version, **overrides)
    return get_success_data(api_client.create_quote(payload, SM))


def issue_quote(quote_id: str) -> dict:
    return get_success_data(api_client.issue_quote(quote_id, SM))


def approve_quote(quote_id: str, customer_id: str) -> dict:
    return get_success_data(api_client.approve_quote(quote_id, make_customer_headers(customer_id)))


def record_test_run(ro_id: str, measured_points=None, test_type="PERFORMANCE_CURVE",
                    technician_id: str = "tech-001") -> dict:
    payload = create_test_run_payload(
        test_type=test_type,
        measured_points=measured_points if measured_points is not None else [POINT_ZERO_DEVIATION],
    )
    return get_success_data(api_client.create_test_run(
        ro_id, payload, make_technician_headers(technician_id)))


def reserve_pool_unit(unit_id: str, ro_id: str) -> dict:
    return get_success_data(api_client.reserve_pool_unit(unit_id, ro_id, IC))


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, SM))


# ---------------------------------------------------------------------------
# Tier 2: the shop context (customer + asset + capacity window)
# ---------------------------------------------------------------------------

def setup_shop(customer_over=None, asset_over=None, window_capacity=1000,
               window_over=None) -> dict:
    """Customer + one asset + one capacity window.

    Returns a dict: {"customer", "asset", "window"}. Later stages add
    "ro", "report", "quote", "test_run", "certification" keys.
    """
    customer = create_customer(**(customer_over or {}))
    asset = create_asset(customer["id"], **(asset_over or {}))
    w_over = {"bay_hours_capacity": window_capacity}
    w_over.update(window_over or {})
    window = create_capacity_window(**w_over)
    return {"customer": customer, "asset": asset, "window": window}


def add_asset(shop: dict, **overrides) -> dict:
    """Register another asset for the shop's customer."""
    return create_asset(shop["customer"]["id"], **overrides)


# ---------------------------------------------------------------------------
# Tier 3: repair-order pipeline stages
# ---------------------------------------------------------------------------

def drive_ro_to_quote_in_progress(shop: dict, ro: dict, report_part_lines=None,
                                  report_over=None) -> dict:
    """Walk a freshly created order RECEIVED -> IN_INSPECTION -> QUOTE_IN_PROGRESS.
    Mutates and returns the shop dict with fresh "ro" and "report"."""
    start_teardown(ro["id"])
    report = author_and_finalize_report(ro["id"], part_lines=report_part_lines,
                                        **(report_over or {}))
    shop["ro"] = get_repair_order(ro["id"])
    shop["report"] = report
    return shop


def setup_quote_in_progress_shop(ro_over=None, report_part_lines=None,
                                 report_over=None, **shop_kwargs) -> dict:
    """Shop + one repair order driven to QUOTE_IN_PROGRESS."""
    shop = setup_shop(**shop_kwargs)
    ro = create_repair_order(shop["customer"]["id"], shop["asset"]["id"], **(ro_over or {}))
    return drive_ro_to_quote_in_progress(shop, ro, report_part_lines, report_over)


def add_ro_in_quote_in_progress(shop: dict, asset=None, ro_over=None,
                                report_part_lines=None) -> dict:
    """Add another order (own asset by default) to an existing shop, driven to
    QUOTE_IN_PROGRESS. Returns the fresh order."""
    asset = asset or add_asset(shop)
    ro = create_repair_order(shop["customer"]["id"], asset["id"], **(ro_over or {}))
    start_teardown(ro["id"])
    author_and_finalize_report(ro["id"], part_lines=report_part_lines)
    return get_repair_order(ro["id"])


def issue_quote_for(shop: dict, ro: dict = None, quote_over=None) -> dict:
    """Create + issue a quote for the shop's (or given) order. Returns the
    ISSUED quote."""
    ro = ro or shop["ro"]
    quote = create_quote_for_ro(ro["id"], shop["window"]["id"], **(quote_over or {}))
    return issue_quote(quote["id"])


def setup_issued_quote_shop(quote_over=None, **kwargs) -> dict:
    """Shop + order in QUOTE_IN_PROGRESS + one ISSUED quote."""
    shop = setup_quote_in_progress_shop(**kwargs)
    shop["quote"] = issue_quote_for(shop, quote_over=quote_over)
    return shop


def setup_authorized_shop(quote_over=None, ro_over=None, reserve_unit=None,
                          **kwargs) -> dict:
    """Shop + order AUTHORIZED via an approved quote.

    If the order has exchange_requested set, pass reserve_unit (a pool unit of
    the same customer) so the approval's pool gate is satisfied.
    """
    shop = setup_issued_quote_shop(quote_over=quote_over, ro_over=ro_over, **kwargs)
    if reserve_unit is not None:
        reserve_pool_unit(reserve_unit["id"], shop["ro"]["id"])
    approve_quote(shop["quote"]["id"], shop["customer"]["id"])
    shop["quote"] = get_quote(shop["quote"]["id"])
    shop["ro"] = get_repair_order(shop["ro"]["id"])
    return shop


def setup_in_test_shop(technician_id: str = "tech-001", **kwargs) -> dict:
    """Shop + order IN_TEST (assembly logged first when certification applies)."""
    shop = setup_authorized_shop(**kwargs)
    tech = make_technician_headers(technician_id)
    get_success_data(api_client.start_repair(shop["ro"]["id"], tech))
    if shop["ro"]["requires_certification"]:
        get_success_data(api_client.log_assembly(shop["ro"]["id"], tech))
    get_success_data(api_client.submit_for_test(shop["ro"]["id"], tech))
    shop["ro"] = get_repair_order(shop["ro"]["id"])
    return shop


def setup_complete_shop(test_points=None, test_type="PERFORMANCE_CURVE",
                        technician_id: str = "tech-001", certifier_id: str = "cert-002",
                        cert_set_pressure=None, **kwargs) -> dict:
    """Shop + order COMPLETE: a passing test run, plus a certification when the
    order's asset is a safety-relief valve."""
    shop = setup_in_test_shop(technician_id=technician_id, **kwargs)
    shop["test_run"] = record_test_run(
        shop["ro"]["id"], measured_points=test_points, test_type=test_type,
        technician_id=technician_id)
    shop["ro"] = get_repair_order(shop["ro"]["id"])
    if shop["ro"]["requires_certification"]:
        pressure = cert_set_pressure
        if pressure is None:
            pressure = shop["asset"].get("set_pressure_psig", 100)
        cert = get_success_data(api_client.create_certification(
            shop["ro"]["id"],
            create_certification_payload(set_pressure_psig=pressure),
            make_certifier_headers(certifier_id)))
        shop["certification"] = cert
        shop["ro"] = get_repair_order(shop["ro"]["id"])
    return shop


def setup_closed_shop(**kwargs) -> dict:
    """Full lifecycle through CLOSED."""
    shop = setup_complete_shop(**kwargs)
    closed = get_success_data(api_client.close_repair_order(shop["ro"]["id"], IC))
    shop["ro"] = closed
    return shop


def setup_srv_ready_for_cert_shop(assembler_id: str = "tech-001", **kwargs) -> dict:
    """SRV order driven to READY_FOR_CERT with assembly logged by assembler_id.

    Asset defaults: SAFETY_RELIEF_VALVE with set_pressure_psig 100.
    """
    asset_over = {"equipment_class": "SAFETY_RELIEF_VALVE",
                  "manufacturer": "Consolidated", "model": "1900",
                  "set_pressure_psig": 100}
    asset_over.update(kwargs.pop("asset_over", {}) or {})
    ro_over = {"failure_mode": "SPRING_DRIFT"}
    ro_over.update(kwargs.pop("ro_over", {}) or {})
    shop = setup_in_test_shop(technician_id=assembler_id,
                              asset_over=asset_over, ro_over=ro_over, **kwargs)
    record_test_run(shop["ro"]["id"], test_type="POP_TEST",
                    technician_id=assembler_id)
    shop["ro"] = get_repair_order(shop["ro"]["id"])
    return shop


# ---------------------------------------------------------------------------
# Tier 4: window loading / threshold targeting
# ---------------------------------------------------------------------------

def setup_window_with_reserved_hours(reserved_hours: int, capacity: int = 100,
                                     **kwargs) -> dict:
    """Shop whose window already holds `reserved_hours` of approved work:
    one order with estimated_bay_hours == reserved_hours approved into it.
    The shop's order is left AUTHORIZED."""
    return setup_authorized_shop(window_capacity=capacity,
                                 ro_over={"estimated_bay_hours": reserved_hours},
                                 **kwargs)


# ---------------------------------------------------------------------------
# Tier 5: terminal / warranty / pool scenarios
# ---------------------------------------------------------------------------

def setup_warranty_shop(customer_over=None, parent_ro_over=None,
                        warranty_ro_over=None, **kwargs) -> dict:
    """A CLOSED parent order plus a second order (driven to QUOTE_IN_PROGRESS)
    that claims warranty against it.

    Returns shop with "parent_ro" (CLOSED) and "ro" (QUOTE_IN_PROGRESS,
    warranty_case true). Same asset reused: the parent is terminal, so the
    closed service window does not conflict with the new order's window.
    """
    shop = setup_closed_shop(customer_over=customer_over, ro_over=parent_ro_over, **kwargs)
    parent = shop["ro"]
    w_over = {"warranty_parent_ro_id": parent["id"]}
    w_over.update(warranty_ro_over or {})
    warranty_ro = create_repair_order(shop["customer"]["id"], shop["asset"]["id"], **w_over)
    shop["parent_ro"] = parent
    return drive_ro_to_quote_in_progress(shop, warranty_ro)


def setup_pool_shop(customer_over=None, **kwargs) -> dict:
    """Pool-program customer + two assets + one enrolled pool unit on asset 1.

    Returns shop with "pool_unit" added; shop["asset"] is the unit's asset and
    shop["asset2"] is a second serialized unit of the same customer.
    """
    c_over = {"pool_program": True}
    c_over.update(customer_over or {})
    shop = setup_shop(customer_over=c_over, **kwargs)
    shop["asset2"] = add_asset(shop)
    shop["pool_unit"] = create_pool_unit(shop["customer"]["id"], shop["asset"]["id"])
    return shop
