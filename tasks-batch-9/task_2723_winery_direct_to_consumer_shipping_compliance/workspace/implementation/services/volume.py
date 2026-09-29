"""Volume ledger aggregation and the consumer risk model (PRD 3.4)."""
import math
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction

import clock
from rounding import dec, rhu_liters, liters_out
from store import db, base_row, next_seq, new_id

SETTLED_STATUSES = ("IN_TRANSIT", "DELIVERED", "RETURNED")
RETURN_WEIGHT = 10
DENIAL_WEIGHT = 15
ELEVATED_TIER_THRESHOLD = 50
ROLLING_12_MONTHS_DAYS = 365
ROLLING_30_DAYS_DAYS = 30


def window_start(period, ref=None):
    """Lower edge (INCLUSIVE) of the rolling window for a per_consumer_period."""
    ref = ref or clock.now()
    if period == "ROLLING_30_DAYS":
        return ref - timedelta(days=ROLLING_30_DAYS_DAYS)
    if period == "CALENDAR_YEAR":
        return datetime(ref.year, 1, 1, 0, 0, 0, 0)
    return ref - timedelta(days=ROLLING_12_MONTHS_DAYS)


def state_rule_for(state_code):
    for rule in db.state_rules.values():
        if rule["state_code"] == state_code:
            return rule
    return None


def period_for_state(state_code):
    rule = state_rule_for(state_code)
    if rule is None:
        return "ROLLING_12_MONTHS"
    return rule["per_consumer_period"]


def entry_instant(entry):
    return entry["_occurred_at_dt"]


def is_settled(entry):
    order_id = entry.get("order_id")
    if not order_id:
        return True
    order = db.orders.get(order_id)
    if order is None:
        return True
    return order["fulfillment_status"] in SETTLED_STATUSES


def consumer_entries(consumer_id):
    return [e for e in db.ledger_entries.values() if e["consumer_id"] == consumer_id]


def _in_window(entry, state_code, ref):
    start = window_start(period_for_state(state_code), ref)
    at = entry_instant(entry)
    return start <= at <= ref


def _excluded(entry, exclude_order_id):
    if exclude_order_id is None:
        return False
    return (entry.get("order_id") == exclude_order_id
            and entry.get("event_type") in ("SHIPMENT_ACCEPTED", "RETURN_CREDIT"))


def rolling_state_liters(consumer_id, state_code, settled=False, exclude_order_id=None,
                         extra=None, ref=None):
    """Signed sum of the consumer's in-window entries for one state, 3dp half-up."""
    ref = ref or clock.now()
    total = Decimal("0")
    for entry in consumer_entries(consumer_id):
        if entry["state_code"] != state_code:
            continue
        if _excluded(entry, exclude_order_id):
            continue
        if not _in_window(entry, state_code, ref):
            continue
        if settled and not is_settled(entry):
            continue
        total += dec(entry["liters"])
    if extra is not None:
        total += dec(extra)
    return rhu_liters(total)


def rolling_map(consumer_id, settled=False, ref=None):
    ref = ref or clock.now()
    out = {}
    for entry in consumer_entries(consumer_id):
        state = entry["state_code"]
        if not _in_window(entry, state, ref):
            continue
        if settled and not is_settled(entry):
            continue
        out[state] = out.get(state, Decimal("0")) + dec(entry["liters"])
    return dict((k, rhu_liters(v)) for k, v in out.items())


def all_time_map(consumer_id):
    out = {}
    for entry in consumer_entries(consumer_id):
        state = entry["state_code"]
        out[state] = out.get(state, Decimal("0")) + dec(entry["liters"])
    return dict((k, rhu_liters(v)) for k, v in out.items())


def winery_annual_liters(winery_id, state_code, exclude_order_id=None, extra=None, ref=None):
    """Calendar-year signed sum for a (winery, state) pair, 3dp half-up."""
    ref = ref or clock.now()
    year_start = datetime(ref.year, 1, 1, 0, 0, 0, 0)
    total = Decimal("0")
    for entry in db.ledger_entries.values():
        if entry["winery_id"] != winery_id or entry["state_code"] != state_code:
            continue
        if _excluded(entry, exclude_order_id):
            continue
        at = entry_instant(entry)
        if at < year_start or at > ref:
            continue
        total += dec(entry["liters"])
    if extra is not None:
        total += dec(extra)
    return rhu_liters(total)


def widest_window_start(consumer_id, ref=None):
    """Lower edge of the widest per_consumer_period window in play."""
    ref = ref or clock.now()
    states = set(e["state_code"] for e in consumer_entries(consumer_id))
    periods = []
    for state in states:
        periods.append(period_for_state(state))
    if not periods:
        periods = [r["per_consumer_period"] for r in db.state_rules.values()]
    if not periods:
        periods = ["ROLLING_12_MONTHS"]
    return min(window_start(p, ref) for p in periods)


