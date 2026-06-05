"""ExchangeAccount service (PRD §3.7)."""
from __future__ import annotations

import datetime as dt
from typing import Any

from clock import CLOCK, parse_iso
from db import DB_INSTANCE, new_id
from errors import (
    ERR_EXCHANGE_ID_DEADLINE_PASSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    err,
)
from exchange_eval import evaluate_exchange_account
from lookup import get_exchange_or_404
from validation import require_fields, require_str


def create_exchange(body: dict) -> dict:
    require_fields(body, ["taxpayer_name", "qualified_intermediary_name", "relinquished_closing_date"])
    taxpayer = require_str(body, "taxpayer_name")
    qi = require_str(body, "qualified_intermediary_name")
    relinquished_iso = require_str(body, "relinquished_closing_date")
    try:
        relinquished = parse_iso(relinquished_iso)
    except ValueError as exc:
        raise err(ERR_INVALID_REQUEST, "relinquished_closing_date must be ISO 8601") from exc

    now = CLOCK.now()
    x = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "taxpayer_name": taxpayer,
        "qualified_intermediary_name": qi,
        "relinquished_closing_date": relinquished,
        "identification_deadline": relinquished + dt.timedelta(days=45),
        "exchange_deadline": relinquished + dt.timedelta(days=180),
        "replacement_property_identified": False,
        "identified_at": None,
        "status": "OPEN",
    }
    DB_INSTANCE.exchange_accounts[x["id"]] = x
    return x


def identify(x_id: str, body: dict) -> dict:
    x = get_exchange_or_404(x_id)
    # Evaluate deadlines synchronously before state check.
    evaluate_exchange_account(x)
    if x["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "exchange account is not in OPEN")
    addr = body.get("replacement_property_address")
    if not isinstance(addr, str) or addr == "":
        raise err(ERR_INVALID_REQUEST, "replacement_property_address must be non-empty")
    if CLOCK.now() > x["identification_deadline"]:
        raise err(ERR_EXCHANGE_ID_DEADLINE_PASSED, "identification_deadline has passed")
    x["replacement_property_identified"] = True
    x["identified_at"] = CLOCK.now()
    x["status"] = "IDENTIFIED"
    x["updated_at"] = CLOCK.now()
    x["version"] += 1
    return x


def fetch(x_id: str) -> dict:
    x = get_exchange_or_404(x_id)
    evaluate_exchange_account(x)
    return x


def list_exchanges(filters: dict[str, Any]) -> list[dict]:
    # Evaluate all rows so list reflects deadline-driven failures.
    for x in DB_INSTANCE.exchange_accounts.values():
        evaluate_exchange_account(x)
    items = list(DB_INSTANCE.exchange_accounts.values())
    if filters.get("status"):
        items = [x for x in items if x["status"] == filters["status"]]
    items.sort(key=lambda x: x["created_at"])
    return items
