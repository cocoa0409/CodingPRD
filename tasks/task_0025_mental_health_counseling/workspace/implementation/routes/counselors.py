"""Counselor endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination, get_user
from response import success, success_list
from services import audit
from services.cascades import disqualify_counselor
from services.validation import (
    get_body, require_str, require_field, optional_str, check_version,
    validate_email, validate_specialty_tags, validate_supported_channels,
    SPECIALTY_TAGS, CHANNELS,
)


bp = Blueprint("counselors", __name__)


def _counselor_public(c: dict) -> dict:
    return db.public(c)


def _open_first_cycle(counselor: dict):
    cyc = {
        "counselor_id": counselor["id"],
        "cycle_index": 1,
        "required_supervision_hours": 40,
        "required_ce_hours": 12,
        "window_start_at": counselor["created_at"],
        "window_end_at": iso(parse_iso(counselor["created_at"]) + timedelta(days=365)),
        "status": "OPEN",
        "decided_at": None,
        "decided_by_user_id": None,
    }
    db.stamp_create(cyc, common_fields=True)
    db.certification_cycles[cyc["id"]] = cyc
    return cyc


@bp.route("/counseling/counselors", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_counselor():
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    license_number = require_str(body, "license_number")
    license_expires_at = require_str(body, "license_expires_at")
    specialty_tags = require_field(body, "specialty_tags")
    supported_channels = require_field(body, "supported_channels")
    timezone = require_str(body, "timezone")
    revenue_share_bps = body.get("revenue_share_bps", 7000)

    validate_email(email)
    validate_specialty_tags(specialty_tags)
    validate_supported_channels(supported_channels)
    try:
        parse_iso(license_expires_at)
    except ValueError:
        raise err("ERR_VALIDATION", "license_expires_at must be ISO 8601")

    if isinstance(revenue_share_bps, bool) or not isinstance(revenue_share_bps, int):
        raise err("ERR_VALIDATION", "revenue_share_bps must be an integer")
    if revenue_share_bps < 0 or revenue_share_bps > 10000:
        raise err("ERR_VALIDATION", "revenue_share_bps must be in [0, 10000]")

    # Uniqueness of email (lowercase)
    for c in db.counselors.values():
        if c["email"] == email:
            raise err("ERR_VALIDATION", f"email already in use")
    # Uniqueness of license_number among non-DISQUALIFIED counselors
    for c in db.counselors.values():
        if c["license_number"] == license_number and c["status"] != "DISQUALIFIED":
            raise err("ERR_VALIDATION", f"license_number already in use")

    # Validate timezone
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(timezone)
    except Exception:
        raise err("ERR_VALIDATION", "timezone must be a valid IANA timezone")

    counselor = {
        "full_name": full_name,
        "email": email,
        "license_number": license_number,
        "license_expires_at": license_expires_at,
        "specialty_tags": list(specialty_tags),
        "supported_channels": list(supported_channels),
        "timezone": timezone,
        "status": "PENDING_CERT",
        "revenue_share_bps": int(revenue_share_bps),
        "total_supervision_hours": 0,
        "total_ce_hours": 0,
    }
    db.stamp_create(counselor, common_fields=True)
    db.counselors[counselor["id"]] = counselor

    _open_first_cycle(counselor)

    return success(_counselor_public(counselor), 201)


@bp.route("/counseling/counselors", methods=["GET"])
def list_counselors():
    user_id, role = get_user(allow_public=True)
    if role not in {"Public", "Client", "Counselor", "Supervisor", "PlatformAdmin"}:
        raise err("ERR_FORBIDDEN", "Role not authorized")

    limit, offset = get_pagination()
    specialty_tag = request.args.get("specialty_tag")
    channel = request.args.get("channel")
    timezone = request.args.get("timezone")

    items = []
    for c in db.counselors.values():
        if c["status"] != "ACTIVE":
            continue
        if specialty_tag and specialty_tag not in (c.get("specialty_tags") or []):
            continue
        if channel and channel not in (c.get("supported_channels") or []):
            continue
        if timezone and c.get("timezone") != timezone:
            continue
        items.append(c)
    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_counselor_public(c) for c in page], limit, offset, total)


@bp.route("/counseling/counselors/<id>", methods=["GET"])
def get_counselor(id):
    user_id, role = get_user(allow_public=True)
    if role not in {"Public", "Client", "Counselor", "Supervisor", "PlatformAdmin"}:
        raise err("ERR_FORBIDDEN", "Role not authorized")
    c = db.counselors.get(id)
    if c is None:
        raise err("ERR_NOT_FOUND", f"Counselor {id} not found")
    return success(_counselor_public(c))


@bp.route("/counseling/counselors/<id>", methods=["PATCH"])
@require_auth(roles={"Counselor", "PlatformAdmin"})
def patch_counselor(id):
    c = db.counselors.get(id)
    if c is None:
        raise err("ERR_NOT_FOUND", f"Counselor {id} not found")
    if g.user_role == "Counselor" and g.user_id != id:
        raise err("ERR_FORBIDDEN", "Counselor may only edit own profile")

    body = get_body()
    check_version(c, body)

    if "specialty_tags" in body and body["specialty_tags"] is not None:
        validate_specialty_tags(body["specialty_tags"])
        c["specialty_tags"] = list(body["specialty_tags"])
    if "supported_channels" in body and body["supported_channels"] is not None:
        validate_supported_channels(body["supported_channels"])
        c["supported_channels"] = list(body["supported_channels"])
    if "timezone" in body and body["timezone"] is not None:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(body["timezone"])
        except Exception:
            raise err("ERR_VALIDATION", "timezone must be a valid IANA timezone")
        c["timezone"] = body["timezone"]
    if "license_expires_at" in body and body["license_expires_at"] is not None:
        try:
            parse_iso(body["license_expires_at"])
        except ValueError:
            raise err("ERR_VALIDATION", "license_expires_at must be ISO 8601")
        c["license_expires_at"] = body["license_expires_at"]

    db.stamp_update(c)
    return success(_counselor_public(c))


@bp.route("/counseling/counselors/<id>/disqualify", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def post_disqualify(id):
    c = db.counselors.get(id)
    if c is None:
        raise err("ERR_NOT_FOUND", f"Counselor {id} not found")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot disqualify counselor in status {c['status']}")
    body = get_body()
    reason = optional_str(body, "reason")
    disqualify_counselor(c, g.user_role, g.user_id, reason=reason)
    return success(_counselor_public(c))
