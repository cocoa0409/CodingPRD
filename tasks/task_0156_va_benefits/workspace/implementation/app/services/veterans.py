"""Veteran service: registration, projection, and the recompute helpers."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from flask import g

from ..calculations import (
    combined_rating,
    entitlement_projection,
    entitlement_used_chronological,
    post_911_tier,
)
from ..clock import Clock
from ..errors import ApiError
from ..store import Store
from ..util import money, new_id

VALID_BRANCHES = {"ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE"}
VALID_DISCHARGE = {"HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE", "BAD_CONDUCT", "DISHONORABLE"}


def _now_iso(store: Store) -> str:
    return Clock.format(store.clock.now())


def create_veteran(store: Store, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")

    full_name = body.get("full_name")
    branch = body.get("branch")
    duty_days = body.get("aggregate_active_duty_days")
    discharge = body.get("discharge_status")

    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 120):
        raise ApiError("ERR_INVALID_BODY", "full_name must be 1..120 chars")
    if branch not in VALID_BRANCHES:
        raise ApiError("ERR_INVALID_BODY", "invalid branch")
    if not isinstance(duty_days, int) or isinstance(duty_days, bool) or duty_days < 0:
        raise ApiError("ERR_INVALID_BODY", "aggregate_active_duty_days must be non-negative integer")
    if discharge not in VALID_DISCHARGE:
        raise ApiError("ERR_INVALID_BODY", "invalid discharge_status")

    now = _now_iso(store)
    vid = new_id()
    veteran = {
        "id": vid,
        "full_name": full_name,
        "branch": branch,
        "aggregate_active_duty_days": duty_days,
        "discharge_status": discharge,
        "combined_rating": 0,
        "post_911_eligibility_tier": post_911_tier(duty_days),
        "months_entitlement_used": Decimal("0.00"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.veterans[vid] = veteran
    return veteran


def update_veteran(store: Store, vid: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    v = store.veterans.get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")

    # OCC
    if "version" in body and body["version"] is not None:
        if body["version"] != v["version"]:
            raise ApiError("ERR_VERSION_CONFLICT", "version conflict")

    if "aggregate_active_duty_days" not in body:
        raise ApiError("ERR_INVALID_BODY", "aggregate_active_duty_days required")
    duty_days = body["aggregate_active_duty_days"]
    if not isinstance(duty_days, int) or isinstance(duty_days, bool) or duty_days < 0:
        raise ApiError("ERR_INVALID_BODY", "aggregate_active_duty_days must be non-negative integer")

    v["aggregate_active_duty_days"] = duty_days
    v["post_911_eligibility_tier"] = post_911_tier(duty_days)
    _bump_version(store, v)
    return v


def recompute_combined_rating(store: Store, veteran_id: str, *, treat_claim_as_zero: str | None = None) -> None:
    """Recompute Veteran.combined_rating from GRANTED claims."""
    v = store.veterans.get(veteran_id)
    if v is None:
        return
    pairs: list[tuple[int, str]] = []
    for c in store.claims.values():
        if c["veteran_id"] != veteran_id:
            continue
        if c["status"] != "GRANTED":
            continue
        if treat_claim_as_zero and c["id"] == treat_claim_as_zero:
            # Pretend it has rating 0 — used during reopen.
            pairs.append((0, c["id"]))
        else:
            r = c.get("granted_rating")
            if r is not None:
                pairs.append((r, c["id"]))
    new_rating = combined_rating(pairs)
    if new_rating != v["combined_rating"]:
        v["combined_rating"] = new_rating
        _bump_version(store, v)
    # Defensive recompute of post_911_tier (no change unless duty days changed).
    new_tier = post_911_tier(v["aggregate_active_duty_days"])
    if new_tier != v["post_911_eligibility_tier"]:
        v["post_911_eligibility_tier"] = new_tier
        _bump_version(store, v)


def recompute_entitlement(store: Store, veteran_id: str) -> None:
    v = store.veterans.get(veteran_id)
    if v is None:
        return
    enrolls = [e for e in store.enrollments.values() if e["veteran_id"] == veteran_id]
    total = entitlement_used_chronological(enrolls, now=store.clock.now())
    if total != v["months_entitlement_used"]:
        v["months_entitlement_used"] = total
        _bump_version(store, v)


def _bump_version(store: Store, v: dict) -> None:
    v["updated_at"] = _now_iso(store)
    v["version"] = v["version"] + 1


def get_projection(store: Store, veteran_id: str, include_certified: bool) -> dict:
    v = store.veterans.get(veteran_id)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "veteran not found")
    enrolls = [e for e in store.enrollments.values() if e["veteran_id"] == veteran_id]
    chronological = entitlement_used_chronological(enrolls, now=store.clock.now())
    projected = (
        entitlement_projection(enrolls, now=store.clock.now())
        if include_certified
        else chronological
    )
    return {
        "chronological_used": float(chronological),
        "projected_used": float(projected),
        "remaining_chronological": float(Decimal("36.00") - chronological),
        "remaining_projected": float(Decimal("36.00") - projected),
    }
