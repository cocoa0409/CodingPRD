"""Composite setup helpers.

Every test starts against an empty database, so each scenario has to build its
own preconditions through the published endpoints. This module holds those
build-up chains so no test has to re-invent them:

* single-call primitives that create one row and hand back its stored form;
* state-progression helpers that walk an entity to a named lifecycle state;
* whole-network stacks (a loop with its tariffs, customers, fuel contracts,
  production fleet and a published forecast) that several scenarios share.

Everything accepts ``**overrides`` so a scenario can vary exactly the one input
it turns on, and everything returns the parsed ``data`` object (or a dict of
them) rather than a raw response, because these are preconditions and not the
behaviour under test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import CLOCK_STARTUP_UTC
from .test_users import (
    BILLING_ANALYST,
    DISPATCH_OPERATOR,
    FIELD_TECHNICIAN,
    FIELD_TECHNICIAN_ALT,
    NETWORK_ENGINEER,
    SYSTEM_CONTROLLER,
    make_customer_account_headers,
)

# ─── The logical clock ──────────────────────────────────────────────────────


def set_clock(to_iso8601: str = CLOCK_STARTUP_UTC) -> Dict[str, Any]:
    """Reposition the logical clock; only the controller role may do this."""
    return get_success_data(
        api_client.set_clock(f.clock_payload(to_iso8601), SYSTEM_CONTROLLER)
    )


# ─── NetworkLoop and PipeSegment ───────────────────────────────────────────


def create_loop(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_network_loop(f.network_loop_payload(**overrides), SYSTEM_CONTROLLER)
    )


def read_loop(loop_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_network_loop(loop_id, headers or SYSTEM_CONTROLLER)
    )


def loop_version(loop_id: str) -> int:
    """The loop's current version, as a plan author must read it before writing."""
    return read_loop(loop_id, DISPATCH_OPERATOR)["version"]


def create_segment(loop_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_pipe_segment(
            f.pipe_segment_payload(loop_id, **overrides), NETWORK_ENGINEER
        )
    )


def assess_segment(
    segment_id: str,
    makeup_water_ratio: float,
    historical_leak_count: int,
    insulation_class: str,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.assess_segment_condition(
            segment_id,
            f.condition_assessment_payload(
                makeup_water_ratio, historical_leak_count, insulation_class, **overrides
            ),
            NETWORK_ENGINEER,
        )
    )


# ─── Fuel supply and production fleet ──────────────────────────────────────


def create_fuel_contract(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_fuel_supply_contract(
            f.fuel_supply_contract_payload(**overrides), SYSTEM_CONTROLLER
        )
    )


def set_fuel_contract_status(contract_id: str, status: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_fuel_contract_status(
            contract_id, f.fuel_contract_status_payload(status, **overrides), SYSTEM_CONTROLLER
        )
    )


def create_asset(loop_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_production_asset(
            f.production_asset_payload(loop_id, **overrides), SYSTEM_CONTROLLER
        )
    )


def set_availability(asset_id: str, availability_state: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_asset_availability(
            asset_id, f.availability_payload(availability_state, **overrides), SYSTEM_CONTROLLER
        )
    )


def read_asset(asset_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_production_asset(asset_id, DISPATCH_OPERATOR))


# ─── Tariffs and customers ─────────────────────────────────────────────────


def create_rate_schedule(customer_class: str = "COMMERCIAL_OFFICE", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_rate_schedule(
            f.rate_schedule_payload(customer_class, **overrides), BILLING_ANALYST
        )
    )


def create_agreement(loop_id: str, rate_schedule_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_connection_agreement(
            f.connection_agreement_payload(loop_id, rate_schedule_id, **overrides),
            BILLING_ANALYST,
        )
    )


def activate_agreement(agreement_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.activate_connection_agreement(agreement_id, {}, BILLING_ANALYST)
    )


def set_agreement_state(agreement_id: str, contract_state: str, **overrides) -> Dict[str, Any]:
    payload = f.agreement_status_payload(contract_state, **overrides)
    payload.setdefault("reason", "operational change")
    return get_success_data(
        api_client.set_agreement_status(agreement_id, payload, BILLING_ANALYST)
    )


def read_agreement(agreement_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_connection_agreement(agreement_id, headers or BILLING_ANALYST)
    )


def agreement_version(agreement_id: str) -> int:
    """The agreement's current version, as an invoice author must read it first."""
    return read_agreement(agreement_id)["version"]


def active_agreement(loop_id: str, rate_schedule_id: str, **overrides) -> Dict[str, Any]:
    """A customer that has cleared the capacity check and is taking service."""
    agreement = create_agreement(loop_id, rate_schedule_id, **overrides)
    return activate_agreement(agreement["id"])


# ─── Forecasts ─────────────────────────────────────────────────────────────


def create_forecast(loop_id: str, service_date: str, **overrides) -> Dict[str, Any]:
    payload = f.load_forecast_payload(loop_id, service_date, **overrides)
    payload.setdefault("heating_degree_hours", 0.0)
    payload.setdefault("cooling_degree_hours", 0.0)
    return get_success_data(api_client.create_load_forecast(payload, DISPATCH_OPERATOR))


def publish_forecast(
    forecast_id: str, variant: str = "WEATHER_NORMAL_PROVISIONAL"
) -> Dict[str, Any]:
    return get_success_data(
        api_client.publish_load_forecast(
            forecast_id, f.publish_forecast_payload(variant), DISPATCH_OPERATOR
        )
    )


