"""Shared business services: money, credits, loyalty, allocation, cascades."""

import calc
import constants as C
import store
from errors import ApiError
from store import db, now, touch


# ===========================================================================
# Collection helpers
# ===========================================================================
def subscriptions_of_account(account_id):
    return [s for s in db.subscriptions.values() if s["account_id"] == account_id]


def cycles_of_subscription(sub_id):
    return [c for c in db.cycles.values() if c["subscription_id"] == sub_id]


def lines_of_cycle(cycle_id):
    return store.by_created(
        [l for l in db.cycle_lines.values() if l["cycle_id"] == cycle_id])


def priced_lines(cycle_id):
    """Lines that contribute to subtotal / unit count: ALLOCATED or SUBSTITUTED.
    A SHORT_FILLED line is included in the sum but contributes 0 because its
    line_total_cents was zeroed."""
    return [l for l in lines_of_cycle(cycle_id)
            if l["status"] in ("ALLOCATED", "SUBSTITUTED")]


def credits_of_account(account_id):
    return [c for c in db.credits.values() if c["account_id"] == account_id]


def wallet_of_account(account_id):
    for w in db.loyalty_accounts.values():
        if w["account_id"] == account_id:
            return w
    return None


def entries_of_wallet(wallet_id):
    return store.by_created(
        [e for e in db.points_ledger_entries.values()
         if e["loyalty_account_id"] == wallet_id])


def plan_of_subscription(sub):
    return db.plans.get(sub["plan_id"])


def child_of_subscription(sub):
    return db.children.get(sub["child_id"])


def subscription_of_cycle(cycle):
    return db.subscriptions.get(cycle["subscription_id"])


# ===========================================================================
# Account computed money (PRD 3.1)
# ===========================================================================
def available_credit_cents(account_id):
    total = 0
    for credit in credits_of_account(account_id):
        if calc.spendable(credit, now()):
            total += int(credit["remaining_cents"])
    return total


def credit_bucket_cents(account_id, types):
    total = 0
    for credit in credits_of_account(account_id):
        if credit["credit_type"] in types and calc.spendable(credit, now()):
            total += int(credit["remaining_cents"])
    return total


def _estimate_target_cycle(account_id):
    """Earliest PLANNED/ALLOCATED cycle across the account's non-cancelled
    subscriptions, ordered by window_start ASC then created_at ASC."""
    candidates = []
    for sub in subscriptions_of_account(account_id):
        if sub["lifecycle_state"] == "CANCELLED":
            continue
        for cycle in cycles_of_subscription(sub["id"]):
            if cycle["status"] in ("PLANNED", "ALLOCATED"):
                candidates.append(cycle)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]))
    return candidates[0]


def next_charge_estimate_cents(account_id, include_credits=True):
    target = _estimate_target_cycle(account_id)
    if target is None:
        return 0
    if include_credits:
        return int(target["total_due_cents"])
    return int(target["subtotal_cents"]) + int(target["shipping_cents"])


def next_charge_cents(sub_id):
    """Total due of the earliest non-terminal cycle on the subscription.
    Cycle terminal states are RETURNED and CANCELLED (SCAFFOLD §1.2)."""
    candidates = [c for c in cycles_of_subscription(sub_id)
                  if c["status"] not in ("RETURNED", "CANCELLED")]
    if not candidates:
        return 0
    candidates.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]))
    return int(candidates[0]["total_due_cents"])


# ===========================================================================
# Credits
# ===========================================================================
def issue_credit(account_id, credit_type, issued_cents, refundable,
                 expires_at, source_gift_order_id=None, source_referral_id=None):
    row = store.base_row(full=True)
    row.update({
        "account_id": account_id,
        "source_gift_order_id": source_gift_order_id,
        "source_referral_id": source_referral_id,
        "credit_type": credit_type,
        "issued_cents": int(issued_cents),
        "consumed_cents": 0,
        "remaining_cents": int(issued_cents),
        "forfeited_cents": 0,
        "refundable": bool(refundable),
        "status": "AVAILABLE",
        "expires_at": expires_at,
    })
    db.credits[row["id"]] = row
    return row


def forfeit_credit(credit, terminal_status):
    """Move whatever remains into forfeited_cents and settle in EXPIRED/REVOKED.
    Keeps issued == consumed + remaining + forfeited at every instant."""
    credit["forfeited_cents"] = int(credit["forfeited_cents"]) + int(credit["remaining_cents"])
    credit["remaining_cents"] = 0
    credit["status"] = terminal_status
    touch(credit)
    return credit


