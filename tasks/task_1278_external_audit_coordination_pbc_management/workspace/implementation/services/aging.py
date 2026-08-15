"""PBC aging score calculation per PRD §3.2 and scaffold §1.3 pbc_aging_score.
Pinned evaluation order:
  1. recency_days = max(0, days_between(latest_evidence.uploaded_at, now()));
     if no evidence, days_between(pbc.created_at, now())
  2. freshness = 1 / (1 + recency_days)
  3. backlog_multiplier = 1 + 0.1 * engagement.open_query_count  (current row)
  4. score = round(100 * (1 - freshness) * backlog_multiplier, 2)  half-up
"""
from decimal import Decimal, ROUND_HALF_UP
from db import db
from clock import clock, parse_iso


def _days_between(iso_a, now_dt):
    a = parse_iso(iso_a)
    delta = now_dt - a
    days = delta.total_seconds() / 86400.0
    return max(0, int(days))


def compute_pbc_aging_score(pbc):
    now = clock.now()
    # Step 1: recency_days
    latest_uploaded_at = None
    for e in db.evidence_uploads.values():
        if e["pbc_request_id"] == pbc["id"]:
            if latest_uploaded_at is None or e["uploaded_at"] > latest_uploaded_at:
                latest_uploaded_at = e["uploaded_at"]
    if latest_uploaded_at is not None:
        recency_days = _days_between(latest_uploaded_at, now)
    else:
        recency_days = _days_between(pbc["created_at"], now)

    # Step 2: freshness
    freshness = Decimal(1) / (Decimal(1) + Decimal(recency_days))

    # Step 3: backlog_multiplier from CURRENT engagement row
    eng = db.engagements.get(pbc["engagement_id"])
    open_query_count = eng.get("open_query_count", 0) if eng else 0
    backlog_multiplier = Decimal(1) + Decimal("0.1") * Decimal(open_query_count)

    # Step 4
    score = Decimal(100) * (Decimal(1) - freshness) * backlog_multiplier
    score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(score)
