"""Shared route helpers — input validation, OCC, lookups."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, Optional

from flask import request

from ..errors import APIError, err_invalid_input, err_not_found, err_version_conflict
from ..store import store


def get_json() -> Dict[str, Any]:
    try:
        data = request.get_json(silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_input("Request body must be a JSON object")
    return data


def require_field(body: Dict[str, Any], field: str) -> Any:
    if field not in body or body[field] is None:
        raise err_invalid_input(f"Missing required field '{field}'")
    return body[field]


def require_string(body: Dict[str, Any], field: str, *, allow_empty: bool = False) -> str:
    v = require_field(body, field)
    if not isinstance(v, str):
        raise err_invalid_input(f"Field '{field}' must be a string")
    if not allow_empty and v == "":
        raise err_invalid_input(f"Field '{field}' must be non-empty")
    return v


def require_int(body: Dict[str, Any], field: str, *, min_value: Optional[int] = None,
                max_value: Optional[int] = None) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_input(f"Field '{field}' must be an integer")
    if min_value is not None and v < min_value:
        raise err_invalid_input(f"Field '{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err_invalid_input(f"Field '{field}' must be <= {max_value}")
    return v


def require_number(body: Dict[str, Any], field: str, *, min_value: Optional[float] = None,
                   max_value: Optional[float] = None, strict_min: bool = False) -> float:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_input(f"Field '{field}' must be a number")
    if min_value is not None:
        if strict_min and v <= min_value:
            raise err_invalid_input(f"Field '{field}' must be > {min_value}")
        if not strict_min and v < min_value:
            raise err_invalid_input(f"Field '{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err_invalid_input(f"Field '{field}' must be <= {max_value}")
    return float(v)


def optional_string(body: Dict[str, Any], field: str) -> Optional[str]:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise err_invalid_input(f"Field '{field}' must be a string if provided")
    return v


def optional_bool(body: Dict[str, Any], field: str) -> Optional[bool]:
    if field not in body:
        return None
    v = body[field]
    if v is None:
        return None
    if not isinstance(v, bool):
        raise err_invalid_input(f"Field '{field}' must be a boolean")
    return v


def optional_int(body: Dict[str, Any], field: str, *, min_value: Optional[int] = None,
                 max_value: Optional[int] = None) -> Optional[int]:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_input(f"Field '{field}' must be an integer if provided")
    if min_value is not None and v < min_value:
        raise err_invalid_input(f"Field '{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err_invalid_input(f"Field '{field}' must be <= {max_value}")
    return v


def optional_number(body: Dict[str, Any], field: str, *, min_value: Optional[float] = None,
                    max_value: Optional[float] = None) -> Optional[float]:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_input(f"Field '{field}' must be a number if provided")
    if min_value is not None and v < min_value:
        raise err_invalid_input(f"Field '{field}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err_invalid_input(f"Field '{field}' must be <= {max_value}")
    return float(v)


def check_version(entity: Dict[str, Any], body: Dict[str, Any]) -> None:
    """If body carries 'version', enforce OCC; else skip the check."""
    if "version" not in body or body["version"] is None:
        return
    v = body["version"]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_input("Field 'version' must be an integer")
    if v != entity["version"]:
        raise err_version_conflict()


# ---- Resource lookups ----

def get_grid_or_404(grid_id: str) -> Dict[str, Any]:
    g = store().grids.get(grid_id)
    if not g:
        raise err_not_found("Grid not found")
    return g


def get_grid_by_code(code: str) -> Optional[Dict[str, Any]]:
    s = store()
    gid = s.grid_code_index.get(code)
    if not gid:
        return None
    return s.grids.get(gid)


def get_driver_or_404(driver_id: str) -> Dict[str, Any]:
    d = store().drivers.get(driver_id)
    if not d:
        raise err_not_found("Driver not found")
    return d


def get_rider_or_404(rider_id: str) -> Dict[str, Any]:
    r = store().riders.get(rider_id)
    if not r:
        raise err_not_found("Rider not found")
    return r


def get_ride_or_404(ride_id: str) -> Dict[str, Any]:
    r = store().rides.get(ride_id)
    if not r:
        raise err_not_found("Ride not found")
    return r


def get_dispute_or_404(dispute_id: str) -> Dict[str, Any]:
    d = store().disputes.get(dispute_id)
    if not d:
        raise err_not_found("Dispute not found")
    return d


def get_quest_or_404(quest_id: str) -> Dict[str, Any]:
    q = store().quest_bonuses.get(quest_id)
    if not q:
        raise err_not_found("Quest bonus not found")
    return q


def get_rush_hour_or_404(window_id: str) -> Dict[str, Any]:
    w = store().rush_hour_windows.get(window_id)
    if not w:
        raise err_not_found("Rush-hour window not found")
    return w


GRID_CODE_PATTERN = re.compile(r"^G-[0-9]{3}$")
DAY_OF_WEEK_VALUES = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
REASON_CODES = {"OVERCHARGE", "DRIVER_NO_SHOW", "ROUTE_DEVIATION", "OTHER"}


def filter_by_status(items, status_value):
    if status_value is None:
        return items
    return [x for x in items if x.get("status") == status_value]
