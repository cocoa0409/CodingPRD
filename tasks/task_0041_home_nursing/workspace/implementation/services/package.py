"""Package logic."""
import db
from clock import parse_iso, iso
from errors import err
from services.util import require_str, require_int


def create_package(body: dict) -> dict:
    patient_id = require_str(body, "patient_id")
    code = require_str(body, "service_item_code")
    total_credits = require_int(body, "total_credits")
    if total_credits <= 0:
        raise err("ERR_INVALID_REQUEST", "total_credits must be > 0")
    expires_at_raw = require_str(body, "expires_at")
    try:
        expires_at_dt = parse_iso(expires_at_raw)
    except ValueError as e:
        raise err("ERR_INVALID_REQUEST", str(e))

    # service item existence is required for clean linkage
    if code not in db.service_items:
        raise err("ERR_RESOURCE_LINK_INVALID", "service_item_code does not exist")

    pkg = {
        "patient_id": patient_id,
        "service_item_code": code,
        "total_credits": total_credits,
        "used_credits": 0,
        "expires_at": iso(expires_at_dt),
        "status": "ACTIVE",
    }
    db.stamp_create(pkg, common_fields=True)
    db.packages[pkg["id"]] = pkg
    return pkg


def list_packages_for_patient(patient_id: str, limit: int, offset: int):
    rows = [p for p in db.packages.values() if p.get("patient_id") == patient_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total


def list_all_packages(limit: int, offset: int):
    rows = list(db.packages.values())
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total


def get_package(package_id: str) -> dict:
    pkg = db.packages.get(package_id)
    if pkg is None:
        raise err("ERR_PACKAGE_NOT_FOUND", f"package {package_id} not found")
    return pkg
