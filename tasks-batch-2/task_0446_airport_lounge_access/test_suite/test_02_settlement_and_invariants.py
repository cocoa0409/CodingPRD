"""Settlement crystallisation, the two-sided ledger, and conserved-quantity
invariants.

Completion pins settlement_amount_cents from the lounge rate at completion and
creates a PAYABLE settlement that raises the lounge's payable balance (PRD §3.4,
§3.8). The settlement summary diverges payable vs lifetime once paid. Reversal and
refund are compensations that restore conserved balances. Covers queue-A
dual_variant_calc / transitive_cascade / compensating_invariant and queue-B
endpoint/validation/entity corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Queue A: dual_variant_calc — rate snapshot at completion ────────────────
def test_settlement_uses_rate_at_completion_per_lounge(api):
    """PRD §3.4: "Completion computes and pins the visit's `settlement_amount_cents`
    as the visit's `occupant_count` multiplied by the lounge's `settlement_rate_cents`,
    where the occupant count is the value frozen at check-in (one plus the guest
    count) and the rate is the lounge's rate at completion time — if the lounge's
    settlement rate changed between check-in and completion, the rate in force at
    completion is the one that crystallises."

    Same single-occupant pattern at two lounges with rates 1200 and 1500 settles
    at 1200 and 1500 respectively.

    Design: Difficulty/dual_variant_calc/dvc_visit_settlement_rate_snapshot_at_completion
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE_PLUS", included_visits_per_year=-1)
    la = fixtures.create_lounge(airport_code="LAX", capacity=20, settlement_rate_cents=1200, guest_fee_cents=1000)
    lb = fixtures.create_lounge(airport_code="JFK", capacity=20, settlement_rate_cents=1500, guest_fee_cents=1000)
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])

    va = fixtures.open_hold(la["id"], member_id=member["id"])
    fixtures.check_in(va["id"], la["id"])
    vb = fixtures.open_hold(lb["id"], member_id=member["id"])
    fixtures.check_in(vb["id"], lb["id"])

    va_done = fixtures.complete_visit(va["id"], la["id"])
    vb_done = fixtures.complete_visit(vb["id"], lb["id"])
    assert va_done["settlement_amount_cents"] == 1200, va_done
    assert vb_done["settlement_amount_cents"] == 1500, vb_done


def test_settlement_summary_payable_vs_lifetime_diverge_after_pay(api):
    """PRD §3.8: "a separate settlement summary read exposes both this payable
    figure as `payable_balance_cents` and a `lifetime_earned_cents` that sums
    settlements in `PAYABLE` and `PAID` status (excluding `REVERSED`), alongside
    `paid_cents` — the two figures diverge once any settlement has been paid."
    PRD §3.8: "because the balance counts only `PAYABLE` settlements, paying them
    out recomputes the lounge's `settlement_balance_cents` down to zero, and the
    batch reports `paid_count` and `paid_total_cents`."

    Two visits of occupant_count 3 at rate 1200 each settle 3600 (total 7200);
    after payout payable drops to 0 while lifetime stays 7200.

    Design: Difficulty/dual_variant_calc/dvc_lounge_payable_vs_lifetime_settlement
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(
        tier="PRESTIGE", included_visits_per_year=10, included_guest_visits_per_year=10,
        guest_charge_cents=2500,
    )
    lounge = fixtures.create_lounge(
        airport_code="SFO", capacity=50, settlement_rate_cents=1200, guest_fee_cents=1505
    )
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])

    v1 = fixtures.open_hold(lounge["id"], member_id=member["id"], guest_count=2, guest_names=["G1", "G2"])
    fixtures.check_in(v1["id"], lounge["id"])
    fixtures.complete_visit(v1["id"], lounge["id"])
    v2 = fixtures.open_hold(lounge["id"], member_id=member["id"], guest_count=2, guest_names=["H1", "H2"])
    fixtures.check_in(v2["id"], lounge["id"])
    fixtures.complete_visit(v2["id"], lounge["id"])

    pre = get_success_data(api_client.get_settlement_summary(lounge["id"], ADMIN))
    assert pre["payable_balance_cents"] == 7200, pre
    assert pre["lifetime_earned_cents"] == 7200, pre

    get_success_data(api_client.pay_settlements(lounge["id"], ADMIN))

    post = get_success_data(api_client.get_settlement_summary(lounge["id"], ADMIN))
    assert post["payable_balance_cents"] == 0, post
    assert post["lifetime_earned_cents"] == 7200, post


# ─── Queue A: transitive_cascade — complete -> settlement -> balance ─────────
def test_complete_creates_payable_settlement_and_lifts_balance(api):
    """PRD §3.4: "Completion creates a **settlement** record for the lounge in
    `PAYABLE` status carrying that `amount_cents`, recomputes the lounge's
    `settlement_balance_cents` upward to include it, and frees the seats by
    recomputing the lounge's `current_occupancy` downward by `occupant_count`."

    Design: Difficulty/transitive_cascade/tc_complete_settlement_lounge_balance_depth2
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "ATL", "capacity": 50, "settlement_rate_cents": 1200},
    )
    settlement = fixtures.get_settlement_for_visit(visit["id"])
    assert settlement["status"] == "PAYABLE", settlement
    assert settlement["amount_cents"] == 1200, settlement
    lounge_now = fixtures.get_lounge(lounge["id"])
    assert lounge_now["settlement_balance_cents"] == 1200, lounge_now


