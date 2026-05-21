"""Per-diem rate resolver."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.store import store
from core.utils import parse_iso


def resolve_per_diem(
    city: str, state: str, when: datetime
) -> Optional[dict]:
    """Find a PerDiemRate row covering `when` for the given (city, state).

    Match rules: city case-insensitive, state exact.
    Window: [effective_from, effective_to).
    """
    if when is None:
        return None
    city_lower = (city or "").strip().lower()
    state_upper = (state or "").strip().upper()

    for rate in store.per_diem_rates.values():
        if (rate["city"] or "").strip().lower() != city_lower:
            continue
        if (rate["state"] or "").strip().upper() != state_upper:
            continue
        eff_from = parse_iso(rate["effective_from"])
        eff_to = parse_iso(rate["effective_to"])
        if eff_from is None or eff_to is None:
            continue
        if eff_from <= when < eff_to:
            return rate
    return None


def resolve_per_diem_by_id(rate_id: Optional[str]) -> Optional[dict]:
    if not rate_id:
        return None
    return store.per_diem_rates.get(rate_id)
