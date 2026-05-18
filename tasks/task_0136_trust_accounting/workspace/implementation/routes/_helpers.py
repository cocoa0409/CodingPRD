"""Shared route helpers: body parsing, pagination, validation primitives."""
from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import g, request

from config import (
    ASSET_CLASSES,
    ASSET_CLASSIFICATIONS,
    BENEFICIARY_CLASSES,
    BENEFICIARY_RELATION_CLASSES,
    BENEFICIARY_STATUSES,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    DISTRIBUTION_STATUSES,
    DISTRIBUTION_TIERS,
    DISTRIBUTION_TYPES,
    GRANTOR_TAX_STATUSES,
    K1_STATUSES,
    MAX_LIMIT,
    MIN_LIMIT,
    TAX_YEAR_STATUSES,
    TRUST_STATUSES,
    TRUST_TYPES,
    TXN_TYPES,
    PRINCIPAL_OR_INCOME,
)
from db import store
from errors import (
    ApiError,
    err_bad_request,
    err_forbidden,
    err_not_found,
    err_version_mismatch,
)
from utils import parse_iso


# ── Body parsing ────────────────────────────────────────────────────────────


def get_json() -> dict:
    """Return the request JSON body as a dict (empty body → empty dict)."""
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        data = request.get_data(as_text=True)
        if not data or not data.strip():
            return {}
        try:
            body = json.loads(data)
        except Exception:
            raise err_bad_request("Body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_bad_request("Body must be a JSON object.")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err_bad_request(f"Missing field: {name}")
    return body[name]


def require_string(body: dict, name: str) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or not v.strip():
        raise err_bad_request(f"Field {name} must be a non-empty string.")
    return v


def require_enum(body: dict, name: str, choices: set) -> str:
    v = require_string(body, name)
    if v not in choices:
        raise err_bad_request(f"Field {name} must be one of {sorted(choices)}.")
    return v


def require_bool(body: dict, name: str, default=None) -> bool:
    if name not in body or body[name] is None:
        if default is None:
            raise err_bad_request(f"Missing boolean field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err_bad_request(f"Field {name} must be boolean.")
    return v


def require_int(body: dict, name: str) -> int:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        # Try string-to-int.
        if isinstance(v, str):
            try:
                return int(v)
            except (TypeError, ValueError):
                raise err_bad_request(f"Field {name} must be an integer.")
        raise err_bad_request(f"Field {name} must be an integer.")
    return v


def require_money(body: dict, name: str, allow_zero: bool = True) -> Decimal:
    """A non-negative decimal money value. Reject negatives → ERR_BAD_REQUEST."""
    v = require_field(body, name)
    if isinstance(v, bool):
        raise err_bad_request(f"Field {name} must be a number.")
    try:
        if isinstance(v, (int, float)):
            d = Decimal(repr(v)) if isinstance(v, float) else Decimal(v)
        elif isinstance(v, str):
            d = Decimal(v)
        else:
            raise err_bad_request(f"Field {name} must be a number.")
    except (InvalidOperation, TypeError, ValueError):
        raise err_bad_request(f"Field {name} must be a number.")
    if d < 0:
        raise err_bad_request(f"Field {name} must be non-negative.")
    if not allow_zero and d == 0:
        raise err_bad_request(f"Field {name} must be > 0.")
    return d


def require_date(body: dict, name: str) -> datetime:
    raw = require_field(body, name)
    try:
        dt = parse_iso(raw)
    except Exception:
        raise err_bad_request(f"Field {name} must be ISO 8601.")
    if dt is None:
        raise err_bad_request(f"Field {name} must be ISO 8601.")
    return dt


def optional_date(body: dict, name: str):
    if name not in body or body[name] is None:
        return None
    try:
        return parse_iso(body[name])
    except Exception:
        raise err_bad_request(f"Field {name} must be ISO 8601.")


# ── OCC version ─────────────────────────────────────────────────────────────


def parse_version(body: dict):
    """Read body['version']; None means OCC skipped."""
    if "version" not in body or body["version"] is None:
        return None
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise err_bad_request("version must be integer.")
    return v


def check_version(entity: dict, expected) -> None:
    if expected is None:
        return
    if int(entity.get("version", 0)) != int(expected):
        raise err_version_mismatch()


# ── Pagination ──────────────────────────────────────────────────────────────


def parse_pagination():
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(request.args.get("offset", DEFAULT_OFFSET))
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
    return sorted(items, key=lambda x: x["created_at"])


# ── Path resolution (PRD §2.6 left-to-right) ────────────────────────────────


def get_trust_or_404(trust_id: str) -> dict:
    t = store.trusts.get(trust_id)
    if t is None:
        raise err_not_found("Trust not found.")
    return t


def get_trustee_or_404(trust: dict, trustee_id: str) -> dict:
    t = store.trustees.get(trustee_id)
    if t is None or t["trust_id"] != trust["id"]:
        raise err_not_found("Trustee not found.")
    return t


def get_beneficiary_or_404(trust: dict, beneficiary_id: str) -> dict:
    b = store.beneficiaries.get(beneficiary_id)
    if b is None or b["trust_id"] != trust["id"]:
        raise err_not_found("Beneficiary not found.")
    return b


def get_asset_or_404(trust: dict, asset_id: str) -> dict:
    a = store.assets.get(asset_id)
    if a is None or a["trust_id"] != trust["id"]:
        raise err_not_found("Asset not found.")
    return a


def get_transaction_or_404(trust: dict, transaction_id: str) -> dict:
    tx = store.transactions.get(transaction_id)
    if tx is None or tx["trust_id"] != trust["id"]:
        raise err_not_found("Transaction not found.")
    return tx


def get_distribution_or_404(trust: dict, distribution_id: str) -> dict:
    d = store.distributions.get(distribution_id)
    if d is None or d["trust_id"] != trust["id"]:
        raise err_not_found("Distribution not found.")
    return d


def get_tax_year_or_404(trust: dict, tax_year_id: str) -> dict:
    ty = store.tax_years.get(tax_year_id)
    if ty is None or ty["trust_id"] != trust["id"]:
        raise err_not_found("TaxYear not found.")
    return ty


def get_k1_or_404(tax_year: dict, k1_id: str) -> dict:
    k = store.k1s.get(k1_id)
    if k is None or k["tax_year_id"] != tax_year["id"]:
        raise err_not_found("K-1 not found.")
    return k


# ── Ownership / role-scope checks ───────────────────────────────────────────


def enforce_grantor_owns_trust(trust: dict) -> None:
    """Grantor role: X-User-ID must equal trust.grantor_user_id."""
    if g.role == "Grantor" and trust["grantor_user_id"] != g.user_id:
        raise err_forbidden("Grantor may only act on their own trust.")


def enforce_trustee_is_under_trust(trust: dict) -> None:
    """Trustee role: X-User-ID must be a Trustee.user_id of an ACTIVE trustee
    under this trust.
    """
    if g.role != "Trustee":
        return
    match = next(
        (
            t for t in store.trustees.values()
            if t["trust_id"] == trust["id"] and t["user_id"] == g.user_id
        ),
        None,
    )
    if match is None or match["status"] != "ACTIVE":
        raise err_forbidden("Trustee not registered or not ACTIVE under this trust.")


def enforce_beneficiary_owns_record(beneficiary: dict) -> None:
    if g.role == "Beneficiary" and beneficiary["id"] != g.user_id:
        raise err_forbidden("Beneficiary may only read own record.")


# Re-export enum sets for routes that import them.
__all__ = [
    "ASSET_CLASSES", "ASSET_CLASSIFICATIONS",
    "BENEFICIARY_CLASSES", "BENEFICIARY_RELATION_CLASSES", "BENEFICIARY_STATUSES",
    "DISTRIBUTION_STATUSES", "DISTRIBUTION_TIERS", "DISTRIBUTION_TYPES",
    "GRANTOR_TAX_STATUSES",
    "K1_STATUSES",
    "TAX_YEAR_STATUSES",
    "TRUST_STATUSES", "TRUST_TYPES",
    "TXN_TYPES",
    "PRINCIPAL_OR_INCOME",
]
