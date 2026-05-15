"""Referee service."""
from __future__ import annotations

from typing import Any, Optional

from ..clock import parse_iso
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store


VALID_LEVELS = {"L1": 1, "L2": 2, "L3": 3}


def _require_referee(rfid: str) -> dict[str, Any]:
    r = get_store().referees.get(rfid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", f"Referee {rfid} not found.")
    return r


def create_referee(body: dict[str, Any]) -> dict[str, Any]:
    for k in ("user_id", "full_name", "certification_level", "certification_expiry"):
        if k not in body:
            raise ApiError("ERR_BAD_REQUEST", f"Missing field: {k}")
    if body["certification_level"] not in VALID_LEVELS:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid certification_level: {body['certification_level']}")
    # Validate expiry
    parse_iso(body["certification_expiry"])
    r = common_fields_create()
    r.update({
        "user_id": body["user_id"],
        "full_name": body["full_name"],
        "certification_level": body["certification_level"],
        "certification_expiry": body["certification_expiry"],
        "status": "ACTIVE",
    })
    get_store().referees[r["id"]] = r
    return dict(r)


def get_referee(rfid: str) -> dict[str, Any]:
    return dict(_require_referee(rfid))


def patch_referee(rfid: str, body: dict[str, Any]) -> dict[str, Any]:
    r = _require_referee(rfid)
    if "version" in body:
        if int(body["version"]) != int(r["version"]):
            raise ApiError("ERR_VERSION_CONFLICT",
                           f"Version mismatch: provided {body['version']}, current {r['version']}.")
    if "status" in body:
        if body["status"] not in {"ACTIVE", "SUSPENDED"}:
            raise ApiError("ERR_BAD_REQUEST", f"Invalid status: {body['status']}")
        r["status"] = body["status"]
    if "certification_level" in body:
        if body["certification_level"] not in VALID_LEVELS:
            raise ApiError("ERR_BAD_REQUEST", f"Invalid certification_level: {body['certification_level']}")
        r["certification_level"] = body["certification_level"]
    if "certification_expiry" in body:
        parse_iso(body["certification_expiry"])  # validate format
        r["certification_expiry"] = body["certification_expiry"]
    bump_version(r)
    return dict(r)


def referee_by_user_id(user_id: str) -> Optional[dict[str, Any]]:
    for r in get_store().referees.values():
        if r.get("user_id") == user_id:
            return r
    return None
