"""Shared helpers for routes: body parsing, pagination, ownership, OCC."""
from __future__ import annotations

import json as _json
from typing import Any, Iterable

from flask import g, request

from config import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    MAX_LIMIT,
    MIN_LIMIT,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import (
    err_forbidden,
    err_invalid_input,
    err_resource_not_found,
    err_return_not_found,
    err_taxpayer_not_found,
    err_version_conflict,
)


# ── Body parsing ────────────────────────────────────────────────────────


def get_json() -> dict:
    """Return the request JSON body as a dict (tolerates empty/missing body)."""
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        data = request.get_data(as_text=True)
        if not data.strip():
            return {}
        try:
            body = _json.loads(data)
        except Exception:
            body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


# ── Pagination ──────────────────────────────────────────────────────────


def parse_pagination():
    """Return (limit, offset) honouring scaffold defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise err_invalid_input("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise err_invalid_input("offset must be an integer")
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    return items[offset : offset + limit]


def sort_by_created_at(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda x: x["created_at"])


# ── Entity loaders ──────────────────────────────────────────────────────


def get_taxpayer_or_404(taxpayer_id: str) -> dict:
    tp = store.taxpayers.get(taxpayer_id)
    if tp is None:
        raise err_taxpayer_not_found()
    return tp


def get_return_or_404(return_id: str) -> dict:
    r = store.tax_returns.get(return_id)
    if r is None:
        raise err_return_not_found()
    return r


def get_income_doc_or_404(doc_id: str) -> dict:
    d = store.income_documents.get(doc_id)
    if d is None:
        raise err_resource_not_found("IncomeDocument not found.")
    return d


def get_schedule_or_404(schedule_id: str) -> dict:
    s = store.schedules.get(schedule_id)
    if s is None:
        raise err_resource_not_found("Schedule not found.")
    return s


def get_credit_or_404(credit_id: str) -> dict:
    c = store.tax_credits.get(credit_id)
    if c is None:
        raise err_resource_not_found("TaxCredit not found.")
    return c


def get_efiling_or_404(efiling_id: str) -> dict:
    e = store.efilings.get(efiling_id)
    if e is None:
        raise err_resource_not_found("EFiling not found.")
    return e


def get_amendment_or_404(amendment_id: str) -> dict:
    a = store.amendments.get(amendment_id)
    if a is None:
        raise err_resource_not_found("Amendment not found.")
    return a


def get_payment_or_404(payment_id: str) -> dict:
    p = store.estimated_payments.get(payment_id)
    if p is None:
        raise err_resource_not_found("EstimatedTaxPayment not found.")
    return p


# ── Ownership enforcement (PRD §2.1) ────────────────────────────────────


def enforce_taxpayer_self(taxpayer: dict) -> None:
    """If caller is Taxpayer role, their X-User-ID must equal the taxpayer's id."""
    if g.role == ROLE_TAXPAYER and taxpayer["id"] != g.user_id:
        raise err_forbidden("Taxpayer can only access their own resources.")


def enforce_return_owner(tax_return: dict) -> None:
    """If caller is Taxpayer role, the return's taxpayer_id must equal X-User-ID."""
    if g.role == ROLE_TAXPAYER and tax_return["taxpayer_id"] != g.user_id:
        raise err_forbidden("Taxpayer can only access their own returns.")


def enforce_child_owner_via_return(tax_return_id: str) -> dict:
    """Verify the parent return exists and caller may access it; return the parent."""
    r = get_return_or_404(tax_return_id)
    enforce_return_owner(r)
    return r


# ── OCC ─────────────────────────────────────────────────────────────────


def parse_version(body: dict):
    """Return the version int from body, or None if absent.

    A non-integer / negative version is treated as a mismatch
    (ERR_VERSION_CONFLICT, per scaffold validation priority 20).
    """
    if "version" not in body:
        return None
    v = body.get("version")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_version_conflict()
    return v


def check_version(entity: dict, expected) -> None:
    if expected is None:
        return
    if entity.get("version") != expected:
        raise err_version_conflict()