def consumer_orders(consumer_id):
    return [o for o in db.orders.values() if o["consumer_id"] == consumer_id]


def denied_exceptions(consumer_id):
    order_ids = set(o["id"] for o in consumer_orders(consumer_id))
    return [e for e in db.compliance_exceptions.values()
            if e["order_id"] in order_ids and e["status"] == "DENIED"]


def _utilisation_factor(liters_by_state):
    """f3: the state with the greatest liters/limit ratio, tie-broken state_code ASC.

    The ratio is carried as an EXACT rational rather than a Decimal quotient. A
    finite-precision division truncates 30 * 1.500 / 4.500 -- which is exactly 10
    -- to 9.999... and then floors it to 9, losing a whole point off the score.
    """
    best = None
    for state in sorted(liters_by_state.keys()):
        rule = state_rule_for(state)
        if rule is None:
            continue
        limit = Fraction(dec(rule["per_consumer_limit_liters"]))
        if limit <= 0:
            continue
        ratio = Fraction(dec(liters_by_state[state])) / limit
        if best is None or ratio > best[0]:
            best = (ratio, state)
    if best is None:
        return 0
    # 30 x ratio, truncated downward to a whole number, then capped at 30
    factor = math.floor(30 * best[0])
    if factor > 30:
        factor = 30
    if factor < 0:
        factor = 0
    return factor


def _score(f1, f2, f3):
    total = min(40, f1) + min(30, f2) + min(30, f3)
    if total > 100:
        total = 100
    if total < 0:
        total = 0
    return total


def consumer_derived(consumer, ref=None):
    """Every derived field of a Consumer, recomputed from the ledger and exceptions."""
    ref = ref or clock.now()
    cid = consumer["id"]
    rolling = rolling_map(cid, settled=False, ref=ref)
    settled = rolling_map(cid, settled=True, ref=ref)
    all_time = all_time_map(cid)

    wide_start = widest_window_start(cid, ref)
    entries = consumer_entries(cid)

    return_credits_wide = 0
    for entry in entries:
        if entry["event_type"] != "RETURN_CREDIT":
            continue
        at = entry_instant(entry)
        if wide_start <= at <= ref:
            return_credits_wide += 1

    screening_returns = 0
    for entry in entries:
        if entry["event_type"] != "RETURN_CREDIT":
            continue
        if not _in_window(entry, entry["state_code"], ref):
            continue
        if not is_settled(entry):
            continue
        screening_returns += 1

    denials = denied_exceptions(cid)
    denied_total = len(denials)
    denied_in_window = 0
    for exc in denials:
        at = clock.parse_instant(exc.get("decided_at")) if exc.get("decided_at") else None
        if at is None or (wide_start <= at <= ref):
            denied_in_window += 1

    score_screening = _score(RETURN_WEIGHT * screening_returns,
                             DENIAL_WEIGHT * denied_in_window,
                             _utilisation_factor(settled))
    score_audit = _score(RETURN_WEIGHT * len([e for e in entries if e["event_type"] == "RETURN_CREDIT"]),
                         DENIAL_WEIGHT * denied_total,
                         _utilisation_factor(all_time))
    tier = "ELEVATED" if score_screening >= ELEVATED_TIER_THRESHOLD else "STANDARD"
    return {
        "rolling_liters_by_state": dict((k, liters_out(v)) for k, v in rolling.items()),
        "rolling_liters_settled_by_state": dict((k, liters_out(v)) for k, v in settled.items()),
        "return_credit_count": return_credits_wide,
        "denied_exception_count": denied_total,
        "risk_score_screening": score_screening,
        "risk_score_audit": score_audit,
        "screening_tier": tier,
    }


def screening_tier(consumer):
    return consumer_derived(consumer)["screening_tier"]


def append_entry(consumer_id, winery_id, state_code, liters, event_type,
                 order_id=None, shipment_id=None, occurred_raw=None, occurred_dt=None,
                 reason=None):
    """Append an immutable ledger entry (id + created_at only; PRD 2.5)."""
    row = base_row(versioned=False)
    if occurred_dt is None:
        occurred_dt = clock.now()
        occurred_raw = clock.now_iso()
    if occurred_raw is None:
        occurred_raw = clock.iso(occurred_dt)
    row.update({
        "consumer_id": consumer_id,
        "winery_id": winery_id,
        "order_id": order_id,
        "shipment_id": shipment_id,
        "state_code": state_code,
        "liters": rhu_liters(liters),
        "event_type": event_type,
        "occurred_at": occurred_raw,
        "reason": reason,
        "_occurred_at_dt": occurred_dt,
    })
    db.ledger_entries[row["id"]] = row
    return row
