"""Composite setup helpers.

Every test starts against an empty database with the logical clock at its
startup default (2026-08-01T00:00:00Z, PRD §2.7). These helpers build
preconditions from scratch using only PRD-declared endpoints, threading the
entity-backed Customer identity (X-User-ID == Customer.id) wherever an
ownership-gated call is made (PRD §2.1).
"""
import math

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    PASSING_WEATHER,
    STANDARD_MATERIAL,
    WASTE_FACTOR,
)
from .factories import (
    create_assessment_payload,
    create_crew_payload,
    create_customer_payload,
    create_material_lot_payload,
    create_material_payload,
    create_property_payload,
    create_quote_payload,
    create_route_sheet_payload,
    create_warranty_claim_payload,
    create_weather_snapshot_payload,
    finish_application_payload,
    reschedule_work_order_payload,
    schedule_work_order_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["office_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]


# ---------------------------------------------------------------------------
# Primitive creators (Tier 0/1)
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_current_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


def create_property(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_property(create_property_payload(customer_id, **overrides), ADMIN)
    )


def create_assessment(property_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_assessment(
            create_assessment_payload(property_id, **overrides), ESTIMATOR
        )
    )


def submit_assessment(assessment_id: str) -> dict:
    return get_success_data(api_client.submit_assessment(assessment_id, ESTIMATOR))


def create_submitted_assessment(property_id: str, **overrides) -> dict:
    assessment = create_assessment(property_id, **overrides)
    return submit_assessment(assessment["id"])


def create_material(**overrides) -> dict:
    return get_success_data(
        api_client.create_material(create_material_payload(**overrides), ADMIN)
    )


def create_material_lot(material_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_material_lot(
            create_material_lot_payload(material_id, **overrides), ADMIN
        )
    )


def create_crew(**overrides) -> dict:
    return get_success_data(api_client.create_crew(create_crew_payload(**overrides), ADMIN))


def create_route_sheet(
    crew_id: str, service_date: str, capacity_sqft=None, publish: bool = True
) -> dict:
    overrides = {}
    if capacity_sqft is not None:
        overrides["capacity_sqft"] = capacity_sqft
    sheet = get_success_data(
        api_client.create_route_sheet(
            create_route_sheet_payload(crew_id, service_date, **overrides), DISPATCHER
        )
    )
    if publish:
        sheet = get_success_data(api_client.publish_route_sheet(sheet["id"], DISPATCHER))
    return sheet


def post_weather_snapshot(target_date: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_weather_snapshot(
            create_weather_snapshot_payload(target_date, **overrides), DISPATCHER
        )
    )


def get_property(property_id: str) -> dict:
    return get_success_data(api_client.get_property(property_id, ADMIN))


def get_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, DISPATCHER))


def get_material_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_material_lot(lot_id, DISPATCHER))


def get_route_sheet(sheet_id: str) -> dict:
    return get_success_data(api_client.get_route_sheet(sheet_id, DISPATCHER))


def get_displacement_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_displacement_plan(plan_id, DISPATCHER))


def get_quote(quote_id: str) -> dict:
    return get_success_data(api_client.get_quote(quote_id, ESTIMATOR))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, ADMIN))


def get_warranty_record(record_id: str) -> dict:
    return get_success_data(api_client.get_warranty_record(record_id, ADMIN))


def get_warranty_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, ADMIN))


# ---------------------------------------------------------------------------
# Quote lifecycle (OCC-aware)
# ---------------------------------------------------------------------------
def create_quote(
    property_id: str,
    assessment_id: str,
    material_id: str,
    expected_property_version=None,
    **overrides,
) -> dict:
    """Create a DRAFT quote. When expected_property_version is omitted, the
    property's current version is read first (OCC, PRD §2.6)."""
    if expected_property_version is None:
        expected_property_version = get_property(property_id)["version"]
    return get_success_data(
        api_client.create_quote(
            create_quote_payload(
                property_id,
                assessment_id,
                material_id,
                expected_property_version,
                **overrides,
            ),
            ESTIMATOR,
        )
    )


def send_quote(quote_id: str) -> dict:
    return get_success_data(api_client.send_quote(quote_id, ESTIMATOR))


def accept_quote(quote_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.accept_quote(quote_id, make_customer_headers(customer_id))
    )