def published_forecast(
    loop_id: str,
    service_date: str,
    variant: str = "WEATHER_NORMAL_PROVISIONAL",
    **overrides,
) -> Dict[str, Any]:
    """A forecast carried straight through to PUBLISHED so a plan can bind it."""
    forecast = create_forecast(loop_id, service_date, **overrides)
    return publish_forecast(forecast["id"], variant)


def read_forecast(forecast_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_load_forecast(forecast_id, DISPATCH_OPERATOR))


# ─── Dispatch plans ────────────────────────────────────────────────────────


def create_plan(
    loop_id: str,
    forecast_id: str,
    expected_loop_version: Optional[int] = None,
    author_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Open a plan, reading the loop's version first when none was supplied."""
    if expected_loop_version is None:
        expected_loop_version = loop_version(loop_id)
    return get_success_data(
        api_client.create_dispatch_plan(
            f.dispatch_plan_payload(loop_id, forecast_id, expected_loop_version),
            author_headers or DISPATCH_OPERATOR,
        )
    )


def optimize_plan(plan_id: str, author_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.optimize_dispatch_plan(plan_id, {}, author_headers or DISPATCH_OPERATOR)
    )


def submit_plan(
    plan_id: str, submission_note: str = "ready for review", author_headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_dispatch_plan(
            plan_id, {"submission_note": submission_note}, author_headers or DISPATCH_OPERATOR
        )
    )


def review_plan(
    plan_id: str,
    decision: str = "APPROVE",
    review_note: str = "cleared",
    reviewer_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.review_dispatch_plan(
            plan_id,
            f.plan_review_payload(decision, review_note=review_note),
            reviewer_headers or SYSTEM_CONTROLLER,
        )
    )


def commit_plan(plan_id: str, author_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.commit_dispatch_plan(plan_id, {}, author_headers or DISPATCH_OPERATOR)
    )


def decommit_plan(plan_id: str, reason: str = "withdrawn") -> Dict[str, Any]:
    return get_success_data(
        api_client.decommit_dispatch_plan(plan_id, {"reason": reason}, SYSTEM_CONTROLLER)
    )


def read_plan(plan_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_dispatch_plan(plan_id, DISPATCH_OPERATOR))


def plan_orders(plan_id: str) -> List[Dict[str, Any]]:
    """Every dispatch order belonging to one plan, in merit-rank order."""
    body = api_client.list_dispatch_orders(DISPATCH_OPERATOR, {"plan_id": plan_id, "limit": 100})
    rows = get_success_data(body)
    if isinstance(rows, dict):
        rows = rows.get("data", rows)
    return sorted(rows, key=lambda o: o["merit_rank"])


def plan_in_state(
    plan_state: str,
    loop_id: str,
    forecast_id: str,
    author_headers: Optional[Dict] = None,
    reviewer_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Walk one plan to ``plan_state`` through its declared transitions.

    Recognised targets: DRAFT (opened), OPTIMIZED (still DRAFT but with orders),
    SUBMITTED, APPROVED, COMMITTED.
    """
    plan = create_plan(loop_id, forecast_id, author_headers=author_headers)
    plan_id = plan["id"]
    if plan_state == "DRAFT":
        return plan
    plan = optimize_plan(plan_id, author_headers)
    if plan_state == "OPTIMIZED":
        return plan
    plan = submit_plan(plan_id, author_headers=author_headers)
    if plan_state == "SUBMITTED":
        return plan
    plan = review_plan(plan_id, "APPROVE", reviewer_headers=reviewer_headers)
    if plan_state == "APPROVED":
        return plan
    if plan_state == "COMMITTED":
        return commit_plan(plan_id, author_headers)
    raise ValueError(f"unsupported plan state: {plan_state}")


# ─── Metering ──────────────────────────────────────────────────────────────


def create_point(agreement_id: str, segment_id: str, **overrides) -> Dict[str, Any]:
    payload = f.metering_point_payload(agreement_id, segment_id, **overrides)
    payload.setdefault("multiplier", 1.0)
    return get_success_data(api_client.create_metering_point(payload, FIELD_TECHNICIAN))


def commission_point(point_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.commission_metering_point(point_id, {}, FIELD_TECHNICIAN))


def remove_point(point_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.remove_metering_point(point_id, {}, FIELD_TECHNICIAN))


def commissioned_point(agreement_id: str, segment_id: str, **overrides) -> Dict[str, Any]:
    """A metering point installed and put into service so it can take reads."""
    point = create_point(agreement_id, segment_id, **overrides)
    return commission_point(point["id"])


def add_reading(
    point_id: str,
    read_at: str,
    cumulative_energy_mwh: float,
    peak_demand_kw: float,
    read_type: str = "ACTUAL",
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_meter_reading(
            point_id,
            f.meter_reading_payload(
                read_at, cumulative_energy_mwh, peak_demand_kw, read_type, **overrides
            ),
            FIELD_TECHNICIAN,
        )
    )


def add_readings(point_id: str, readings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Post a whole register history in the order given."""
    return [add_reading(point_id, **reading) for reading in readings]


# ─── Invoices ──────────────────────────────────────────────────────────────


def create_invoice(
    agreement_id: str,
    period_start: str,
    period_end: str,
    variant: str = "ESTIMATED",
    expected_agreement_version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    if expected_agreement_version is None:
        expected_agreement_version = agreement_version(agreement_id)
    return get_success_data(
        api_client.create_invoice(
            f.invoice_payload(
                agreement_id,
                period_start,
                period_end,
                variant,
                expected_agreement_version,
                **overrides,
            ),
            BILLING_ANALYST,
        )
    )


def issue_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.issue_invoice(invoice_id, {}, BILLING_ANALYST))


def adjust_invoice(invoice_id: str, variant: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.adjust_invoice(
            invoice_id, f.invoice_adjust_payload(variant, **overrides), BILLING_ANALYST
        )
    )


def pay_invoice(invoice_id: str, amount: float, agreement_id: str, **overrides) -> Dict[str, Any]:
    """Settle an issued invoice as the connected customer that owns it."""
    return get_success_data(
        api_client.pay_invoice(
            invoice_id,
            f.payment_payload(amount, **overrides),
            make_customer_account_headers(agreement_id),
        )
    )


def void_invoice(invoice_id: str, reason: str = "billing correction") -> Dict[str, Any]:
    return get_success_data(
        api_client.void_invoice(invoice_id, {"reason": reason}, BILLING_ANALYST)
    )


def read_invoice(invoice_id: str, headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice(invoice_id, headers or BILLING_ANALYST))


def invoice_in_state(
    invoice_state: str,
    agreement_id: str,
    period_start: str,
    period_end: str,
    variant: str = "ESTIMATED",
) -> Dict[str, Any]:
    """Walk one invoice to ``invoice_state``: DRAFT, ISSUED, PAID or VOID."""
    invoice = create_invoice(agreement_id, period_start, period_end, variant)
    invoice_id = invoice["id"]
    if invoice_state == "DRAFT":
        return invoice
    if invoice_state == "VOID":
        return void_invoice(invoice_id)
    invoice = issue_invoice(invoice_id)
    if invoice_state == "ISSUED":
        return invoice
    if invoice_state == "PAID":
        return pay_invoice(invoice_id, invoice["total_amount"], agreement_id)
    raise ValueError(f"unsupported invoice state: {invoice_state}")


# ─── Work orders ───────────────────────────────────────────────────────────


def create_work_order(
    segment_id: str,
    loop_id: str,
    window_start: str,
    window_end: str,
    reporter_headers: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    payload = f.work_order_payload(segment_id, loop_id, window_start, window_end, **overrides)
    payload.setdefault("requires_isolation", False)
    return get_success_data(
        api_client.create_work_order(payload, reporter_headers or FIELD_TECHNICIAN)
    )


def submit_permit(work_order_id: str, reporter_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_work_order_permit(
            work_order_id, {}, reporter_headers or FIELD_TECHNICIAN
        )
    )


def decide_permit(work_order_id: str, permit_decision: str = "GRANTED", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_work_order_permit(
            work_order_id, f.permit_decision_payload(permit_decision, **overrides), NETWORK_ENGINEER
        )
    )


def begin_excavation(work_order_id: str, reporter_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.begin_excavation(work_order_id, {}, reporter_headers or FIELD_TECHNICIAN)
    )


def begin_repair(work_order_id: str, reporter_headers: Optional[Dict] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.begin_repair(work_order_id, {}, reporter_headers or FIELD_TECHNICIAN)
    )


def backfill_work_order(
    work_order_id: str, reporter_headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return get_success_data(
        api_client.backfill_work_order(work_order_id, {}, reporter_headers or FIELD_TECHNICIAN)
    )


def complete_work_order(
    work_order_id: str,
    completion_note: str = "work signed off",
    completer_headers: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    """Close out a backfilled order; the closer must differ from the reporter."""
    payload: Dict[str, Any] = {"completion_note": completion_note}
    payload.update(overrides)
    return get_success_data(
        api_client.complete_work_order(
            work_order_id, payload, completer_headers or FIELD_TECHNICIAN_ALT
        )
    )


def read_work_order(work_order_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_work_order(work_order_id, FIELD_TECHNICIAN))


def work_order_in_state(
    work_state: str,
    segment_id: str,
    loop_id: str,
    window_start: str,
    window_end: str,
    reporter_headers: Optional[Dict] = None,
    **overrides,
) -> Dict[str, Any]:
    """Walk one work order to ``work_state`` through its declared transitions.

    Recognised targets: DRAFT, PERMIT_PENDING, SCHEDULED, EXCAVATING,
    REPAIRING, BACKFILLED, COMPLETED. Reaching EXCAVATING or beyond needs the
    logical clock to already sit inside the order's window.
    """
    order = create_work_order(
        segment_id, loop_id, window_start, window_end, reporter_headers, **overrides
    )
    order_id = order["id"]
    if work_state == "DRAFT":
        return order
    order = submit_permit(order_id, reporter_headers)
    if work_state == "PERMIT_PENDING":
        return order
    order = decide_permit(order_id, "GRANTED")
    if work_state == "SCHEDULED":
        return order
    order = begin_excavation(order_id, reporter_headers)
    if work_state == "EXCAVATING":
        return order
    order = begin_repair(order_id, reporter_headers)
    if work_state == "REPAIRING":
        return order
    order = backfill_work_order(order_id, reporter_headers)
    if work_state == "BACKFILLED":
        return order
    if work_state == "COMPLETED":
        return complete_work_order(order_id)
    raise ValueError(f"unsupported work order state: {work_state}")


# ─── Expansion projects ────────────────────────────────────────────────────


def create_project(loop_id: str, rate_schedule_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_expansion_project(
            f.expansion_project_payload(loop_id, rate_schedule_id, **overrides), NETWORK_ENGINEER
        )
    )


def size_project(project_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.size_expansion_project(project_id, f.sizing_payload(**overrides), NETWORK_ENGINEER)
    )


def decide_project(project_id: str, decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.decide_expansion_project(
            project_id, f.project_decision_payload(decision, **overrides), SYSTEM_CONTROLLER
        )
    )


def convert_project(
    project_id: str,
    reserved_capacity_kw: float,
    service_mode: str = "HEATING",
    service_start_date: str = "2026-09-01T00:00:00Z",
    service_end_date: str = "2027-09-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.convert_expansion_project(
            project_id,
            f.convert_project_payload(
                reserved_capacity_kw,
                service_mode,
                service_start_date,
                service_end_date,
                **overrides,
            ),
            BILLING_ANALYST,
        )
    )


def read_project(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_expansion_project(project_id, NETWORK_ENGINEER))


def project_in_state(
    project_state: str, loop_id: str, rate_schedule_id: str, **overrides
) -> Dict[str, Any]:
    """Walk one project to ``project_state``: SCREENING, SIZED, APPROVED or REJECTED."""
    project = create_project(loop_id, rate_schedule_id, **overrides)
    project_id = project["id"]
    if project_state == "SCREENING":
        return project
    project = size_project(project_id)
    if project_state == "SIZED":
        return project
    if project_state == "APPROVED":
        return decide_project(project_id, "APPROVE")
    if project_state == "REJECTED":
        return decide_project(project_id, "REJECT")
    raise ValueError(f"unsupported project state: {project_state}")


# ─── Tariff sets ───────────────────────────────────────────────────────────


def hospital_rate_schedule(**overrides) -> Dict[str, Any]:
    defaults = dict(
        code="RS-H",
        fixed_service_charge=1200.00,
        demand_charge_per_kw=14.50,
        minimum_bill_amount=5000.00,
        tiers=[
            {"load_factor_max": 30.0, "energy_rate_per_mwh": 92.00},
            {"load_factor_max": 60.0, "energy_rate_per_mwh": 78.50},
            {"load_factor_max": 100.0, "energy_rate_per_mwh": 64.00},
        ],
    )
    defaults.update(overrides)
    return create_rate_schedule("HOSPITAL", **defaults)


def commercial_rate_schedule(**overrides) -> Dict[str, Any]:
    defaults = dict(
        code="RS-C",
        fixed_service_charge=800.00,
        demand_charge_per_kw=12.00,
        minimum_bill_amount=4000.00,
        tiers=[
            {"load_factor_max": 30.0, "energy_rate_per_mwh": 88.00},
            {"load_factor_max": 65.0, "energy_rate_per_mwh": 74.00},
            {"load_factor_max": 100.0, "energy_rate_per_mwh": 61.00},
        ],
    )
    defaults.update(overrides)
    return create_rate_schedule("COMMERCIAL_OFFICE", **defaults)


def residential_rate_schedule(**overrides) -> Dict[str, Any]:
    defaults = dict(
        code="RS-R",
        fixed_service_charge=250.00,
        demand_charge_per_kw=6.00,
        minimum_bill_amount=3000.00,
        tiers=[
            {"load_factor_max": 30.0, "energy_rate_per_mwh": 110.00},
            {"load_factor_max": 70.0, "energy_rate_per_mwh": 95.00},
            {"load_factor_max": 100.0, "energy_rate_per_mwh": 82.00},
        ],
    )
    defaults.update(overrides)
    return create_rate_schedule("RESIDENTIAL_MULTIFAMILY", **defaults)


def industrial_rate_schedule(**overrides) -> Dict[str, Any]:
    defaults = dict(
        code="RS-I",
        fixed_service_charge=2000.00,
        demand_charge_per_kw=9.00,
        minimum_bill_amount=6000.00,
        tiers=[
            {"load_factor_max": 40.0, "energy_rate_per_mwh": 70.00},
            {"load_factor_max": 100.0, "energy_rate_per_mwh": 58.00},
        ],
    )
    defaults.update(overrides)
    return create_rate_schedule("INDUSTRIAL_PROCESS", **defaults)


def university_rate_schedule(**overrides) -> Dict[str, Any]:
    defaults = dict(
        code="RS-U",
        fixed_service_charge=1500.00,
        demand_charge_per_kw=11.00,
        minimum_bill_amount=4500.00,
        tiers=[
            {"load_factor_max": 35.0, "energy_rate_per_mwh": 85.00},
            {"load_factor_max": 100.0, "energy_rate_per_mwh": 66.00},
        ],
    )
    defaults.update(overrides)
    return create_rate_schedule("UNIVERSITY", **defaults)


# ─── Whole-network stacks ──────────────────────────────────────────────────


def three_fuel_fleet(loop_id: str) -> Dict[str, Any]:
    """A gas, biomass and oil supply plus one storage unit and three generators.

    Costs are ordered so the merit list is storage, then combined heat and power,
    then biomass, then oil, and the fuels are spread widely enough that a plan
    drawing on all of them clears the concentration ceiling.
    """
    gas = create_fuel_contract(
        supplier_code="FCG-C",
        fuel_type="NATURAL_GAS",
        contracted_energy_mwh_per_year=40000.0,
        price_per_mwh=30.00,
        delivery_firmness="FIRM",
    )
    biomass = create_fuel_contract(
        supplier_code="FCB-C",
        fuel_type="BIOMASS",
        contracted_energy_mwh_per_year=20000.0,
        price_per_mwh=42.00,
        delivery_firmness="INTERRUPTIBLE",
    )
    oil = create_fuel_contract(
        supplier_code="FCO-C",
        fuel_type="FUEL_OIL",
        contracted_energy_mwh_per_year=8000.0,
        price_per_mwh=80.00,
        delivery_firmness="FIRM",
    )
    storage = create_asset(
        loop_id,
        code="C_STO",
        asset_type="THERMAL_STORAGE",
        rated_capacity_kw=1000.0,
        marginal_cost_per_mwh=6.00,
        emission_factor_kg_per_mwh=0.0,
        storage_capacity_kwh=4000.0,
        state_of_charge_kwh=4000.0,
    )
    chp = create_asset(
        loop_id,
        code="C_CHP",
        asset_type="CHP",
        rated_capacity_kw=1200.0,
        marginal_cost_per_mwh=40.00,
        emission_factor_kg_per_mwh=205.0,
        fuel_contract_id=gas["id"],
        derated_capacity_kw=600.0,
        min_stable_output_kw=400.0,
    )
    bio = create_asset(
        loop_id,
        code="C_BIO",
        asset_type="BIOMASS_BOILER",
        rated_capacity_kw=1500.0,
        marginal_cost_per_mwh=52.00,
        emission_factor_kg_per_mwh=28.0,
        fuel_contract_id=biomass["id"],
        derated_capacity_kw=750.0,
        min_stable_output_kw=300.0,
    )
    boiler = create_asset(
        loop_id,
        code="C_OIL",
        asset_type="BOILER",
        rated_capacity_kw=2000.0,
        marginal_cost_per_mwh=90.00,
        emission_factor_kg_per_mwh=260.0,
        fuel_contract_id=oil["id"],
        derated_capacity_kw=1000.0,
        min_stable_output_kw=200.0,
    )
    return {
        "gas_contract": gas,
        "biomass_contract": biomass,
        "oil_contract": oil,
        "storage": storage,
        "chp": chp,
        "biomass_boiler": bio,
        "oil_boiler": boiler,
    }


def campus_dispatch_stack(plan_state: Optional[str] = None) -> Dict[str, Any]:
    """The campus loop with one commercial customer, a full fleet and a forecast.

    The published forecast for 2026-08-05 under a full weekday profile with no
    degree hours calls for 2527.20 kW, which the merit list can serve out of
    storage, the combined heat and power unit and the biomass boiler.
    ``plan_state`` optionally walks a plan to DRAFT, OPTIMIZED, SUBMITTED,
    APPROVED or COMMITTED.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-C",
        name="Campus Loop C",
        service_mode="DUAL",
        design_supply_temp_c=90.0,
        max_pressure_kpa=1400.0,
        rated_capacity_kw=8000.0,
    )
    tariff = commercial_rate_schedule()
    agreement = active_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Campus Facilities",
        customer_class="COMMERCIAL_OFFICE",
        reserved_capacity_kw=3000.0,
        service_mode="DUAL",
    )
    fleet = three_fuel_fleet(loop["id"])
    forecast = published_forecast(loop["id"], "2026-08-05T00:00:00Z", occupancy_profile="WEEKDAY_FULL")
    stack: Dict[str, Any] = {
        "loop": loop,
        "tariff": tariff,
        "agreement": agreement,
        "forecast": forecast,
        **fleet,
    }
    if plan_state is not None:
        stack["plan"] = plan_in_state(plan_state, loop["id"], forecast["id"])
    return stack


def hospital_billing_stack() -> Dict[str, Any]:
    """A hospital customer with one commissioned meter and a June register history.

    The three reads cover 2026-06-01 through 2026-06-30 and rise monotonically,
    so a June invoice has both an opening and a closing read to work from.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-A",
        name="Downtown Loop A",
        service_mode="DUAL",
        design_supply_temp_c=95.0,
        max_pressure_kpa=1600.0,
        rated_capacity_kw=9000.0,
    )
    segment = create_segment(
        loop["id"],
        code="SEG-A1",
        length_m=400.0,
        diameter_mm=200,
        install_year=2016,
        insulation_class="A",
        buried_depth_m=1.2,
    )
    tariff = hospital_rate_schedule()
    agreement = active_agreement(
        loop["id"],
        tariff["id"],
        customer_name="City Hospital",
        customer_class="HOSPITAL",
        reserved_capacity_kw=4000.0,
        service_mode="DUAL",
    )
    point = commissioned_point(agreement["id"], segment["id"], code="MP1", multiplier=1.0)
    readings = add_readings(
        point["id"],
        [
            {
                "read_at": "2026-06-01T00:00:00Z",
                "cumulative_energy_mwh": 1000.000,
                "peak_demand_kw": 2600.0,
                "read_type": "ACTUAL",
            },
            {
                "read_at": "2026-06-15T00:00:00Z",
                "cumulative_energy_mwh": 1420.500,
                "peak_demand_kw": 3100.0,
                "read_type": "ACTUAL",
            },
            {
                "read_at": "2026-06-30T00:00:00Z",
                "cumulative_energy_mwh": 1900.250,
                "peak_demand_kw": 2900.0,
                "read_type": "ESTIMATED",
            },
        ],
    )
    return {
        "loop": loop,
        "segment": segment,
        "tariff": tariff,
        "agreement": agreement,
        "point": point,
        "readings": readings,
    }


def riverside_residential_stack() -> Dict[str, Any]:
    """A heating-only loop carrying three multifamily customers.

    Reserved capacities of 1010, 2035 and 3060 kW are deliberately awkward so
    each customer's diversified contribution has to be rounded on its own before
    the coincident total is formed.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-B",
        name="Riverside Loop B",
        service_mode="HEATING",
        design_supply_temp_c=85.0,
        max_pressure_kpa=1200.0,
        rated_capacity_kw=6000.0,
    )
    tariff = residential_rate_schedule()
    agreements = [
        active_agreement(
            loop["id"],
            tariff["id"],
            customer_name=name,
            customer_class="RESIDENTIAL_MULTIFAMILY",
            reserved_capacity_kw=reserved,
            service_mode="HEATING",
        )
        for name, reserved in (
            ("Elm Court", 1010.0),
            ("Birch Flats", 2035.0),
            ("Cedar Row", 3060.0),
        )
    ]
    return {"loop": loop, "tariff": tariff, "agreements": agreements}


def industrial_boundary_stack() -> Dict[str, Any]:
    """A loop whose fleet brackets the minimum-stable-output threshold.

    Four generators share a 2052.00 kW call: two 750 kW units clear first, the
    third can only take 552.00 kW, and the fourth's floor of 552.01 kW sits one
    hundredth above the remainder so it must be passed over.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-E",
        name="Eastside Loop E",
        service_mode="HEATING",
        design_supply_temp_c=100.0,
        max_pressure_kpa=1500.0,
        rated_capacity_kw=2000.0,
    )
    tariff = industrial_rate_schedule()
    agreement = active_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Eastside Processing",
        customer_class="INDUSTRIAL_PROCESS",
        reserved_capacity_kw=2000.0,
        service_mode="HEATING",
    )
    gas = create_fuel_contract(
        supplier_code="FCG-E",
        fuel_type="NATURAL_GAS",
        contracted_energy_mwh_per_year=30000.0,
        price_per_mwh=28.00,
        delivery_firmness="FIRM",
    )
    biomass = create_fuel_contract(
        supplier_code="FCB-E",
        fuel_type="BIOMASS",
        contracted_energy_mwh_per_year=15000.0,
        price_per_mwh=40.00,
        delivery_firmness="FIRM",
    )
    oil = create_fuel_contract(
        supplier_code="FCO-E",
        fuel_type="FUEL_OIL",
        contracted_energy_mwh_per_year=9000.0,
        price_per_mwh=75.00,
        delivery_firmness="FIRM",
    )
    electric = create_fuel_contract(
        supplier_code="FCE-E",
        fuel_type="ELECTRICITY",
        contracted_energy_mwh_per_year=6000.0,
        price_per_mwh=95.00,
        delivery_firmness="INTERRUPTIBLE",
    )
    cheapest = create_asset(
        loop["id"],
        code="E_A",
        asset_type="BOILER",
        rated_capacity_kw=750.0,
        marginal_cost_per_mwh=30.00,
        emission_factor_kg_per_mwh=220.0,
        fuel_contract_id=gas["id"],
        derated_capacity_kw=375.0,
        min_stable_output_kw=100.0,
    )
    second = create_asset(
        loop["id"],
        code="E_D",
        asset_type="BIOMASS_BOILER",
        rated_capacity_kw=750.0,
        marginal_cost_per_mwh=32.00,
        emission_factor_kg_per_mwh=30.0,
        fuel_contract_id=biomass["id"],
        derated_capacity_kw=375.0,
        min_stable_output_kw=100.0,
    )
    just_above = create_asset(
        loop["id"],
        code="E_C",
        asset_type="BOILER",
        rated_capacity_kw=1000.0,
        marginal_cost_per_mwh=35.00,
        emission_factor_kg_per_mwh=260.0,
        fuel_contract_id=oil["id"],
        derated_capacity_kw=500.0,
        min_stable_output_kw=552.01,
    )
    exactly_equal = create_asset(
        loop["id"],
        code="E_B",
        asset_type="CHP",
        rated_capacity_kw=800.0,
        marginal_cost_per_mwh=40.00,
        emission_factor_kg_per_mwh=10.0,
        fuel_contract_id=electric["id"],
        derated_capacity_kw=400.0,
        min_stable_output_kw=552.00,
    )
    forecast = published_forecast(loop["id"], "2026-08-06T00:00:00Z", occupancy_profile="WEEKDAY_FULL")
    return {
        "loop": loop,
        "tariff": tariff,
        "agreement": agreement,
        "cheapest": cheapest,
        "second": second,
        "just_above_remainder": just_above,
        "exactly_at_remainder": exactly_equal,
        "forecast": forecast,
    }


def industrial_leak_stack() -> Dict[str, Any]:
    """An old, poorly insulated segment already surveyed into the suspect band.

    SEG-G1 is a 1986 class C run whose makeup-water ratio and leak history put
    its risk score at 79.42, which carries the loop into a constrained posture;
    SEG-G9 is a modern class A run that stays sound for contrast.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-G",
        name="Industrial Loop G",
        service_mode="HEATING",
        design_supply_temp_c=110.0,
        max_pressure_kpa=2000.0,
        rated_capacity_kw=20000.0,
    )
    suspect_segment = create_segment(
        loop["id"],
        code="SEG-G1",
        length_m=1200.0,
        diameter_mm=300,
        install_year=1986,
        insulation_class="C",
        buried_depth_m=1.5,
    )
    sound_segment = create_segment(
        loop["id"],
        code="SEG-G9",
        length_m=900.0,
        diameter_mm=250,
        install_year=2010,
        insulation_class="A",
        buried_depth_m=1.3,
    )
    assessed = assess_segment(suspect_segment["id"], 0.06, 2, "C")
    return {
        "loop": loop,
        "suspect_segment": assessed,
        "sound_segment": sound_segment,
    }


def midtown_reservation_stack() -> Dict[str, Any]:
    """A loop with two pending customers, one of which already has a meter.

    Reservations of 3000 and 2000 kW against a 10000 kW loop leave room for both,
    so the running reserved total can be watched across activation, suspension
    and termination.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-M",
        name="Midtown Loop M",
        service_mode="HEATING",
        design_supply_temp_c=98.0,
        max_pressure_kpa=1450.0,
        rated_capacity_kw=10000.0,
    )
    segment = create_segment(
        loop["id"],
        code="SEG-M1",
        length_m=500.0,
        diameter_mm=150,
        install_year=2012,
        insulation_class="A",
        buried_depth_m=1.2,
    )
    tariff = commercial_rate_schedule()
    larger = create_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Midtown Plaza",
        customer_class="COMMERCIAL_OFFICE",
        reserved_capacity_kw=3000.0,
        service_mode="HEATING",
    )
    smaller = create_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Midtown Annex",
        customer_class="COMMERCIAL_OFFICE",
        reserved_capacity_kw=2000.0,
        service_mode="HEATING",
    )
    point = create_point(larger["id"], segment["id"], code="MP-M1", multiplier=1.0)
    return {
        "loop": loop,
        "segment": segment,
        "tariff": tariff,
        "larger": larger,
        "smaller": smaller,
        "point": point,
    }


