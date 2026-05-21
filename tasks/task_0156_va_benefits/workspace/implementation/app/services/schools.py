"""School registration."""
from __future__ import annotations

import re
from decimal import Decimal

from ..clock import Clock
from ..errors import ApiError
from ..store import Store
from ..util import money, new_id

VALID_PROGRAM = {"PUBLIC_IN_STATE", "PRIVATE_NATIONAL", "FOREIGN", "VOC_TECH"}
ZIP_RE = re.compile(r"^\d{5}$")


def _now_iso(store: Store) -> str:
    return Clock.format(store.clock.now())


def create_school(store: Store, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    name = body.get("name")
    facility_code = body.get("facility_code")
    program_type = body.get("program_type")
    yr_enrolled = body.get("yellow_ribbon_enrolled", False)
    yr_max = body.get("yellow_ribbon_max_per_year", 0.00)
    zip_code = body.get("zip_bah_code")

    if not isinstance(name, str) or not (1 <= len(name) <= 200):
        raise ApiError("ERR_INVALID_BODY", "name must be 1..200 chars")
    if not isinstance(facility_code, str) or len(facility_code) != 8:
        raise ApiError("ERR_INVALID_BODY", "facility_code must be 8 chars")
    if program_type not in VALID_PROGRAM:
        raise ApiError("ERR_INVALID_BODY", "invalid program_type")
    if not isinstance(yr_enrolled, bool):
        raise ApiError("ERR_INVALID_BODY", "yellow_ribbon_enrolled must be boolean")
    if yr_enrolled:
        if yr_max is None:
            raise ApiError("ERR_INVALID_BODY", "yellow_ribbon_max_per_year required when enrolled")
    if yr_max is not None:
        if isinstance(yr_max, bool) or not isinstance(yr_max, (int, float)):
            raise ApiError("ERR_INVALID_BODY", "yellow_ribbon_max_per_year must be number")
        if yr_max < 0:
            raise ApiError("ERR_INVALID_BODY", "yellow_ribbon_max_per_year must be >= 0")
    if not isinstance(zip_code, str) or not ZIP_RE.match(zip_code):
        raise ApiError("ERR_INVALID_BODY", "zip_bah_code must be 5 digits")

    # Uniqueness of facility_code.
    store.reserve_facility_code(facility_code)

    now = _now_iso(store)
    sid = new_id()
    school = {
        "id": sid,
        "name": name,
        "facility_code": facility_code,
        "program_type": program_type,
        "yellow_ribbon_enrolled": yr_enrolled,
        "yellow_ribbon_max_per_year": money(yr_max) if yr_max is not None else Decimal("0.00"),
        "zip_bah_code": zip_code,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.schools[sid] = school
    return school
