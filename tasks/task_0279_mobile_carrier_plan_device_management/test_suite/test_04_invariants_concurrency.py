"""Conserved-quantity invariants, optimistic concurrency, immediate
consistency, and derived-field reconciliation.

Translates difficulty queue (A) compensating_invariant instances and the corner
queue (B) cross_cutting_complexity_layers and consistency_model instances.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    create_device_payload, create_installment_plan_payload,
    create_line_payload, create_upgrade_payload,
    setup_account_plan, setup_active_line, setup_line_with_active_eip,
    complete_port_in,
)
import test_helpers as H

CA = TEST_USERS["carrier_agent_headers"]
PO = TEST_USERS["porting_ops_headers"]


# ─── Queue A: compensating_invariant ──────────────────────────────────────

def test_portin_complete_then_revert_conserves_number(api):
    """PRD §3.7: "On a port-in, the line's `phone_number` is set to the imported
    `external_number`". PRD §3.7: "A successful port-in revert clears the line's
    `phone_number` back to null, returning the number to the donor and restoring
    the conserved number-pool invariant."

    Design: Difficulty/compensating_invariant/number_pool_conserved_on_portin_revert
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    line_after, pr = complete_port_in(account["id"], line["id"],
                                      external_number="12025550112", account_pin="7777")
    assert line_after["phone_number"] == "12025550112", "live-number count rose to 1"

    validate_success(api.revert_port_request(pr["id"], PO), 200)
    line_final = validate_success(api.get_line(line["id"], CA), 200)
    assert line_final.get("phone_number") is None, \
        "number released; live-number count back to baseline across the pair"


def test_upgrade_payoff_conserves_eip_outstanding(api):
    """PRD §3.6: "The one-time settlement charge `payoff_charge_cents` is the old
    plan's `remaining_balance_cents` at upgrade time minus the
    `trade_in_credit_cents`, floored at zero". PRD §3.6: "The old installment plan
    is moved to `CANCELLED` with its `remaining_balance_cents` settled to 0." PRD
    §3.6: "A brand-new installment plan is created `ACTIVE` whose financed amount
    is the new device's `retail_price_cents` minus `new_down_payment_cents`".

    Design: Difficulty/compensating_invariant/eip_outstanding_conserved_on_upgrade_payoff
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    dev_old = validate_success(api.create_device(
        create_device_payload(retail_price_cents=99900, stock_count=5), CA), 201)
    dev_new = validate_success(api.create_device(
        create_device_payload(retail_price_cents=119900, stock_count=5), CA), 201)
    old_eip = validate_success(api.create_installment_plan(
        create_installment_plan_payload(line["id"], dev_old["id"],
                                        term_months=24, down_payment_cents=9900), CA), 201)
    assert old_eip["remaining_balance_cents"] == 90000

    upgrade = validate_success(api.create_upgrade(
        create_upgrade_payload(line["id"], old_eip["id"], dev_new["id"],
                               new_term_months=24, new_down_payment_cents=19900,
                               trade_in_credit_cents=50000), CA), 201)
    assert upgrade["payoff_charge_cents"] == 40000  # max(0, 90000 - 50000)

    old_after = validate_success(api.get_installment_plan(old_eip["id"], CA), 200)
    assert old_after["status"] == "CANCELLED"
    assert old_after["remaining_balance_cents"] == 0

    new_eip = validate_success(api.get_installment_plan(upgrade["new_installment_plan_id"], CA), 200)
    assert new_eip["financed_cents"] == 100000  # 119900 - 19900
    assert new_eip["remaining_balance_cents"] == 100000

    acc = validate_success(api.get_account(account["id"], CA), 200)
    assert acc["total_eip_outstanding_cents"] == 100000, \
        "outstanding == sum of ACTIVE EIP remaining; no drift from old 90000"


# ─── Queue B: optimistic concurrency ──────────────────────────────────────

def test_occ_correct_version_succeeds_and_bumps(api):
    """PRD §2.7: "If they match, provisioning proceeds". PRD §3.2: "the act of
    provisioning increments the owning account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_then_increments
    """
    account, plan = setup_account_plan()
    assert account["version"] == 1
    validate_success(api.create_line(
        create_line_payload(account["id"], plan["id"], 1, sim_type="ESIM"), CA), 201)

    acc = validate_success(api.get_account(account["id"], CA), 200)
    assert acc["version"] == 2, "provisioning bumps account version by exactly 1"


def test_occ_stale_version_rejected(api):
    """PRD §2.7: "if they differ — meaning some earlier line provisioning or line
    state change has already advanced the account's `version`, and therefore
    possibly its `active_line_count` and `group_discount_pct` — the request is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_second_provision_returns_412
    """
    account, plan = setup_account_plan()
    stale_version = account["version"]  # 1
    validate_success(api.create_line(
        create_line_payload(account["id"], plan["id"], stale_version, sim_type="ESIM"), CA), 201)

    res = api.create_line(
        create_line_payload(account["id"], plan["id"], stale_version, sim_type="ESIM"), CA)
    validate_error(res, "ERR_STALE_ACCOUNT_VERSION")


def test_esim_activation_code_populated_on_activate(api):
    """PRD §3.2: "transitions the linked SIM assignment from `ISSUED` to
    `ACTIVATED` — populating `esim_activation_code` at that moment if the SIM is
    an eSIM".

    Design: Corner/cross_cutting_complexity_layers/esim_activation_code_populated_on_activate
    """
    account, plan = setup_account_plan()
    line = H.provision_line(account["id"], plan["id"], sim_type="ESIM")
    sim = H.issue_sim(line["id"], sim_type="ESIM")
    validate_success(api.activate_line(line["id"], CA), 200)

    sim_after = validate_success(api.get_sim_assignment(sim["id"], CA), 200)
    assert sim_after["status"] == "ACTIVATED"
    assert sim_after.get("esim_activation_code"), "eSIM LPA activation string issued"


# ─── Queue B: immediate consistency ───────────────────────────────────────

def test_eip_outstanding_visible_immediately_after_create(api):
    """PRD §2.5: "Whenever an installment plan is opened, paid off, accelerated,
    or superseded, the account's `total_eip_outstanding_cents` is recomputed."
    PRD §3.6: "Opening the EIP decrements the device's `stock_count` by one and
    recomputes the account's `total_eip_outstanding_cents`."

    Design: Corner/consistency_model/immediate_visibility_eip_outstanding_after_create
    """
    account, plan, line, device, eip = setup_line_with_active_eip(
        retail_price_cents=99900, down_payment_cents=9900)
    assert eip["financed_cents"] == 90000

    acc = validate_success(api.get_account(account["id"], CA), 200)
    assert acc["total_eip_outstanding_cents"] == 90000, "immediate same-request visibility"
