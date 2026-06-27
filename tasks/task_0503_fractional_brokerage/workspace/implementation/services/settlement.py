"""Settlement sweep and leg failure (PRD §3.6, §3.11)."""
from decimal import Decimal

from db import db
from models import touch
from money import round_half_up
from services.account import recompute_account, auto_meet_margin_calls
from timeutil import parse_iso


def settle_leg(settlement):
    """Move an UNSETTLED leg to SETTLED, performing the cash movement (PRD §3.6)."""
    acct = db.accounts.get(settlement["account_id"])
    amount = settlement["amount_cents"]
    rebate = settlement.get("_pfof_rebate_cents", 0)

    if settlement["direction"] == "DEBIT":
        acct["settled_cash_cents"] -= amount
        acct["unsettled_cash_cents"] += amount
    else:  # CREDIT
        acct["settled_cash_cents"] += amount
        acct["unsettled_cash_cents"] -= amount

    # PFOF rebate credited to settled cash at settlement (PRD §3.4)
    if rebate:
        acct["settled_cash_cents"] += rebate

    settlement["status"] = "SETTLED"
    touch(settlement)
    recompute_account(acct)
    auto_meet_margin_calls(acct["id"])
    touch(acct)


def fail_leg(settlement):
    """Move an UNSETTLED leg to FAILED, reversing the provisional fill effects
    (compensation, PRD §3.6)."""
    acct = db.accounts.get(settlement["account_id"])
    amount = settlement["amount_cents"]

    # reverse the provisional unsettled-cash effect applied at fill time
    if settlement["direction"] == "DEBIT":
        # BUY had unsettled -= amount; reverse it
        acct["unsettled_cash_cents"] += amount
    else:  # CREDIT (SELL had unsettled += amount)
        acct["unsettled_cash_cents"] -= amount

    # reverse the position effect of the originating fill
    fill = db.fills.get(settlement["fill_id"])
    if fill is not None:
        _reverse_fill_position(fill)

    settlement["status"] = "FAILED"
    touch(settlement)
    recompute_account(acct)
    auto_meet_margin_calls(acct["id"])
    touch(acct)


def _reverse_fill_position(fill):
    """Undo the position/lot effect of a fill (best-effort compensation)."""
    from services.position import recompute_position
    order = db.orders.get(fill["order_id"])
    if order is None:
        return
    pos = _find_position(order["account_id"], order["security_id"])
    if pos is None:
        return
    if order["side"] == "BUY":
        # close the lot opened by this fill (find a lot with matching original qty
        # and remaining == original, opened most recently — best effort)
        candidates = [l for l in db.lots.values() if l["position_id"] == pos["id"]]
        candidates.sort(key=lambda l: l["_seq"], reverse=True)
        target = None
        for l in candidates:
            if abs(l["original_quantity"] - fill["fill_quantity"]) < 1e-9 and l["status"] == "OPEN":
                target = l
                break
        if target is not None:
            del db.lots[target["id"]]
        recompute_position(pos)
        touch(pos)


def _find_position(account_id, security_id):
    for p in db.positions.values():
        if p["account_id"] == account_id and p["security_id"] == security_id:
            return p
    return None


def run_sweep():
    """Settle every PENDING deposit and UNSETTLED leg whose settles_on <= clock
    (PRD §3.11)."""
    from routes.clock import settle_deposit  # local import to avoid cycle
    clock = db.clock
    # deposits first, then settlements (order is not load-bearing; both recompute)
    for dep in list(db.deposits.values()):
        if dep["status"] == "PENDING" and parse_iso(dep["settles_on"]) <= clock:
            settle_deposit(dep)
    for s in list(db.settlements.values()):
        if s["status"] == "UNSETTLED" and parse_iso(s["settles_on"]) <= clock:
            settle_leg(s)
