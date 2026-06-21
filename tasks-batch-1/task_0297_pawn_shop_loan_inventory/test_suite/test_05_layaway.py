"""Layaway: schedule computation (floor-then-remainder), the installment self-loop to
completion, installment-amount mismatch, and the closed-interval restock buffer conflict."""
from test_helpers import (
    validate_success, validate_error,
    factories as f,
    fixtures as fx,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


# ── Difficulty: layaway schedule rounds deposit half-up, floors installments,
#    and the final installment absorbs the remainder ──

def test_layaway_deposit_and_total_price(api):
    """PRD §3.9: "On creation the plan snapshots its `total_price_cents` from the
    inventory item's `list_price_cents`, then builds its schedule. The required up-front
    `deposit_cents` is the total price multiplied by the deposit rate of 2000 basis points
    (twenty percent), divided by 10000, rounded half-up."

    Design: Difficulty/combinatorial_formula/layaway_schedule_floor_then_remainder_mode_b
    """
    ctx = fx.setup_layaway_plan(installment_count=3, appraised_value_cents=40075)
    plan = ctx["plan"]
    # 40075*1.35 = 54101.25 -> $541.00 -> 54100; deposit round_half_up(54100*0.20)=10820.
    assert plan["total_price_cents"] == 54100
    assert plan["deposit_cents"] == 10820


def test_layaway_installments_floor_then_remainder(api):
    """PRD §3.9: "The remainder after the deposit is split into `installment_count` equal
    scheduled installments: each non-final installment's `amount_cents` is the floor of
    the remainder divided by the installment count, and the final installment absorbs
    whatever is left so the deposit plus all installments sum exactly to the total price."

    Design: Difficulty/combinatorial_formula/layaway_schedule_floor_then_remainder_mode_b
    """
    ctx = fx.setup_layaway_plan(installment_count=3, appraised_value_cents=40075)
    installments = sorted(ctx["installments"], key=lambda i: i["sequence"])
    # remaining = 54100 - 10820 = 43280; base = floor(43280/3) = 14426; final = 14428.
    assert installments[0]["amount_cents"] == 14426
    assert installments[2]["amount_cents"] == 14428


# ── Difficulty: installment self-loop stays ACTIVE then completes on the final one ──

def test_layaway_installment_self_loop_stays_active(api):
    """PRD §3.9: "Posting marks that installment `paid`, adds the amount to the plan's
    `paid_cents`, and increases the drawer's `balance_cents` by the amount."

    Design: Difficulty/non_linear_state_machine/layaway_installment_self_loop_then_complete
    """
    ctx = fx.setup_layaway_plan(installment_count=4, appraised_value_cents=40000)
    plan = ctx["plan"]
    # list 54000, n=4: deposit 10800, four installments of 10800.
    s1 = validate_success(api.post_layaway_installment(
        plan["id"], f.post_installment_payload(10800), MANAGER), 200)
    s2 = validate_success(api.post_layaway_installment(
        plan["id"], f.post_installment_payload(10800), MANAGER), 200)
    s3 = validate_success(api.post_layaway_installment(
        plan["id"], f.post_installment_payload(10800), MANAGER), 200)
    assert s1["status"] == "ACTIVE"
    assert s2["status"] == "ACTIVE"
    assert s3["status"] == "ACTIVE"


def test_layaway_final_installment_completes_plan(api):
    """PRD §3.9: "When the installment posted is the final one — that is, when the plan's
    `paid_cents` now equals its `total_price_cents` — the plan moves to `COMPLETED` and,
    bubbling up, the inventory item is auto-sold: it moves to `SOLD` with its
    `sold_price_cents` set to the plan's `total_price_cents`."

    Design: Difficulty/non_linear_state_machine/layaway_installment_self_loop_then_complete
    """
    ctx = fx.setup_layaway_plan(installment_count=4, appraised_value_cents=40000)
    plan = ctx["plan"]
    for _ in range(3):
        validate_success(api.post_layaway_installment(
            plan["id"], f.post_installment_payload(10800), MANAGER), 200)
    final = validate_success(api.post_layaway_installment(
        plan["id"], f.post_installment_payload(10800), MANAGER), 200)
    assert final["status"] == "COMPLETED"
    assert final["paid_cents"] == 54000


# ── Corner: installment with the wrong amount is rejected ──

def test_installment_wrong_amount_returns_mismatch(api):
    """PRD §3.9: "A posting is accepted only while the plan is `ACTIVE`, there is a next
    unpaid scheduled installment, and the supplied amount equals that installment's
    scheduled `amount_cents`; a mismatched amount or an exhausted schedule is rejected
    with `ERR_INSTALLMENT_MISMATCH`."

    Design: Corner/errors/installment_wrong_amount_returns_mismatch
    """
    ctx = fx.setup_layaway_plan(installment_count=4, appraised_value_cents=40000)
    res = api.post_layaway_installment(
        ctx["plan"]["id"], f.post_installment_payload(9999), MANAGER)
    validate_error(res, "ERR_INSTALLMENT_MISMATCH", 422)


# ── Difficulty: closed-interval restock buffer conflict on a new layaway ──

def test_layaway_reservation_closed_buffer_overlap(api):
    """PRD §3.9: "A new plan's `reserved_from_at` must be at or after the inventory item's
    `last_layaway_end_at` advanced by the schedule's `layaway_buffer_days`; the buffer
    endpoint itself is inclusive, so a `reserved_from_at` earlier than that buffered
    instant conflicts and the creation is rejected with `ERR_LAYAWAY_RESERVATION_CONFLICT`."
    PRD §3.9: "On cancellation the plan moves to `DEFAULTED`, the inventory item returns
    to `AVAILABLE`, and the item's `last_layaway_end_at` is set to the current clock
    instant (which is what the next plan's cool-down buffer measures from)."

    Design: Difficulty/resource_temporal_overlap/layaway_reservation_closed_buffer_overlap
    """
    ctx = fx.setup_forfeited_inventory(appraised_value_cents=40000)
    inv = ctx["inventory"]
    # First layaway, then cancel it at 2026-03-10 -> last_layaway_end_at = 2026-03-10.
    fx.set_clock("2026-03-10T00:00:00.000Z")
    plan1 = validate_success(api.create_layaway_plan(
        f.create_layaway_plan_payload(inv["id"], ctx["customer"]["id"],
                                      installment_count=2,
                                      reserved_until_at="2026-06-01T00:00:00.000Z"),
        MANAGER), 201)
    validate_success(api.cancel_layaway_plan(plan1["id"], MANAGER), 200)
    # Buffer is 7 days -> next plan must start >= 2026-03-17. A start at 2026-03-13 conflicts.
    fx.set_clock("2026-03-13T00:00:00.000Z")
    res = api.create_layaway_plan(
        f.create_layaway_plan_payload(inv["id"], ctx["customer"]["id"],
                                      installment_count=2,
                                      reserved_until_at="2026-07-01T00:00:00.000Z"),
        MANAGER)
    validate_error(res, "ERR_LAYAWAY_RESERVATION_CONFLICT", 409)


def test_layaway_after_buffer_elapsed_is_allowed(api):
    """PRD §3.9: "A new plan's `reserved_from_at` must be at or after the inventory item's
    `last_layaway_end_at` advanced by the schedule's `layaway_buffer_days`; the buffer
    endpoint itself is inclusive".

    Design: Difficulty/resource_temporal_overlap/layaway_reservation_closed_buffer_overlap
    """
    ctx = fx.setup_forfeited_inventory(appraised_value_cents=40000)
    inv = ctx["inventory"]
    fx.set_clock("2026-03-10T00:00:00.000Z")
    plan1 = validate_success(api.create_layaway_plan(
        f.create_layaway_plan_payload(inv["id"], ctx["customer"]["id"],
                                      installment_count=2,
                                      reserved_until_at="2026-06-01T00:00:00.000Z"),
        MANAGER), 201)
    validate_success(api.cancel_layaway_plan(plan1["id"], MANAGER), 200)
    # last_layaway_end_at 2026-03-10 + 7 buffer days = 2026-03-17 (inclusive) is allowed.
    fx.set_clock("2026-03-17T00:00:00.000Z")
    plan2 = validate_success(api.create_layaway_plan(
        f.create_layaway_plan_payload(inv["id"], ctx["customer"]["id"],
                                      installment_count=2,
                                      reserved_until_at="2026-07-01T00:00:00.000Z"),
        MANAGER), 201)
    assert plan2["status"] == "ACTIVE"
