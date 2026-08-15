"""Composite setup helpers — multi-step PRD workflows encapsulated.

Every fixture builds its preconditions from scratch against a fresh server
(the harness restarts the API before each test) and uses get_success_data()
so setup failures surface as clear "Setup step failed" errors.
"""
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLEAN_SAMPLE, CLOCK_DEFAULT, DEFAULT_TEST_WINDOW
from .factories import (
    create_customer_payload,
    create_cylinder_payload,
    create_exchange_unit_payload,
    create_field_service_job_payload,
    create_inventory_item_payload,
    create_seal_kit_payload,
    create_shop_payload,
    create_teardown_report_payload,
    create_technician_payload,
    create_test_bay_payload,
    create_work_order_payload,
    hose_assembly,
    record_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_inspector_headers,
    make_technician_headers,
)

ADMIN = TEST_USERS["shop_admin_headers"]
ADVISOR = TEST_USERS["service_advisor_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creation
# ---------------------------------------------------------------------------

def create_shop(**overrides):
    """Set the logical clock and create the shop configuration."""
    get_success_data(api_client.set_clock({"to_iso8601": CLOCK_DEFAULT}, ADMIN))
    return get_success_data(api_client.create_shop(create_shop_payload(**overrides), ADMIN))


def create_seal_kit(**overrides):
    return get_success_data(api_client.create_seal_kit(create_seal_kit_payload(**overrides), ADMIN))


def create_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADVISOR))


def create_technician(**overrides):
    return get_success_data(api_client.create_technician(create_technician_payload(**overrides), ADMIN))


def create_field_technician(**overrides):
    overrides.setdefault("skills", ["FIELD_SERVICE"])
    return create_technician(**overrides)


def create_test_bay(**overrides):
    return get_success_data(api_client.create_test_bay(create_test_bay_payload(**overrides), ADMIN))


def create_cylinder(customer_id, seal_kit_id, **overrides):
    return get_success_data(
        api_client.create_cylinder(
            create_cylinder_payload(customer_id, seal_kit_id, **overrides), ADVISOR
        )
    )


def create_inventory_item(**overrides):
    return get_success_data(
        api_client.create_inventory_item(create_inventory_item_payload(**overrides), ADMIN)
    )


def create_exchange_unit(**overrides):
    return get_success_data(
        api_client.create_exchange_unit(create_exchange_unit_payload(**overrides), ADMIN)
    )