def consume_credit(credit, cents):
    credit["consumed_cents"] = int(credit["consumed_cents"]) + cents
    credit["remaining_cents"] = int(credit["remaining_cents"]) - cents
    if credit["remaining_cents"] <= 0:
        credit["remaining_cents"] = 0
        credit["status"] = "CONSUMED"
    else:
        credit["status"] = "PARTIALLY_CONSUMED"
    touch(credit)


def restore_credit(credit, cents):
    credit["consumed_cents"] = int(credit["consumed_cents"]) - cents
    credit["remaining_cents"] = int(credit["remaining_cents"]) + cents
    if credit["consumed_cents"] <= 0:
        credit["consumed_cents"] = 0
        credit["remaining_cents"] = int(credit["issued_cents"]) - int(credit["forfeited_cents"])
        credit["status"] = "AVAILABLE"
    else:
        credit["status"] = "PARTIALLY_CONSUMED"
    touch(credit)


def reverse_credit_consumption_on_planned_cycles(credit):
    """Revoking a PARTIALLY_CONSUMED credit reverses whatever consumption it had
    recorded against a cycle whose status is PLANNED or ALLOCATED (PRD 3.7)."""
    for cycle_id, contributions in list(db.cycle_credit_contributions.items()):
        cycle = db.cycles.get(cycle_id)
        if cycle is None or cycle["status"] not in ("PLANNED", "ALLOCATED"):
            continue
        remaining = []
        reversed_cents = 0
        for entry in contributions:
            if entry["credit_id"] == credit["id"]:
                reversed_cents += entry["cents"]
            else:
                remaining.append(entry)
        if reversed_cents:
            db.cycle_credit_contributions[cycle_id] = remaining
            _reverse_gift_application(cycle, credit, reversed_cents)


def _reverse_gift_application(cycle, credit, cents):
    """Cascade hops 3..5 of the gift-refund chain."""
    if credit["credit_type"] == "GIFT":
        cycle["gift_credit_applied_cents"] = max(
            0, int(cycle["gift_credit_applied_cents"]) - cents)
    else:
        cycle["referral_credit_applied_cents"] = max(
            0, int(cycle["referral_credit_applied_cents"]) - cents)
    after = (int(cycle["subtotal_cents"]) + int(cycle["shipping_cents"])
             - int(cycle["gift_credit_applied_cents"])
             - int(cycle["referral_credit_applied_cents"])
             - int(cycle["loyalty_redemption_applied_cents"]))
    cycle["total_due_cents"] = max(0, after - int(cycle["promo_discount_cents"]))
    if cycle["total_due_cents"] > 0 and cycle["payment_status"] == "FULLY_COVERED":
        cycle["payment_status"] = "UNCHARGED"
        cycle["charged_cash_cents"] = 0
        cycle["retained_cash_cents"] = 0
    touch(cycle)
    sub = subscription_of_cycle(cycle)
    if sub is not None:
        recompute_account_estimate(sub["account_id"])


def recompute_account_estimate(account_id):
    account = db.accounts.get(account_id)
    if account is None:
        return
    account["next_charge_estimate_cents"] = next_charge_estimate_cents(account_id, True)
    account["available_credit_cents"] = available_credit_cents(account_id)


# ===========================================================================
# Loyalty ledger
# ===========================================================================
def write_ledger_entry(wallet, entry_type, delta_points, cycle_id=None,
                       earn_base_cents=0, tier_multiplier_applied=0,
                       expires_at=None):
    row = store.base_row(full=False)
    row.update({
        "loyalty_account_id": wallet["id"],
        "cycle_id": cycle_id,
        "entry_type": entry_type,
        "delta_points": int(delta_points),
        "earn_base_cents": int(earn_base_cents),
        "tier_multiplier_applied": tier_multiplier_applied,
        "expires_at": expires_at,
    })
    db.points_ledger_entries[row["id"]] = row
    recompute_wallet_balance(wallet)
    return row


def recompute_wallet_balance(wallet):
    """points_balance always equals the sum of its ledger movements. The balance
    is permitted to go negative after a clawback; no floor is applied."""
    total = 0
    for entry in db.points_ledger_entries.values():
        if entry["loyalty_account_id"] == wallet["id"]:
            total += int(entry["delta_points"])
    wallet["points_balance"] = total
    wallet["trailing_earned_points"] = trailing_earned_points(wallet["id"])
    return wallet


def trailing_earned_points(wallet_id):
    floor_instant = store.minus_days(now(), C.TIER_EVAL_WINDOW_DAYS)
    total = 0
    for entry in db.points_ledger_entries.values():
        if entry["loyalty_account_id"] != wallet_id:
            continue
        if entry["entry_type"] != "EARN":
            continue
        if entry["created_at"] >= floor_instant:
            total += int(entry["delta_points"])
    return total


