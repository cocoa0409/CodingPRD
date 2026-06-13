"""Second-angle depth tests for the difficulty queue.

Each test here asserts a distinct PRD-grounded facet of a difficulty instance
already exercised once in test_01–test_05, satisfying the >=2-tests-per-instance
depth requirement. Every assertion is uniquely derivable from the cited prose.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_subscriber_headers,
    create_addon_payload, create_device_payload, create_installment_plan_payload,
    create_line_payload, create_upgrade_payload, create_port_request_payload,
    setup_account_plan, setup_active_line, setup_active_line_on_open_cycle,
    setup_validated_portout, setup_n_active_lines,
    provision_and_activate_line, ingest_data_usage, set_clock,
    create_billing_cycle, create_device,
    SAMPLE_MISSING_UUID,
)
import test_helpers as H

CA = TEST_USERS["carrier_agent_headers"]
BS = TEST_USERS["billing_system_headers"]
PO = TEST_USERS["porting_ops_headers"]


# ─── transitive_cascade ───────────────────────────────────────────────────

def test_portout_complete_releases_number_and_completes_request(api):
    """PRD §3.7: "On a port-out, the line's `phone_number` is released to null and
    the line is driven to `CANCELLED`".

    Design: Difficulty/transitive_cascade/portout_complete_depth2_cascade_line_then_account
    """
    account = H.create_account()
    plan = H.create_plan()
    provision_and_activate_line(account["id"], plan["id"])
    line2 = provision_and_activate_line(account["id"], plan["id"])
    pr = setup_validated_portout(account["id"], line2["id"],
                                 external_number="12025550199", account_pin="1234")

    pr_done = validate_success(api.complete_port_request(pr["id"], PO), 200)
    assert pr_done["status"] == "COMPLETED"
    line2_after = validate_success(api.get_line(line2["id"], CA), 200)
    assert line2_after.get("phone_number") is None, "port-out releases the number to null"


def test_line_cancel_deactivates_sim_and_releases_number(api):
    """PRD §3.5: "The linked SIM assignment is moved to `DEACTIVATED`. The line's
    `phone_number` is released back to the carrier number pool and set to null."

    Design: Difficulty/transitive_cascade/line_cancel_depth3_cascade_eip_addon_account
    """
    account, plan, line, device, eip, _ = H.setup_cancel_ready_line()
    validate_success(api.cancel_line(line["id"], make_subscriber_headers(account["id"])), 200)

    line_after = validate_success(api.get_line(line["id"], CA), 200)
    assert line_after.get("phone_number") is None, "number released on cancel"
    sims = validate_success(api.list_sim_assignments(CA, params={"line_id": line["id"]}), 200)
    assert sims[0]["status"] == "DEACTIVATED", "SIM deactivated by cancel cascade"


# ─── resource_temporal_overlap ────────────────────────────────────────────

def test_portin_of_unused_number_succeeds(api):
    """PRD §3.7: "For a port-in, the requested `external_number` must not already
    be live on another line: if any line currently holds that number as a
    non-null `phone_number`, the request is rejected with `ERR_NUMBER_IN_USE`".

    Design: Difficulty/resource_temporal_overlap/portin_number_in_use_uniqueness_on_line_pool
    """
    account, plan, line_a = setup_active_line(sim_type="PHYSICAL")
    H.complete_port_in(account["id"], line_a["id"],
                       external_number="12025550111", account_pin="5555")
    line_b = H.provision_line(account["id"], plan["id"], sim_type="PHYSICAL")

    # A genuinely different, unused number is portable (uniqueness blocks only live numbers).
    res = api.create_port_request(
        create_port_request_payload(line_b["id"], direction="PORT_IN",
                                    external_number="12025550222", account_pin="6666"),
        make_subscriber_headers(account["id"]))
    validate_success(res, 201)


def test_daypass_addon_exact_adjacency_allowed(api):
    """PRD §3.8: "their half-open day-ranges from `window_start` (inclusive) to
    `window_end` (exclusive) must not intersect, though exact adjacency where one
    ends precisely as the next begins is permitted."

    Design: Difficulty/resource_temporal_overlap/daypass_addon_overlap_half_open_on_line
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    sub = make_subscriber_headers(account["id"])
    validate_success(api.create_addon(
        create_addon_payload(line["id"], "ROAMING_DAYPASS",
                             "2026-06-10T00:00:00Z", "2026-06-15T00:00:00Z",
                             daily_fee_cents=1000), sub), 201)

    # Second daypass starts precisely where the first ends -> adjacency, allowed.
    res = api.create_addon(
        create_addon_payload(line["id"], "ROAMING_DAYPASS",
                             "2026-06-15T00:00:00Z", "2026-06-18T00:00:00Z",
                             daily_fee_cents=1000), sub)
    validate_success(res, 201)


