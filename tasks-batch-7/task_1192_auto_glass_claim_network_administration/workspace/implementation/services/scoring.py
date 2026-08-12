"""Shop network audit scores: rolling EMA (alpha 0.3) and period-close mean."""

from decimal import Decimal, ROUND_HALF_UP

from db import touch

EMA_ALPHA = Decimal("0.3")
EMA_ONE_MINUS = Decimal("0.7")
INITIAL_SCORE = 100


def _round2(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def event_score(invoice):
    submitted = invoice["submitted_total_cents"]
    if submitted == 0:
        variance = Decimal(0)
    else:
        variance = Decimal(invoice["adjustment_total_cents"]) / Decimal(submitted)
    return Decimal(100) * (Decimal(1) - variance)


def record_approve_event(shop, invoice):
    """Called on every audit-decisions APPROVE for an invoice of this shop."""
    score = event_score(invoice)
    shop.setdefault("_audit_events", []).append(
        {"score": score, "decision_dt": None, "invoice_created": invoice["_created_dt"]}
    )
    previous = Decimal(str(shop["rolling_audit_score"]))
    updated = EMA_ONE_MINUS * previous + EMA_ALPHA * score
    shop["rolling_audit_score"] = _round2(updated)
    touch(shop)


def period_close_score(shop):
    events = shop.get("_audit_events", [])
    if not events:
        return INITIAL_SCORE
    mean = sum((e["score"] for e in events), Decimal(0)) / Decimal(len(events))
    return _round2(mean)