def evaluate_tier(wallet, upgrade_only):
    computed = calc.tier_for(trailing_earned_points(wallet["id"]))
    stored = wallet["tier"]
    if upgrade_only and calc.TIER_RANK[computed] < calc.TIER_RANK[stored]:
        computed = stored
    wallet["tier"] = computed
    wallet["tier_evaluated_at"] = now()
    return computed


def apply_free_shipping_from_tier(account_id, tier, flipped_only=True):
    """Cascade hops 4 and 5 of the delivery chain."""
    eligible = tier in ("SILVER", "GOLD")
    if not eligible:
        return
    for sub in subscriptions_of_account(account_id):
        if sub["lifecycle_state"] not in ("ACTIVE", "PAUSED"):
            continue
        was = bool(sub["free_shipping_eligible"])
        sub["free_shipping_eligible"] = True
        touch(sub)
        if flipped_only and was:
            continue
        # HOP 5 — the earliest PLANNED/ALLOCATED cycle loses its shipping charge.
        candidates = [c for c in cycles_of_subscription(sub["id"])
                      if c["status"] in ("PLANNED", "ALLOCATED")]
        if not candidates:
            continue
        candidates.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]))
        cycle = candidates[0]
        apply_pricing(cycle, force_shipping=0)
        touch(cycle)
    recompute_account_estimate(account_id)


def points_expiry_sweep(wallet):
    """FIFO by expires_at ASC then created_at ASC; consumption is charged against
    lots in that same order. Returns the number of EXPIRE entries written."""
    entries = entries_of_wallet(wallet["id"])
    lots = [e for e in entries if e["entry_type"] == "EARN"]
    lots.sort(key=lambda e: (e["expires_at"], e["created_at"], e["_seq"]))

    pool = 0
    for entry in entries:
        if entry["entry_type"] in ("REDEEM", "CLAWBACK") and entry["delta_points"] < 0:
            pool += -int(entry["delta_points"])

    charged = {}
    for lot in lots:
        already = int(lot.get("_expired", 0))
        capacity = max(0, int(lot["delta_points"]) - already)
        take = min(pool, capacity)
        charged[lot["id"]] = already + take
        pool -= take

    written = 0
    for lot in lots:
        if lot.get("_swept"):
            continue
        if lot["expires_at"] is None or lot["expires_at"] > now():
            continue
        unconsumed = int(lot["delta_points"]) - charged.get(lot["id"], 0)
        if unconsumed > 0:
            write_ledger_entry(wallet, "EXPIRE", -unconsumed, cycle_id=None)
            lot["_expired"] = unconsumed
            written += 1
        lot["_swept"] = True
    recompute_wallet_balance(wallet)
    return written


# ===========================================================================
# Pricing — the nine-step derivation (PRD 3.7)
# ===========================================================================
def _pool(account_id, types, named=None):
    rows = []
    for credit in credits_of_account(account_id):
        if credit["credit_type"] not in types:
            continue
        if named is not None:
            if credit["id"] not in named:
                continue
            if credit["status"] not in ("AVAILABLE", "PARTIALLY_CONSUMED"):
                continue
        elif not calc.spendable(credit, now()):
            continue
        if named is not None and credit["expires_at"] <= now():
            continue
        rows.append(credit)
    rows.sort(key=calc.credit_pool_key)
    return rows


def _draw(pool, amount):
    """Take `amount` cents from the pool in order; returns the plan."""
    plan = []
    remaining = amount
    for credit in pool:
        if remaining <= 0:
            break
        take = min(remaining, int(credit["remaining_cents"]))
        if take > 0:
            plan.append({"credit": credit, "cents": take})
            remaining -= take
    return plan


