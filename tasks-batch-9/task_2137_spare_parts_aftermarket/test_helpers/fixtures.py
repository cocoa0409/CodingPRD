"""Composite setup helpers.

Every test starts against an empty database, so each helper builds the whole
precondition chain from PRD-declared endpoints only.  Setup calls use the
lenient validator so a broken precondition reports as a setup failure.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_allocation_request_payload, create_campaign_payload,
    create_dealer_payload, create_equipment_model_payload,
    create_forecast_payload, create_installed_unit_payload,
    create_part_applicability_payload, create_part_line_payload,
    create_part_payload, create_price_rule_payload,
    create_replenishment_order_payload, create_return_authorization_payload,
    create_work_order_payload,
)
from .test_users import TEST_USERS, make_dealer_headers

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
PRICING = TEST_USERS["pricing_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Tier 0: single-step primitives ─────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_price_rule(criticality_class="DESIRABLE", base_uplift_pct=0.35,
                      max_uplift_pct=0.60, min_margin_pct=0.20) -> dict:
    return get_success_data(api_client.create_price_rule(
        create_price_rule_payload(criticality_class, base_uplift_pct,
                                  max_uplift_pct, min_margin_pct), PRICING))


def create_dealer(dealer_code="D-0001", tier="GOLD", region="NA",
                  credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"]) -> dict:
    return get_success_data(api_client.create_dealer(
        create_dealer_payload(dealer_code=dealer_code, tier=tier, region=region,
                              credit_limit_cents=credit_limit_cents), ADMIN))


def create_equipment_model(model_code="EM-0001", name="Test machine model") -> dict:
    return get_success_data(api_client.create_equipment_model(
        create_equipment_model_payload(model_code=model_code, name=name), ADMIN))


def create_installed_unit(model_id, dealer_id, serial_number="SN-0001",
                          build_revision=TEST_DEFAULTS["BUILD_REVISION"],
                          region="NA") -> dict:
    return get_success_data(api_client.create_installed_unit(
        create_installed_unit_payload(model_id, dealer_id,
                                      serial_number=serial_number,
                                      build_revision=build_revision,
                                      region=region), ADMIN))


def create_part(part_number="PN-0001", description="Test spare part",
                unit_cost_cents=TEST_DEFAULTS["UNIT_COST_CENTS"],
                lead_time_days=TEST_DEFAULTS["LEAD_TIME_DAYS"],
                weight_kg=TEST_DEFAULTS["WEIGHT_KG"],
                hazmat=None, max_stock_units=None) -> dict:
    payload = create_part_payload(part_number=part_number, description=description,
                                  unit_cost_cents=unit_cost_cents,
                                  lead_time_days=lead_time_days, weight_kg=weight_kg)
    if hazmat is not None:
        payload["hazmat"] = hazmat
    if max_stock_units is not None:
        payload["max_stock_units"] = max_stock_units
    return get_success_data(api_client.create_part(payload, PLANNER))


def create_applicability(part_id, model_id, effective_from_build_revision=0,
                         effective_to_build_revision=None, qty_per_unit=1) -> dict:
    payload = create_part_applicability_payload(
        part_id, model_id,
        effective_from_build_revision=effective_from_build_revision,
        qty_per_unit=qty_per_unit)
    if effective_to_build_revision is not None:
        payload["effective_to_build_revision"] = effective_to_build_revision
    return get_success_data(api_client.create_part_applicability(payload, PLANNER))


def create_work_order(installed_unit_id, dealer_id,
                      work_type="SCHEDULED_MAINTENANCE",
                      downtime_priority="PLANNED") -> dict:
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(installed_unit_id, work_type=work_type,
                                  downtime_priority=downtime_priority),
        make_dealer_headers(dealer_id)))


def add_part_line(work_order_id, dealer_id, part_id, qty_requested) -> dict:
    return get_success_data(api_client.create_part_line(
        work_order_id, create_part_line_payload(part_id, qty_requested),
        make_dealer_headers(dealer_id)))


def consume_line(line_id, dealer_id, qty_consumed) -> dict:
    return get_success_data(
        api_client.consume_part_line(line_id, qty_consumed,
                                     make_dealer_headers(dealer_id)))


def close_work_order(work_order_id, dealer_id) -> dict:
    return get_success_data(
        api_client.close_work_order(work_order_id, make_dealer_headers(dealer_id)))


def adjust_balance(dealer_id, amount_cents, reason="test adjustment") -> dict:
    return get_success_data(
        api_client.adjust_dealer_balance(dealer_id, amount_cents, reason, ADMIN))


def create_forecast(part_id, horizon_months=12, method="INSTALLED_BASE_RATE",
                    lookback_days=None) -> dict:
    payload = create_forecast_payload(horizon_months=horizon_months, method=method)
    if lookback_days is not None:
        payload["lookback_days"] = lookback_days
    return get_success_data(api_client.create_forecast(part_id, payload, PLANNER))


def classify_part(part_id) -> dict:
    return get_success_data(api_client.classify_part(part_id, PLANNER))


def phase_out_part(part_id) -> dict:
    return get_success_data(api_client.phase_out_part(part_id, PLANNER))


def read_part(part_id) -> dict:
    return get_success_data(api_client.get_part(part_id, PLANNER))


def read_dealer(dealer_id) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, ADMIN))


def read_work_order(work_order_id) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, PLANNER))


def read_part_line(line_id) -> dict:
    return get_success_data(api_client.get_part_line(line_id, PLANNER))


def read_campaign(campaign_id) -> dict:
    return get_success_data(api_client.get_campaign(campaign_id, PLANNER))


def read_allocation_request(request_id) -> dict:
    return get_success_data(api_client.get_allocation_request(request_id, PLANNER))


def read_replenishment_order(order_id) -> dict:
    return get_success_data(api_client.get_replenishment_order(order_id, CONTROLLER))


def read_return_authorization(return_id) -> dict:
    return get_success_data(api_client.get_return_authorization(return_id, PLANNER))


def read_installed_unit(unit_id) -> dict:
    return get_success_data(api_client.get_installed_unit(unit_id, ADMIN))


def read_applicability(applicability_id) -> dict:
    return get_success_data(api_client.get_part_applicability(applicability_id, PLANNER))


def part_version(part_id) -> int:
    return read_part(part_id)["version"]


def campaign_version(campaign_id) -> int:
    return read_campaign(campaign_id)["version"]


def list_ledger(part_id) -> tuple:
    return validate_paginated(
        api_client.list_ledger_entries(part_id, CONTROLLER, params={"limit": 100}))


def list_auto_replenishment_orders(part_id) -> tuple:
    return validate_paginated(api_client.list_replenishment_orders(
        CONTROLLER, params={"part_id": part_id, "auto_generated": "true"}))


# ─── Tier 1: stock progression ──────────────────────────────────────────────

def receive_stock(part_id, qty) -> dict:
    """Raise a STOCK replenishment order and walk it approve -> ship -> receive
    so the part ends with `qty` more units on hand.  Returns the order."""
    order = get_success_data(api_client.create_replenishment_order(
        create_replenishment_order_payload(part_id, "STOCK", qty), CONTROLLER))
    oid = order["id"]
    get_success_data(api_client.approve_replenishment_order(oid, CONTROLLER))
    get_success_data(api_client.ship_replenishment_order(oid, CONTROLLER))
    return get_success_data(api_client.receive_replenishment_order(oid, CONTROLLER))


def ship_stock_order(part_id, qty) -> dict:
    """Raise a STOCK order and walk it only as far as IN_TRANSIT."""
    order = get_success_data(api_client.create_replenishment_order(
        create_replenishment_order_payload(part_id, "STOCK", qty), CONTROLLER))
    oid = order["id"]
    get_success_data(api_client.approve_replenishment_order(oid, CONTROLLER))
    return get_success_data(api_client.ship_replenishment_order(oid, CONTROLLER))


# ─── Tier 2: catalogue + registry scenario ──────────────────────────────────

def setup_catalogue(
    part_number="PN-0001",
    unit_cost_cents=TEST_DEFAULTS["UNIT_COST_CENTS"],
    lead_time_days=TEST_DEFAULTS["LEAD_TIME_DAYS"],
    weight_kg=TEST_DEFAULTS["WEIGHT_KG"],
    hazmat=None,
    max_stock_units=None,
    dealer_code="D-0001",
    dealer_tier="GOLD",
    dealer_region="NA",
    credit_limit_cents=TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    model_code="EM-0001",
    installed_units=1,
    build_revision=TEST_DEFAULTS["BUILD_REVISION"],
    serial_prefix="SN",
    qty_per_unit=1,
    applicability_from=0,
    applicability_to=None,
    with_applicability=True,
    price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),),
    stock_units=0,
) -> dict:
    """Publish price rules, register a dealer, a model, N installed units, a
    part and its applicability row, then optionally receive opening stock.

    Returns a dict with keys: rules, dealer, dealer_headers, model, units,
    part, applicability.
    """
    rules = [create_price_rule(*r) for r in price_rules]
    dealer = create_dealer(dealer_code, dealer_tier, dealer_region, credit_limit_cents)
    model = create_equipment_model(model_code, f"Model {model_code}")
    units = [
        create_installed_unit(model["id"], dealer["id"],
                              serial_number=f"{serial_prefix}-{i + 1:04d}",
                              build_revision=build_revision, region=dealer_region)
        for i in range(installed_units)
    ]
    part = create_part(part_number, f"Part {part_number}", unit_cost_cents,
                       lead_time_days, weight_kg, hazmat, max_stock_units)
    applicability = None
    if with_applicability:
        applicability = create_applicability(part["id"], model["id"],
                                             applicability_from, applicability_to,
                                             qty_per_unit)
    if stock_units:
        receive_stock(part["id"], stock_units)
    return {
        "rules": rules,
        "dealer": dealer,
        "dealer_headers": make_dealer_headers(dealer["id"]),
        "model": model,
        "units": units,
        "unit": units[0] if units else None,
        "part": part,
        "applicability": applicability,
    }


def setup_open_work_order(scenario, work_type="SCHEDULED_MAINTENANCE",
                          downtime_priority="PLANNED", unit_index=0) -> dict:
    """Open a work order on one of the scenario's installed units."""
    unit = scenario["units"][unit_index]
    return create_work_order(unit["id"], scenario["dealer"]["id"],
                             work_type, downtime_priority)


