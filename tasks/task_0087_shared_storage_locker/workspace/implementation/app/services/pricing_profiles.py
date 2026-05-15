"""Pricing-profile business logic."""
from __future__ import annotations

from typing import Any, Optional

from .. import constants
from ..errors import ApiError
from ..store import common_fields_append_only, get_store
from .serializers import serialize_pricing_profile
from .validation import require_field, require_in, require_int, require_str


def create_pricing_profile(body: dict[str, Any]) -> dict[str, Any]:
    size_class = require_in(require_field(body, "size_class"), "size_class", constants.SIZE_CLASSES)
    rental_mode = require_in(require_field(body, "rental_mode"), "rental_mode", constants.RENTAL_MODES)
    unit_price_cents = require_int(require_field(body, "unit_price_cents"), "unit_price_cents", min_value=1)
    deposit_cents = require_int(require_field(body, "deposit_cents"), "deposit_cents", min_value=0)
    grace_minutes = require_int(require_field(body, "grace_minutes"), "grace_minutes", min_value=0)
    overdue_rate = require_int(
        require_field(body, "overdue_rate_cents_per_hour"),
        "overdue_rate_cents_per_hour",
        min_value=0,
    )
    forced_clearance_hours = require_int(
        require_field(body, "forced_clearance_hours"), "forced_clearance_hours", min_value=1
    )
    # forced_clearance_hours > grace_minutes / 60
    if forced_clearance_hours <= grace_minutes / 60.0:
        raise ApiError(
            "ERR_BAD_REQUEST",
            "forced_clearance_hours must be greater than grace_minutes/60.",
        )

    store = get_store()
    key = (size_class, rental_mode)
    if key in store.pricing_uniq:
        raise ApiError(
            "ERR_DUPLICATE_PROFILE",
            f"PricingProfile already exists for ({size_class}, {rental_mode}).",
        )

    profile = common_fields_append_only()
    profile.update(
        {
            "size_class": size_class,
            "rental_mode": rental_mode,
            "unit_price_cents": unit_price_cents,
            "deposit_cents": deposit_cents,
            "grace_minutes": grace_minutes,
            "overdue_rate_cents_per_hour": overdue_rate,
            "forced_clearance_hours": forced_clearance_hours,
        }
    )
    store.pricing_profiles[profile["id"]] = profile
    store.pricing_uniq[key] = profile["id"]
    return serialize_pricing_profile(profile)


def list_pricing_profiles(
    size_class: Optional[str],
    rental_mode: Optional[str],
) -> list[dict[str, Any]]:
    store = get_store()
    items = list(store.pricing_profiles.values())
    if size_class:
        items = [p for p in items if p["size_class"] == size_class]
    if rental_mode:
        items = [p for p in items if p["rental_mode"] == rental_mode]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return [serialize_pricing_profile(p) for p in items]


def find_pricing_profile(size_class: str, rental_mode: str) -> Optional[dict[str, Any]]:
    store = get_store()
    pid = store.pricing_uniq.get((size_class, rental_mode))
    if pid is None:
        return None
    return store.pricing_profiles.get(pid)