def derive_pricing(cycle, named_credit_ids=None):
    sub = subscription_of_cycle(cycle)
    plan_row = plan_of_subscription(sub) if sub else None
    account_id = sub["account_id"] if sub else None
    lines = priced_lines(cycle["id"])

    # step 1 — subtotal
    subtotal = sum(int(l["line_total_cents"]) for l in lines)
    # step 2 — shipping, from the PRE-credit, PRE-discount subtotal
    units = calc.total_units(lines)
    shipping = calc.shipping_cents(
        subtotal, units, bool(sub["free_shipping_eligible"]) if sub else False)
    # step 3 — the base
    base = subtotal + shipping

    named = set(named_credit_ids) if named_credit_ids is not None else None

    # step 4 — gift credit, stack position one (cap is the whole base)
    gift_pool = _pool(account_id, ("GIFT",), named) if account_id else []
    gift_available = sum(int(c["remaining_cents"]) for c in gift_pool)
    gift_applied = min(gift_available, base)

    # step 5 — referral / goodwill / short-fill, capped at 50% of the ORIGINAL base
    ref_pool = _pool(account_id, ("REFERRAL", "GOODWILL", "SHORT_FILL"), named) \
        if account_id else []
    ref_available = sum(int(c["remaining_cents"]) for c in ref_pool)
    ref_applied = min(ref_available, base - gift_applied, calc.referral_cap(base))
    if ref_applied < 0:
        ref_applied = 0

    # step 6 — loyalty redemption, capped at 30% of the running remainder
    after_ref = base - gift_applied - ref_applied
    wallet = wallet_of_account(account_id) if account_id else None
    balance = int(wallet["points_balance"]) if wallet else 0
    loyalty_applied, points_redeemed = calc.loyalty_redemption(after_ref, balance)

    # step 7 — the amount after loyalty
    after_loyalty = base - gift_applied - ref_applied - loyalty_applied

    # step 8 — promotional discount, per line then summed
    promo_pct = plan_row["promo_discount_pct"] if plan_row else 0
    promo = calc.promo_discount(lines, promo_pct, after_loyalty)

    # step 9 — the total
    total = max(0, after_loyalty - promo)

    return {
        "subtotal_cents": subtotal,
        "shipping_cents": shipping,
        "base": base,
        "gift_credit_applied_cents": gift_applied,
        "referral_credit_applied_cents": ref_applied,
        "loyalty_redemption_applied_cents": loyalty_applied,
        "loyalty_points_redeemed": points_redeemed,
        "promo_discount_cents": promo,
        "total_due_cents": total,
        "gift_plan": _draw(gift_pool, gift_applied),
        "referral_plan": _draw(ref_pool, ref_applied),
        "points_earn_base_cents": max(0, subtotal - gift_applied - promo),
    }


def apply_pricing(cycle, force_shipping=None, rederive_credits=False):
    """Write the derivation onto the cycle.

    The full nine-step stack of section 3.7 is re-derived only where the PRD says
    the cycle's money is "computed as described in section 3.7" — that is, at
    allocation and re-allocation (and, separately, at charge and on the preview
    read, which call derive_pricing directly). Every other site in the PRD names
    the exact fields it recomputes: the short fill recomputes "subtotal_cents and
    total_due_cents" (3.6), the substitution hop recomputes "subtotal_cents,
    shipping_cents and total_due_cents" (3.6), and cascade hop five recomputes
    "shipping_cents ... to 0 and its total_due_cents ... accordingly" (3.8). None
    of those name a credit-application field, and none of them is caused by a
    change in the household's credit or point position, so the applications
    already recorded on the cycle are carried through untouched.

    `force_shipping` pins step two (cascade hop 5 pins it to 0)."""
    lines = priced_lines(cycle["id"])
    subtotal = sum(int(l["line_total_cents"]) for l in lines)
    cycle["subtotal_cents"] = subtotal
    sub = subscription_of_cycle(cycle)
    plan_row = plan_of_subscription(sub) if sub else None

    # step 2 — shipping, from the PRE-credit, PRE-discount subtotal.
    if force_shipping is not None:
        cycle["shipping_cents"] = int(force_shipping)
    else:
        units = calc.total_units(lines)
        cycle["shipping_cents"] = calc.shipping_cents(
            subtotal, units, bool(sub["free_shipping_eligible"]) if sub else False)

    if rederive_credits and cycle["payment_status"] == "UNCHARGED":
        breakdown = derive_pricing(cycle)
        cycle["gift_credit_applied_cents"] = breakdown["gift_credit_applied_cents"]
        cycle["referral_credit_applied_cents"] = breakdown["referral_credit_applied_cents"]
        cycle["loyalty_redemption_applied_cents"] = breakdown["loyalty_redemption_applied_cents"]
        cycle["loyalty_points_redeemed"] = breakdown["loyalty_points_redeemed"]

    base = int(cycle["subtotal_cents"]) + int(cycle["shipping_cents"])
    after_loyalty = (base - int(cycle["gift_credit_applied_cents"])
                     - int(cycle["referral_credit_applied_cents"])
                     - int(cycle["loyalty_redemption_applied_cents"]))
    promo = calc.promo_discount(
        lines, plan_row["promo_discount_pct"] if plan_row else 0, after_loyalty)
    cycle["promo_discount_cents"] = promo
    cycle["total_due_cents"] = max(0, after_loyalty - promo)
    return cycle