# ─── Queue A: compensating_invariant ─────────────────────────────────────────
def test_reverse_settlement_restores_lounge_balance(api):
    """PRD §3.8: "The operator can also reverse an individual `PAYABLE` settlement
    as a compensation, moving it to `REVERSED` and recomputing the lounge's
    `settlement_balance_cents` downward by that settlement's amount as it drops out
    of the payable sum; the conserved-quantity invariant on settlements holds
    across reversal."

    Design: Difficulty/compensating_invariant/ci_settlement_reverse_lounge_balance_conserved
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "RDU", "capacity": 50, "settlement_rate_cents": 1200},
    )
    settlement = fixtures.get_settlement_for_visit(visit["id"])
    assert fixtures.get_lounge(lounge["id"])["settlement_balance_cents"] == 1200
    get_success_data(api_client.reverse_settlement(settlement["id"], ADMIN))
    assert fixtures.get_lounge(lounge["id"])["settlement_balance_cents"] == 0


def test_day_pass_refund_restores_wallet_balance(api):
    """PRD §3.6: "refunding moves the pass to the terminal `REFUNDED` status, posts
    a `DAY_PASS_REFUND` ledger entry for the member with a negative amount equal to
    the negation of the pass's `price_cents`, and recomputes the member's
    `wallet_balance_cents` so that it drops by the pass price."
    PRD §3.6: "When the buyer is a member, the purchase posts a `DAY_PASS` ledger
    entry for the member and recomputes that member's `wallet_balance_cents`."

    Design: Difficulty/compensating_invariant/ci_daypass_refund_wallet_balance_conserved
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    lounge = fixtures.create_lounge(airport_code="TPA", capacity=50, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(lounge["id"], member["id"])

    assert fixtures.get_member(member["id"])["wallet_balance_cents"] == 4000
    get_success_data(api_client.refund_day_pass(day_pass["id"], ADMIN))
    assert fixtures.get_member(member["id"])["wallet_balance_cents"] == 0


# ─── Queue B: endpoint / entity / validation corners ─────────────────────────
def test_pay_settlements_batch_reports_count_and_total(api):
    """PRD §3.8: "The operator can pay out a lounge's settlements as a batch in
    creation order, moving each `PAYABLE` settlement of that lounge to `PAID`;
    because the balance counts only `PAYABLE` settlements, paying them out
    recomputes the lounge's `settlement_balance_cents` down to zero, and the batch
    reports `paid_count` and `paid_total_cents`."

    Design: Corner/endpoints/ep_settlements_pay_batch_side_effect
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "MSP", "capacity": 10, "settlement_rate_cents": 1200},
    )
    result = get_success_data(api_client.pay_settlements(lounge["id"], ADMIN))
    assert result["paid_count"] == 1, result
    assert result["paid_total_cents"] == 1200, result
    assert fixtures.get_lounge(lounge["id"])["settlement_balance_cents"] == 0


def test_settlement_is_append_only_no_version(api):
    """PRD §2.4: "Two entities are append-only event records and deliberately carry
    a reduced field set: a settlement and a ledger entry each carry only `id` and
    `created_at`. For these two, both `updated_at` and `version` are absent — their
    status changes are modelled as new facts and recomputations elsewhere rather
    than as in-place versioned edits."

    Design: Corner/entities/entity_settlement_immutable_no_update_no_version
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "ORD", "capacity": 10, "settlement_rate_cents": 1200},
    )
    settlement = fixtures.get_settlement_for_visit(visit["id"])
    assert settlement["status"] == "PAYABLE", settlement
    assert settlement["amount_cents"] == 1200, settlement
    assert "version" not in settlement, settlement
    assert "updated_at" not in settlement, settlement