def open_work_order(cylinder_id, **overrides):
    return get_success_data(
        api_client.create_work_order(
            create_work_order_payload(cylinder_id, **overrides), ADVISOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: master-data bundle
# ---------------------------------------------------------------------------

def setup_master_data(with_bay=False, kit_overrides=None, customer_overrides=None,
                      tech_overrides=None, shop_overrides=None):
    """Clock + shop + seal kit + customer + cylinder-repair technician (+ bay)."""
    shop = create_shop(**(shop_overrides or {}))
    kit = create_seal_kit(**(kit_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    tech = create_technician(**(tech_overrides or {}))
    bay = create_test_bay() if with_bay else None
    return SimpleNamespace(shop=shop, kit=kit, customer=customer, tech=tech, bay=bay)


# ---------------------------------------------------------------------------
# Tier 2: work-order state progression (repair spine)
# ---------------------------------------------------------------------------

def begin_teardown(work_order, tech):
    """INTAKE -> TEARDOWN; assigns the technician."""
    return get_success_data(
        api_client.start_teardown(work_order["id"], {"technician_id": tech["id"]}, ADVISOR)
    )


def file_findings(work_order, tech, **overrides):
    """File teardown findings; TEARDOWN -> QUOTE_DRAFT. Returns the report.

    Cut lengths are omitted unless the corresponding material is needed
    (PRD §3.3: each cut length is mandatory exactly when its *_needed is true).
    """
    payload = create_teardown_report_payload(work_order["id"], **overrides)
    if not payload.get("rod_needed"):
        payload.pop("rod_cut_length_mm", None)
    if not payload.get("tube_needed"):
        payload.pop("tube_cut_length_mm", None)
    return get_success_data(
        api_client.create_teardown_report(payload, make_technician_headers(tech["id"]))
    )


def draft_quote(work_order):
    return get_success_data(api_client.create_quote({"work_order_id": work_order["id"]}, ADVISOR))


def send_quote(quote):
    return get_success_data(api_client.send_quote(quote["id"], ADVISOR))


def approve_quote(quote, customer):
    return get_success_data(
        api_client.approve_quote(quote["id"], make_customer_headers(customer["id"]))
    )


def start_repair(work_order, tech):
    return get_success_data(
        api_client.start_repair(work_order["id"], make_technician_headers(tech["id"]))
    )


def consume_all_reservations(work_order, tech):
    """Consume every OPEN reservation of the work order as the assignee."""
    data, _meta = _list_reservations(work_order["id"])
    consumed = []
    for res in data:
        if res["status"] == "OPEN":
            consumed.append(
                get_success_data(
                    api_client.consume_stock_reservation(
                        res["id"], make_technician_headers(tech["id"])
                    )
                )
            )
    return consumed


def _list_reservations(work_order_id):
    resp = api_client.list_stock_reservations(ADVISOR, params={"work_order_id": work_order_id})
    body = resp.json()
    assert resp.status_code == 200, f"Setup step failed listing reservations: {resp.text}"
    return body["data"], body["meta"]


def record_passing_cleanliness(work_order, tech, **overrides):
    """Record a contamination sample that meets all default targets."""
    payload = dict(CLEAN_SAMPLE)
    payload.update(overrides)
    return get_success_data(
        api_client.record_cleanliness_check(
            work_order["id"], payload, make_technician_headers(tech["id"])
        )
    )


def complete_assembly(work_order, tech):
    return get_success_data(
        api_client.complete_assembly(work_order["id"], make_technician_headers(tech["id"]))
    )


def book_pressure_test(work_order, bay, window_start=None, window_end=None):
    payload = {
        "work_order_id": work_order["id"],
        "test_bay_id": bay["id"],
        "window_start": window_start or DEFAULT_TEST_WINDOW[0],
        "window_end": window_end or DEFAULT_TEST_WINDOW[1],
    }
    return get_success_data(api_client.create_pressure_test(payload, INSPECTOR))


def record_pass(test, **overrides):
    payload = record_result_payload(**overrides)
    return get_success_data(api_client.record_pressure_test_result(test["id"], payload, INSPECTOR))


def issue_certificate(work_order, inspector_user_id="insp-9"):
    """Issue a certificate; the inspector id must differ from the assigned
    technician id (segregation of duties, PRD §3.7)."""
    return get_success_data(
        api_client.create_certificate(
            {"work_order_id": work_order["id"]}, make_inspector_headers(inspector_user_id)
        )
    )


def close_work_order(work_order, actual_labor_hours):
    return get_success_data(
        api_client.close_work_order(
            work_order["id"], {"actual_labor_hours": actual_labor_hours}, ADVISOR
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: full repair-lifecycle scenarios
# ---------------------------------------------------------------------------

def setup_quote_draft(*, with_bay=False, rod_needed=True, rod_cut_length_mm=500,
                      honing_passes=1, estimated_labor_hours=2.5, tier="EXPEDITE",
                      promised_hours=30, kit_overrides=None, customer_overrides=None,
                      serial=None):
    """Work order in QUOTE_DRAFT with a filed teardown report (version 1)."""
    md = setup_master_data(with_bay=with_bay, kit_overrides=kit_overrides,
                           customer_overrides=customer_overrides)
    cyl_kwargs = {"serial_number": serial} if serial else {}
    cylinder = create_cylinder(md.customer["id"], md.kit["id"], **cyl_kwargs)
    wo = open_work_order(cylinder["id"], tier=tier, promised_hours=promised_hours)
    begin_teardown(wo, md.tech)
    report = file_findings(
        wo, md.tech, rod_needed=rod_needed, rod_cut_length_mm=rod_cut_length_mm,
        tube_needed=False, honing_passes=honing_passes,
        estimated_labor_hours=estimated_labor_hours,
    )
    return SimpleNamespace(**vars(md), cylinder=cylinder, work_order=wo, report=report)


def setup_quote_sent(**kwargs):
    """Work order in QUOTE_SENT with a SENT quote pinned to report v1."""
    sc = setup_quote_draft(**kwargs)
    quote = draft_quote(sc.work_order)
    quote = send_quote(quote)
    sc.quote = quote
    return sc


def setup_approved(*, with_inventory=True, inventory_overrides=None, **kwargs):
    """Work order APPROVED: quote sent + customer approved (material cascade ran)."""
    sc = setup_quote_sent(**kwargs)
    if with_inventory and kwargs.get("rod_needed", True):
        item_kwargs = {"material": "CHROME_ROD", "diameter_mm": 45, "length_mm": 1000,
                       "cost_per_mm_cents": 42}
        item_kwargs.update(inventory_overrides or {})
        sc.rod_item = create_inventory_item(**item_kwargs)
    sc.quote = approve_quote(sc.quote, sc.customer)
    sc.work_order = get_success_data(api_client.get_work_order(sc.work_order["id"], ADVISOR))
    return sc


def setup_in_repair(**kwargs):
    """Work order IN_REPAIR (repair started by the assigned technician)."""
    sc = setup_approved(**kwargs)
    sc.work_order = start_repair(sc.work_order, sc.tech)
    return sc


def setup_assembled(**kwargs):
    """Work order ASSEMBLED: reservations consumed, cleanliness passed."""
    sc = setup_in_repair(**kwargs)
    sc.reservations = consume_all_reservations(sc.work_order, sc.tech)
    sc.work_order = record_passing_cleanliness(sc.work_order, sc.tech)
    sc.work_order = complete_assembly(sc.work_order, sc.tech)
    return sc


def setup_test_pending(*, window_start=None, window_end=None, **kwargs):
    """Work order TEST_PENDING with a SCHEDULED pressure test booked."""
    kwargs.setdefault("with_bay", True)
    sc = setup_assembled(**kwargs)
    sc.pressure_test = book_pressure_test(
        sc.work_order, sc.bay, window_start=window_start, window_end=window_end
    )
    sc.work_order = get_success_data(api_client.get_work_order(sc.work_order["id"], ADVISOR))
    return sc


def setup_certified(**kwargs):
    """Work order CERTIFIED: test passed and certificate issued by insp-9."""
    sc = setup_test_pending(**kwargs)
    sc.pressure_test = record_pass(sc.pressure_test)
    sc.certificate = issue_certificate(sc.work_order)
    sc.work_order = get_success_data(api_client.get_work_order(sc.work_order["id"], ADVISOR))
    return sc


# ---------------------------------------------------------------------------
# Tier 4: exchange-pool scenarios
# ---------------------------------------------------------------------------

def setup_exchange_selected(*, unit_overrides=None, **kwargs):
    """Work order EXCHANGE_SELECTED with a matching unit RESERVED."""
    kwargs.setdefault("rod_needed", False)
    kwargs.setdefault("honing_passes", 0)
    kwargs.setdefault("estimated_labor_hours", 1.0)
    sc = setup_quote_sent(**kwargs)
    sc.unit = create_exchange_unit(**(unit_overrides or {}))
    sc.work_order = get_success_data(
        api_client.select_exchange(
            sc.work_order["id"],
            {"exchange_unit_id": sc.unit["id"]},
            make_customer_headers(sc.customer["id"]),
        )
    )
    sc.unit = get_success_data(api_client.get_exchange_unit(sc.unit["id"], ADVISOR))
    return sc


def setup_exchange_fulfilled(**kwargs):
    """Exchange deal FULFILLED (provisional core credit computed)."""
    sc = setup_exchange_selected(**kwargs)
    sc.unit = get_success_data(api_client.fulfill_exchange_unit(sc.unit["id"], ADVISOR))
    return sc


def setup_exchange_settled(condition="WORN", completeness="COMPLETE", **kwargs):
    """Exchange deal SETTLED (final core credit computed at grading)."""
    sc = setup_exchange_fulfilled(**kwargs)
    get_success_data(api_client.receive_core(sc.unit["id"], ADVISOR))
    sc.unit = get_success_data(
        api_client.evaluate_core(
            sc.unit["id"], {"condition": condition, "completeness": completeness}, INSPECTOR
        )
    )
    return sc


# ---------------------------------------------------------------------------
# Tier 5: field-service scenarios
# ---------------------------------------------------------------------------

def setup_field_job(*, assemblies=None, distance_km=60, site_address="12 Quarry Rd",
                    customer_overrides=None):
    """Shop + customer + FIELD_SERVICE technician + one REQUESTED job."""
    md = setup_master_data(customer_overrides=customer_overrides)
    field_tech = create_field_technician()
    if assemblies is None:
        assemblies = [hose_assembly()]
    job = get_success_data(
        api_client.create_field_service_job(
            create_field_service_job_payload(
                md.customer["id"], site_address=site_address,
                distance_km=distance_km, assemblies=assemblies,
            ),
            ADVISOR,
        )
    )
    return SimpleNamespace(**vars(md), field_tech=field_tech, job=job)


def schedule_field_job(job, tech, window_start, window_end, expected_version=None):
    """Schedule a field job (OCC on Technician.version)."""
    if expected_version is None:
        expected_version = get_success_data(api_client.get_technician(tech["id"], ADVISOR))["version"]
    return api_client.schedule_field_service_job(
        job["id"],
        {
            "technician_id": tech["id"],
            "window_start": window_start,
            "window_end": window_end,
            "expected_technician_version": expected_version,
        },
        ADVISOR,
    )


def setup_field_job_dispatched(*, window_start="2026-08-05T09:00:00Z",
                               window_end="2026-08-05T11:00:00Z", **kwargs):
    """Field job DISPATCHED to its assigned technician."""
    sc = setup_field_job(**kwargs)
    resp = schedule_field_job(sc.job, sc.field_tech, window_start, window_end)
    sc.job = get_success_data(resp)
    sc.job = get_success_data(
        api_client.dispatch_field_service_job(
            sc.job["id"], make_technician_headers(sc.field_tech["id"])
        )
    )
    return sc
