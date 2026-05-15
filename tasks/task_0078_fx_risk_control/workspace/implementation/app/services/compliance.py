"""Compliance report version helpers."""
from __future__ import annotations

from typing import Optional

from app.store import Store, new_id, now_iso


LARGE_TRADE_THRESHOLD_USD = 10_000_000


def next_version(store: Store, report_type: str, reference_trade_id: Optional[str]) -> int:
    existing = [
        r for r in store.compliance_reports.values()
        if r["report_type"] == report_type
        and r.get("reference_trade_id") == reference_trade_id
    ]
    if not existing:
        return 1
    return max(r["version"] for r in existing) + 1


def file_report(
    store: Store,
    *,
    report_type: str,
    reference_trade_id: Optional[str],
    payload: dict,
    filed_by_user_id: str,
) -> dict:
    version = next_version(store, report_type, reference_trade_id)
    ts = now_iso()
    row = {
        "id": new_id(),
        "created_at": ts,
        "report_type": report_type,
        "reference_trade_id": reference_trade_id,
        "version": version,
        "payload": payload,
        "filed_at": ts,
        "filed_by_user_id": filed_by_user_id,
    }
    store.compliance_reports[row["id"]] = row
    return row