# ===========================================================================
# Allocation — selector, waterfall and empty-pool diagnosis (PRD 3.5)
# ===========================================================================
def active_skus_at_stage(stage):
    return [s for s in db.skus.values()
            if s["status"] == "ACTIVE" and s["stage"] == stage]


def diagnose_empty_pool(pool_at_stage, child, plan_row):
    """The earliest rung that explains the empty pool wins. ERR_NO_ELIGIBLE_SKU
    is returned only when no ACTIVE SKU exists at the child's stage at all."""
    if not pool_at_stage:
        raise ApiError("ERR_NO_ELIGIBLE_SKU")
    fails = []
    for sku in pool_at_stage:
        fails.append((
            not calc.allergen_eligible(sku, child),
            not calc.hypo_required_ok(sku, child),
            not calc.plan_allows_ok(sku, plan_row),
        ))
    for index, error_id in enumerate(("ERR_ALLERGEN_BLOCKED",
                                      "ERR_HYPOALLERGENIC_REQUIRED",
                                      "ERR_HYPOALLERGENIC_NOT_ALLOWED")):
        for row in fails:
            if row[index] and sum(1 for x in row if x) == 1:
                raise ApiError(error_id)
    for index, error_id in enumerate(("ERR_ALLERGEN_BLOCKED",
                                      "ERR_HYPOALLERGENIC_REQUIRED",
                                      "ERR_HYPOALLERGENIC_NOT_ALLOWED")):
        for row in fails:
            if row[index]:
                raise ApiError(error_id)
    raise ApiError("ERR_NO_ELIGIBLE_SKU")


def allocation_candidates(child, plan_row):
    """Raises the diagnosing error when the pool is empty."""
    at_stage = active_skus_at_stage(child["stage"])
    if not at_stage:
        raise ApiError("ERR_NO_ELIGIBLE_SKU")
    safe = [s for s in at_stage
            if calc.allergen_eligible(s, child)
            and calc.hypo_required_ok(s, child)
            and calc.plan_allows_ok(s, plan_row)]
    if not safe:
        diagnose_empty_pool(at_stage, child, plan_row)
    stocked = [s for s in safe if int(s["stock_packs"]) >= 1]
    stocked.sort(key=calc.rank_key)
    return stocked


def build_lines(cycle, sub, child, plan_row):
    """Waterfall allocation. A partial allocation is NEVER persisted."""
    candidates = allocation_candidates(child, plan_row)
    remaining = int(sub["pack_count"])
    takes = []
    for sku in candidates:
        if remaining <= 0:
            break
        take = min(remaining, int(sku["stock_packs"]))
        if take > 0:
            takes.append((sku, take))
            remaining -= take
    if remaining > 0:
        raise ApiError("ERR_SKU_OUT_OF_STOCK")

    created = []
    for sku, take in takes:
        sku["stock_packs"] = int(sku["stock_packs"]) - take
        store.touch(sku)
        unit = calc.effective_unit_price(sku)
        row = store.base_row(full=True)
        row.update({
            "cycle_id": cycle["id"],
            "sku_id": sku["id"],
            "quantity_packs": take,
            "unit_price_cents": unit,
            "line_total_cents": take * unit,
            "status": "ALLOCATED",
            "substitution_attempts": 0,
            "short_filled_units": 0,
            "_pending_reason": None,
        })
        db.cycle_lines[row["id"]] = row
        created.append(row)
    return created


def return_line_stock(line):
    sku = db.skus.get(line["sku_id"])
    if sku is not None and int(line["quantity_packs"]) > 0:
        sku["stock_packs"] = int(sku["stock_packs"]) + int(line["quantity_packs"])
        store.touch(sku)


def return_cycle_stock(cycle, delete_lines=True):
    for line in lines_of_cycle(cycle["id"]):
        return_line_stock(line)
        if delete_lines:
            db.cycle_lines.pop(line["id"], None)


def allocate_cycle(cycle, sub, child, plan_row):
    # The freeze of stage_at_allocation is only persisted once the selector and
    # the waterfall have both succeeded: PRD 2.6 allows exactly one rung to leave
    # a trace behind a rejection, and it is not this one, so a failed allocation
    # must leave stage_at_allocation null ("it stays null while the cycle is
    # still PLANNED", PRD 3.5).
    build_lines(cycle, sub, child, plan_row)
    cycle["stage_at_allocation"] = child["stage"]
    apply_pricing(cycle, rederive_credits=True)
    return cycle