def setup_scenario_with_work_order(work_type="SCHEDULED_MAINTENANCE",
                                   downtime_priority="PLANNED", **kwargs) -> dict:
    """setup_catalogue plus one OPEN work order.  Returns the scenario dict
    extended with a `work_order` key."""
    scenario = setup_catalogue(**kwargs)
    scenario["work_order"] = setup_open_work_order(scenario, work_type,
                                                   downtime_priority)
    return scenario


# ─── Tier 3: consumed-line and closed-work-order shortcuts ──────────────────

def consume_on_new_work_order(scenario, qty, work_type="SCHEDULED_MAINTENANCE",
                              downtime_priority="PLANNED", unit_index=0,
                              close=False) -> dict:
    """Open a work order, add one RESERVED line for `qty`, consume all of it and
    optionally close the work order.  Returns {work_order, line}."""
    dealer_id = scenario["dealer"]["id"]
    unit = scenario["units"][unit_index]
    wo = create_work_order(unit["id"], dealer_id, work_type, downtime_priority)
    line = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], qty)
    line = consume_line(line["id"], dealer_id, qty)
    if close:
        wo = close_work_order(wo["id"], dealer_id)
    return {"work_order": wo, "line": line}


def setup_consumed_line(part_number="PN-0001", qty=7, stock_units=20,
                        unit_cost_cents=TEST_DEFAULTS["UNIT_COST_CENTS"],
                        **kwargs) -> dict:
    """Full chain up to one CONSUMED line: rules, dealer, model, unit, part,
    applicability, opening stock, work order, line, consume."""
    scenario = setup_catalogue(part_number=part_number, stock_units=stock_units,
                               unit_cost_cents=unit_cost_cents, **kwargs)
    consumed = consume_on_new_work_order(scenario, qty)
    scenario.update(consumed)
    return scenario


