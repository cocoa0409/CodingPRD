"""Share link routes including the public token view (PRD §3.5)."""
import uuid

from flask import Blueprint, request

from db import db, create_versioned, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_INVALID_TOKEN,
)
from helpers import (
    get_json_body, require_fields, parse_pagination, paginate,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_share_link, serialize_report
from services.common import (
    get_or_404, require_account_owner, assert_not_purge_pending,
)

share_links_bp = Blueprint("share_links", __name__)


def _mint_token():
    return "shr_" + uuid.uuid4().hex


def _report_owner_account_id(report):
    pet = db.pets.get(report["pet_id"])
    return pet["account_id"] if pet else None


@share_links_bp.route("/dna/share-links", methods=["POST"])
def create_share_link():
    user_id, role = require_roles({"Account"})
    body = get_json_body()
    require_fields(body, ["report_id", "vet_email"])

    report = get_or_404(db.reports, body["report_id"])
    owner_account = _report_owner_account_id(report)
    require_account_owner(owner_account, user_id, role)

    # purge-in-progress freeze: issuing a share link is blocked (priority 8).
    assert_not_purge_pending(owner_account)

    rec = create_versioned(db.share_links, {
        "report_id": report["id"],
        "vet_email": body["vet_email"],
        "token": _mint_token(),
        "status": "ACTIVE",
    })
    return success(serialize_share_link(rec), status=201)


@share_links_bp.route("/dna/share-links/<rid>", methods=["GET"])
def get_share_link(rid):
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    rec = get_or_404(db.share_links, rid)
    if role == "Account":
        report = db.reports.get(rec["report_id"])
        owner = _report_owner_account_id(report) if report else None
        require_account_owner(owner, user_id, role)
    return success(serialize_share_link(rec), status=200)


@share_links_bp.route("/dna/share-links", methods=["GET"])
def list_share_links():
    user_id, role = require_roles({"PlatformAdmin", "Account"})
    limit, offset = parse_pagination()
    report_id = request.args.get("report_id")

    items = list(db.share_links.values())
    if report_id is not None:
        items = [s for s in items if s["report_id"] == report_id]
    if role == "Account":
        owned_pet_ids = {p["id"] for p in db.pets.values() if p["account_id"] == user_id}
        owned_report_ids = {r["id"] for r in db.reports.values()
                            if r["pet_id"] in owned_pet_ids}
        items = [s for s in items if s["report_id"] in owned_report_ids]

    window, total = paginate(items, limit, offset)
    return list_success(
        [serialize_share_link(s) for s in window], limit, offset, total
    )


@share_links_bp.route("/dna/shared-reports/<token>", methods=["GET"])
def get_shared_report(token):
    # Public token view: no auth headers required (PRD §2.1).
    link = None
    for sl in db.share_links.values():
        if sl["token"] == token:
            link = sl
            break
    # Token not found, or link REVOKED -> ERR_INVALID_TOKEN.
    if link is None or link["status"] != "ACTIVE":
        raise err(ERR_INVALID_TOKEN, "Share token not found or revoked")

    report = db.reports.get(link["report_id"])
    if report is None:
        raise err(ERR_INVALID_TOKEN, "Shared report not found")
    return success(serialize_report(report), status=200)


@share_links_bp.route("/dna/share-links/<rid>/revoke", methods=["POST"])
def revoke_share_link(rid):
    user_id, role = require_roles({"Account"})
    rec = get_or_404(db.share_links, rid)

    report = db.reports.get(rec["report_id"])
    owner = _report_owner_account_id(report) if report else None
    require_account_owner(owner, user_id, role)

    # Only an ACTIVE link may be revoked.
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Only an ACTIVE share link may be revoked")

    rec["status"] = "REVOKED"
    touch(rec)
    return success(serialize_share_link(rec), status=200)
