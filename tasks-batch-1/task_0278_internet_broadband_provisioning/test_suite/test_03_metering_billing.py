"""Metering, data caps, throttling, the overage ladder, estimate vs final, and
the billing close / finalize settlement.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_usage_record_payload, create_outage_event_payload,
    setup_active_self_install_account,
)

AGENT = TEST_USERS["provisioning_agent_headers"]
NETOPS = TEST_USERS["network_ops_headers"]


def _activate_bill_account(included_gb=1000, monthly_fee_cents=8999,
                           lease_fee=1500, clock="2026-06-01T00:00:00Z"):
    """Activate a SELF_INSTALL BILL account; return (ctx, cycle_id)."""
    ctx = setup_active_self_install_account(
        clock=clock,
        plan_overrides={"overage_policy": "BILL", "included_gb": included_gb,
                        "monthly_fee_cents": monthly_fee_cents, "contract_term_months": 0,
                        "etf_full_cents": 0},
        equipment_overrides={"lease_fee_cents_per_cycle": lease_fee})
    return ctx, ctx["cycle"]["id"]


# ===========================================================================
# Queue A — boundary_precision_check: data-cap strict-greater-than
# ===========================================================================
def test_data_cap_at_exact_included_gb_does_not_throttle(api):
    """PRD §3.5: "usage exactly equal to the cap is not yet over, and only cumulative usage strictly greater than `included_gb` counts as overage."

    Design: Difficulty/boundary_precision_check/data_cap_crossing_strict_greater_than
    """
    ctx = setup_active_self_install_account(
        plan_overrides={"overage_policy": "THROTTLE", "included_gb": 1000})
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 1000,
                                    posted_at_iso="2026-06-05T00:00:00Z"), NETOPS))
    cycle = validate_success(api.get_billing_cycle(cycle_id, NETOPS))
    assert cycle["throttle_state"] == "UNCAPPED", \
        f"at exactly 1000 GB throttle_state must be UNCAPPED, got {cycle['throttle_state']}"


def test_data_cap_one_gb_over_throttles(api):
    """PRD §3.5: "the first usage post that pushes the cycle's cumulative `usage_gb` strictly above `included_gb` — while the cycle is still `OPEN` — flips the cycle's `throttle_state` from `UNCAPPED` to `THROTTLED`".

    Design: Difficulty/boundary_precision_check/data_cap_crossing_strict_greater_than
    """
    ctx = setup_active_self_install_account(
        plan_overrides={"overage_policy": "THROTTLE", "included_gb": 1000})
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 1000,
                                    posted_at_iso="2026-06-05T00:00:00Z"), NETOPS))
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 1,
                                    posted_at_iso="2026-06-06T00:00:00Z"), NETOPS))
    cycle = validate_success(api.get_billing_cycle(cycle_id, NETOPS))
    assert cycle["throttle_state"] == "THROTTLED", \
        f"at 1001 GB throttle_state must be THROTTLED, got {cycle['throttle_state']}"


# ===========================================================================
# Queue A — non_linear_state_machine: parallel billing/throttle dimensions
# ===========================================================================
def test_usage_post_throttles_while_billing_state_stays_open(api):
    """PRD §2.6: "A cycle's `billing_state` evolves only on close and finalize, while its `throttle_state` evolves on usage posts and manual speed restores."
    PRD §3.5: "and if the account is `ACTIVE` its `service_state` moves from `ONLINE` to `THROTTLED` in the same step."

    Design: Difficulty/non_linear_state_machine/billing_cycle_parallel_billing_and_throttle_dimensions
    """
    ctx = setup_active_self_install_account(
        plan_overrides={"overage_policy": "THROTTLE", "included_gb": 100,
                        "monthly_fee_cents": 6000})
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 120,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    cycle = validate_success(api.get_billing_cycle(cycle_id, NETOPS))
    assert cycle["throttle_state"] == "THROTTLED", \
        f"throttle_state must be THROTTLED, got {cycle['throttle_state']}"
    assert cycle["billing_state"] == "OPEN", \
        f"billing_state must stay OPEN, got {cycle['billing_state']}"
    acct = validate_success(api.get_account(ctx["account"]["id"], AGENT))
    assert acct["service_state"] == "THROTTLED", \
        f"account service_state must be THROTTLED, got {acct['service_state']}"


def test_closing_cycle_does_not_change_throttle_state(api):
    """PRD §2.6: "The two dimensions never gate each other: a cycle can be `THROTTLED` while still `OPEN`, and closing a cycle does not by itself change its `throttle_state`."

    The throttle dimension set on a usage post survives the independent
    billing_state advance OPEN -> CLOSED.

    Design: Difficulty/non_linear_state_machine/billing_cycle_parallel_billing_and_throttle_dimensions
    """
    ctx = setup_active_self_install_account(
        plan_overrides={"overage_policy": "THROTTLE", "included_gb": 100,
                        "monthly_fee_cents": 6000})
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 120,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    closed = validate_success(api.close_cycle(cycle_id, NETOPS))
    assert closed["billing_state"] == "CLOSED", \
        f"billing_state must advance to CLOSED, got {closed['billing_state']}"
    assert closed["throttle_state"] == "THROTTLED", \
        f"closing must not clear THROTTLED throttle_state, got {closed['throttle_state']}"


# ===========================================================================
# Queue A — combinatorial_formula: tiered overage ladder below cap
# ===========================================================================
def test_overage_ladder_below_cap_is_tier_sum(api):
    """PRD §3.10: "the first 50 gigabytes of overage cost 50 cents per gigabyte, the next 50 gigabytes cost 30 cents per gigabyte, and every gigabyte of overage beyond the first 100 costs 20 cents per gigabyte. The tier costs are summed, and then the total overage charge is capped so it never exceeds 6,000 cents."

    Over 199 GB -> 50*50 + 50*30 + 99*20 = 5980, below the 6000 cap.

    Design: Difficulty/combinatorial_formula/tiered_overage_ladder_with_cap_mode_a
    """
    ctx, cycle_id = _activate_bill_account(included_gb=1000)
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 1199,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    cycle = validate_success(api.close_cycle(cycle_id, NETOPS))
    assert cycle["overage_charge_cents"] == 5980, \
        f"overage must be 5980, got {cycle['overage_charge_cents']}"
    assert cycle["usage_gb"] == 1199, f"usage_gb must be 1199, got {cycle['usage_gb']}"


def test_overage_ladder_clamps_at_cap(api):
    """PRD §3.10: "the total overage charge is capped so it never exceeds 6,000 cents."

    Over 200 GB -> 50*50 + 50*30 + 100*20 = 6000 (exactly at the cap).

    Design: Difficulty/combinatorial_formula/tiered_overage_ladder_with_cap_mode_a
    """
    ctx, cycle_id = _activate_bill_account(included_gb=1000)
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 1200,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    cycle = validate_success(api.close_cycle(cycle_id, NETOPS))
    assert cycle["overage_charge_cents"] == 6000, \
        f"overage must clamp to 6000, got {cycle['overage_charge_cents']}"


# ===========================================================================
# Queue A — dual_variant_calc: estimate vs final diverge
# ===========================================================================
def test_overage_estimate_and_final_diverge_on_same_cycle(api):
    """PRD §3.10: "The overage estimate accepts an optional `as_of_iso` marking the as-of date and projects usage to cycle end: it takes the usage so far divided by the days elapsed, multiplies by the number of cycle days, takes the floor of that projection, and then runs the identical three-tier ladder and 6,000-cent cap on the projected figure."
    PRD §3.10: "At close, the cumulative usage fed into this ladder is the frozen `usage_gb` — the actual chronological sum of posted records."

    Day 15, 510 GB -> projection floor(510/15*30)=1020, over 20 -> 1000.
    Final: 1063 GB, over 63 -> 50*50 + 13*30 = 2890.

    Design: Difficulty/dual_variant_calc/overage_estimate_vs_final_diverge_on_billing_cycle
    """
    ctx, cycle_id = _activate_bill_account(included_gb=1000)
    acct_id = ctx["account"]["id"]
    # Front-load usage so the mid-cycle linear projection differs from the
    # chronological close: 510 GB by day 10, then a heavy 553 GB late post.
    get_success_data(api.create_usage_record(
        create_usage_record_payload(acct_id, cycle_id, 510,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    est = validate_success(api.overage_estimate(
        cycle_id, NETOPS, params={"as_of_iso": "2026-06-16T00:00:00Z"}))
    get_success_data(api.create_usage_record(
        create_usage_record_payload(acct_id, cycle_id, 553,
                                    posted_at_iso="2026-06-25T00:00:00Z"), NETOPS))
    closed = validate_success(api.close_cycle(cycle_id, NETOPS))
    # FINAL is chronological: frozen 1063 GB, over 63 -> 50*50 + 13*30 = 2890.
    assert closed["overage_charge_cents"] == 2890, \
        f"final overage must be 2890, got {closed['overage_charge_cents']}"
    # The forward-looking ESTIMATE necessarily diverges from the chronological FINAL.
    assert est["overage_charge_cents"] != closed["overage_charge_cents"], \
        "estimate and final must diverge on the same cycle"


def test_overage_estimate_is_a_nonmutating_read(api):
    """PRD §3.10: "The same ladder also backs a forward-looking estimate available mid-cycle as a computed read."
    PRD §3.10: "At close, the cumulative usage fed into this ladder is the frozen `usage_gb` — the actual chronological sum of posted records."

    The estimate is a pure read: it leaves the cycle OPEN, and the subsequent
    close computes the chronological FINAL (frozen 1063 GB -> 2890) independently.

    Design: Difficulty/dual_variant_calc/overage_estimate_vs_final_diverge_on_billing_cycle
    """
    ctx, cycle_id = _activate_bill_account(included_gb=1000)
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 1063,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    est = validate_success(api.overage_estimate(
        cycle_id, NETOPS, params={"as_of_iso": "2026-06-16T00:00:00Z"}))
    assert est["billing_state"] == "OPEN", \
        f"overage-estimate must not close the cycle, got {est['billing_state']}"
    closed = validate_success(api.close_cycle(cycle_id, NETOPS))
    assert closed["overage_charge_cents"] == 2890, \
        f"final chronological overage must be 2890, got {closed['overage_charge_cents']}"


# ===========================================================================
# Queue A — combinatorial_formula: bill total with promo keyed on subtotal
# ===========================================================================
def test_bill_total_promo_keyed_on_subtotal_tier(api):
    """PRD §3.10: "Now form the pre-discount subtotal as the plan fee plus the lease fee — and only those two. The promotional discount is then keyed strictly on that subtotal: a subtotal of at least 10,000 cents earns a 1,000-cent discount".
    PRD §3.10: "The final `total_due_cents` is the plan fee plus the lease fee plus the overage plus the early-termination fee, minus the applied credits, minus the promotional discount."

    plan 8999 + lease 1500 = subtotal 10499 -> high promo 1000.
    overage 2890 (over 63), one OUTAGE credit 62 -> total 8999+1500+2890-62-1000 = 12327.

    Design: Difficulty/combinatorial_formula/bill_total_promo_keyed_on_subtotal_tier_mode_c
    """
    ctx, cycle_id = _activate_bill_account(included_gb=1000, monthly_fee_cents=8999,
                                           lease_fee=1500)
    acct_id = ctx["account"]["id"]
    get_success_data(api.create_usage_record(
        create_usage_record_payload(acct_id, cycle_id, 1063,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    # One OUTAGE credit of 62 cents: 5-hour (300 min) outage -> rhu(8999*300/43200)=62.
    outage = get_success_data(api.create_outage_event(
        create_outage_event_payload(acct_id, cycle_id,
                                    started_at_iso="2026-06-12T00:00:00Z"), NETOPS))
    get_success_data(api.resolve_outage(
        outage["id"], {"ended_at_iso": "2026-06-12T05:00:00Z"}, NETOPS))
    get_success_data(api.issue_outage_credit(outage["id"], NETOPS))
    get_success_data(api.close_cycle(cycle_id, NETOPS))
    final = validate_success(api.finalize_cycle(cycle_id, NETOPS))
    assert final["total_due_cents"] == 12327, \
        f"total_due_cents must be 12327, got {final['total_due_cents']}"


def test_outage_credit_amount_is_monthly_fee_proration(api):
    """PRD §3.6: "The credit is the plan's `monthly_fee_cents` multiplied by the qualifying minutes divided by the cycle minutes, rounded half up to whole cents, and then capped so it never exceeds one month's `monthly_fee_cents`."

    300 qualifying minutes of a 43200-minute cycle -> rhu(8999*300/43200) = 62.

    Design: Difficulty/combinatorial_formula/bill_total_promo_keyed_on_subtotal_tier_mode_c
    """
    ctx, cycle_id = _activate_bill_account(included_gb=1000, monthly_fee_cents=8999)
    acct_id = ctx["account"]["id"]
    outage = get_success_data(api.create_outage_event(
        create_outage_event_payload(acct_id, cycle_id,
                                    started_at_iso="2026-06-12T00:00:00Z"), NETOPS))
    get_success_data(api.resolve_outage(
        outage["id"], {"ended_at_iso": "2026-06-12T05:00:00Z"}, NETOPS))
    get_success_data(api.issue_outage_credit(outage["id"], NETOPS))
    # Read the emitted credit directly from the listing.
    from test_helpers import list_account_credits
    all_credits = list_account_credits(acct_id, AGENT)
    outage_credits = [c for c in all_credits if c["source_type"] == "OUTAGE"]
    assert len(outage_credits) == 1, f"expected one OUTAGE credit, got {len(outage_credits)}"
    assert outage_credits[0]["amount_cents"] == 62, \
        f"outage credit must be 62, got {outage_credits[0]['amount_cents']}"


# ===========================================================================
# Queue B — calculations: overage zero on THROTTLE policy
# ===========================================================================
def test_overage_zero_for_throttle_policy(api):
    """PRD §3.10: "a plan whose policy is `THROTTLE` or `UNLIMITED` never bills overage, so its overage charge is zero."

    Design: Corner/calculations/overage_zero_for_throttle_policy
    """
    ctx = setup_active_self_install_account(
        plan_overrides={"overage_policy": "THROTTLE", "included_gb": 100,
                        "monthly_fee_cents": 6000})
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], cycle_id, 200,
                                    posted_at_iso="2026-06-10T00:00:00Z"), NETOPS))
    cycle = validate_success(api.close_cycle(cycle_id, NETOPS))
    assert cycle["overage_charge_cents"] == 0, \
        f"THROTTLE policy overage must be 0, got {cycle['overage_charge_cents']}"
    assert cycle["throttle_state"] == "THROTTLED", \
        f"throttle_state must be THROTTLED, got {cycle['throttle_state']}"


# ===========================================================================
# Queue B — validations: cycle close/finalize guards, usage window
# ===========================================================================
def test_close_cycle_with_open_outage_rejected(api):
    """PRD §3.10: "Closing a cycle moves its `billing_state` from `OPEN` to `CLOSED`, but only when none of the cycle's outage events is still `OPEN` — every outage on the cycle must be `RESOLVED`, `CREDITED`, or `DISMISSED` first, or the close is rejected with `ERR_CYCLE_HAS_OPEN_OUTAGE`."

    Design: Corner/validations/close_cycle_with_open_outage_rejected
    """
    ctx = setup_active_self_install_account()
    cycle_id = ctx["cycle"]["id"]
    get_success_data(api.create_outage_event(
        create_outage_event_payload(ctx["account"]["id"], cycle_id,
                                    started_at_iso="2026-06-05T00:00:00Z"), NETOPS))
    resp = api.close_cycle(cycle_id, NETOPS)
    validate_error(resp, ApiErrorId.ERR_CYCLE_HAS_OPEN_OUTAGE, expected_status=409)


def test_finalize_open_cycle_rejected(api):
    """PRD §3.10: "finalize called on a cycle that is not `CLOSED` is rejected with `ERR_CYCLE_NOT_CLOSED`."

    Design: Corner/validations/finalize_open_cycle_returns_not_closed
    """
    ctx = setup_active_self_install_account()
    resp = api.finalize_cycle(ctx["cycle"]["id"], NETOPS)
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_CLOSED, expected_status=409)


def test_usage_record_outside_cycle_window_rejected(api):
    """PRD §3.5: "The `posted_at_iso` must fall within the target cycle's window; a record metered outside the window from `cycle_start_iso` to `cycle_end_iso` is rejected with `ERR_USAGE_OUTSIDE_CYCLE` (HTTP 422)."

    Design: Corner/validations/usage_record_outside_cycle_window_rejected
    """
    ctx = setup_active_self_install_account()
    resp = api.create_usage_record(
        create_usage_record_payload(ctx["account"]["id"], ctx["cycle"]["id"], 10,
                                    posted_at_iso="2026-07-02T00:00:00Z"), NETOPS)
    validate_error(resp, ApiErrorId.ERR_USAGE_OUTSIDE_CYCLE, expected_status=422)
