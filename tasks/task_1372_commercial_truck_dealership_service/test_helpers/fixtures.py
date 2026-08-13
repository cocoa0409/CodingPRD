"""Composite setup helpers.

Every fixture builds preconditions from scratch via PRD-declared endpoints (the
harness restarts the server before each test, so each test starts empty).
Setup calls use the lenient get_success_data() so failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_account_payload, create_slot_pool_payload,
    create_factory_order_payload, create_trade_appraisal_payload,
    create_service_bay_payload, create_mobile_unit_payload,
    create_repair_order_payload, create_ro_labor_line_payload,
    create_ro_part_line_payload, create_service_booking_payload,
    create_warranty_claim_payload, create_part_payload,
    unique_vin,
)
from .test_users import TEST_USERS, make_fleet_customer_headers, make_warranty_admin_headers

ADMIN = TEST_USERS["admin_headers"]
SALES_MANAGER = TEST_USERS["sales_manager_headers"]
SALES_CONSULTANT = TEST_USERS["sales_consultant_headers"]
SERVICE_MANAGER = TEST_USERS["service_manager_headers"]
SERVICE_ADVISOR = TEST_USERS["service_advisor_headers"]
PARTS_REP = TEST_USERS["parts_counter_rep_headers"]
WARRANTY_ADMIN = TEST_USERS["warranty_admin_headers"]
OEM_ADJUDICATOR = TEST_USERS["oem_adjudicator_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


# --- clock / sweep -----------------------------------------------------------

def set_clock(to_iso8601: str):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    data = get_success_data(resp)
    assert "current_utc" in data, f"Setup failed: set_clock -> {data}"
    return data


def run_sweep() -> dict:
    resp = api_client.run_daily_sweep(ADMIN)
    data = get_success_data(resp)
    assert isinstance(data, dict), f"Setup failed: run-daily-sweep -> {data}"
    return data


# --- accounts ----------------------------------------------------------------

def create_account(account_type="RETAIL", tier=None, credit_limit_cents=None,
                   name=None) -> dict:
    overrides = {}
    if tier is not None:
        overrides["fleet_tier"] = tier
    if credit_limit_cents is not None:
        overrides["credit_limit_cents"] = credit_limit_cents
    if name is not None:
        overrides["account_name"] = name
    payload = create_customer_account_payload(account_type=account_type, **overrides)
    resp = api_client.create_customer_account(payload, SALES_MANAGER)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_customer_account -> {data}"
    return data


def create_fleet_account(tier="STANDARD", credit_limit_cents=100000000, name=None) -> dict:
    return create_account("FLEET", tier=tier, credit_limit_cents=credit_limit_cents, name=name)


# --- slot pools / factory orders ----------------------------------------------

def create_slot_pool(build_month="2026-08", vocation_group="STANDARD", capacity=5) -> dict:
    resp = api_client.create_factory_build_slot(
        create_slot_pool_payload(build_month=build_month, vocation_group=vocation_group,
                                 capacity=capacity),
        SALES_MANAGER)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_slot_pool -> {data}"
    return data


def get_slot(slot_id) -> dict:
    return get_success_data(api_client.get_factory_build_slot(slot_id, SALES_MANAGER))


def create_order(slot_id, account_id=None, chassis_model="M2_106", engine_option="DD13",
                 axle_config="A4X2", upfit_lines=None) -> dict:
    overrides = {}
    if account_id is not None:
        overrides["customer_account_id"] = account_id
    if upfit_lines is not None:
        overrides["upfit_lines"] = upfit_lines
    payload = create_factory_order_payload(
        factory_build_slot_id=slot_id, chassis_model=chassis_model,
        engine_option=engine_option, axle_config=axle_config, **overrides)
    resp = api_client.create_factory_order(payload, SALES_CONSULTANT)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_factory_order -> {data}"
    return data


def commit_order(order_id) -> dict:
    data = get_success_data(api_client.commit_factory_order(order_id, SALES_CONSULTANT))
    assert data.get("status") == "COMMITTED", f"Setup failed: commit -> {data}"
    return data


def create_shipped_order(slot_id=None, receive_date="2026-08-15T00:00:00Z",
                         **order_kw) -> dict:
    """Order driven to SHIPPED: commit at default clock, sweep promotes to
    IN_PRODUCTION at the first of the build month, second sweep at
    receive_date (>= first + 14 days) promotes to SHIPPED."""
    slot_id = slot_id or create_slot_pool()["id"]
    order = create_order(slot_id, **order_kw)
    commit_order(order["id"])
    run_sweep()  # COMMITTED -> IN_PRODUCTION (build month 2026-08 starts 2026-08-01)
    set_clock(receive_date)
    run_sweep()  # IN_PRODUCTION -> SHIPPED
    return get_success_data(api_client.get_factory_order(order["id"], SALES_MANAGER))


def receive_unit_from_order(order_id, vin=None, apr_bp=None) -> dict:
    """Receive a SHIPPED order; returns the created Unit (via GET)."""
    payload = {"vin": vin or unique_vin()}
    if apr_bp is not None:
        payload["apr_bp"] = apr_bp
    resp = api_client.receive_factory_order(order_id, payload, SALES_MANAGER)
    data = get_success_data(resp)
    unit_id = data.get("received_unit_id")
    assert unit_id, f"Setup failed: receive -> {data}"
    return get_success_data(api_client.get_unit(unit_id, CONTROLLER))


def create_new_unit(receive_date="2026-08-15T00:00:00Z", vin=None, apr_bp=None,
                    slot=None, **order_kw) -> dict:
    """Full chain: pool -> order -> commit -> build-cycle sweeps -> receive.
    Returns the NEW unit in IN_STOCK (invoice 10085000 for the default spec)."""
    slot = slot or create_slot_pool()
    order = create_shipped_order(slot_id=slot["id"], receive_date=receive_date, **order_kw)
    return receive_unit_from_order(order["id"], vin=vin, apr_bp=apr_bp)


def create_ready_unit(**kw) -> dict:
    """NEW unit inspected PASS -> READY."""
    unit = create_new_unit(**kw)
    data = get_success_data(api_client.inspect_unit(unit["id"], {"outcome": "PASS"}, SERVICE_MANAGER))
    assert data.get("status") == "READY", f"Setup failed: inspect PASS -> {data}"
    return get_success_data(api_client.get_unit(unit["id"], CONTROLLER))


# --- service resources / bookings ----------------------------------------------

def create_bay(bay_type="STANDARD", open_hour=None, close_hour=None) -> dict:
    overrides = {}
    if open_hour is not None:
        overrides["open_hour"] = open_hour
    if close_hour is not None:
        overrides["close_hour"] = close_hour
    resp = api_client.create_service_bay(
        create_service_bay_payload(bay_type=bay_type, **overrides), SERVICE_MANAGER)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_service_bay -> {data}"
    return data


def create_mobile_unit(default_travel_minutes=30) -> dict:
    resp = api_client.create_mobile_service_unit(
        create_mobile_unit_payload(default_travel_minutes=default_travel_minutes),
        SERVICE_MANAGER)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_mobile_service_unit -> {data}"
    return data


def create_bay_booking(ro_id, bay_id, start_at="2026-08-05T09:00:00Z",
                       end_at="2026-08-05T10:00:00Z") -> dict:
    resp = api_client.create_service_booking(
        create_service_booking_payload(repair_order_id=ro_id, service_bay_id=bay_id,
                                       start_at=start_at, end_at=end_at),
        SERVICE_ADVISOR)
    data = get_success_data(resp)
    assert data.get("status") == "BOOKED", f"Setup failed: create_bay_booking -> {data}"
    return data


def check_in_booking(booking_id) -> dict:
    data = get_success_data(api_client.check_in_booking(booking_id, SERVICE_ADVISOR))
    assert data.get("status") == "CHECKED_IN", f"Setup failed: check_in -> {data}"
    return data


# --- repair orders -------------------------------------------------------------

def create_repair_order(account_id, external_vin=None, unit_id=None,
                        promised_ready_at="2026-08-20T17:00:00Z",
                        labor_rate_cents=None, concern="customer concern") -> dict:
    overrides = {"concern": concern, "promised_ready_at": promised_ready_at}
    if unit_id is not None:
        overrides["unit_id"] = unit_id
        overrides["external_vin"] = None
        payload = {"customer_account_id": account_id, "unit_id": unit_id,
                   "concern": concern, "promised_ready_at": promised_ready_at}
    else:
        payload = create_repair_order_payload(
            customer_account_id=account_id,
            external_vin=external_vin or unique_vin(), **overrides)
    if labor_rate_cents is not None:
        payload["labor_rate_cents"] = labor_rate_cents
    resp = api_client.create_repair_order(payload, SERVICE_ADVISOR)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_repair_order -> {data}"
    return data


def add_labor_line(ro_id, hours=1.0, warranty_eligible=False, description="labor") -> dict:
    resp = api_client.create_repair_order_line(
        create_ro_labor_line_payload(repair_order_id=ro_id, hours=hours,
                                     warranty_eligible=warranty_eligible,
                                     description=description),
        SERVICE_ADVISOR)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: add_labor_line -> {data}"
    return data


def add_part_line(ro_id, part_id, quantity=1, warranty_eligible=False) -> dict:
    resp = api_client.create_repair_order_line(
        create_ro_part_line_payload(repair_order_id=ro_id, part_id=part_id,
                                    quantity=quantity, warranty_eligible=warranty_eligible),
        SERVICE_ADVISOR)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: add_part_line -> {data}"
    return data


def get_ro(ro_id) -> dict:
    return get_success_data(api_client.get_repair_order(ro_id, SERVICE_ADVISOR))


def get_account(account_id) -> dict:
    return get_success_data(api_client.get_customer_account(account_id, CONTROLLER))


def drive_ro_to_invoiced(account_id, labor_hours=1.0, labor_rate_cents=None,
                         warranty_eligible=False, part_id=None, part_qty=1,
                         promised_ready_at="2026-08-20T17:00:00Z",
                         booking_start="2026-08-05T09:00:00Z",
                         booking_end="2026-08-05T10:00:00Z") -> dict:
    """Full RO lifecycle to INVOICED: create -> line(s) -> submit -> approve ->
    bay booking -> check-in -> start -> complete -> invoice.
    Returns dict(account_id, ro, bay, booking)."""
    ro = create_repair_order(account_id, promised_ready_at=promised_ready_at,
                             labor_rate_cents=labor_rate_cents)
    add_labor_line(ro["id"], hours=labor_hours, warranty_eligible=warranty_eligible)
    if part_id is not None:
        add_part_line(ro["id"], part_id, quantity=part_qty,
                      warranty_eligible=warranty_eligible)
    data = get_success_data(api_client.submit_estimate(ro["id"], SERVICE_ADVISOR))
    assert data.get("auth_status") == "PENDING_APPROVAL", f"Setup failed: submit -> {data}"
    data = get_success_data(api_client.approve_estimate(
        ro["id"], make_fleet_customer_headers(account_id)))
    assert data.get("auth_status") == "APPROVED", f"Setup failed: approve -> {data}"
    bay = create_bay()
    booking = create_bay_booking(ro["id"], bay["id"], booking_start, booking_end)
    check_in_booking(booking["id"])
    data = get_success_data(api_client.start_work(ro["id"], SERVICE_ADVISOR))
    assert data.get("work_status") == "IN_PROGRESS", f"Setup failed: start -> {data}"
    data = get_success_data(api_client.complete_work(ro["id"], SERVICE_ADVISOR))
    assert data.get("work_status") == "COMPLETED", f"Setup failed: complete -> {data}"
    data = get_success_data(api_client.invoice_repair_order(ro["id"], SERVICE_MANAGER))
    assert data.get("work_status") == "INVOICED", f"Setup failed: invoice -> {data}"
    return {"account_id": account_id, "ro": data, "bay": bay, "booking": booking}


# --- warranty claims -----------------------------------------------------------

def create_claim(ro_id, claimed_labor_cents, claimed_parts_cents) -> dict:
    resp = api_client.create_warranty_claim(
        create_warranty_claim_payload(repair_order_id=ro_id,
                                      claimed_labor_cents=claimed_labor_cents,
                                      claimed_parts_cents=claimed_parts_cents),
        WARRANTY_ADMIN)
    data = get_success_data(resp)
    assert data.get("status") == "DRAFT", f"Setup failed: create_claim -> {data}"
    return data


def create_submitted_claim(ro_id, claimed_labor_cents, claimed_parts_cents,
                           submitter_id="wadmin-1") -> dict:
    claim = create_claim(ro_id, claimed_labor_cents, claimed_parts_cents)
    data = get_success_data(api_client.submit_warranty_claim(
        claim["id"], make_warranty_admin_headers(submitter_id)))
    assert data.get("status") == "SUBMITTED", f"Setup failed: submit claim -> {data}"
    return data


# --- trade appraisals ----------------------------------------------------------

def create_appraisal(account_id, trade_vin=None, model_year=2023, mileage=120000,
                     condition_grade="B", base_book_value_cents=6000000) -> dict:
    resp = api_client.create_trade_appraisal(
        create_trade_appraisal_payload(
            customer_account_id=account_id, trade_vin=trade_vin or unique_vin(),
            model_year=model_year, mileage=mileage, condition_grade=condition_grade,
            base_book_value_cents=base_book_value_cents),
        SALES_CONSULTANT)
    data = get_success_data(resp)
    assert data.get("status") == "DRAFT", f"Setup failed: create_appraisal -> {data}"
    return data


def offer_appraisal(appraisal_id, market_index_bp=10000, offered_allowance_cents=3800000) -> dict:
    data = get_success_data(api_client.offer_trade_appraisal(
        appraisal_id, {"market_index_bp": market_index_bp,
                       "offered_allowance_cents": offered_allowance_cents},
        SALES_MANAGER))
    assert data.get("status") == "OFFERED", f"Setup failed: offer -> {data}"
    return data


# --- parts ---------------------------------------------------------------------

def create_part(list_price_cents=1000, cost_cents=500, on_hand=10,
                has_core_charge=False, core_charge_cents=0, sku=None,
                part_name="Part") -> dict:
    overrides = {}
    if sku is not None:
        overrides["sku"] = sku
    resp = api_client.create_part(
        create_part_payload(list_price_cents=list_price_cents, cost_cents=cost_cents,
                            on_hand=on_hand, has_core_charge=has_core_charge,
                            core_charge_cents=core_charge_cents, part_name=part_name,
                            **overrides),
        PARTS_REP)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_part -> {data}"
    return data


def create_parts_sale(account_id, lines) -> dict:
    resp = api_client.create_parts_sale(
        {"customer_account_id": account_id, "lines": lines}, PARTS_REP)
    data = get_success_data(resp)
    assert "id" in data, f"Setup failed: create_parts_sale -> {data}"
    return data


def get_sale_lines(sale_id) -> list:
    data = get_success_data(api_client.list_parts_sale_lines(
        PARTS_REP, params={"parts_sale_id": sale_id}))
    assert isinstance(data, list), f"Setup failed: list sale lines -> {data}"
    return data
