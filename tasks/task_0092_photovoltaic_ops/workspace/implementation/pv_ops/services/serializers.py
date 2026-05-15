"""Serialization helpers: convert internal dicts into the public output shape."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


def _public_copy(row: dict, *, exclude: tuple = ()) -> dict:
    out = {}
    for k, v in row.items():
        if k in exclude:
            continue
        out[k] = deepcopy(v)
    return out


def station_view(row: dict) -> dict:
    return _public_copy(row)


def array_view(row: dict) -> dict:
    return _public_copy(row)


def pvstring_view(row: dict) -> dict:
    return _public_copy(row)


def module_view(row: dict) -> dict:
    return _public_copy(row)


def inverter_view(row: dict) -> dict:
    return _public_copy(row)


def transformer_view(row: dict) -> dict:
    return _public_copy(row)


def supplier_view(row: dict) -> dict:
    return _public_copy(row)


def reading_view(row: dict) -> dict:
    return _public_copy(row)


def alarm_code_view(row: dict) -> dict:
    return _public_copy(row)


def alarm_event_view(row: dict) -> dict:
    return _public_copy(row)


def patrol_plan_view(row: dict) -> dict:
    return _public_copy(row)


def patrol_record_view(row: dict) -> dict:
    return _public_copy(row)


def defect_view(row: dict) -> dict:
    return _public_copy(row)


def work_order_view(row: dict) -> dict:
    return _public_copy(row)


def spare_part_view(row: dict) -> dict:
    return _public_copy(row)


def metering_view(row: dict) -> dict:
    return _public_copy(row)


def settlement_view(row: dict, distributions: list[dict] | None = None) -> dict:
    view = _public_copy(row)
    if distributions is not None:
        view["distributions"] = [revenue_distribution_view(d) for d in distributions]
    return view


def investor_share_view(row: dict) -> dict:
    return _public_copy(row)


def revenue_distribution_view(row: dict) -> dict:
    return _public_copy(row)


def subsidy_policy_view(row: dict) -> dict:
    return _public_copy(row)


def subsidy_declaration_view(row: dict) -> dict:
    return _public_copy(row)


def audit_view(row: dict) -> dict:
    return _public_copy(row)
