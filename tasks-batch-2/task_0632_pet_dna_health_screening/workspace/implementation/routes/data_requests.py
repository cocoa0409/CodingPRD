"""Data export / deletion request routes (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import clock, parse_iso8601, format_iso8601
from db import db, create_versioned, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_PURGE_IN_PROGRESS,
    ERR_GRACE_NOT_ELAPSED,
)
from helpers import (
    get_json_body, require_fields, require_enum, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import (
    serialize_data_request, serialize_pet, serialize_report,
    serialize_relative_match,
)
from services.common import get_or_404, require_account_owner
from services.cascades import purge_finalize_cascade

GRACE_DAYS = 30

data_requests_bp = Blueprint("data_requests", __name__)


def _assemble_export_payload(account_id):
    """Bundle of the account's pets, reports, and matches (PRD §3.8)."""
    pets = [p for p in db.pets.values() if p["account_id"] == account_id]
    pet_ids = {p["id"] for p in pets}
    reports = [r for r in db.reports.values() if r["pet_id"] in pet_ids]
    matches = [
        m for m in db.relative_matches.values()
        if m["pet_id"] in pet_ids or m["relative_pet_id"] in pet_ids
    ]
    return {
        "pets": [serialize_pet(p) for p in sorted(pets, key=lambda x: (x["created_at"], x["_seq"]))],
        "reports": [serialize_report(r) for r in sorted(reports, key=lambda x: (x["created_at"], x["_seq"]))],
        "matches": [serialize_relative_match(m) for m in sorted(matches, key=lambda x: (x["created_at"], x["_seq"]))],
    }


@data_requests_bp.route("/dna/data-requests", methods=["POST"])
def create_data_request():
    user_id, role = require_roles({"Account"})
    body = get_json_body()
    require_fields(body, ["account_id", "kind"])

    account = get_or_404(db.accounts, body["account_id"])
    require_account_owner(account["id"], user_id, role)
    require_enum(body["kind"], {"DOWNLOAD", "DELETE"}, "kind")

    kind = body["kind"]

    if kind == "DOWNLOAD":
        # PENDING auto-advances to READY; assemble export_payload; grace null.
        rec = create_versioned(db.data_requests, {
            "account_id": account["id"],
            "kind": "DOWNLOAD",
            "status": "READY",
            "grace_until": None,
            "export_payload": _assemble_export_payload(account["id"]),
        })
        return success(serialize_data_request(rec), status=201)

    # DELETE: only when no other DataRequest for this account in {GRACE, PURGING}.
    for dr in db.data_requests.values():
        if dr["account_id"] == account["id"] and dr["status"] in ("GRACE", "PURGING"):
            raise err(ERR_PURGE_IN_PROGRESS,
                      "Another deletion request is already in progress")

    grace_until = format_iso8601(clock.now() + timedelta(days=GRACE_DAYS))
    rec = create_versioned(db.data_requests, {
        "account_id": account["id"],
        "kind": "DELETE",
        "status": "GRACE",
        "grace_until": grace_until,
        "export_payload": None,
    })
    # account.purge_pending is derived from DELETE requests in GRACE/PURGING.
    return success(serialize_data_request(rec), status=201)


@data_requests_bp.route("/dna/data-requests/<rid>", methods=["GET"])
def get_data_request(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    rec = get_or_404(db.data_requests, rid)
    require_account_owner(rec["account_id"], user_id, role)
    return success(serialize_data_request(rec), status=200)


@data_requests_bp.route("/dna/data-requests", methods=["GET"])
def list_data_requests():
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")

    items = list(db.data_requests.values())
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    if role == "Account":
        items = [d for d in items if d["account_id"] == user_id]

    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_data_request(d) for d in window], limit, offset, total
    )


@data_requests_bp.route("/dna/data-requests/<rid>/purge", methods=["POST"])
def purge_data_request(rid):
    require_roles({"PlatformAdmin"})
    rec = get_or_404(db.data_requests, rid)

    # GRACE -> PURGING.
    if rec["status"] != "GRACE":
        raise err(ERR_INVALID_STATE, "Data request is not in GRACE state")

    # Temporal: clock >= grace_until (priority 12).
    if rec["grace_until"] is None or clock.now() < parse_iso8601(rec["grace_until"]):
        raise err(ERR_GRACE_NOT_ELAPSED, "Grace window has not yet elapsed")

    rec["status"] = "PURGING"
    touch(rec)
    return success(serialize_data_request(rec), status=200)


@data_requests_bp.route("/dna/data-requests/<rid>/purge-finalize", methods=["POST"])
def purge_finalize_data_request(rid):
    require_roles({"PlatformAdmin"})
    rec = get_or_404(db.data_requests, rid)

    # PURGING -> PURGED.
    if rec["status"] != "PURGING":
        raise err(ERR_INVALID_STATE, "Data request is not in PURGING state")

    # Irreversible cascade.
    purge_finalize_cascade(rec["account_id"])

    rec["status"] = "PURGED"
    touch(rec)
    # account.purge_pending derived -> becomes false (no DELETE in GRACE/PURGING).
    return success(serialize_data_request(rec), status=200)


@data_requests_bp.route("/dna/data-requests/<rid>/cancel", methods=["POST"])
def cancel_data_request(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.data_requests, rid)
    require_account_owner(rec["account_id"], user_id, role)

    # GRACE -> CANCELLED (account may always rescind during cool-off).
    if rec["status"] != "GRACE":
        raise err(ERR_INVALID_STATE, "Only a GRACE data request may be cancelled")

    rec["status"] = "CANCELLED"
    touch(rec)
    # account.purge_pending derived -> false.
    return success(serialize_data_request(rec), status=200)
