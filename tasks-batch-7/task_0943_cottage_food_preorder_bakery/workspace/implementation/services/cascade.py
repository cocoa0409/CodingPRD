"""The three declared cascades.

  * recall               -- 6 hops, PRD 3.10, with its two deliberate stops
  * label supersession   -- 3 hops, PRD 3.2
  * shortfall allocation -- 4 hops, PRD 3.7

Every entity a hop mutates has its `version` incremented and its `updated_at`
refreshed; a hop that does not fire mutates nothing (PRD 2.11).
"""

import config
from db import DB, touch
from errors import ApiError
from services import allergen, capacity, money
from services.gates import active_payment
from tsutil import cents, dec


# ---------------------------------------------------------------------------
# label supersession cascade (recipe republication)
# ---------------------------------------------------------------------------

def supersede_labels(recipe, now):
    """hop 1: ISSUED labels pinned behind the new published_version become
    SUPERSEDED.  hop 2 is the loss of the rung-35 handoff gate (no write of its
    own).  hop 3: menu-item allergen summaries are recomputed."""
    published = recipe.get("published_version") or 0
    for label in DB.values("labels"):
        if label.get("recipe_id") != recipe["id"]:
            continue
        if label.get("label_status") != "ISSUED":
            continue
        if (label.get("recipe_version_pinned") or 0) >= published:
            continue
        label["label_status"] = "SUPERSEDED"
        touch(label, now)
    allergen.recompute_menu_item_summaries(recipe["id"])


# ---------------------------------------------------------------------------
# recall cascade
# ---------------------------------------------------------------------------

def recall_lot(lot, now):
    """Hops 1-6.  Returns a per-hop summary (useful for tracing)."""
    summary = {"components": 0, "recipes": 0, "batches": 0, "lines": 0,
               "orders": 0, "labels": 0, "refunds": 0}

    # ---- hop 1: latch recalled_component on every referencing component ----
    affected_recipe_ids = []
    for comp in DB.values("recipe_components"):
        if comp.get("ingredient_lot_id") != lot["id"]:
            continue
        comp["recalled_component"] = True
        touch(comp, now)
        summary["components"] += 1
        if comp.get("recipe_id") not in affected_recipe_ids:
            affected_recipe_ids.append(comp["recipe_id"])

    # ---- hop 2: each affected PUBLISHED recipe moves to REVISING ------------
    revised_recipe_ids = []
    for rid in affected_recipe_ids:
        recipe = DB.get("recipes", rid)
        if recipe is None or recipe.get("recipe_status") != "PUBLISHED":
            continue  # a recipe that was not PUBLISHED is not moved
        recipe["recipe_status"] = "REVISING"
        touch(recipe, now)
        revised_recipe_ids.append(rid)
        summary["recipes"] += 1

    # ---- hop 3: scrap PLANNED / MIXED / BAKED batches of those recipes -----
    # FIRST DELIBERATE STOP: YIELD_CONFIRMED, ALLOCATED and CLOSED batches are
    # not scrapped, and no later hop reaches anything behind them.
    scrapped_batch_ids = []
    for batch in DB.values("batches"):
        if batch.get("recipe_id") not in revised_recipe_ids:
            continue
        if batch.get("batch_status") not in ("PLANNED", "MIXED", "BAKED"):
            continue
        batch["batch_status"] = "SCRAPPED_RECALL"
        touch(batch, now)
        scrapped_batch_ids.append(batch["id"])
        summary["batches"] += 1

    # ---- hop 4: void every line pointing at a scrapped batch ---------------
    voided_order_ids = []
    for line in DB.values("order_lines"):
        if line.get("batch_id") not in scrapped_batch_ids:
            continue
        line["line_status"] = "RECALL_VOID"
        line["allocated_units"] = 0
        touch(line, now)
        summary["lines"] += 1
        if line.get("order_id") not in voided_order_ids:
            voided_order_ids.append(line["order_id"])

    # ---- hop 5: owning CONFIRMED / IN_PRODUCTION / READY orders void -------
    # SECOND DELIBERATE STOP: FULFILLED, CANCELLED, FORFEITED and already
    # VOIDED_RECALL orders are left completely untouched, and hop 6 therefore
    # neither voids their labels nor refunds them.
    moved_orders = []
    touched_windows = set()
    for oid in voided_order_ids:
        order = DB.get("orders", oid)
        if order is None:
            continue
        if order.get("order_status") not in ("CONFIRMED", "IN_PRODUCTION", "READY"):
            continue
        order["order_status"] = "VOIDED_RECALL"
        touch(order, now)
        moved_orders.append(order)
        summary["orders"] += 1
        touched_windows.add(order.get("offer_window_id"))

    # ---- hop 6: void the labels of those orders, refund a CAPTURED payment --
    for order in moved_orders:
        line_ids = [l["id"] for l in DB.values("order_lines")
                    if l.get("order_id") == order["id"]]
        for label in DB.values("labels"):
            if label.get("order_line_id") not in line_ids:
                continue
            if label.get("label_status") not in ("ISSUED", "SUPERSEDED"):
                continue
            label["label_status"] = "VOID"
            touch(label, now)
            summary["labels"] += 1
        pay = active_payment(order["id"])
        if pay is not None and pay.get("payment_state") == "CAPTURED":
            amount = money.refundable_remainder(pay)
            if amount > 0:
                legs = money.waterfall(order, amount)
                money.create_movement(
                    now,
                    customer_id=order.get("customer_id"),
                    ledger_scope="SETTLEMENT",
                    movement_kind="REFUND",
                    reason="RECALL_VOID",
                    amount_cents=amount,
                    order_id=order["id"],
                    payment_id=pay["id"],
                    legs=legs,
                )
                pay["refunded_cents"] = (pay.get("refunded_cents") or 0) + amount
                touch(pay, now)
                order["payment_status"] = "REFUNDED"
                touch(order, now)
                summary["refunds"] += 1

    # ---- statutory and capacity consequences -------------------------------
    bakers = {}
    for order in moved_orders:
        baker = money.baker_of_order(order)
        if baker is not None:
            bakers[baker["id"]] = baker
    for baker in bakers.values():
        money.refresh_gross_sales(baker)
        money.refresh_payout_net(baker)
        touch(baker, now)
    for cust_id in {o.get("customer_id") for o in moved_orders}:
        cust = DB.get("customers", cust_id)
        if cust is not None:
            money.refresh_credit_balance(cust, now)
    for wid in touched_windows:
        capacity.sync(DB.get("offer_windows", wid), now)
    return summary