def test_reverse_already_reversed_settlement_rejected(api):
    """PRD §3.8: "A settlement lives over `PAYABLE`, `PAID`, and `REVERSED`, and
    only a `PAYABLE` settlement may be paid or reversed — an attempt against any
    other status is rejected with `ERR_SETTLEMENT_NOT_PAYABLE` (HTTP 409)."

    Design: Corner/validations/val_settlement_not_payable_double_reverse
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "AUS", "capacity": 10, "settlement_rate_cents": 1200},
    )
    settlement = fixtures.get_settlement_for_visit(visit["id"])
    get_success_data(api_client.reverse_settlement(settlement["id"], ADMIN))
    resp = api_client.reverse_settlement(settlement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_PAYABLE.value)


# ─── Queue A second-coverage: dual_variant_calc ──────────────────────────────
def test_settlement_amount_scales_with_occupant_count(api):
    """PRD §3.4: "Completion computes and pins the visit's `settlement_amount_cents`
    as the visit's `occupant_count` multiplied by the lounge's `settlement_rate_cents`,
    where the occupant count is the value frozen at check-in (one plus the guest
    count) and the rate is the lounge's rate at completion time..."

    A visit with two guests (occupant_count 3) at rate 1200 settles at 3600,
    distinguishing the occupant_count factor of the same formula.

    Design: Difficulty/dual_variant_calc/dvc_visit_settlement_rate_snapshot_at_completion
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={
            "tier": "PRESTIGE", "included_visits_per_year": 10,
            "included_guest_visits_per_year": 10,
        },
        lounge_overrides={"airport_code": "JFK", "capacity": 20, "settlement_rate_cents": 1200},
        visit_overrides={"guest_count": 2, "guest_names": ["G1", "G2"]},
    )
    assert visit["occupant_count"] == 3, visit
    assert visit["settlement_amount_cents"] == 3600, visit