def reallocate_cycle(cycle):
    """A resize landing APPLIED_CURRENT rebuilds the cycle's lines at the new
    stage. Best effort: if the new stage cannot be filled, the previous lines are
    restored so that the measurement itself still succeeds."""
    sub = subscription_of_cycle(cycle)
    if sub is None:
        return
    child = child_of_subscription(sub)
    plan_row = plan_of_subscription(sub)
    if child is None:
        return
    if cycle["status"] != "ALLOCATED":
        return
    snapshot = lines_of_cycle(cycle["id"])
    stock_snapshot = dict((s["id"], int(s["stock_packs"])) for s in db.skus.values())
    for line in snapshot:
        return_line_stock(line)
        db.cycle_lines.pop(line["id"], None)
    try:
        build_lines(cycle, sub, child, plan_row)
    except ApiError:
        for sku_id, packs in stock_snapshot.items():
            if sku_id in db.skus:
                db.skus[sku_id]["stock_packs"] = packs
        for line in snapshot:
            db.cycle_lines[line["id"]] = line
        return
    cycle["stage_at_allocation"] = child["stage"]
    apply_pricing(cycle, rederive_credits=True)
    touch(cycle)
    recompute_account_estimate(sub["account_id"])


# ===========================================================================
# Substitution ladder (PRD 3.6)
# ===========================================================================
def _passes_safety(sku, child, plan_row):
    return (calc.allergen_eligible(sku, child)
            and calc.hypo_required_ok(sku, child)
            and calc.plan_allows_ok(sku, plan_row))


def substitution_candidates(line, from_sku, child, plan_row):
    """Returns (rung, ranked_candidates) for the FIRST rung with a non-empty set."""
    need = int(line["quantity_packs"])
    active = [s for s in db.skus.values() if s["status"] == "ACTIVE"]

    rung1 = [s for s in active
             if s["stage"] == from_sku["stage"]
             and s["line"] == from_sku["line"]
             and int(s["pack_size_units"]) != int(from_sku["pack_size_units"])
             and int(s["stock_packs"]) >= need
             and _passes_safety(s, child, plan_row)]
    if rung1:
        return 1, sorted(rung1, key=calc.rank_key)

    rung2 = [s for s in active
             if s["stage"] == from_sku["stage"]
             and s["line"] == "HYPOALLERGENIC"
             and int(s["stock_packs"]) >= need
             and _passes_safety(s, child, plan_row)
             and plan_row is not None and bool(plan_row["allows_hypoallergenic"])]
    if rung2:
        return 2, sorted(rung2, key=calc.rank_key)

    index = C.STAGE_ORDER.index(from_sku["stage"])
    up_index = index + C.SUBSTITUTION_ADJACENT_STAGE_STEP
    up_stage = C.STAGE_ORDER[up_index] if up_index < len(C.STAGE_ORDER) else None
    rung3 = []
    if up_stage is not None:
        rung3 = [s for s in active
                 if s["stage"] == up_stage
                 and s["line"] == from_sku["line"]
                 and int(s["stock_packs"]) >= need
                 and _passes_safety(s, child, plan_row)]
    if rung3:
        return 3, sorted(rung3, key=calc.rank_key)
    return 0, []


def write_substitution_event(line, from_sku_id, to_sku_id, rung, outcome,
                             price_delta, reason):
    row = store.base_row(full=False)
    row.update({
        "cycle_line_id": line["id"],
        "from_sku_id": from_sku_id,
        "to_sku_id": to_sku_id,
        "ladder_rung": rung,
        "outcome": outcome,
        "price_delta_cents": price_delta,
        "reason": reason,
    })
    db.substitution_events[row["id"]] = row
    return row


def flag_line_pending(line, reason):
    line["status"] = "SUBSTITUTION_PENDING"
    line["_pending_reason"] = reason
    touch(line)


def rescreen_lines_for_child(child, reason="ALLERGEN_RESCREEN"):
    """Cascade hop 2: every re-screenable line whose SKU no longer passes moves
    to SUBSTITUTION_PENDING. A CUTOFF_LOCKED or later cycle is never re-screened."""
    touched = []
    for sub in db.subscriptions.values():
        if sub["child_id"] != child["id"]:
            continue
        plan_row = plan_of_subscription(sub)
        for cycle in cycles_of_subscription(sub["id"]):
            if cycle["status"] not in ("PLANNED", "ALLOCATED"):
                continue
            for line in lines_of_cycle(cycle["id"]):
                if line["status"] not in ("ALLOCATED", "SUBSTITUTED"):
                    continue
                sku = db.skus.get(line["sku_id"])
                if sku is None:
                    continue
                if not _passes_safety(sku, child, plan_row):
                    flag_line_pending(line, reason)
                    touched.append(line)
    return touched


