"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test. Helpers use the lenient
get_success_data() validator so setup failures surface as clear "Setup failed" errors.

All setup runs as StoreManager, who holds override authority on every endpoint (PRD §4).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS
from .factories import (
    create_trade_account_payload,
    create_fixture_model_payload,
    create_order_payload,
    create_order_line_payload,
    create_installer_payload,
    create_delivery_truck_payload,
    create_rebate_program_payload,
    create_special_order_payload,
    create_design_consult_payload,
    create_delivery_job_payload,
    create_install_referral_payload,
    create_return_request_payload,
    create_rebate_claim_payload,
)

SM = TEST_USERS["sm_headers"]


# ---------------------------------------------------------------- low-level steps
def set_clock(api, iso):
    return get_success_data(api.set_clock({"to_iso8601": iso}, SM))


def create_account(api, **overrides):
    return get_success_data(api.create_trade_account(create_trade_account_payload(**overrides), SM))


def create_fixture(api, **overrides):
    return get_success_data(api.create_fixture_model(create_fixture_model_payload(**overrides), SM))


def create_order(api, **overrides):
    return get_success_data(api.create_order(create_order_payload(**overrides), SM))


def add_line(api, order_id, fixture_model_id, **overrides):
    payload = create_order_line_payload(fixture_model_id=fixture_model_id, **overrides)
    return get_success_data(api.add_order_line(order_id, payload, SM))


def order_version(api, order_id):
    return get_success_data(api.get_order(order_id, SM))["version"]


def quote(api, order_id, expected_version=None):
    if expected_version is None:
        expected_version = order_version(api, order_id)
    return get_success_data(api.quote_order(order_id, {"expected_order_version": expected_version}, SM))


def confirm(api, order_id):
    return get_success_data(api.confirm_order(order_id, SM))


def cancel(api, order_id):
    return get_success_data(api.cancel_order(order_id, SM))


def pay(api, order_id, kind, amount_cents):
    return get_success_data(api.pay_order(order_id, {"kind": kind, "amount_cents": amount_cents}, SM))


def create_installer(api, **overrides):
    return get_success_data(api.create_installer(create_installer_payload(**overrides), SM))


def create_truck(api, **overrides):
    return get_success_data(api.create_delivery_truck(create_delivery_truck_payload(**overrides), SM))


def create_program(api, **overrides):
    return get_success_data(api.create_rebate_program(create_rebate_program_payload(**overrides), SM))


def create_special_order(api, order_id, order_line_id, supplier_lead_days=30):
    payload = create_special_order_payload(
        order_id=order_id, order_line_id=order_line_id, supplier_lead_days=supplier_lead_days
    )
    return get_success_data(api.create_special_order(payload, SM))


def create_delivery_job(api, order_id, delivery_truck_id, window_start, window_end):
    payload = create_delivery_job_payload(
        order_id=order_id, delivery_truck_id=delivery_truck_id,
        window_start=window_start, window_end=window_end,
    )
    return get_success_data(api.create_delivery_job(payload, SM))


def deliver_job(api, job_id):
    return get_success_data(api.deliver_delivery_job(job_id, SM))


def create_referral(api, order_id, installer_id, delivery_job_id):
    payload = create_install_referral_payload(
        order_id=order_id, installer_id=installer_id, delivery_job_id=delivery_job_id
    )
    return get_success_data(api.create_install_referral(payload, SM))


def schedule_referral(api, referral_id, appointment_start, appointment_end):
    payload = {"appointment_start": appointment_start, "appointment_end": appointment_end}
    return get_success_data(api.schedule_install_referral(referral_id, payload, SM))


def create_return(api, order_id, order_line_id, reason):
    payload = create_return_request_payload(order_id=order_id, order_line_id=order_line_id, reason=reason)
    return get_success_data(api.create_return_request(payload, SM))


def create_claim(api, order_id, rebate_program_id):
    payload = create_rebate_claim_payload(order_id=order_id, rebate_program_id=rebate_program_id)
    return get_success_data(api.create_rebate_claim(payload, SM))