def setup_received_rma(qty_returned, return_reason, clock_after=None,
                       **consumed_kwargs) -> dict:
    """Consume a line, optionally advance the clock, then raise an RMA and walk
    it approve -> receive.  Returns the scenario extended with `rma`."""
    scenario = setup_consumed_line(**consumed_kwargs)
    if clock_after:
        set_clock(clock_after)
    rma = create_rma(scenario["line"]["id"], scenario["dealer"]["id"],
                     qty_returned, return_reason)
    approve_rma(rma["id"])
    scenario["rma"] = receive_rma(rma["id"])
    return scenario


def create_rma(line_id, dealer_id, qty_returned, return_reason) -> dict:
    return get_success_data(api_client.create_return_authorization(
        create_return_authorization_payload(line_id, qty_returned, return_reason),
        make_dealer_headers(dealer_id)))


def approve_rma(return_id) -> dict:
    return get_success_data(api_client.approve_return_authorization(return_id, PLANNER))


def receive_rma(return_id) -> dict:
    return get_success_data(api_client.receive_return_authorization(return_id, PLANNER))


def inspect_rma(return_id, disposition) -> dict:
    return get_success_data(
        api_client.inspect_return_authorization(return_id, disposition, PLANNER))


# ─── Tier 4: obsolescence lifecycle ─────────────────────────────────────────