# ===========================================================================
# Resize landing (PRD 3.2 "Where a resize lands")
# ===========================================================================
RESIZE_CANDIDATE_STATUSES = ("PLANNED", "ALLOCATED", "CUTOFF_LOCKED",
                             "DISPATCHED", "DELIVERED")


def resize_target_cycle(sub):
    """Returns (status, target_cycle_id, current_cycle)."""
    candidates = [c for c in cycles_of_subscription(sub["id"])
                  if c["status"] in RESIZE_CANDIDATE_STATUSES]
    candidates.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]))
    if not candidates:
        return "APPLIED_NEXT", None, None
    current = candidates[0]
    if current["status"] in ("PLANNED", "ALLOCATED") and now() < current["cutoff_at"]:
        return "APPLIED_CURRENT", current["id"], current
    following = None
    for cycle in candidates[1:]:
        if cycle["status"] == "PLANNED":
            following = cycle["id"]
            break
    return "APPLIED_NEXT", following, current


def write_resize_event(sub, child, origin, from_stage, to_stage, status,
                       target_cycle_id, measured_weight_grams, reject_reason=None):
    row = store.base_row(full=False)
    row.update({
        "subscription_id": sub["id"] if sub else None,
        "child_id": child["id"],
        "target_cycle_id": target_cycle_id,
        "origin": origin,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "status": status,
        "measured_weight_grams": measured_weight_grams,
        "reject_reason": reject_reason,
    })
    db.resize_events[row["id"]] = row
    return row


def auto_resize_count_in_period(sub_id):
    floor_instant = store.minus_days(now(), C.AUTO_RESIZE_PERIOD_DAYS)
    count = 0
    for event in db.resize_events.values():
        if event["subscription_id"] != sub_id:
            continue
        if event["origin"] != "AUTO":
            continue
        if event["status"] not in ("APPLIED_CURRENT", "APPLIED_NEXT"):
            continue
        if event["created_at"] >= floor_instant:
            count += 1
    return count


def resize_subscription_for_child(child):
    """The subscription whose allocation stage the child's weight drives."""
    live = [s for s in db.subscriptions.values()
            if s["child_id"] == child["id"]
            and s["lifecycle_state"] in ("ACTIVE", "PAUSED")]
    if live:
        return store.by_created(live)[0]
    draft = [s for s in db.subscriptions.values()
             if s["child_id"] == child["id"] and s["lifecycle_state"] == "DRAFT"]
    if draft:
        return store.by_created(draft)[0]
    return None


# ===========================================================================
# Skips and pauses
# ===========================================================================
def skip_allowance_remaining(sub_id):
    floor_instant = store.minus_days(now(), C.SKIP_WINDOW_DAYS)
    used = 0
    for record in db.skip_records.values():
        if record["subscription_id"] != sub_id:
            continue
        if record["status"] != "APPLIED":
            continue
        if record["created_at"] >= floor_instant:
            used += 1
    return C.SKIP_ALLOWANCE_PER_WINDOW - used


def pause_records_of(sub_id):
    return store.by_created(
        [p for p in db.pause_records.values() if p["subscription_id"] == sub_id])


def recompute_pause_days(sub):
    """Closed-closed day intervals: both endpoints count."""
    total = 0
    for record in pause_records_of(sub["id"]):
        if record["status"] == "ENDED" and record["actual_end_date"] is not None:
            days = (record["actual_end_date"] - record["start_date"]).days + 1
        elif record["status"] == "ACTIVE":
            days = (store.today() - record["start_date"]).days + 1
        else:
            days = 0
        record["consumed_days"] = max(0, days)
        total += max(0, days)
    sub["cumulative_pause_days"] = total
    return total


# ===========================================================================
# Shipments
# ===========================================================================
def create_shipment(account_id, cycle_id, gift_order_id, service_level):
    row = store.base_row(full=True)
    row.update({
        "account_id": account_id,
        "cycle_id": cycle_id,
        "gift_order_id": gift_order_id,
        "status": "CREATED",
        "exception_count": 0,
        "service_level": service_level or "STANDARD",
        "eta_days": C.SHIPMENT_ETA_DAYS_STANDARD,
        "dispatched_at": now(),
        "delivered_at": None,
    })
    db.shipments[row["id"]] = row
    return row


def check_shipment_spacing(account_id):
    """POINT occupation with a symmetric buffer. 'Within' is STRICT: a gap of
    exactly 12 hours is allowed. Counts across BOTH pipelines."""
    buffer_seconds = C.SHIPMENT_SPACING_BUFFER_HOURS * 3600
    for shipment in db.shipments.values():
        if shipment["account_id"] != account_id:
            continue
        if shipment["status"] == "RETURNED":
            continue
        if shipment["dispatched_at"] is None:
            continue
        delta = abs((now() - shipment["dispatched_at"]).total_seconds())
        if delta < buffer_seconds:
            raise ApiError("ERR_SHIPMENT_SPACING_VIOLATION")


