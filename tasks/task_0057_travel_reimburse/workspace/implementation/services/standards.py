"""ExpenseStandard lookup helpers."""

from __future__ import annotations

from datetime import datetime

from db import STORE
from utils import parse_ts


def find_active_standard(at_time: datetime, *, city_tier: str, employee_level: str):
    """Return the ExpenseStandard row whose [effective_from, effective_to) window
    contains `at_time` for the given (city_tier, employee_level). None if none."""
    for row in STORE.expense_standards.values():
        if row["city_tier"] != city_tier or row["employee_level"] != employee_level:
            continue
        ef = parse_ts(row["effective_from"])
        et = row.get("effective_to")
        et_parsed = parse_ts(et) if et else None
        if ef is None or ef is False:
            continue
        if at_time < ef:
            continue
        if et_parsed is not None and et_parsed is not False and at_time >= et_parsed:
            continue
        return row
    return None


def find_standard_pinned(*, version: int, city_tier: str, employee_level: str):
    """Find ExpenseStandard row by (version, city_tier, employee_level) triple."""
    for row in STORE.expense_standards.values():
        if (row["version"] == version
                and row["city_tier"] == city_tier
                and row["employee_level"] == employee_level):
            return row
    return None