def create_campaign_for(part_id, method="FLAT_RATE", coverage_years=3,
                        ltb_window_start=TEST_DEFAULTS["LTB_WINDOW_START"],
                        ltb_window_end=TEST_DEFAULTS["LTB_WINDOW_END"],
                        expected_part_version=None) -> dict:
    if expected_part_version is None:
        expected_part_version = part_version(part_id)
    payload = create_campaign_payload(
        part_id, expected_part_version, method=method,
        coverage_years=coverage_years, ltb_window_start=ltb_window_start,
        ltb_window_end=ltb_window_end)
    return get_success_data(api_client.create_campaign(payload, PLANNER))


def submit_campaign(campaign_id, headers=None) -> dict:
    return get_success_data(
        api_client.submit_campaign(campaign_id, headers or PLANNER))


def approve_campaign(campaign_id, approved_qty, headers=None) -> dict:
    return get_success_data(
        api_client.approve_campaign(campaign_id, approved_qty, headers or CONTROLLER))


def create_allocation_request(campaign_id, dealer_id, requested_units,
                              expected_campaign_version=None) -> dict:
    if expected_campaign_version is None:
        expected_campaign_version = campaign_version(campaign_id)
    payload = create_allocation_request_payload(
        campaign_id, dealer_id, requested_units, expected_campaign_version)
    return get_success_data(
        api_client.create_allocation_request(payload, make_dealer_headers(dealer_id)))


def allocate_campaign(campaign_id) -> dict:
    return get_success_data(api_client.allocate_campaign(campaign_id, CONTROLLER))


def close_campaign(campaign_id) -> dict:
    return get_success_data(api_client.close_campaign(campaign_id, CONTROLLER))


def setup_approved_campaign(part_number="LTB-0001", approved_qty=100,
                            forecast_method="INSTALLED_BASE_RATE",
                            campaign_method="FLAT_RATE", coverage_years=3,
                            **catalogue_kwargs) -> dict:
    """Part driven to PHASE_OUT with a CURRENT 12-month forecast, a campaign
    drafted, submitted by the planner and approved by the controller."""
    scenario = setup_catalogue(part_number=part_number, **catalogue_kwargs)
    create_forecast(scenario["part"]["id"], 12, forecast_method)
    phase_out_part(scenario["part"]["id"])
    campaign = create_campaign_for(scenario["part"]["id"], campaign_method,
                                   coverage_years)
    submit_campaign(campaign["id"])
    scenario["campaign"] = approve_campaign(campaign["id"], approved_qty)
    return scenario


def drive_part_to_obsolete(scenario, approved_qty=5, allocating_dealer_id=None) -> dict:
    """Walk an already PHASE_OUT-ready part through campaign approve, allocate,
    close and finally obsolete.  Returns the campaign."""
    part_id = scenario["part"]["id"]
    campaign = scenario.get("campaign")
    if campaign is None:
        create_forecast(part_id, 12, "INSTALLED_BASE_RATE")
        phase_out_part(part_id)
        campaign = create_campaign_for(part_id)
        submit_campaign(campaign["id"])
        campaign = approve_campaign(campaign["id"], approved_qty)
    dealer_id = allocating_dealer_id or scenario["dealer"]["id"]
    create_allocation_request(campaign["id"], dealer_id, approved_qty)
    allocate_campaign(campaign["id"])
    close_campaign(campaign["id"])
    get_success_data(api_client.obsolete_part(part_id, PLANNER))
    return read_campaign(campaign["id"])
