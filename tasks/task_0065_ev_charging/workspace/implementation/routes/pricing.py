"""Pricing version and promo activity endpoints."""

from flask import Blueprint, request

import db
from clock import parse_iso
from errors import raise_error
from middleware import require_roles
from response import paginated, success
from validators import (
    HHMM_COLON_RE,
    HHMM_RE,
    get_pagination,
    paginate_list,
    parse_json_body,
    require_enum,
    require_int,
    require_str,
)


bp = Blueprint("pricing", __name__)

VALID_TIERS = {"BASIC", "SILVER", "GOLD", "PLATINUM"}


def _hhmm_to_minutes(value: str) -> int:
    if HHMM_RE.match(value):
        return int(value[:2]) * 60 + int(value[2:])
    if HHMM_COLON_RE.match(value):
        return int(value[:2]) * 60 + int(value[3:])
    raise_error("ERR_VALIDATION", "hhmm must be a 24-hour HHMM or HH:MM string")


def _validate_windows(windows: list, label: str) -> list[tuple[int, int]]:
    if not isinstance(windows, list):
        raise_error("ERR_VALIDATION", f"{label} must be an array")
    if len(windows) > 6:
        raise_error("ERR_VALIDATION", f"{label} has too many entries")
    parsed: list[tuple[int, int]] = []
    for w in windows:
        if not isinstance(w, dict):
            raise_error("ERR_VALIDATION", f"{label} entry must be object")
        s = w.get("start_hhmm")
        e = w.get("end_hhmm")
        if not isinstance(s, str) or not isinstance(e, str):
            raise_error("ERR_VALIDATION", f"{label} entry missing start_hhmm/end_hhmm")
        sm = _hhmm_to_minutes(s)
        em = _hhmm_to_minutes(e)
        if not (sm < em):
            raise_error("ERR_VALIDATION", f"{label} entry start must be < end")
        parsed.append((sm, em))
    return parsed


def _intervals_overlap(intervals_a: list[tuple[int, int]], intervals_b: list[tuple[int, int]]) -> bool:
    for s1, e1 in intervals_a:
        for s2, e2 in intervals_b:
            if s1 < e2 and s2 < e1:
                return True
    return False


def _self_overlap(intervals: list[tuple[int, int]]) -> bool:
    sorted_iv = sorted(intervals)
    for i in range(1, len(sorted_iv)):
        if sorted_iv[i][0] < sorted_iv[i - 1][1]:
            return True
    return False


@bp.post("/pricing-versions")
@require_roles({"PlatformOperator"})
def create_pricing_version():
    body = parse_json_body()
    operator_id = require_str(body, "operator_id")
    if operator_id not in db.operators:
        raise_error("ERR_NOT_FOUND", "operator_id not found")
    version_label = require_str(body, "version_label", 1, 40)
    effective_from = require_str(body, "effective_from")
    effective_to = require_str(body, "effective_to")
    try:
        ef = parse_iso(effective_from)
        et = parse_iso(effective_to)
    except Exception:
        raise_error("ERR_VALIDATION", "effective_from/to must be ISO 8601")
    if not (et > ef):
        raise_error("ERR_VALIDATION", "effective_to must be > effective_from")

    peak_rate = require_int(body, "peak_rate_per_kwh_cents", 1)
    flat_rate = require_int(body, "flat_rate_per_kwh_cents", 1)
    valley_rate = require_int(body, "valley_rate_per_kwh_cents", 1)
    service_fee_rate = require_int(body, "service_fee_per_kwh_cents", 0)
    tax_bps = require_int(body, "tax_bps", 0, 5000)

    peak_windows = body.get("peak_windows", [])
    valley_windows = body.get("valley_windows", [])
    peak_iv = _validate_windows(peak_windows, "peak_windows")
    valley_iv = _validate_windows(valley_windows, "valley_windows")

    # Check internal self-overlap within peak / valley sets.
    if _self_overlap(peak_iv) or _self_overlap(valley_iv):
        raise_error("ERR_TOU_WINDOWS_OVERLAP", "windows overlap themselves")
    # Cross overlap between peak and valley.
    if _intervals_overlap(peak_iv, valley_iv):
        raise_error("ERR_TOU_WINDOWS_OVERLAP", "peak/valley windows overlap")

    tier_disc = body.get("tier_service_fee_discount_bps", {})
    if not isinstance(tier_disc, dict):
        raise_error("ERR_VALIDATION", "tier_service_fee_discount_bps must be object")
    for k, v in tier_disc.items():
        if k not in VALID_TIERS:
            raise_error("ERR_VALIDATION", f"unknown tier in discount map: {k}")
        if not isinstance(v, int) or isinstance(v, bool):
            raise_error("ERR_VALIDATION", "tier discount must be integer bps")
        if v < 0 or v > 5000:
            raise_error("ERR_VALIDATION", "tier discount out of range")

    # Uniqueness on version_label within operator_id.
    for existing in db.pricing_versions.values():
        if existing["operator_id"] == operator_id and existing["version_label"] == version_label:
            raise_error("ERR_VALIDATION", "version_label not unique within operator")

    # Window-overlap check against other pricing versions for same operator.
    for existing in db.pricing_versions.values():
        if existing["operator_id"] != operator_id:
            continue
        ef2 = parse_iso(existing["effective_from"])
        et2 = parse_iso(existing["effective_to"])
        if ef < et2 and ef2 < et:
            raise_error("ERR_PRICING_WINDOW_OVERLAP", "pricing window overlaps existing")

    record = {
        "operator_id": operator_id,
        "version_label": version_label,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "peak_rate_per_kwh_cents": peak_rate,
        "flat_rate_per_kwh_cents": flat_rate,
        "valley_rate_per_kwh_cents": valley_rate,
        "service_fee_per_kwh_cents": service_fee_rate,
        "tax_bps": tax_bps,
        "peak_windows": peak_windows,
        "valley_windows": valley_windows,
        "tier_service_fee_discount_bps": tier_disc,
    }
    db.append_only_record(record)
    db.pricing_versions[record["id"]] = record
    return success(db.public(record), status=201)