def capacity_sweep_stack() -> Dict[str, Any]:
    """A 20000 kW loop already carrying overlapping reservations.

    Three live customers hold 22000 kW between them across staggered service
    windows, one of which ends exactly on 2026-06-01, so two waiting candidates
    of 5000.01 and 5000.00 kW straddle the oversubscription ceiling of 23000.00.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-K",
        name="Campus Loop K",
        service_mode="HEATING",
        design_supply_temp_c=95.0,
        max_pressure_kpa=1600.0,
        rated_capacity_kw=20000.0,
    )
    tariff = commercial_rate_schedule()

    def peer(name: str, reserved: float, start: str, end: str) -> Dict[str, Any]:
        return active_agreement(
            loop["id"],
            tariff["id"],
            customer_name=name,
            customer_class="COMMERCIAL_OFFICE",
            reserved_capacity_kw=reserved,
            service_mode="HEATING",
            service_start_date=start,
            service_end_date=end,
        )

    early = peer("Peer K1", 9000.0, "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z")
    spanning = peer("Peer K2", 9000.0, "2026-04-01T00:00:00Z", "2026-10-01T00:00:00Z")
    ends_on_boundary = peer("Peer K4", 4000.0, "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z")
    over_ceiling = create_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Candidate K5",
        customer_class="COMMERCIAL_OFFICE",
        reserved_capacity_kw=5000.01,
        service_mode="HEATING",
        service_start_date="2026-06-01T00:00:00Z",
        service_end_date="2026-12-01T00:00:00Z",
    )
    at_ceiling = create_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Candidate K3",
        customer_class="COMMERCIAL_OFFICE",
        reserved_capacity_kw=5000.0,
        service_mode="HEATING",
        service_start_date="2026-06-01T00:00:00Z",
        service_end_date="2026-12-01T00:00:00Z",
    )
    return {
        "loop": loop,
        "tariff": tariff,
        "early": early,
        "spanning": spanning,
        "ends_on_boundary": ends_on_boundary,
        "over_ceiling": over_ceiling,
        "at_ceiling": at_ceiling,
    }


def work_window_stack() -> Dict[str, Any]:
    """One segment with a permitted job and two candidates around its buffer.

    The peer job runs 08:00 to 16:00 on 2026-09-01; adding the refill buffer
    pushes its exclusion zone out to 22:00, and the two candidates start at
    exactly 22:00 and one minute later.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-K",
        name="Campus Loop K",
        service_mode="HEATING",
        design_supply_temp_c=95.0,
        max_pressure_kpa=1600.0,
        rated_capacity_kw=20000.0,
    )
    segment = create_segment(
        loop["id"],
        code="SEG-K1",
        length_m=700.0,
        diameter_mm=200,
        install_year=2004,
        insulation_class="B",
        buried_depth_m=1.5,
    )
    peer = create_work_order(
        segment["id"],
        loop["id"],
        "2026-09-01T08:00:00Z",
        "2026-09-01T16:00:00Z",
        work_type="VALVE_REPLACEMENT",
        requires_isolation=False,
    )
    submit_permit(peer["id"])
    on_buffer_end = create_work_order(
        segment["id"],
        loop["id"],
        "2026-09-01T22:00:00Z",
        "2026-09-02T02:00:00Z",
        work_type="INSPECTION",
        requires_isolation=False,
    )
    after_buffer_end = create_work_order(
        segment["id"],
        loop["id"],
        "2026-09-01T22:01:00Z",
        "2026-09-02T02:00:00Z",
        work_type="INSPECTION",
        requires_isolation=False,
    )
    return {
        "loop": loop,
        "segment": segment,
        "peer": peer,
        "on_buffer_end": on_buffer_end,
        "after_buffer_end": after_buffer_end,
    }


