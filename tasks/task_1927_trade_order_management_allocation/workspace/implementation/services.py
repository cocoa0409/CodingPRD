"""Shared business logic: fetch helpers, recomputes, cascades, allocation math."""
from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal

import audit
import db
from errors import raise_err
from util import commission_cents, new_id, rhu_int, vwap_cents, wall_now_iso

COUNTING_LINE_STATUSES = ("POSTED", "SETTLED", "ERROR_FLAGGED")
MEMBER_STATUSES = ("BLOCKED", "ALLOCATED", "UNDER_CORRECTION")
FAIRNESS_TOLERANCE_BP = 200
DEVIATION_CAP_BP = 99999
EQUITY_LAG_DAYS = 1
FIXED_INCOME_LAG_DAYS = 2
FAIL_GRACE_DAYS = 1
FAIL_ESCALATION_THRESHOLD = 2


# ---------------------------------------------------------------- fetch ----
def fetch(kind, rid, error_id):
    rec = db.store[kind].get(rid)
    if rec is None:
        raise_err(error_id, f"{kind[:-1]} {rid} not found")
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a state-changing mutation."""
    rec["updated_at"] = wall_now_iso()
    rec["version"] += 1


def new_record(common=True):
    rec = {"id": new_id(), "created_at": wall_now_iso(), "_seq": db.next_seq()}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


# ---------------------------------------------------------------- orders ---
def recompute_order_stats(order):
    """allocated_qty / avg_executed_price_cents over the order's lines with
    status IN {POSTED, SETTLED, ERROR_FLAGGED} (round half up; null until the
    first counting line)."""
    lines = [a for a in db.store["allocations"].values()
             if a["order_id"] == order["id"] and a["status"] in COUNTING_LINE_STATUSES]
    if not lines:
        order["allocated_qty"] = 0
        order["avg_executed_price_cents"] = None
        return
    order["allocated_qty"] = sum(l["alloc_qty"] for l in lines)
    order["avg_executed_price_cents"] = vwap_cents(
        [(l["alloc_qty"], l["alloc_price_cents"]) for l in lines])


def order_live_lines(order_id):
    """Lines that gate settlement bubble-up: POSTED / SETTLED / ERROR_FLAGGED."""
    return [a for a in db.store["allocations"].values()
            if a["order_id"] == order_id and a["status"] in COUNTING_LINE_STATUSES]


def maybe_settle_order(order):
    live = order_live_lines(order["id"])
    if order["status"] in ("ALLOCATED", "UNDER_CORRECTION") and live and \
            all(l["status"] == "SETTLED" for l in live):
        frm = order["status"]
        order["status"] = "SETTLED"
        touch(order)
        audit.record_system("Order", order["id"], "ORDER_SETTLED",
                            f"status: {frm} -> SETTLED")


def clear_correction_context_if_done(order):
    """UNDER_CORRECTION -> ALLOCATED once no line of the order stays flagged."""
    flagged = [a for a in db.store["allocations"].values()
               if a["order_id"] == order["id"] and a["status"] == "ERROR_FLAGGED"]
    if flagged:
        return
    if order["status"] == "UNDER_CORRECTION":
        order["status"] = "ALLOCATED"
        recompute_order_stats(order)
        touch(order)
        audit.record_system("Order", order["id"], "ORDER_CORRECTION_CLEARED",
                            "status: UNDER_CORRECTION -> ALLOCATED")


# ---------------------------------------------------------------- blocks ---
def block_fills(block_id):
    return sorted((f for f in db.store["fills"].values() if f["block_id"] == block_id),
                  key=lambda f: f["fill_seq"])


def block_members(block_id):
    """Attached member orders (block-scoped children): still attached and not
    terminal; ordered by creation for deterministic splits."""
    members = [o for o in db.store["orders"].values()
               if o["block_id"] == block_id and o["status"] in MEMBER_STATUSES]
    return sorted(members, key=lambda o: o["_seq"])


def recompute_block_fill_stats(block):
    fills = block_fills(block["id"])
    block["filled_qty"] = sum(f["fill_qty"] for f in fills)
    block["avg_fill_price_cents"] = vwap_cents(
        [(f["fill_qty"], f["fill_price_cents"]) for f in fills])


# ------------------------------------------------------------- positions ---
def position_apply(account_id, security_id, signed_delta):
    key = (account_id, security_id)
    pid = db.position_index.get(key)
    if pid is None:
        pos = new_record()
        pos.update({"account_id": account_id, "security_id": security_id,
                    "net_qty": signed_delta})
        db.store["positions"][pos["id"]] = pos
        db.position_index[key] = pos["id"]
    else:
        pos = db.store["positions"][pid]
        pos["net_qty"] += signed_delta
        touch(pos)
    return pos


def position_net_qty(account_id, security_id):
    pid = db.position_index.get((account_id, security_id))
    if pid is None:
        return 0
    return db.store["positions"][pid]["net_qty"]


# -------------------------------------------------------------- budgets ----
def find_open_budget(account_id, trade_date):
    """Unique OPEN budget whose half-open window covers trade_date."""
    for b in db.store["budgets"].values():
        if b["account_id"] == account_id and b["status"] == "OPEN" and \
                b["_period_start"] <= trade_date < b["_period_end"]:
            return b
    return None


def find_covering_budget(account_id, trade_date):
    """Budget (OPEN or EXHAUSTED) whose window covers trade_date — the row a
    line's commission was accrued to."""
    for b in db.store["budgets"].values():
        if b["account_id"] == account_id and \
                b["_period_start"] <= trade_date < b["_period_end"]:
            return b
    return None


