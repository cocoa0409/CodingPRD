"""CCRReview service — append-only."""
from __future__ import annotations

from typing import Any

from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import ERR_INVALID_REQUEST, err
from lookup import get_fk_agreement
from validation import require_bool, require_fields, require_str


def create_ccr(body: dict) -> dict:
    require_fields(body, ["agreement_id", "restrictions_summary", "buyer_acknowledged"])
    agreement_id = require_str(body, "agreement_id")
    restrictions_summary = require_str(body, "restrictions_summary", allow_empty=True)
    buyer_acknowledged = require_bool(body, "buyer_acknowledged")
    hoa_name = body.get("hoa_name")
    if hoa_name is not None and not isinstance(hoa_name, str):
        raise err(ERR_INVALID_REQUEST, "hoa_name must be a string or null")

    get_fk_agreement(agreement_id)

    now = CLOCK.now()
    c = {
        "id": new_id(),
        "created_at": now,
        "agreement_id": agreement_id,
        "hoa_name": hoa_name,
        "restrictions_summary": restrictions_summary,
        "buyer_acknowledged": buyer_acknowledged,
    }
    DB_INSTANCE.ccr_reviews[c["id"]] = c
    return c


def list_ccrs(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.ccr_reviews.values())
    if filters.get("agreement_id"):
        items = [c for c in items if c["agreement_id"] == filters["agreement_id"]]
    items.sort(key=lambda c: c["created_at"])
    return items
