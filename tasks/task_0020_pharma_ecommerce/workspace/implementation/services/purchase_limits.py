"""Purchase-limit aggregation (PRD §3.5, SCAFFOLD purchase_limit_aggregation).

Order of checks is pinned: per-order cap → special-population block →
rolling-window aggregation. Past orders contribute only if payment_status==PAID
and paid_at falls in [now - window_days, now). Window is closed at the left,
open at the right.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable

from db import db, parse_iso
from errors import err


def _rules_by_category(platform_id: str) -> dict[str, dict]:
    return {
        r["control_category"]: r
        for r in db.purchase_limit_rules.values()
        if r.get("platform_id") == platform_id
    }


def check_per_order_caps(items: list[dict], drug_index: dict[str, dict]) -> None:
    """Per-order: line.qty <= drug.per_order_qty_cap (priority 31)."""
    for line in items:
        drug = drug_index.get(line["drug_id"])
        if not drug:
            continue
        cap = int(drug.get("per_order_qty_cap") or 0)
        if cap > 0 and int(line["qty"]) > cap:
            raise err(
                "ERR_PURCHASE_LIMIT_EXCEEDED",
                f"qty {line['qty']} exceeds per_order_qty_cap {cap} for drug {drug['id']}.",
            )


def check_special_population(
    customer: dict, items: list[dict], drug_index: dict[str, dict], rules_by_cat: dict[str, dict]
) -> None:
    """Customer's special_population_flags ∩ rule.blocks_special_populations == ∅."""
    flags = set(customer.get("special_population_flags") or [])
    if not flags:
        return
    seen_categories: set[str] = set()
    for line in items:
        drug = drug_index.get(line["drug_id"])
        if not drug:
            continue
        cat = drug.get("control_category") or "NONE"
        if cat in seen_categories:
            continue
        seen_categories.add(cat)
        rule = rules_by_cat.get(cat)
        if not rule:
            continue
        blocked = set(rule.get("blocks_special_populations") or [])
        if flags & blocked:
            raise err(
                "ERR_SPECIAL_POPULATION_RESTRICTED",
                f"Customer flags {sorted(flags & blocked)} blocked from category {cat}.",
            )


def check_window_aggregation(
    platform: dict,
    customer_id: str,
    items: list[dict],
    drug_index: dict[str, dict],
    rules_by_cat: dict[str, dict],
    *,
    exclude_order_id: str | None = None,
) -> None:
    """Rolling-window aggregation per category."""
    if not rules_by_cat:
        return
    clock = parse_iso(platform["current_clock_iso"])

    # Aggregate proposed quantities by category (within the order under check)
    proposed_by_cat: dict[str, int] = {}
    for line in items:
        drug = drug_index.get(line["drug_id"])
        if not drug:
            continue
        cat = drug.get("control_category") or "NONE"
        proposed_by_cat[cat] = proposed_by_cat.get(cat, 0) + int(line["qty"])

    # For each category that has a rule, compute existing units in window.
    # Build a category-keyed drug index across the platform once.
    drug_to_cat: dict[str, str] = {}
    for d in db.drugs.values():
        if d.get("platform_id") == platform["id"]:
            drug_to_cat[d["id"]] = d.get("control_category") or "NONE"

    # Iterate over categories in chronological insertion order of the rules to
    # achieve deterministic ordering (per SCAFFOLD note about message determinism).
    rule_items = sorted(rules_by_cat.values(), key=lambda r: r.get("_seq", 0))
    for rule in rule_items:
        cat = rule["control_category"]
        proposed_units = proposed_by_cat.get(cat, 0)
        if proposed_units <= 0:
            continue
        window_days = int(rule["window_days"])
        window_start = clock - _dt.timedelta(days=window_days)

        # Sum existing units in window for this customer + category.
        existing_units = 0
        # Sort past orders by paid_at chronologically to pin determinism.
        past = [
            o
            for o in db.orders.values()
            if o.get("platform_id") == platform["id"]
            and o.get("customer_id") == customer_id
            and o.get("payment_status") == "PAID"
            and o.get("paid_at") is not None
            and (exclude_order_id is None or o["id"] != exclude_order_id)
        ]
        past.sort(key=lambda o: parse_iso(o["paid_at"]))
        for past_o in past:
            paid_at = parse_iso(past_o["paid_at"])
            if not (window_start <= paid_at < clock):
                continue
            for past_line in past_o.get("items") or []:
                pcat = drug_to_cat.get(past_line["drug_id"]) or "NONE"
                if pcat == cat:
                    existing_units += int(past_line["qty"])

        if existing_units + proposed_units > int(rule["max_units_per_window"]):
            raise err(
                "ERR_PURCHASE_LIMIT_EXCEEDED",
                f"Category {cat} would exceed max_units_per_window "
                f"({existing_units}+{proposed_units} > {rule['max_units_per_window']}).",
            )


def run_purchase_limits(
    platform: dict,
    customer: dict,
    items: list[dict],
    drug_index: dict[str, dict],
    *,
    exclude_order_id: str | None = None,
) -> None:
    """Run the three checks in pinned order: per_order → special_pop → window."""
    rules = _rules_by_category(platform["id"])
    check_per_order_caps(items, drug_index)
    check_special_population(customer, items, drug_index, rules)
    check_window_aggregation(
        platform,
        customer["id"],
        items,
        drug_index,
        rules,
        exclude_order_id=exclude_order_id,
    )