@bp.get("/pricing-versions")
@require_roles({"PlatformOperator", "StationOwner", "CustomerService"})
def list_pricing_versions():
    operator_id = request.args.get("operator_id")
    active_at = request.args.get("active_at")
    limit, offset = get_pagination()

    items = sorted(db.pricing_versions.values(), key=lambda r: r["_seq"])
    if operator_id:
        items = [pv for pv in items if pv["operator_id"] == operator_id]
    if active_at:
        try:
            instant = parse_iso(active_at)
        except Exception:
            raise_error("ERR_VALIDATION", "active_at must be ISO 8601")
        items = [
            pv for pv in items
            if parse_iso(pv["effective_from"]) <= instant < parse_iso(pv["effective_to"])
        ]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)


@bp.post("/promo-activities")
@require_roles({"PlatformOperator"})
def create_promo():
    body = parse_json_body()
    operator_id = require_str(body, "operator_id")
    if operator_id not in db.operators:
        raise_error("ERR_NOT_FOUND", "operator_id not found")
    name = require_str(body, "name", 1, 80)
    starts_at = require_str(body, "starts_at")
    ends_at = require_str(body, "ends_at")
    try:
        s = parse_iso(starts_at)
        e = parse_iso(ends_at)
    except Exception:
        raise_error("ERR_VALIDATION", "starts_at/ends_at must be ISO 8601")
    if not (e > s):
        raise_error("ERR_VALIDATION", "ends_at must be > starts_at")
    discount = require_int(body, "service_fee_discount_bps", 0, 5000)
    tiers = body.get("applies_to_tiers")
    if not isinstance(tiers, list) or not tiers:
        raise_error("ERR_VALIDATION", "applies_to_tiers must be non-empty list")
    for t in tiers:
        if t not in VALID_TIERS:
            raise_error("ERR_VALIDATION", f"applies_to_tiers contains invalid tier {t}")

    record = {
        "operator_id": operator_id,
        "name": name,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "service_fee_discount_bps": discount,
        "applies_to_tiers": tiers,
    }
    db.append_only_record(record)
    db.promo_activities[record["id"]] = record
    return success(db.public(record), status=201)


@bp.get("/promo-activities")
@require_roles({"PlatformOperator", "StationOwner", "EVDriver"})
def list_promos():
    operator_id = request.args.get("operator_id")
    active_at = request.args.get("active_at")
    limit, offset = get_pagination()
    items = sorted(db.promo_activities.values(), key=lambda r: r["_seq"])
    if operator_id:
        items = [p for p in items if p["operator_id"] == operator_id]
    if active_at:
        try:
            instant = parse_iso(active_at)
        except Exception:
            raise_error("ERR_VALIDATION", "active_at must be ISO 8601")
        items = [
            p for p in items
            if parse_iso(p["starts_at"]) <= instant < parse_iso(p["ends_at"])
        ]
    page, total = paginate_list(items, limit, offset)
    return paginated(db.public_list(page), limit, offset, total)
