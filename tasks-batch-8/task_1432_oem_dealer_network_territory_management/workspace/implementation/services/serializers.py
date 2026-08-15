"""Entity serializers: strip internal fields, add derived read-only fields."""

from __future__ import annotations


def serialize(entity: dict) -> dict:
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    return out


def serialize_dealer(dealer: dict) -> dict:
    out = serialize(dealer)
    out["floorplan_available_cents"] = (
        dealer["credit_limit_cents"] - dealer["floorplan_utilization_cents"]
    )
    return out


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]


def serialize_dealer_list(items: list) -> list:
    return [serialize_dealer(it) for it in items]