# ------------------------------------------------------------------- composites
def setup_quoted_retail_order(api, base_price_cents=5000, quantity=1, category="SCONCE",
                              base_wattage=40, **fx_over):
    """Retail order with one line, quoted (fulfillment QUOTED, payment UNPAID).
    Returns (order, line, fixture)."""
    fx = create_fixture(api, base_price_cents=base_price_cents, base_wattage=base_wattage,
                        category=category, **fx_over)
    order = create_order(api, customer_name="Retail")
    line = add_line(api, order["id"], fx["id"], quantity=quantity)
    order = quote(api, order["id"])
    return order, line, fx


def setup_confirmed_retail_order(api, base_price_cents=5000, quantity=1, category="SCONCE",
                                 base_wattage=40, **fx_over):
    """Retail order with one line, confirmed. Returns (order, line, fixture)."""
    order, line, fx = setup_quoted_retail_order(
        api, base_price_cents=base_price_cents, quantity=quantity, category=category,
        base_wattage=base_wattage, **fx_over
    )
    order = confirm(api, order["id"])
    return order, line, fx


def setup_gold_account(api, credit_limit_cents=100000000):
    """Trade account pushed to GOLD tier via a settled 5,000,000-cent order.
    Returns (account, spend_fixture)."""
    acct = create_account(api, credit_limit_cents=credit_limit_cents)
    fx = create_fixture(api, sku_base="F-SPEND", category="CHANDELIER",
                        base_price_cents=1000000, base_wattage=100)
    o = create_order(api, customer_name="spend", trade_account_id=acct["id"])
    add_line(api, o["id"], fx["id"], quantity=5)
    quote(api, o["id"])
    confirm(api, o["id"])
    pay(api, o["id"], "SETTLEMENT", 5000000)
    return acct, fx


def setup_confirmed_order_with_delivered_job(api, truck_name="T-DEL",
                                             window_start="2026-07-10T08:00:00Z",
                                             window_end="2026-07-10T09:00:00Z"):
    """Confirmed retail order + truck + delivery job driven to DELIVERED.
    Returns (order, truck, job, fixture)."""
    truck = create_truck(api, name=truck_name)
    order, line, fx = setup_confirmed_retail_order(api)
    job = create_delivery_job(api, order["id"], truck["id"], window_start, window_end)
    job = deliver_job(api, job["id"])
    return order, truck, job, fx


def setup_settled_retail_order_two_lines(api, base_price_cents=5000):
    """Retail order with two ACTIVE lines, confirmed and SETTLED (total_final over both lines).
    Returns (order, line1, line2, fixture)."""
    fx = create_fixture(api, base_price_cents=base_price_cents, base_wattage=40, category="PENDANT")
    order = create_order(api, customer_name="TwoLine")
    l1 = add_line(api, order["id"], fx["id"], quantity=1)
    l2 = add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    confirm(api, order["id"])
    pay(api, order["id"], "SETTLEMENT", base_price_cents * 2)
    return order, l1, l2, fx


def setup_energy_star_order(api, base_price_cents=2010, base_wattage=60, wattage_ceiling=100,
                            budget_total_cents=100000000, rebate_rate=0.075, num_lines=1):
    """Rebate program + ENERGY STAR fixture + order with num_lines ACTIVE eligible lines.
    Returns (program, fixture, order, lines)."""
    prog = create_program(api, rebate_rate=rebate_rate, wattage_ceiling=wattage_ceiling,
                          budget_total_cents=budget_total_cents)
    fx = create_fixture(api, sku_base="F-ES", category="RECESSED",
                        base_price_cents=base_price_cents, base_wattage=base_wattage,
                        energy_star=True)
    order = create_order(api, customer_name="ES")
    lines = [add_line(api, order["id"], fx["id"], quantity=1) for _ in range(num_lines)]
    return prog, fx, order, lines