def test_settlement_summary_lifetime_excludes_reversed(api):
    """PRD §3.8: "a separate settlement summary read exposes both this payable
    figure as `payable_balance_cents` and a `lifetime_earned_cents` that sums
    settlements in `PAYABLE` and `PAID` status (excluding `REVERSED`), alongside
    `paid_cents`..."

    After reversing the only settlement, both payable and lifetime drop to 0
    because REVERSED is excluded from the lifetime sum.

    Design: Difficulty/dual_variant_calc/dvc_lounge_payable_vs_lifetime_settlement
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "SFO", "capacity": 50, "settlement_rate_cents": 1200},
    )
    settlement = fixtures.get_settlement_for_visit(visit["id"])
    pre = get_success_data(api_client.get_settlement_summary(lounge["id"], ADMIN))
    assert pre["payable_balance_cents"] == 1200, pre
    assert pre["lifetime_earned_cents"] == 1200, pre
    get_success_data(api_client.reverse_settlement(settlement["id"], ADMIN))
    post = get_success_data(api_client.get_settlement_summary(lounge["id"], ADMIN))
    assert post["payable_balance_cents"] == 0, post
    assert post["lifetime_earned_cents"] == 0, post


# ─── Queue A second-coverage: transitive_cascade (complete) ──────────────────
def test_complete_frees_seats_alongside_settlement(api):
    """PRD §3.4: "Completion creates a **settlement** record for the lounge in
    `PAYABLE` status carrying that `amount_cents`, recomputes the lounge's
    `settlement_balance_cents` upward to include it, and frees the seats by
    recomputing the lounge's `current_occupancy` downward by `occupant_count`."

    The same complete operation that raises the payable balance also releases the
    visit's occupied seat — the cascade touches both lounge counters.

    Design: Difficulty/transitive_cascade/tc_complete_settlement_lounge_balance_depth2
    """
    plan, lounge, member, card, checked_in = fixtures.setup_checked_in_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "ATL", "capacity": 50, "settlement_rate_cents": 1200},
    )
    assert fixtures.get_lounge(lounge["id"])["current_occupancy"] == 1
    fixtures.complete_visit(checked_in["id"], lounge["id"])
    lounge_now = fixtures.get_lounge(lounge["id"])
    assert lounge_now["settlement_balance_cents"] == 1200, lounge_now
    assert lounge_now["current_occupancy"] == 0, lounge_now


# ─── Queue A second-coverage: compensating_invariant ─────────────────────────
def test_reverse_settlement_marks_reversed_status(api):
    """PRD §3.8: "The operator can also reverse an individual `PAYABLE` settlement
    as a compensation, moving it to `REVERSED` and recomputing the lounge's
    `settlement_balance_cents` downward by that settlement's amount as it drops out
    of the payable sum; the conserved-quantity invariant on settlements holds
    across reversal."

    Beyond restoring the balance, the settlement itself is moved to REVERSED.

    Design: Difficulty/compensating_invariant/ci_settlement_reverse_lounge_balance_conserved
    """
    plan, lounge, member, card, visit = fixtures.setup_completed_visit(
        plan_overrides={"included_visits_per_year": 10},
        lounge_overrides={"airport_code": "RDU", "capacity": 50, "settlement_rate_cents": 1200},
    )
    settlement = fixtures.get_settlement_for_visit(visit["id"])
    reversed_s = get_success_data(api_client.reverse_settlement(settlement["id"], ADMIN))
    assert reversed_s["status"] == "REVERSED", reversed_s
    assert fixtures.get_lounge(lounge["id"])["settlement_balance_cents"] == 0


def test_day_pass_refund_posts_negative_ledger_entry(api):
    """PRD §3.6: "refunding moves the pass to the terminal `REFUNDED` status, posts
    a `DAY_PASS_REFUND` ledger entry for the member with a negative amount equal to
    the negation of the pass's `price_cents`, and recomputes the member's
    `wallet_balance_cents` so that it drops by the pass price."

    The compensation posts a DAY_PASS_REFUND entry of -price_cents and moves the
    pass to REFUNDED.

    Design: Difficulty/compensating_invariant/ci_daypass_refund_wallet_balance_conserved
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    lounge = fixtures.create_lounge(airport_code="TPA", capacity=50, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(lounge["id"], member["id"])
    refunded = get_success_data(api_client.refund_day_pass(day_pass["id"], ADMIN))
    assert refunded["status"] == "REFUNDED", refunded
    entries = get_success_data(
        api_client.list_ledger_entries(
            ADMIN, params={"member_id": member["id"], "kind": "DAY_PASS_REFUND"}
        )
    )
    assert len(entries) == 1, entries
    assert entries[0]["amount_cents"] == -4000, entries[0]
