"""RevenueRecord emission helpers."""
from __future__ import annotations

from typing import Any, Optional

from ..calculations import revenue_split_per_row
from ..clock import now_iso_ms
from ..store import common_fields_append_only, get_store


def emit_revenue_record(
    rental: dict[str, Any],
    revenue_kind: str,
    gross_cents: int,
    occurred_at: Optional[str] = None,
) -> dict[str, Any]:
    """Create a RevenueRecord row using per-row split (PRD §2.12)."""
    store = get_store()
    cabinet = store.cabinets[rental["cabinet_id"]]
    partner_pct = int(cabinet["partner_share_pct"])
    partner, platform = revenue_split_per_row(int(gross_cents), partner_pct)

    row = common_fields_append_only()
    row.update(
        {
            "rental_id": rental["id"],
            "cabinet_id": rental["cabinet_id"],
            "revenue_kind": revenue_kind,
            "gross_cents": int(gross_cents),
            "partner_share_cents": int(partner),
            "platform_share_cents": int(platform),
            "occurred_at": occurred_at or now_iso_ms(),
        }
    )
    store.revenue_records[row["id"]] = row
    return row
