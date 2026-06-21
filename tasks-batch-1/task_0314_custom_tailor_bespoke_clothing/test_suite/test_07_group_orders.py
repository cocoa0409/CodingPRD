"""Wedding/group orders: the sum-then-discount total, the lock vs cancel branch, and
the OCC group-version guard.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_group_with_confirmed_members, lock_group, create_group, add_confirmed_member,
    create_fabric,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── Queue A: combinatorial_formula (group total) ───────────────────────

def test_group_total_sum_then_discount_tier1(api):
    """PRD §3.9: "their `locked_total_cents` are summed into a raw sum. A member-count discount tier is then chosen from the number of such members: if there are at least 8 members the discount rate is ten percent; otherwise if there are at least 4 members the discount rate is five percent; otherwise there is no discount."
    PRD §3.9: "The group total is the raw sum minus the discount, where the discount is the
    raw sum multiplied by the chosen rate and rounded up to a whole cent — the sum is
    formed first and only then is the rounded discount subtracted from it."

    4 members each locked 39500: raw_sum 158000; n=4 -> 5% -> ceil(158000*0.05)=7900 ->
    group_total 150100.

    Design: Difficulty/combinatorial_formula/combinatorial_group_total_sum_then_discount_tier
    """
    group, members = setup_group_with_confirmed_members(num_members=4)
    # Each member locked at 39500 (base 20000 + yardage(3,6000)=18000 + MONOGRAM 1500).
    for m in members:
        assert m["order"]["locked_total_cents"] == 39500
    locked = lock_group(group["id"])
    assert locked["group_total_cents"] == 150100, \
        f"Expected 150100, got {locked['group_total_cents']}"
    assert locked["member_order_count"] == 4
    assert locked["status"] == "LOCKED"


def test_group_total_no_discount_below_tier1(api):
    """PRD §3.9: "if there are at least 8 members the discount rate is ten percent;
    otherwise if there are at least 4 members the discount rate is five percent; otherwise
    there is no discount."

    Second combinatorial instance on the same sum-then-discount rule at the no-discount
    branch: 3 members each 39500 -> raw_sum 118500, n=3 < 4 -> no discount -> 118500.

    Design: Difficulty/combinatorial_formula/combinatorial_group_total_sum_then_discount_tier
    """
    group, members = setup_group_with_confirmed_members(num_members=3)
    for m in members:
        assert m["order"]["locked_total_cents"] == 39500
    locked = lock_group(group["id"])
    assert locked["group_total_cents"] == 118500, \
        f"Expected 118500 (no discount), got {locked['group_total_cents']}"
    assert locked["member_order_count"] == 3


# ─── Queue A: non_linear_state_machine (group branch) ───────────────────

def test_group_cancel_cascade_cancels_members(api):
    """PRD §3.9: "cancelling drives the group to `CANCELLED`, advances its `version`, and cascade-cancels each of its non-terminal member orders — those in `DRAFT`, `CONFIRMED`, `IN_FITTING`, `REMAKE`, or `READY` — through the same order-cancellation release cascade described in §3.8."

    The FORMING -> CANCELLED branch: cancelling a 3-confirmed-member group cancels the
    group and each member order.

    Design: Difficulty/non_linear_state_machine/nonlinear_group_branch_lock_vs_cancel_divergent_effects
    """
    group, members = setup_group_with_confirmed_members(num_members=3)
    group = get_success_data(api.get_group_order(group["id"], SA))
    cancelled = validate_success(api.cancel_group_order(
        group["id"], {"expected_group_order_version": group["version"]}, SM), 200)
    assert cancelled["status"] == "CANCELLED"
    for m in members:
        after = get_success_data(api.get_order(m["order"]["id"], SA))
        assert after["status"] == "CANCELLED", f"member {m['order']['id']} should be CANCELLED"


def test_group_lock_branch_freezes_total(api):
    """PRD §3.9: "A successful lock moves the group from `FORMING` to `LOCKED`, recomputes `group_total_cents` over the locked-in member set, and advances the group's `version`."

    The other branch from FORMING: LOCK freezes the group total and does NOT cancel its
    members — a divergent side-effect from the CANCEL branch.

    Design: Difficulty/non_linear_state_machine/nonlinear_group_branch_lock_vs_cancel_divergent_effects
    """
    group, members = setup_group_with_confirmed_members(num_members=3)
    locked = lock_group(group["id"])
    assert locked["status"] == "LOCKED"
    # Members remain CONFIRMED, not cancelled.
    for m in members:
        after = get_success_data(api.get_order(m["order"]["id"], SA))
        assert after["status"] == "CONFIRMED"


# ─── Queue B: cross_cutting corner (OCC group lock) ─────────────────────

def test_group_lock_with_stale_version_rejected(api):
    """PRD §2.9: "locking a group requires `expected_group_order_version` holding the client's last-observed `GroupOrder.version`, and a mismatch with the group's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412); this guards against the group's membership having changed (a member joining, confirming, or cancelling, each of which recomputes membership and advances the group's version) since the client read it."

    A version captured before members joined/confirmed is stale once 3 members confirm.

    Design: Corner/cross_cutting_complexity_layers/occ_group_lock_stale_version
    """
    fabric = create_fabric(price_per_meter_cents=6000, bolt_meters_initial=2000)
    group = create_group()
    early = get_success_data(api.get_group_order(group["id"], SA))
    stale_version = early["version"]

    # Three members confirm, each advancing the group's version.
    for _ in range(3):
        add_confirmed_member(group["id"], fabric=fabric)

    res = api.lock_group_order(group["id"], {"expected_group_order_version": stale_version}, SM)
    validate_error(res, "ERR_STALE_VERSION")
    after = get_success_data(api.get_group_order(group["id"], SA))
    assert after["status"] == "FORMING"