# ---------------------------------------------------------------------------
# shortfall allocation cascade (yield confirmation)
# ---------------------------------------------------------------------------

def _sort_key(line):
    """calculations.shortfall_allocation -- the four-part composite key."""
    order = DB.get("orders", line.get("order_id"))
    k1 = 0 if (order or {}).get("source") == "SUBSCRIPTION_CLUB" else 1
    k2 = 0 if (order or {}).get("prepaid") else 1
    k3 = (order or {}).get("created_at")
    return (k1, k2, k3.dt if k3 is not None else line["created_at"].dt,
            (order or {}).get("id") or "", line["created_at"].dt, line["id"])


def allocate_yield(batch, actual_yield_units, now):
    """The BAKED fork: YIELD_CONFIRMED (fully supplied) or UNDER_YIELD."""
    candidates = [l for l in DB.values("order_lines")
                  if l.get("batch_id") == batch["id"]
                  and l.get("line_status") == "PENDING"]
    demand = sum((l.get("quantity") or 0) for l in candidates)
    candidates.sort(key=_sort_key)

    shorted = []
    remaining = actual_yield_units
    for line in candidates:
        qty = line.get("quantity") or 0
        grant = qty if qty <= remaining else remaining
        if grant < 0:
            grant = 0
        line["allocated_units"] = grant
        line["shorted_units"] = qty - grant
        remaining -= grant
        if grant >= qty:
            line["line_status"] = "ALLOCATED"
        else:
            line["line_status"] = "SHORTED"
            order = DB.get("orders", line.get("order_id"))
            if order is not None and not order.get("shortfall_flag"):
                order["shortfall_flag"] = True
                touch(order, now)
            shorted.append(line)
        touch(line, now)

    if actual_yield_units >= demand:
        batch["batch_status"] = "YIELD_CONFIRMED"
        batch["surplus_units"] = remaining
    else:
        batch["batch_status"] = "UNDER_YIELD"
        batch["surplus_units"] = 0
    batch["actual_yield_units"] = actual_yield_units

    # ---- hop 3: every SHORTED line becomes CREDITED -------------------------
    affected_bakers = {}
    affected_customers = set()
    for line in shorted:
        credit = _shortfall_credit(line)
        line["line_status"] = "CREDITED"
        touch(line, now)
        order = DB.get("orders", line.get("order_id"))
        if order is None or credit <= 0:
            continue
        pay = active_payment(order["id"])
        state = pay.get("payment_state") if pay is not None else None
        if state == "CAPTURED":
            # money leaves the operator
            legs = money.waterfall(order, min(credit, money.refundable_remainder(pay)))
            amount = sum(legs)
            if amount > 0:
                money.create_movement(
                    now,
                    customer_id=order.get("customer_id"),
                    ledger_scope="SETTLEMENT",
                    movement_kind="REFUND",
                    reason="SHORTFALL",
                    amount_cents=amount,
                    order_id=order["id"],
                    payment_id=pay["id"],
                    legs=legs,
                )
                pay["refunded_cents"] = (pay.get("refunded_cents") or 0) + amount
                touch(pay, now)
                order["payment_status"] = (
                    "REFUNDED" if money.refundable_remainder(pay) == 0
                    else "PARTIALLY_REFUNDED"
                )
                touch(order, now)
        else:
            # Adjudication of friction 8: DECLINED / VOIDED take the CREDIT
            # branch.  The two declared branches cover CAPTURED on one side and
            # INITIATED / AUTHORIZED / no-payment on the other; a DECLINED or
            # VOIDED payment means no money ever left the operator, which is
            # precisely the ground the credit branch stands on.  Writing
            # nothing would leave a CREDITED line with no ledger entry at all
            # and would make the SHORTFALL_CREDIT movement unreachable for
            # every order whose only payment attempt was declined.
            money.create_movement(
                now,
                customer_id=order.get("customer_id"),
                ledger_scope="CUSTOMER_CREDIT",
                movement_kind="SHORTFALL_CREDIT",
                reason="SHORTFALL",
                amount_cents=credit,
                order_id=order["id"],
                payment_id=pay["id"] if pay is not None else None,
            )
            affected_customers.add(order.get("customer_id"))
        baker = money.baker_of_order(order)
        if baker is not None:
            affected_bakers[baker["id"]] = baker

    # ---- hop 4: the arithmetic consequence ---------------------------------
    for cust_id in affected_customers:
        cust = DB.get("customers", cust_id)
        if cust is not None:
            money.refresh_credit_balance(cust, now)
    for baker in affected_bakers.values():
        money.refresh_gross_sales(baker)
        money.refresh_payout_net(baker)
        touch(baker, now)

    # ---- yield conservation, then the auto-advance to ALLOCATED ------------
    if not yield_conserved(batch):
        raise ApiError("ERR_VALIDATION",
                       "The yield conservation invariant does not hold.")
    batch["batch_status"] = "ALLOCATED"
    touch(batch, now)
    return batch


