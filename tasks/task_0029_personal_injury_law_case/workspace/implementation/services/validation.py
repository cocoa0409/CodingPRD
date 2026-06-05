"""Shared validation helpers (PRD §2.9 priority order)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from decimal import Decimal, InvalidOperation

from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_FK_NOT_FOUND,
    ERR_STATUTE_EXPIRED,
)

import db
from services.calculations import STATUTE_YEARS


# ---- generic input shape (priority 20 ERR_INVALID_REQUEST) ------------------

def require_field(body: dict, name: str) -> Any:
    if name not in body:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return body[name]


def require_str(body: dict, name: str) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a non-empty string")
    return v


def require_int(body: dict, name: str, min_value: Optional[int] = None,
                max_value: Optional[int] = None) -> int:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    if min_value is not None and v < min_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be <= {max_value}")
    return v


def require_enum(body: dict, name: str, allowed: set) -> str:
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_iso8601(body: dict, name: str) -> str:
    v = require_field(body, name)
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an ISO 8601 string")
    try:
        db.parse_iso_dt(v)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} is not a valid ISO 8601 datetime")
    return v


def require_decimal_range(body: dict, name: str, min_value, max_value) -> Decimal:
    v = require_field(body, name)
    if isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a number")
    if isinstance(v, (int, float)):
        d = Decimal(str(v))
    elif isinstance(v, str):
        try:
            d = Decimal(v)
        except (InvalidOperation, ValueError):
            raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} is not a number")
    else:
        raise APIError(ERR_INVALID_REQUEST, 400, f"Field {name} must be numeric")
    if d < Decimal(str(min_value)) or d > Decimal(str(max_value)):
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"Field {name} must be between {min_value} and {max_value}")
    return d


# ---- existence checks (priorities 3-4) --------------------------------------

def get_or_404_path(store: Dict[str, Any], rid: str, kind: str) -> Dict[str, Any]:
    """Resolve a path {id} segment; ERR_RESOURCE_NOT_FOUND (404) if missing."""
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


def get_or_fk_404(store: Dict[str, Any], rid: str, kind: str) -> Dict[str, Any]:
    """Resolve a body FK; ERR_FK_NOT_FOUND (404) if missing."""
    if not isinstance(rid, str) or rid == "":
        raise APIError(ERR_FK_NOT_FOUND, 404, f"{kind} FK is missing or malformed")
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


# ---- Statute of limitations (priority 7 ERR_STATUTE_EXPIRED) ----------------

def effective_sol_dt(case: Dict[str, Any]) -> datetime:
    """accident_date + STATUTE_YEARS[jurisdiction] + sol_tolled_days."""
    accident = db.parse_iso_dt(case["accident_date"])
    years = STATUTE_YEARS[case["jurisdiction"]]
    # naive year offset — replace year on accident date
    try:
        sol = accident.replace(year=accident.year + years)
    except ValueError:
        # Feb 29 -> Feb 28
        sol = accident.replace(month=2, day=28, year=accident.year + years)
    sol = sol + timedelta(days=int(case.get("sol_tolled_days", 0)))
    return sol


def assert_sol_not_expired(case: Dict[str, Any]) -> None:
    """Raise ERR_STATUTE_EXPIRED if current_utc >= effective SOL.

    Boundary is closed on the EXPIRED side per PRD §2.6: at the exact instant
    the clock equals the effective SOL date, the statute has run.
    """
    sol = effective_sol_dt(case)
    now = db.current_clock_dt()
    if now >= sol:
        raise APIError(ERR_STATUTE_EXPIRED, 422, "Statute of limitations has run for this case")


def sol_iso(case: Dict[str, Any]) -> str:
    """Return the (un-tolled) statute_of_limitations_date as ISO 8601 UTC.

    Per scaffold entity table, statute_of_limitations_date stores
    accident_date + STATUTE_YEARS[jurisdiction] (the tolled days are added at
    comparison time, not baked into this stored value). PRD §3.1 phrases it
    as "the statute date" with "tolling number added on top in days" — we
    persist the base SOL and apply tolling at guard time.
    """
    accident = db.parse_iso_dt(case["accident_date"])
    years = STATUTE_YEARS[case["jurisdiction"]]
    try:
        sol = accident.replace(year=accident.year + years)
    except ValueError:
        sol = accident.replace(month=2, day=28, year=accident.year + years)
    return db.to_iso_z(sol)
