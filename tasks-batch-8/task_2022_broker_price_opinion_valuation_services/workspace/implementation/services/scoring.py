"""Broker composite score (scaffold 1.3 'composite_score', PRD 3.3).

Recomputed on every QC verdict, every order completion, every revision
resolved late, and every broker decline. Rolling 90-day window:
[now - 90 days, now). Global variant: components pooled across clients,
weights are order-count-weighted averages of contributing clients' weights.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db

WINDOW_DAYS = 90
DECLINE_PENALTY_PTS = Fraction(1, 1)
VERDICT_VALUES = {"APPROVE": Fraction(1, 1), "REVISE": Fraction(1, 2), "REJECT": Fraction(0, 1)}

_DEFAULT_W_T = Fraction(1, 2)   # 0.5
_DEFAULT_W_Q = Fraction(3, 10)  # 0.3
_DEFAULT_W_R = Fraction(1, 5)   # 0.2


def _w(value) -> Fraction:
    return Fraction(str(value))


def compute_composite_score(broker_id: str) -> Decimal:
    broker = db.brokers.get(broker_id)
    now = db.logical_now()
    window_start = now - timedelta(days=WINDOW_DAYS)

    broker_orders = [
        o for o in db.orders.values() if o["assigned_broker_id"] == broker_id
    ]
    completed = [
        o for o in broker_orders
        if o["fulfillment_status"] == "COMPLETED"
        and o["completed_at"] is not None
        and window_start <= o["completed_at"] <= now
    ]
    total_completed = len(completed)
    late_completed = [
        o for o in completed
        if o["sla_due_at"] is not None and o["completed_at"] > o["sla_due_at"]
    ]

    turnaround = Fraction(1) - min(
        Fraction(1), Fraction(len(late_completed), max(1, total_completed))
    )

    order_ids = {o["id"] for o in broker_orders}
    verdicts = [
        r for r in db.qc_reviews.values()
        if r["order_id"] in order_ids
        and r["reviewed_at"] is not None
        and window_start <= r["reviewed_at"] <= now
    ]
    if verdicts:
        quality = sum((VERDICT_VALUES[r["verdict"]] for r in verdicts), Fraction(0)) / len(verdicts)
    else:
        quality = Fraction(1)

    revisions = [
        r for r in db.revision_requests.values()
        if r["order_id"] in order_ids
        and window_start <= r["created_at"] <= now
    ]
    revision = Fraction(1) - min(
        Fraction(1), Fraction(len(revisions), max(1, total_completed))
    )

    # Weights: order-count-weighted average of each *contributing* client's
    # scorecard weights. A client contributes through any of the broker's
    # orders with in-window scoring activity — completed orders, QC verdicts,
    # or revision requests (so a REJECTED order's client still contributes).
    contributing_ids = {o["id"] for o in completed}
    contributing_ids |= {r["order_id"] for r in verdicts}
    contributing_ids |= {r["order_id"] for r in revisions}
    contributing = [
        o for o in broker_orders
        if o["id"] in contributing_ids and o["client_id"] in db.client_accounts
    ]
    if contributing:
        n = len(contributing)
        w_t = sum((_w(db.client_accounts[o["client_id"]]["scorecard_weight_turnaround"])
                   for o in contributing), Fraction(0)) / n
        w_q = sum((_w(db.client_accounts[o["client_id"]]["scorecard_weight_quality"])
                   for o in contributing), Fraction(0)) / n
        w_r = sum((_w(db.client_accounts[o["client_id"]]["scorecard_weight_revision"])
                   for o in contributing), Fraction(0)) / n
    else:
        w_t, w_q, w_r = _DEFAULT_W_T, _DEFAULT_W_Q, _DEFAULT_W_R

    raw = 100 * (w_t * turnaround + w_q * quality + w_r * revision)
    declines = [d for d in broker["decline_events"] if window_start <= d <= now]
    raw -= DECLINE_PENALTY_PTS * len(declines)

    score = (Decimal(raw.numerator) / Decimal(raw.denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if score < 0:
        score = Decimal("0.00")
    elif score > 100:
        score = Decimal("100.00")
    return score


def recompute_composite_score(broker_id: str) -> None:
    broker = db.brokers.get(broker_id)
    if broker is None:
        return
    broker["composite_score"] = compute_composite_score(broker_id)