def single_asset_stack() -> Dict[str, Any]:
    """A hilltop loop with exactly one biomass generator and one customer.

    A fleet of one makes both the fuel-concentration ceiling and the reserve
    margin bite, and leaves room to publish a second forecast that supersedes
    the first.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-H",
        name="Hilltop Loop H",
        service_mode="HEATING",
        design_supply_temp_c=88.0,
        max_pressure_kpa=1250.0,
        rated_capacity_kw=5000.0,
    )
    tariff = university_rate_schedule()
    agreement = active_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Hilltop University",
        customer_class="UNIVERSITY",
        reserved_capacity_kw=1000.0,
        service_mode="HEATING",
    )
    contract = create_fuel_contract(
        supplier_code="FCB-H",
        fuel_type="BIOMASS",
        contracted_energy_mwh_per_year=12000.0,
        price_per_mwh=44.00,
        delivery_firmness="FIRM",
    )
    asset = create_asset(
        loop["id"],
        code="H_B",
        asset_type="BIOMASS_BOILER",
        rated_capacity_kw=1200.0,
        marginal_cost_per_mwh=50.00,
        emission_factor_kg_per_mwh=25.0,
        fuel_contract_id=contract["id"],
        derated_capacity_kw=600.0,
        min_stable_output_kw=50.0,
    )
    return {
        "loop": loop,
        "tariff": tariff,
        "agreement": agreement,
        "contract": contract,
        "asset": asset,
    }


def empty_customer_stack() -> Dict[str, Any]:
    """A loop whose only live customer has already reached its end of service.

    One customer's service window closes exactly on 2026-08-01 and the other is
    still waiting on capacity, so a forecast for that date has no contributors.
    """
    set_clock()
    loop = create_loop(
        code="LOOP-F",
        name="Fairview Loop F",
        service_mode="DUAL",
        design_supply_temp_c=92.0,
        max_pressure_kpa=1300.0,
        rated_capacity_kw=5000.0,
    )
    tariff = university_rate_schedule()
    expiring = active_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Fairview College",
        customer_class="UNIVERSITY",
        reserved_capacity_kw=1000.0,
        service_mode="DUAL",
        service_start_date="2026-01-01T00:00:00Z",
        service_end_date="2026-08-01T00:00:00Z",
    )
    pending = create_agreement(
        loop["id"],
        tariff["id"],
        customer_name="Fairview Annex",
        customer_class="UNIVERSITY",
        reserved_capacity_kw=800.0,
        service_mode="DUAL",
    )
    return {"loop": loop, "tariff": tariff, "expiring": expiring, "pending": pending}


__all__ = [
    "set_clock",
    "create_loop",
    "read_loop",
    "loop_version",
    "create_segment",
    "assess_segment",
    "create_fuel_contract",
    "set_fuel_contract_status",
    "create_asset",
    "set_availability",
    "read_asset",
    "create_rate_schedule",
    "create_agreement",
    "activate_agreement",
    "set_agreement_state",
    "read_agreement",
    "agreement_version",
    "active_agreement",
    "create_forecast",
    "publish_forecast",
    "published_forecast",
    "read_forecast",
    "create_plan",
    "optimize_plan",
    "submit_plan",
    "review_plan",
    "commit_plan",
    "decommit_plan",
    "read_plan",
    "plan_orders",
    "plan_in_state",
    "create_point",
    "commission_point",
    "remove_point",
    "commissioned_point",
    "add_reading",
    "add_readings",
    "create_invoice",
    "issue_invoice",
    "adjust_invoice",
    "pay_invoice",
    "void_invoice",
    "read_invoice",
    "invoice_in_state",
    "create_work_order",
    "submit_permit",
    "decide_permit",
    "begin_excavation",
    "begin_repair",
    "backfill_work_order",
    "complete_work_order",
    "read_work_order",
    "work_order_in_state",
    "create_project",
    "size_project",
    "decide_project",
    "convert_project",
    "read_project",
    "project_in_state",
    "hospital_rate_schedule",
    "commercial_rate_schedule",
    "residential_rate_schedule",
    "industrial_rate_schedule",
    "university_rate_schedule",
    "three_fuel_fleet",
    "campus_dispatch_stack",
    "hospital_billing_stack",
    "riverside_residential_stack",
    "industrial_boundary_stack",
    "industrial_leak_stack",
    "midtown_reservation_stack",
    "capacity_sweep_stack",
    "work_window_stack",
    "single_asset_stack",
    "empty_customer_stack",
]