# ─── priority_pair_validation_conflict ────────────────────────────────────

def test_reconnect_nonpayment_on_delinquent_account_blocked(api):
    """PRD §3.4: "if the line was suspended for `NONPAYMENT`, reconnect is
    permitted only when the account's `wallet_credit_cents` is at least 0 and the
    account `status` is not `DELINQUENT`; a `DELINQUENT` account blocks a
    non-payment reconnect with `ERR_RECONNECT_BLOCKED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_reconnect_invalid_state_wins
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    validate_success(api.suspend_line(line["id"], {"suspend_reason": "NONPAYMENT"}, CA), 200)
    validate_success(api.mark_delinquent(account["id"], {"delinquent": True}, BS), 200)

    # Line IS SUSPENDED, so the state check passes; now the fiscal gate fires.
    res = api.reconnect_line(line["id"], CA)
    validate_error(res, "ERR_RECONNECT_BLOCKED")


def test_complete_missing_port_request_not_found(api):
    """PRD §2.4: "When more than one identifier appears in a path, validation
    proceeds left to right and the first identifier that does not resolve to a
    stored entity produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_referential_port_not_found_wins
    """
    res = api.complete_port_request(SAMPLE_MISSING_UUID, PO)
    validate_error(res, "ERR_NOT_FOUND")


# ─── dual_variant_calc ────────────────────────────────────────────────────

def test_activating_pending_line_raises_active_count_and_discount(api):
    """PRD §3.10: "`active_line_count` is the count of lines on the account whose
    `status` is `ACTIVE` or `SUSPENDED` (lines in `PENDING_ACTIVATION` or
    `CANCELLED` are excluded)." "exactly three lines yields 0.10".

    Design: Difficulty/dual_variant_calc/group_discount_projected_vs_actual_on_account
    """
    account, plan = setup_account_plan()
    provision_and_activate_line(account["id"], plan["id"])
    provision_and_activate_line(account["id"], plan["id"])
    pending = H.provision_line(account["id"], plan["id"], sim_type="PHYSICAL")
    acc2 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc2["active_line_count"] == 2 and acc2["group_discount_pct"] == 0.05

    H.issue_sim(pending["id"], sim_type="PHYSICAL")
    validate_success(api.activate_line(pending["id"], CA), 200)
    acc3 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc3["active_line_count"] == 3, "the formerly PENDING line now counts"
    assert acc3["group_discount_pct"] == 0.10


# ─── cross_entity_state_dependency ────────────────────────────────────────

def test_reconnect_succeeds_after_delinquency_cleared(api):
    """PRD §3.11: "when `delinquent` is true the account `status` moves to
    `DELINQUENT`, and when it is false the account returns to `ACTIVE`." PRD §3.4:
    "Reconnecting reverses the park, moving the line from `SUSPENDED` back to
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/line_reconnect_requires_account_active
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    validate_success(api.suspend_line(line["id"], {"suspend_reason": "VOLUNTARY"}, CA), 200)
    validate_success(api.mark_delinquent(account["id"], {"delinquent": True}, BS), 200)
    validate_error(api.reconnect_line(line["id"], CA), "ERR_ACCOUNT_NOT_ACTIVE")

    validate_success(api.mark_delinquent(account["id"], {"delinquent": False}, BS), 200)
    reconnected = validate_success(api.reconnect_line(line["id"], CA), 200)
    assert reconnected["status"] == "ACTIVE", "reconnect succeeds once account is ACTIVE again"


def test_line_activates_on_active_plan(api):
    """PRD §3.2: "Activation is the transition that turns a provisioned line into
    a working one, moving `status` from `PENDING_ACTIVATION` to `ACTIVE`." PRD
    §3.2: "Second, the plan referenced by `plan_id` must still be `ACTIVE`,
    failing with `ERR_PLAN_RETIRED` otherwise."

    Design: Difficulty/cross_entity_state_dependency/line_activate_requires_plan_active
    """
    account, plan = setup_account_plan()
    line = H.provision_line(account["id"], plan["id"], sim_type="PHYSICAL")
    H.issue_sim(line["id"], sim_type="PHYSICAL")

    activated = validate_success(api.activate_line(line["id"], CA), 200)
    assert activated["status"] == "ACTIVE", "line on an ACTIVE plan activates successfully"


# ─── compensating_invariant ───────────────────────────────────────────────