def find_work_order_for_quote(quote_id: str) -> dict:
    data = get_success_data(
        api_client.list_work_orders(DISPATCHER, params={"quote_id": quote_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one work order for quote {quote_id}, got {data!r}"
    )
    return data[0]


def find_displacement_plan(work_order_id: str) -> dict:
    data = get_success_data(
        api_client.list_displacement_plans(
            DISPATCHER, params={"work_order_id": work_order_id}
        )
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one displacement plan for work order {work_order_id}"
    )
    return data[0]


def find_invoice_for_work_order(work_order_id: str) -> dict:
    data = get_success_data(
        api_client.list_invoices(ADMIN, params={"work_order_id": work_order_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one invoice for work order {work_order_id}"
    )
    return data[0]


def find_warranty_record_for_work_order(work_order_id: str) -> dict:
    data = get_success_data(
        api_client.list_warranty_records(ADMIN, params={"work_order_id": work_order_id})
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one warranty record for work order {work_order_id}"
    )
    return data[0]


def expected_gallons(area_sqft, coats, coverage_sqft_per_gallon, include_seal=True) -> int:
    """Whole-gallon reservation: ceil(area * coats * 1.10 / coverage); 0 when
    sealing is out of scope (PRD §3.5)."""
    if not include_seal:
        return 0
    return math.ceil(area_sqft * coats * WASTE_FACTOR / coverage_sqft_per_gallon)


# ---------------------------------------------------------------------------
# Tier 2: scenario builders
# ---------------------------------------------------------------------------
def setup_quote_scenario(
    *,
    lot_kind: str = "COMMERCIAL_LOT",
    address: str = "100 Commerce Way",
    measured_area_sqft=1200,
    crack_linear_ft=40,
    pothole_count=2,
    pothole_area_sqft=10,
    oil_spot_area_sqft=5,
    slope_severity="NONE",
    customer_overrides=None,
    material_overrides=None,
    quote_overrides=None,
    set_clock_to=CLOCK_START_ISO,
) -> dict:
    """Customer + property + SUBMITTED assessment + material + DRAFT quote."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    cust_defaults = (
        {"name": "Acme Parking LLC", "customer_type": "COMMERCIAL",
         "email": "ops@acme.example", "phone": "555-0100"}
        if lot_kind == "COMMERCIAL_LOT"
        else {}
    )
    cust_defaults.update(customer_overrides or {})
    customer = create_customer(**cust_defaults)
    prop = create_property(customer["id"], address=address, lot_kind=lot_kind)
    assessment = create_submitted_assessment(
        prop["id"],
        measured_area_sqft=measured_area_sqft,
        crack_linear_ft=crack_linear_ft,
        pothole_count=pothole_count,
        pothole_area_sqft=pothole_area_sqft,
        oil_spot_area_sqft=oil_spot_area_sqft,
        slope_severity=slope_severity,
    )
    material = create_material(**(material_overrides or {}))
    quote = create_quote(
        prop["id"], assessment["id"], material["id"], **(quote_overrides or {})
    )
    return {
        "customer": customer,
        "property": get_property(prop["id"]),
        "assessment": assessment,
        "material": material,
        "quote": quote,
    }


def setup_sent_quote(**kwargs) -> dict:
    ctx = setup_quote_scenario(**kwargs)
    ctx["quote"] = send_quote(ctx["quote"]["id"])
    return ctx


def setup_accepted_job(**kwargs) -> dict:
    """SENT quote accepted by the owning customer; returns ctx with the
    freshly minted PENDING work order."""
    ctx = setup_sent_quote(**kwargs)
    ctx["quote"] = accept_quote(ctx["quote"]["id"], ctx["customer"]["id"])
    ctx["work_order"] = find_work_order_for_quote(ctx["quote"]["id"])
    return ctx


def add_accepted_job(
    ctx: dict,
    *,
    address: str,
    measured_area_sqft,
    lot_kind: str = "COMMERCIAL_LOT",
    assessment_overrides=None,
    quote_overrides=None,
) -> dict:
    """Attach another property + SUBMITTED assessment + accepted quote to the
    scenario's customer/material. Returns a sub-context."""
    asm_ov = {"measured_area_sqft": measured_area_sqft, "crack_linear_ft": 0,
              "pothole_count": 0, "pothole_area_sqft": 0, "oil_spot_area_sqft": 0,
              "slope_severity": "NONE"}
    asm_ov.update(assessment_overrides or {})
    prop = create_property(ctx["customer"]["id"], address=address, lot_kind=lot_kind)
    assessment = create_submitted_assessment(prop["id"], **asm_ov)
    quote = create_quote(
        prop["id"], assessment["id"], ctx["material"]["id"], **(quote_overrides or {})
    )
    quote = send_quote(quote["id"])
    quote = accept_quote(quote["id"], ctx["customer"]["id"])
    work_order = find_work_order_for_quote(quote["id"])
    return {
        "property": get_property(prop["id"]),
        "assessment": assessment,
        "quote": quote,
        "work_order": work_order,
    }


# ---------------------------------------------------------------------------
# Tier 3: scheduling and execution lifecycle
# ---------------------------------------------------------------------------
def schedule_work_order(
    work_order_id: str,
    route_sheet_id: str,
    material_lot_id: str,
    scheduled_date: str,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.schedule_work_order(
            work_order_id,
            schedule_work_order_payload(
                route_sheet_id, material_lot_id, scheduled_date, **overrides
            ),
            DISPATCHER,
        )
    )


def reschedule_work_order(
    work_order_id: str,
    route_sheet_id: str,
    scheduled_date: str,
    expected_work_order_version=None,
    **overrides,
) -> dict:
    if expected_work_order_version is None:
        expected_work_order_version = get_work_order(work_order_id)["version"]
    return get_success_data(
        api_client.reschedule_work_order(
            work_order_id,
            reschedule_work_order_payload(
                route_sheet_id,
                scheduled_date,
                expected_work_order_version,
                **overrides,
            ),
            DISPATCHER,
        )
    )


def setup_scheduled_job(
    *,
    service_date: str = "2026-08-10",
    window_start_hour: int = 7,
    window_end_hour: int = 11,
    drive_minutes_est: int = 20,
    vehicles_to_move: int = 3,
    delivered_gallons=100,
    reorder_threshold_gallons=15,
    unit_cost_cents=1500,
    received_on="2026-07-15",
    daily_capacity_sqft: int = 8000,
    sheet_capacity=None,
    publish_sheet: bool = True,
    post_weather: bool = True,
    weather_overrides=None,
    **job_kwargs,
) -> dict:
    """Accepted job + material lot + crew + published sheet + passing weather,
    then scheduled onto the sheet with a lot reservation. Displacement plan
    born NOTICE_PENDING."""
    ctx = setup_accepted_job(**job_kwargs)
    lot = create_material_lot(
        ctx["material"]["id"],
        delivered_gallons=delivered_gallons,
        unit_cost_cents=unit_cost_cents,
        received_on=received_on,
        reorder_threshold_gallons=reorder_threshold_gallons,
    )
    crew = create_crew(daily_capacity_sqft=daily_capacity_sqft)
    sheet = create_route_sheet(
        crew["id"], service_date, capacity_sqft=sheet_capacity, publish=publish_sheet
    )
    if post_weather:
        post_weather_snapshot(service_date, **(weather_overrides or {}))
    ctx["lot"] = lot
    ctx["crew"] = crew
    ctx["sheet"] = get_route_sheet(sheet["id"])
    ctx["work_order"] = schedule_work_order(
        ctx["work_order"]["id"],
        sheet["id"],
        lot["id"],
        service_date,
        window_start_hour=window_start_hour,
        window_end_hour=window_end_hour,
        drive_minutes_est=drive_minutes_est,
        vehicles_to_move=vehicles_to_move,
    )
    ctx["service_date"] = service_date
    ctx["plan"] = find_displacement_plan(ctx["work_order"]["id"])
    return ctx


def schedule_onto_sheet(
    ctx: dict,
    sub: dict,
    *,
    sheet: dict,
    service_date: str,
    window_start_hour: int = 7,
    window_end_hour: int = 11,
    drive_minutes_est: int = 15,
    vehicles_to_move: int = 0,
    lot_id=None,
) -> dict:
    """Schedule another accepted job's work order onto an existing sheet."""
    work_order = schedule_work_order(
        sub["work_order"]["id"],
        sheet["id"],
        lot_id or ctx["lot"]["id"],
        service_date,
        window_start_hour=window_start_hour,
        window_end_hour=window_end_hour,
        drive_minutes_est=drive_minutes_est,
        vehicles_to_move=vehicles_to_move,
    )
    return {
        "work_order": work_order,
        "plan": find_displacement_plan(work_order["id"]),
        "sheet": get_route_sheet(sheet["id"]),
    }


def clear_plan_for(work_order_id: str) -> dict:
    """Send the displacement notice and confirm cleared for a work order."""
    plan = find_displacement_plan(work_order_id)
    send_notice(plan["id"])
    return confirm_cleared(plan["id"])


def send_notice(plan_id: str) -> dict:
    return get_success_data(api_client.send_displacement_notice(plan_id, DISPATCHER))


def confirm_cleared(plan_id: str) -> dict:
    return get_success_data(api_client.confirm_displacement_cleared(plan_id, DISPATCHER))


def setup_cleared_job(**kwargs) -> dict:
    """Scheduled job whose displacement plan is NOTICE_SENT then CLEARED."""
    ctx = setup_scheduled_job(**kwargs)
    send_notice(ctx["plan"]["id"])
    ctx["plan"] = confirm_cleared(ctx["plan"]["id"])
    return ctx


def service_morning_iso(service_date: str) -> str:
    return f"{service_date}T07:00:00Z"


def setup_in_progress_job(**kwargs) -> dict:
    """Cleared job started on the service morning."""
    ctx = setup_cleared_job(**kwargs)
    set_clock(service_morning_iso(ctx["service_date"]))
    ctx["work_order"] = get_success_data(
        api_client.start_work_order(ctx["work_order"]["id"], CREW_LEAD)
    )
    return ctx


def setup_curing_job(actuals=None, **kwargs) -> dict:
    """In-progress job finished with recorded actuals; rests in CURING."""
    ctx = setup_in_progress_job(**kwargs)
    if actuals is None:
        asm = ctx["assessment"]
        actuals = {
            "actual_area_sqft": asm["measured_area_sqft"],
            "actual_crack_ft": asm["crack_linear_ft"],
            "actual_pothole_area_sqft": asm["pothole_area_sqft"],
            "actual_stripe_ft": 0,
            "gallons_used": ctx["work_order"]["reserved_gallons"],
        }
    ctx["work_order"] = get_success_data(
        api_client.finish_work_order(
            ctx["work_order"]["id"], finish_application_payload(**actuals), CREW_LEAD
        )
    )
    return ctx


def setup_completed_job(actuals=None, **kwargs) -> dict:
    """Curing job completed once the clock reaches cure_until."""
    ctx = setup_curing_job(actuals=actuals, **kwargs)
    set_clock(ctx["work_order"]["cure_until"])
    ctx["work_order"] = get_success_data(
        api_client.complete_work_order(ctx["work_order"]["id"], CREW_LEAD)
    )
    return ctx


def setup_held_job(
    *,
    hold_snapshot_overrides=None,
    send_notice_first: bool = True,
    clear_notice: bool = False,
    **kwargs,
) -> dict:
    """Scheduled job on a published sheet pushed into WEATHER_HOLD by a failing
    weather snapshot (precip probability > 60 or min temp < 40, PRD §2.8)."""
    ctx = setup_scheduled_job(**kwargs)
    if send_notice_first:
        send_notice(ctx["plan"]["id"])
        if clear_notice:
            confirm_cleared(ctx["plan"]["id"])
    hold = {"min_temp_f": 45, "max_temp_f": 62, "precip_probability_pct": 85,
            "precipitation_mm": 6, "source": "FORECAST"}
    hold.update(hold_snapshot_overrides or {})
    post_weather_snapshot(ctx["service_date"], **hold)
    ctx["sheet"] = get_route_sheet(ctx["sheet"]["id"])
    ctx["work_order"] = get_work_order(ctx["work_order"]["id"])
    ctx["plan"] = get_displacement_plan(ctx["plan"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: terminal states (billing + warranty)
# ---------------------------------------------------------------------------
def setup_completed_job_with_invoice(actuals=None, **kwargs) -> dict:
    ctx = setup_completed_job(actuals=actuals, **kwargs)
    ctx["invoice"] = find_invoice_for_work_order(ctx["work_order"]["id"])
    return ctx


def setup_issued_invoice(actuals=None, **kwargs) -> dict:
    ctx = setup_completed_job_with_invoice(actuals=actuals, **kwargs)
    ctx["invoice"] = get_success_data(
        api_client.issue_invoice(ctx["invoice"]["id"], ADMIN)
    )
    return ctx


def setup_warranty_scenario(actuals=None, **kwargs) -> dict:
    """Completed non-warranty job with its ACTIVE warranty record."""
    ctx = setup_completed_job(actuals=actuals, **kwargs)
    ctx["warranty_record"] = find_warranty_record_for_work_order(
        ctx["work_order"]["id"]
    )
    return ctx


def setup_open_claim(actuals=None, claim_overrides=None, **kwargs) -> dict:
    """Warranty scenario plus one filed claim (record CLAIM_OPEN)."""
    ctx = setup_warranty_scenario(actuals=actuals, **kwargs)
    ctx["claim"] = get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                ctx["warranty_record"]["id"], **(claim_overrides or {})
            ),
            make_customer_headers(ctx["customer"]["id"]),
        )
    )
    ctx["warranty_record"] = get_warranty_record(ctx["warranty_record"]["id"])
    return ctx


def setup_investigating_claim(
    actuals=None, investigator_id: str = "admin-a", claim_overrides=None, **kwargs
) -> dict:
    ctx = setup_open_claim(actuals=actuals, claim_overrides=claim_overrides, **kwargs)
    from .test_users import make_office_admin_headers

    ctx["claim"] = get_success_data(
        api_client.investigate_warranty_claim(
            ctx["claim"]["id"], make_office_admin_headers(investigator_id)
        )
    )
    return ctx
