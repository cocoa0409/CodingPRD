"""Shared helpers for route modules."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

from flask import g, request

from config import (
    AGENT_ROLE_BUYER,
    AGENT_ROLE_DUAL,
    AGENT_ROLE_LISTING,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
)
from db import store
from errors import (
    ApiError,
    err_forbidden_not_owner,
    err_not_found,
    err_version_conflict,
)
from utils import parse_iso


# ─────────────────────────────────────────────────────────────────────────────
# Body parsing
# ─────────────────────────────────────────────────────────────────────────────


def get_json() -> dict:
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        data = request.get_data(as_text=True)
        if not data.strip():
            return {}
        try:
            body = json.loads(data)
        except Exception:
            body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


def require_str(body: dict, key: str, err: ApiError) -> str:
    val = body.get(key)
    if val is None or not isinstance(val, str) or val == "":
        raise err
    return val


def require_int(body: dict, key: str, err: ApiError) -> int:
    val = body.get(key)
    if val is None or isinstance(val, bool) or not isinstance(val, int):
        raise err
    return val


def get_int(body: dict, key: str, default: Optional[int] = None,
            err: Optional[ApiError] = None) -> Optional[int]:
    val = body.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        if err:
            raise err
        return default
    if isinstance(val, int):
        return val
    if err:
        raise err
    return default


def get_number(body: dict, key: str, default=None, err: Optional[ApiError] = None):
    val = body.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        if err:
            raise err
        return default
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            if err:
                raise err
            return default
    if err:
        raise err
    return default


def parse_required_iso(body: dict, key: str, err: ApiError):
    val = body.get(key)
    if val is None:
        raise err
    try:
        return parse_iso(val)
    except Exception:
        raise err


def parse_optional_iso(body: dict, key: str, err: ApiError):
    val = body.get(key)
    if val is None:
        return None
    try:
        return parse_iso(val)
    except Exception:
        raise err


# ─────────────────────────────────────────────────────────────────────────────
# Pagination
# ─────────────────────────────────────────────────────────────────────────────


def parse_pagination():
    try:
        raw_limit = request.args.get("limit", str(DEFAULT_LIMIT))
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        raw_offset = request.args.get("offset", str(DEFAULT_OFFSET))
        offset = int(raw_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    return items[offset : offset + limit]


def sort_by_created_at(items):
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


# ─────────────────────────────────────────────────────────────────────────────
# Existence helpers (raise ERR_NOT_FOUND on miss)
# ─────────────────────────────────────────────────────────────────────────────


def get_agent_or_404(agent_id: str) -> dict:
    a = store.agents.get(agent_id)
    if a is None:
        raise err_not_found("Agent not found.")
    return a


def get_listing_or_404(listing_id: str) -> dict:
    l = store.listings.get(listing_id)
    if l is None:
        raise err_not_found("Listing not found.")
    return l


def get_buyer_or_404(buyer_id: str) -> dict:
    b = store.buyers.get(buyer_id)
    if b is None:
        raise err_not_found("Buyer not found.")
    return b


def get_offer_in_listing_or_404(listing_id: str, offer_id: str) -> dict:
    o = store.offers.get(offer_id)
    if o is None or o["listing_id"] != listing_id:
        raise err_not_found("Offer not found in this listing.")
    return o


def get_showing_in_listing_or_404(listing_id: str, showing_id: str) -> dict:
    s = store.showings.get(showing_id)
    if s is None or s["listing_id"] != listing_id:
        raise err_not_found("Showing not found in this listing.")
    return s


def get_contingency_in_listing_or_404(listing_id: str, contingency_id: str) -> dict:
    c = store.contingencies.get(contingency_id)
    if c is None:
        raise err_not_found("Contingency not found.")
    offer = store.offers.get(c["offer_id"])
    if offer is None or offer["listing_id"] != listing_id:
        raise err_not_found("Contingency not found in this listing.")
    return c


def get_lockbox_of_listing_or_404(listing_id: str) -> dict:
    lb_id = store.lockbox_by_listing.get(listing_id)
    if not lb_id:
        raise err_not_found("Lockbox not found on this listing.")
    lb = store.lockboxes.get(lb_id)
    if lb is None:
        raise err_not_found("Lockbox not found on this listing.")
    return lb


# ─────────────────────────────────────────────────────────────────────────────
# Ownership helpers (PRD §2.1)
# ─────────────────────────────────────────────────────────────────────────────


def listing_agent_is_caller(listing: dict) -> bool:
    return listing["listing_agent_id"] == g.user_id


def buyer_agent_is_caller(buyer: dict) -> bool:
    return buyer["buyer_agent_id"] == g.user_id


def enforce_listing_side_ownership(listing: dict) -> None:
    """ListingAgent caller must own the listing (be the listing_agent_id)."""
    if g.role == "ListingAgent" and not listing_agent_is_caller(listing):
        raise err_forbidden_not_owner(
            "Caller is not the LISTING_AGENT for this listing."
        )


def enforce_buyer_side_ownership(buyer: dict) -> None:
    """BuyerAgent caller must own the buyer (be the buyer_agent_id)."""
    if g.role == "BuyerAgent" and not buyer_agent_is_caller(buyer):
        raise err_forbidden_not_owner(
            "Caller is not the BUYER_AGENT for this buyer."
        )


# ─────────────────────────────────────────────────────────────────────────────
# OCC version helpers (PRD §2.6)
# ─────────────────────────────────────────────────────────────────────────────


def check_version_if_present(entity: dict, body: dict) -> None:
    """If a `version` field is present in the body, it must match the stored row.

    If the field is omitted entirely the optimistic check is skipped (PRD §2.6).
    """
    if "version" not in body:
        return
    expected = body["version"]
    if expected is None:
        return
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_version_conflict("version field must be an integer.")
    if entity.get("version") != expected:
        raise err_version_conflict()