def budget_accrue(budget, amount):
    budget["accrued_commission_cents"] += amount
    touch(budget)
    if budget["status"] == "OPEN" and \
            budget["accrued_commission_cents"] == budget["budget_amount_cents"]:
        budget["status"] = "EXHAUSTED"
        audit.record_system("CommissionBudget", budget["id"], "BUDGET_EXHAUSTED",
                            "accrued_commission_cents reached budget_amount_cents")


# -------------------------------------------------------------- accounts ---
def suspend_account(account, automatic):
    """ACTIVE -> SUSPENDED plus the order-cancellation cascade."""
    if account["status"] != "ACTIVE":
        return
    account["status"] = "SUSPENDED"
    touch(account)
    if automatic:
        audit.record_system("Account", account["id"], "ACCOUNT_SUSPENDED",
                            "status: ACTIVE -> SUSPENDED (settlement-fail escalation)")
    else:
        role, user_id = _request_actor()
        audit.record("Account", account["id"], "ACCOUNT_SUSPENDED", role, user_id,
                     "status: ACTIVE -> SUSPENDED")
    for order in sorted(db.store["orders"].values(), key=lambda o: o["_seq"]):
        if order["account_id"] == account["id"] and \
                order["status"] in ("PENDING_COMPLIANCE", "COMPLIANCE_REJECTED", "APPROVED"):
            frm = order["status"]
            order["status"] = "CANCELLED"
            touch(order)
            audit.record_system("Order", order["id"], "ORDER_CANCELLED",
                                f"status: {frm} -> CANCELLED (account-suspension cascade)")


def _request_actor():
    from middleware import actor
    return actor()


# --------------------------------------------------------- settlement misc -
def instruction_for_allocation(allocation_id):
    for ins in db.store["instructions"].values():
        if ins["allocation_id"] == allocation_id:
            return ins
    return None


def create_instruction(allocation, account, trade_date, settle_date):
    ins = new_record()
    ins.update({
        "allocation_id": allocation["id"],
        "custodian_name": account["custodian_name"],
        "trade_date": trade_date,
        "settle_date": settle_date,
        "instruction_status": "PENDING",
        "fail_reason": None,
        "fail_count": 0,
    })
    db.store["instructions"][ins["id"]] = ins
    return ins


def settle_dates_for(security, trade_date):
    lag = EQUITY_LAG_DAYS if security["asset_class"] == "EQUITY" else FIXED_INCOME_LAG_DAYS
    return trade_date + timedelta(days=lag)


# --------------------------------------------------------- allocation math -
def allocation_split(batch_qty, method, members):
    """Returns (alloc_qty list aligned with members, max_deviation_bp).
    Floor + largest-remainder; fairness baseline is always the PRO_RATA ideal."""
    n = len(members)
    total = sum(o["order_qty"] for o in members)
    ideals_pr = [Decimal(batch_qty) * Decimal(o["order_qty"]) / Decimal(total) for o in members]
    if method == "PRO_RATA":
        ideals = list(ideals_pr)
    else:  # EQUAL_SPLIT
        ideals = [Decimal(batch_qty) / Decimal(n) for _ in members]
    bases = [int(i.to_integral_value(rounding=ROUND_FLOOR)) for i in ideals]
    remainder = batch_qty - sum(bases)
    ranking = sorted(range(n), key=lambda i: (
        -(ideals[i] - Decimal(bases[i])), -members[i]["order_qty"], members[i]["_seq"]))
    alloc = list(bases)
    for k in range(remainder):
        alloc[ranking[k]] += 1
    devs = []
    for i in range(n):
        ideal = ideals_pr[i]
        if ideal == 0:
            devs.append(0 if alloc[i] == 0 else DEVIATION_CAP_BP)
        else:
            devs.append(rhu_int(abs(Decimal(alloc[i]) - ideal) / ideal * Decimal(10000)))
    return alloc, (max(devs) if devs else 0)


def signed_qty(block, qty):
    return qty if block["side"] == "BUY" else -qty
