"""Conversion attribution: LAST_CLICK, POSITION_BASED, DATA_DRIVEN."""
from datetime import datetime, timezone, timedelta
import math

from .. import store


def _parse_ts(s: str) -> datetime:
    # ISO 8601 with 'Z' suffix.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _eligible_touchpoints(conversion: dict) -> list[dict]:
    """Return the set of FINALIZED CLICK/IMPRESSION BillingEvents in the window."""
    window_days = int(conversion.get("attribution_window_days", 7))
    conv_ts = _parse_ts(conversion["created_at"])
    earliest = conv_ts - timedelta(days=window_days)

    user_id = conversion["user_id"]
    advertiser_id = conversion["advertiser_id"]

    candidates = []
    for be in store.list_all("BillingEvent"):
        if be.get("status") != "FINALIZED":
            continue
        if be.get("event_type") not in ("CLICK", "IMPRESSION"):
            continue
        if be.get("advertiser_id") != advertiser_id:
            continue
        # Match user_id by joining through auction.
        auc = store.get("AuctionEvent", be.get("auction_event_id", ""))
        if not auc or auc.get("user_id") != user_id:
            continue
        be_ts = _parse_ts(be["created_at"])
        if not (earliest <= be_ts <= conv_ts):
            continue
        candidates.append(be)

    # View-through rule: drop IMPRESSIONS if any CLICK exists.
    has_click = any(c["event_type"] == "CLICK" for c in candidates)
    if has_click:
        candidates = [c for c in candidates if c["event_type"] == "CLICK"]

    candidates.sort(key=lambda c: (c.get("created_at", ""), c.get("id", "")))
    return candidates


def _allocate_cents(value_cents: int, fractions: list[float]) -> list[int]:
    """Assign integer cents proportionally; remainder goes to the LAST touchpoint."""
    if value_cents == 0 or not fractions:
        return [0] * len(fractions)
    raw = [int(math.floor(value_cents * f)) for f in fractions]
    remainder = value_cents - sum(raw)
    if remainder != 0 and raw:
        raw[-1] += remainder
    return raw


def run_attribution(conversion: dict) -> dict:
    touchpoints = _eligible_touchpoints(conversion)
    if not touchpoints:
        conversion["attribution_status"] = "UNATTRIBUTED"
        conversion["attributed_touchpoints"] = []
        return conversion

    model = conversion.get("attribution_model", "LAST_CLICK")
    n = len(touchpoints)
    fractions: list[float] = []

    if model == "LAST_CLICK":
        # PRD §3.7: "Under LAST_CLICK, the most recent CLICK touchpoint
        # receives 100 percent of the credit; if no CLICK exists, the
        # most recent IMPRESSION receives 100 percent." The credit goes
        # to exactly one touchpoint; the attributed_touchpoints list
        # holds the credited touchpoints, so only that single entry is
        # written.
        clicks = [t for t in touchpoints if t["event_type"] == "CLICK"]
        if clicks:
            winner = clicks[-1]
        else:
            winner = touchpoints[-1]
        touchpoints = [winner]
        fractions = [1.0]
        n = 1

    elif model == "POSITION_BASED":
        if n == 1:
            fractions = [1.0]
        elif n == 2:
            fractions = [0.5, 0.5]
        else:
            mids = n - 2
            middle_each = 0.20 / mids
            fractions = [0.40] + [middle_each] * mids + [0.40]

    elif model == "DATA_DRIVEN":
        raw = [1.0 / (n - i + 1) for i in range(1, n + 1)]  # i is 1-based
        total = sum(raw)
        truncated = [math.floor((r / total) * 10000) / 10000 for r in raw]
        fractions = truncated
    else:
        # Unknown model: fall back to LAST_CLICK semantics
        fractions = [0.0] * (n - 1) + [1.0]

    value = int(conversion.get("value_cents", 0))
    cents = _allocate_cents(value, fractions)

    pairs = []
    for tp, f, c in zip(touchpoints, fractions, cents):
        # Strip non-zero touchpoints, but keep all positions that received any fraction or cent.
        entry = {
            "billing_event_id": tp["id"],
            "credit_fraction": round(float(f), 4),
            "credit_cents": int(c),
        }
        pairs.append(entry)

    conversion["attributed_touchpoints"] = pairs
    conversion["attribution_status"] = "ATTRIBUTED"
    return conversion