def test_portin_request_progresses_completed_then_reverted(api):
    """PRD §3.7: "`PortingOps` completes a `VALIDATED` port, moving it to
    `COMPLETED`". PRD §3.7: "Finally, `PortingOps` may revert a completed port,
    but only a completed `PORT_IN`: revert is defined only from `COMPLETED`".

    Design: Difficulty/compensating_invariant/number_pool_conserved_on_portin_revert
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    line_after, pr = H.complete_port_in(account["id"], line["id"],
                                        external_number="12025550112", account_pin="7777")
    assert pr["status"] == "COMPLETED"
    assert line_after["phone_number"] == "12025550112"

    reverted = validate_success(api.revert_port_request(pr["id"], PO), 200)
    assert reverted["status"] == "REVERTED", "the COMPLETED PORT_IN reverts"


def test_upgrade_decrements_new_device_stock(api):
    """PRD §3.6: "The upgrade decrements the new device's `stock_count`,
    recomputes the account's `total_eip_outstanding_cents`, and is recorded with
    `status` `COMPLETED`".

    Design: Difficulty/compensating_invariant/eip_outstanding_conserved_on_upgrade_payoff
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    dev_old = create_device(retail_price_cents=99900, stock_count=5)
    dev_new = create_device(retail_price_cents=119900, stock_count=5)
    old_eip = validate_success(api.create_installment_plan(
        create_installment_plan_payload(line["id"], dev_old["id"],
                                        term_months=24, down_payment_cents=9900), CA), 201)

    validate_success(api.create_upgrade(
        create_upgrade_payload(line["id"], old_eip["id"], dev_new["id"],
                               new_term_months=24, new_down_payment_cents=19900,
                               trade_in_credit_cents=50000), CA), 201)

    new_dev_after = validate_success(api.get_device(dev_new["id"], CA), 200)
    assert new_dev_after["stock_count"] == 4, "new device stock decremented by the upgrade"


# ─── combinatorial_formula ────────────────────────────────────────────────

def test_overage_exactly_at_tier1_cap(api):
    """PRD §3.10: "The tier-1 megabytes is the lesser of the total overage and the
    plan's `overage_tier1_cap_mb`; the tier-2 megabytes is the remainder of the
    overage beyond that cap, floored at zero."

    Design: Difficulty/combinatorial_formula/per_line_bill_nonlinear_overage_tier_and_discount_mode_a
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(sim_type="ESIM")
    # included 20480 + tier1 cap 5120 = 25600 -> over = 5120, all tier1, none tier2.
    ingest_data_usage(line["id"], 25600, "2026-06-15T01:00:00Z")

    summary = validate_success(api.get_usage_summary(line["id"], CA), 200)
    assert summary["cycle_data_used_mb"] == 25600
    assert summary["overage_cents"] == 5120  # 5120 MB @ 1000 mc/MB -> 5120 c


def test_cycle_total_charges_equal_base_subtotal_when_only_base(api):
    """PRD §3.10: "the cycle's `total_charges_cents` is set to the sum of all
    posted `amount_cents`". PRD §3.10: "the base subtotal across the three lines
    is 18888 — not the 18887 that a sum-then-round order would have produced."

    Design: Difficulty/combinatorial_formula/account_base_subtotal_round_per_line_then_sum_mode_b
    """
    account = H.create_account()
    plan = H.create_plan(monthly_fee_cents=6995)
    set_clock("2026-06-01T00:00:00Z")
    cycle = create_billing_cycle(account["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    for _ in range(3):
        provision_and_activate_line(account["id"], plan["id"], sim_type="ESIM")
    set_clock("2026-07-01T00:00:00Z")
    closed = validate_success(api.close_billing_cycle(cycle["id"], BS), 200)
    # No overage / EIP / add-ons: the only charges are the three PLAN_BASE lines.
    assert closed["total_charges_cents"] == 18888


# ─── boundary_precision_check ─────────────────────────────────────────────

def test_overage_one_mb_over_included(api):
    """PRD §3.10: "the overage megabytes is the line's `cycle_data_used_mb` minus
    the plan's `included_data_mb`, floored at zero; if that is zero the overage is
    zero cents."

    Design: Difficulty/boundary_precision_check/overage_zero_at_exact_included_mb
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(sim_type="ESIM")
    ingest_data_usage(line["id"], 20481, "2026-06-15T01:00:00Z")

    summary = validate_success(api.get_usage_summary(line["id"], CA), 200)
    assert summary["cycle_data_used_mb"] == 20481
    assert summary["overage_cents"] == 1, "1 MB over included @ tier1 1000 mc -> 1 c"


def test_group_discount_stays_capped_at_sixth_line(api):
    """PRD §3.10: "five or more lines yields 0.20, which is the cap."

    Design: Difficulty/boundary_precision_check/group_discount_cap_at_fifth_line
    """
    account, plan, lines = setup_n_active_lines(5, sim_type="ESIM")
    acc5 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc5["group_discount_pct"] == 0.20

    provision_and_activate_line(account["id"], plan["id"], sim_type="ESIM")
    acc6 = validate_success(api.get_account(account["id"], CA), 200)
    assert acc6["active_line_count"] == 6
    assert acc6["group_discount_pct"] == 0.20, "still capped at 0.20 for >=5 lines"
