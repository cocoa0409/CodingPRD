"""Rent Reasonableness records."""

from __future__ import annotations

from app import calculations, clock, store
from app.errors import APIError, fk_not_found, validation
from app.services.common import touch
from app.util import new_id, require_str


def create_record(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        tenancy_id = require_str(payload.get("tenancy_id"), field="tenancy_id")
        comps = payload.get("comparable_rents_cents")
        if not isinstance(comps, list):
            raise ValueError("comparable_rents_cents must be an array")
        for c in comps:
            if c is True or c is False or not isinstance(c, int) or c < 0:
                raise ValueError("comparable_rents_cents entries must be non-negative integers")
    except ValueError as exc:
        raise validation(str(exc))

    tenancy = store.tenancies.get(tenancy_id)
    if tenancy is None:
        raise fk_not_found(f"tenancy_id {tenancy_id!r} not found")

    if len(comps) < 3:
        raise APIError(
            "ERR_INSUFFICIENT_COMPARABLES",
            422,
            "comparable_rents_cents must have length >= 3",
        )

    median, threshold = calculations.calc_rent_reasonableness(comps)
    is_reasonable = tenancy["gross_rent_cents"] <= threshold

    now = clock.now()
    rec_id = new_id()
    record = {
        "id": rec_id,
        "created_at": now,
        "tenancy_id": tenancy_id,
        "comparable_rents_cents": list(comps),
        "median_comparable_cents": median,
        "reasonable_threshold_cents": threshold,
        "is_reasonable": is_reasonable,
        "recorded_at": now,
    }
    store.rent_reasonableness_records[rec_id] = record

    tenancy["rent_reasonable"] = is_reasonable
    touch(tenancy)
    return record
