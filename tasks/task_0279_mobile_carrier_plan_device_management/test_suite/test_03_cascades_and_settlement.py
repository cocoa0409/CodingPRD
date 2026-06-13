"""Cancellation and port-out cascades, and the charge ledger they produce.

Translates difficulty queue (A) transitive_cascade instances and the corner
queue (B) endpoints/charges-listing instance.
"""
from test_helpers import (
    validate_success,
    TEST_USERS, make_subscriber_headers,
    setup_validated_portout,
)
import test_helpers as H

CA = TEST_USERS["carrier_agent_headers"]
PO = TEST_USERS["porting_ops_headers"]
BS = TEST_USERS["billing_system_headers"]


# ─── Queue A: transitive_cascade ──────────────────────────────────────────

def test_line_cancel_cascades_eip_addon_and_account_outstanding(api):
    """PRD §3.5: "each installment plan on the line whose `status` is `ACTIVE` is
    driven to `PAID_OFF` with its `remaining_balance_cents` set to 0". PRD §3.5:
    "Each add-on on the line whose `status` is `SCHEDULED` or `ACTIVE` is moved
    to `CANCELLED`." PRD §3.6: "that field is at all times the sum of
    `remaining_balance_cents` across the installment plans whose `status` is
    `ACTIVE` belonging to the account's lines."

    Design: Difficulty/transitive_cascade/line_cancel_depth3_cascade_eip_addon_account
    """
    account, plan, line, device, eip, addon = H.setup_cancel_ready_line(with_addon=True)
    sub = make_subscriber_headers(account["id"])

    cancelled = validate_success(api.cancel_line(line["id"], sub), 200)
    assert cancelled["status"] == "CANCELLED"  # link 1

    eip_after = validate_success(api.get_installment_plan(eip["id"], CA), 200)
    assert eip_after["status"] == "PAID_OFF"  # link 2, caused by link 1
    assert eip_after["remaining_balance_cents"] == 0

    acc_after = validate_success(api.get_account(account["id"], CA), 200)
    assert acc_after["total_eip_outstanding_cents"] == 0  # link 3, caused by link 2

    addon_after = validate_success(api.get_addon(addon["id"], CA), 200)
    assert addon_after["status"] == "CANCELLED"  # fan-out from cancel


def test_portout_complete_cancels_line_and_recomputes_discount(api):
    """PRD §3.7: "On a port-out, the line's `phone_number` is released to null and
    the line is driven to `CANCELLED` through the very same cancellation cascade
    described in §3.5 — the active EIP is accelerated, add-ons are cancelled, the
    SIM is deactivated, the number-pool invariant is restored, and the account's
    group discount and version are recomputed and incremented." PRD §3.10: "One
    line or fewer yields a discount of 0.00".

    Design: Difficulty/transitive_cascade/portout_complete_depth2_cascade_line_then_account
    """
    account = H.create_account()
    plan = H.create_plan()
    H.provision_and_activate_line(account["id"], plan["id"])  # line 1 stays active
    line2 = H.provision_and_activate_line(account["id"], plan["id"])
    acc2 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc2["active_line_count"] == 2 and acc2["group_discount_pct"] == 0.05

    pr = setup_validated_portout(account["id"], line2["id"],
                                 external_number="12025550199", account_pin="1234")
    validate_success(api.complete_port_request(pr["id"], PO), 200)

    line2_after = validate_success(api.get_line(line2["id"], CA), 200)
    assert line2_after["status"] == "CANCELLED"  # link 1

    acc_after = validate_success(api.get_account(account["id"], CA), 200)
    assert acc_after["active_line_count"] == 1  # link 2
    assert acc_after["group_discount_pct"] == 0.00  # recomputed from single active line


# ─── Queue B: endpoints (charges listing via cascade) ─────────────────────

def test_list_charges_by_line_id_shows_cancel_cascade_charges(api):
    """PRD §2.4: "charges by `billing_cycle_id` or `line_id`". PRD §3.10:
    "simultaneously the entire `remaining_balance_cents` of each `ACTIVE`
    installment plan on the line is posted as a positive `EIP_PAYOFF` charge".

    Design: Corner/endpoints/list_charges_filtered_by_line_id_reverse_reachability
    """
    account, plan, line, device, eip, _ = H.setup_cancel_ready_line()
    sub = make_subscriber_headers(account["id"])
    validate_success(api.cancel_line(line["id"], sub), 200)

    charges = validate_success(api.list_charges(BS, params={"line_id": line["id"]}), 200)
    assert any(c["charge_type"] == "EIP_PAYOFF" and c["amount_cents"] == 90000
               for c in charges), "EIP_PAYOFF 90000 discoverable via line_id filter"
    assert any(c["charge_type"] == "CREDIT" and c["amount_cents"] < 0
               for c in charges), "negative CREDIT charge discoverable via line_id filter"