def _shortfall_credit(line):
    """calculations.shortfall_credit -- proportional, multiplier 1.00."""
    qty = line.get("quantity") or 0
    if qty <= 0:
        return 0
    gross = (line.get("line_total_cents") or 0) + (line.get("line_tax_cents") or 0)
    value = (dec(gross) * dec(line.get("shorted_units") or 0) / dec(qty)
             * dec(config.SHORTFALL_CREDIT_MULTIPLIER))
    return cents(value)


def yield_conserved(batch):
    """Invariant yield_conservation (PRD 2.10)."""
    allocated = 0
    for line in DB.coll("order_lines").values():
        if line.get("batch_id") != batch["id"]:
            continue
        if line.get("line_status") not in ("ALLOCATED", "SHORTED", "CREDITED",
                                           "FULFILLED"):
            continue
        allocated += line.get("allocated_units") or 0
    return (allocated + (batch.get("surplus_units") or 0)
            == (batch.get("actual_yield_units") or 0))


# ---------------------------------------------------------------------------
# hold release (shared by the sweep, the lock and order cancellation)
# ---------------------------------------------------------------------------

def release_pending_lines(order, now):
    """OrderLine PENDING -> RELEASED for one order.  Returns the units released."""
    units = 0
    count = 0
    for line in DB.values("order_lines"):
        if line.get("order_id") != order["id"]:
            continue
        if line.get("line_status") != "PENDING":
            continue
        line["line_status"] = "RELEASED"
        line["hold_expires_at"] = None
        touch(line, now)
        units += line.get("quantity") or 0
        count += 1
    return units, count


def release_cycle(cycle, now):
    """SubscriptionCycle RESERVED/GENERATED -> RELEASED."""
    cycle["cycle_status"] = "RELEASED"
    cycle["reserved_units"] = 0
    touch(cycle, now)
