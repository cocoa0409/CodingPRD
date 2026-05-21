"""QuarterCredit ledger (immutable rows)."""

from __future__ import annotations

from typing import Optional

from app import clock, store
from app.errors import bad_request
from app.routes._helpers import fetch_claimant
from app.services.claimants import recompute_claimant_qc
from app.util import new_uuid


def append_quarter_credit(claimant_id: str, body: dict) -> dict:
    claimant = fetch_claimant(claimant_id)
    for f in ("year", "quarter", "earnings_cents"):
        if f not in body or body[f] is None:
            raise bad_request(f"Missing required field: {f}")
    year = body["year"]
    quarter = body["quarter"]
    earnings = body["earnings_cents"]
    if isinstance(year, bool) or not isinstance(year, int):
        raise bad_request("year must be an integer")
    if isinstance(quarter, bool) or not isinstance(quarter, int):
        raise bad_request("quarter must be an integer")
    if isinstance(earnings, bool) or not isinstance(earnings, int):
        raise bad_request("earnings_cents must be an integer")
    if year < 1978 or year > 2100:
        raise bad_request("year must be in [1978, 2100]")
    if quarter < 1 or quarter > 4:
        raise bad_request("quarter must be in [1, 4]")
    if earnings < 0:
        raise bad_request("earnings_cents must be non-negative")

    now = clock.now()
    new_id = new_uuid()
    row = {
        "id": new_id,
        "claimant_id": claimant_id,
        "year": year,
        "quarter": quarter,
        "earnings_cents": earnings,
        "qc_count": 0,
        "credited": False,
        "created_at": now,
    }
    with store.lock():
        store.quarter_credits[new_id] = row
        recompute_claimant_qc(claimant)
    return store.quarter_credits[new_id]


def list_quarter_credits(
    claimant_id: str,
    year_min: Optional[int],
    year_max: Optional[int],
) -> list[dict]:
    fetch_claimant(claimant_id)  # 404 if missing
    rows = [
        q for q in store.quarter_credits.values()
        if q["claimant_id"] == claimant_id
    ]
    if year_min is not None:
        rows = [r for r in rows if r["year"] >= year_min]
    if year_max is not None:
        rows = [r for r in rows if r["year"] <= year_max]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows
