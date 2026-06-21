"""Precision-sensitive calculations: conversion shares, exercise spread,
liquidation waterfall. PRD §2.5, §3.8, §3.10, §3.12.
"""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import List

from services import core  # noqa: F401  (kept for potential cross-use)


def round_half_up(value) -> int:
    """Round a numeric value half-up to a whole integer (cents/shares)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Exercise spread. PRD §3.8 / SCAFFOLD calc exercise_spread.
# Exact integer cents, no rounding; floored at 0.
# --------------------------------------------------------------------------

def exercise_spread_cents(grant: dict, valuation: dict, share_count: int) -> int:
    fmv = valuation["fmv_per_share_cents"]
    spread_per_share = max(0, fmv - grant["strike_price_cents"])
    return spread_per_share * share_count


# --------------------------------------------------------------------------
# SAFE/Note conversion. PRD §3.10 / SCAFFOLD calc conversion_shares.
# accrued interest round_half_up to whole cents; price arithmetic in floats;
# final share count floored.
# --------------------------------------------------------------------------

DAYS_PER_YEAR = 365


def accrued_interest_cents(note: dict, now: datetime) -> int:
    if note["instrument_type"] != "NOTE":
        return 0
    rate = note["interest_rate_pct"]
    if rate <= 0:
        return 0
    days = (now - note["issue_date"]).total_seconds() / 86400.0
    years = days / DAYS_PER_YEAR
    return round_half_up(note["principal_cents"] * rate * years)


def conversion_share_count(note: dict, target_class: dict, cap_table: dict, now: datetime) -> int:
    accrued = accrued_interest_cents(note, now)
    invested = note["principal_cents"] + accrued
    round_price = float(target_class["original_issue_price_cents"])
    discount_price = round_price * (1.0 - note["discount_pct"])
    if note["valuation_cap_cents"] > 0:
        fd = cap_table["fully_diluted_shares"]
        if fd and fd > 0:
            cap_price = note["valuation_cap_cents"] / float(fd)
            effective_price = min(discount_price, cap_price)
        else:
            effective_price = discount_price
    else:
        effective_price = discount_price
    if effective_price <= 0:
        return 0
    return int(math.floor(invested / effective_price))


# --------------------------------------------------------------------------
# Liquidation waterfall. PRD §3.12 / SCAFFOLD calc liquidation_waterfall.
# --------------------------------------------------------------------------

def seniority_order(preferred_classes: List[dict]) -> List[dict]:
    """Order PREFERRED classes top-down by the seniority chain.

    A class with seniority_below_class_id == null is most senior; each class is
    paid AFTER the class it points to. Tie-break (classes naming the same parent)
    by created_at ASC. PRD §3.12.
    """
    by_id = {c["id"]: c for c in preferred_classes}
    # children grouped by their parent (seniority_below_class_id)
    children = {}
    roots = []
    for c in preferred_classes:
        parent = c.get("seniority_below_class_id")
        if parent is None or parent not in by_id:
            roots.append(c)
        else:
            children.setdefault(parent, []).append(c)

    def sort_key(c):
        return (c["created_at"], c["id"])

    ordered: List[dict] = []
    # BFS-like top-down walk: roots first (sorted), then each class's children.
    stack = sorted(roots, key=sort_key, reverse=True)
    visited = set()
    while stack:
        node = stack.pop()
        if node["id"] in visited:
            continue
        visited.add(node["id"])
        ordered.append(node)
        kids = sorted(children.get(node["id"], []), key=sort_key, reverse=True)
        for k in kids:
            if k["id"] not in visited:
                stack.append(k)
    # any class not reached (defensive) appended in created order
    for c in sorted(preferred_classes, key=sort_key):
        if c["id"] not in visited:
            ordered.append(c)
            visited.add(c["id"])
    return ordered


def compute_waterfall(event: dict, classes: List[dict], now: datetime) -> List[dict]:
    """Return per-class allocation dicts with preference/participation/total cents.

    Two passes. Pass 1: preferences in seniority order. Pass 2: residual pro-rata
    over COMMON + participating-preferred. Residual rounding cents assigned to the
    most-senior class. PRD §3.12.
    """
    total = event["total_proceeds_cents"]
    remaining = total

    alloc = {}
    for c in classes:
        alloc[c["id"]] = {
            "security_class_id": c["id"],
            "preference_paid_cents": 0,
            "participation_paid_cents": 0,
        }

    preferred = [c for c in classes if c["class_type"] == "PREFERRED"]
    senior_first = seniority_order(preferred)

    # ---- Pass 1: liquidation preferences (most senior first) ----
    for c in senior_first:
        invested = c["original_issue_price_cents"] * c["shares_outstanding"]
        pref = round_half_up(c["liquidation_pref_multiple"] * invested)
        pay = min(pref, remaining)
        if pay < 0:
            pay = 0
        alloc[c["id"]]["preference_paid_cents"] = pay
        remaining -= pay

    # ---- Pass 2: residual pro-rata over COMMON + participating preferred ----
    participating = [
        c for c in classes
        if c["class_type"] == "COMMON"
        or (c["class_type"] == "PREFERRED" and c["participating"])
    ]
    participating_shares = sum(c["shares_outstanding"] for c in participating)

    # raw_sum tracks the uncapped per-class participation total. The rounding
    # residual we conserve is the gap between `remaining` and raw_sum -- a few
    # cents from per-class half-up rounding. A participation-cap shortfall is NOT
    # rounding residual: it is money the capped class deliberately does not take,
    # so it stays undistributed (PRD §3.12: "residual cents left BY ROUNDING").
    raw_sum = 0
    if participating_shares > 0 and remaining > 0:
        for c in participating:
            raw = round_half_up(remaining * c["shares_outstanding"] / participating_shares)
            raw_sum += raw
            if c["class_type"] == "PREFERRED" and c["participating"] and c["participation_cap_multiple"] > 0:
                invested = c["original_issue_price_cents"] * c["shares_outstanding"]
                cap_total = round_half_up(c["participation_cap_multiple"] * invested)
                allowed = max(0, cap_total - alloc[c["id"]]["preference_paid_cents"])
                alloc[c["id"]]["participation_paid_cents"] = min(raw, allowed)
            else:
                alloc[c["id"]]["participation_paid_cents"] = raw

    # ---- Conserve the rounding residual onto the most-senior class ----
    # rounding_residual = the distributable pass-2 pot minus the sum of raw
    # (pre-cap) per-class shares. Assigned to the most senior class so per-class
    # allocations sum exactly to the proceeds distributed in pass 2.
    if participating_shares > 0 and remaining > 0:
        rounding_residual = remaining - raw_sum
        if rounding_residual != 0:
            if senior_first:
                target_id = senior_first[0]["id"]
            else:
                target_id = sorted(classes, key=lambda c: (c["created_at"], c["id"]))[0]["id"]
            # only true up a participating class (the senior-most class shares pass 2);
            # if the senior class is non-participating it took no pass-2 share, so
            # fall back to the first participating class by seniority/created order.
            if target_id not in {c["id"] for c in participating}:
                part_sorted = sorted(participating, key=lambda c: (c["created_at"], c["id"]))
                if part_sorted:
                    target_id = part_sorted[0]["id"]
            alloc[target_id]["participation_paid_cents"] += rounding_residual

    rows = []
    for c in classes:
        a = alloc[c["id"]]
        a["total_paid_cents"] = a["preference_paid_cents"] + a["participation_paid_cents"]
        rows.append(a)
    return rows