def shipment_of_cycle(cycle_id):
    rows = [s for s in db.shipments.values() if s["cycle_id"] == cycle_id]
    return store.by_created(rows)[-1] if rows else None


def shipment_of_gift(gift_order_id):
    rows = [s for s in db.shipments.values() if s["gift_order_id"] == gift_order_id]
    return store.by_created(rows)[-1] if rows else None


# ===========================================================================
# Registry
# ===========================================================================
def items_of_registry(registry_id):
    return store.by_created(
        [i for i in db.registry_items.values() if i["registry_id"] == registry_id])


def gifts_of_item(item_id):
    return store.by_created(
        [g for g in db.gift_orders.values() if g["registry_item_id"] == item_id])


def gifts_of_registry(registry_id):
    rows = []
    for item in items_of_registry(registry_id):
        rows.extend(gifts_of_item(item["id"]))
    return rows


def recompute_registry(registry):
    items = items_of_registry(registry["id"])
    requested = sum(int(i["requested_quantity"]) for i in items)
    fulfilled = sum(int(i["fulfilled_quantity"]) for i in items)
    registry["completion_pct"] = calc.registry_completion_pct(requested, fulfilled)
    registry["inflight_gift_count"] = sum(
        1 for g in gifts_of_registry(registry["id"])
        if g["status"] in ("PAID", "CLAIMED_CREDIT", "CLAIMED_ITEM"))
    return registry


def registry_of_item(item):
    return db.registries.get(item["registry_id"])


def apply_item_fulfilment(item, delta):
    """Registry units are conserved; fulfilled_quantity never exceeds requested."""
    item["fulfilled_quantity"] = max(0, int(item["fulfilled_quantity"]) + delta)
    requested = int(item["requested_quantity"])
    if item["fulfilled_quantity"] >= requested:
        item["fulfilled_quantity"] = min(item["fulfilled_quantity"], requested)
        item["status"] = "FULFILLED"
    elif item["fulfilled_quantity"] > 0:
        item["status"] = "PARTIALLY_FULFILLED"
    else:
        item["status"] = "REQUESTED"
    touch(item)
    registry = registry_of_item(item)
    if registry is not None:
        recompute_registry(registry)
        touch(registry)


# ===========================================================================
# Refunds
# ===========================================================================
def create_refund(account_id, cycle_id, gift_order_id, reason, requested_cents,
                  restock_fee_cents):
    row = store.base_row(full=True)
    row.update({
        "account_id": account_id,
        "cycle_id": cycle_id,
        "gift_order_id": gift_order_id,
        "reason": reason,
        "requested_cents": int(requested_cents),
        "refunded_cash_cents": 0,
        "restock_fee_cents": int(restock_fee_cents),
        "points_clawed_back": 0,
        "credits_restored_cents": 0,
        "status": "REQUESTED",
        "approved_by_user_id": None,
        "settled_by_user_id": None,
    })
    db.refunds[row["id"]] = row
    return row


# ===========================================================================
# Referrals
# ===========================================================================
def referrals_of_referrer(account_id):
    return [r for r in db.referrals.values()
            if r["referrer_account_id"] == account_id]


def check_referral_policy(referrer_id, referee_id):
    """Rungs 59, 60 and 61, in that order. The cap is enforced at CREATION."""
    if referrer_id == referee_id:
        raise ApiError("ERR_SELF_REFERRAL")
    for referral in db.referrals.values():
        if referral["referrer_account_id"] == referee_id and \
                referral["referee_account_id"] == referrer_id:
            raise ApiError("ERR_RECIPROCAL_REFERRAL")
    floor_instant = store.minus_days(now(), C.REFERRAL_PERIOD_DAYS)
    count = sum(1 for r in referrals_of_referrer(referrer_id)
                if r["created_at"] >= floor_instant)
    if count >= C.REFERRAL_CAP_PER_PERIOD:
        raise ApiError("ERR_REFERRAL_CAP_EXCEEDED")


def create_referral(referrer_id, referee_id, code):
    row = store.base_row(full=True)
    row.update({
        "referrer_account_id": referrer_id,
        "referee_account_id": referee_id,
        "vesting_cycle_id": None,
        "code": code,
        "status": "PENDING",
        "credit_cents": 0,
        "vested_at": None,
        "expires_at": store.plus_days(now(), C.REFERRAL_VEST_WINDOW_DAYS),
    })
    db.referrals[row["id"]] = row
    return row
