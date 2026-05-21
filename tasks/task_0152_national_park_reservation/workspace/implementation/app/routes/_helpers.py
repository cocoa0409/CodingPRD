"""Shared helpers for routes."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from flask import g

from ..auth import current_role, current_user_id, ROLE_VISITOR
from ..errors import APIError
from ..store import Store, get_store


def _not_found(message: str = "Resource not found"):
    raise APIError("ERR_NOT_FOUND", message, 404)


def lookup_park(park_id: str) -> Dict[str, Any]:
    store = get_store()
    p = store.parks.get(park_id)
    if p is None:
        _not_found(f"Park '{park_id}' not found")
    return p


def lookup_visitor(visitor_id: str) -> Dict[str, Any]:
    store = get_store()
    v = store.visitors.get(visitor_id)
    if v is None:
        _not_found(f"Visitor '{visitor_id}' not found")
    return v


def lookup_campground(campground_id: str) -> Dict[str, Any]:
    store = get_store()
    c = store.campgrounds.get(campground_id)
    if c is None:
        _not_found(f"Campground '{campground_id}' not found")
    return c


def lookup_zone(zone_id: str) -> Dict[str, Any]:
    store = get_store()
    z = store.backcountry_zones.get(zone_id)
    if z is None:
        _not_found(f"Backcountry zone '{zone_id}' not found")
    return z


def lookup_lottery_permit(permit_id: str) -> Dict[str, Any]:
    store = get_store()
    lp = store.lottery_permits.get(permit_id)
    if lp is None:
        _not_found(f"Lottery permit '{permit_id}' not found")
    return lp


def require_visitor_ownership(visitor_id: str) -> None:
    """When the caller is a Visitor, enforce visitor_id matches X-User-ID."""
    if current_role() == ROLE_VISITOR and current_user_id() != visitor_id:
        raise APIError("ERR_FORBIDDEN", "Visitor may only act on own resources", 403)


def filter_visitor_owned(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter results to caller's visitor_id when role is Visitor."""
    if current_role() == ROLE_VISITOR:
        uid = current_user_id()
        return [it for it in items if it.get("visitor_id") == uid]
    return list(items)
