"""Design endpoints — upload, mockup, approve, reject with cascade."""
from flask import Blueprint, request

import db
from errors import raise_error
from middleware import require_auth
from response import ok, created, paginate_and_serialize
from services.calc import STRIKE_THRESHOLD
from services.serialize import serialize

bp = Blueprint("designs", __name__)


def _get_design_or_404(did):
    row = db.designs.get(did)
    if not row:
        raise_error("ERR_NOT_FOUND", f"design {did} not found")
    return row


def _get_creator_or_404(cid):
    row = db.creators.get(cid)
    if not row:
        raise_error("ERR_NOT_FOUND", f"creator {cid} not found")
    return row


@bp.post("/pod/creators/<cid>/designs")
@require_auth(["Creator"])
def upload_design(cid):
    creator = _get_creator_or_404(cid)
    body = request.get_json(silent=True) or {}
    file_hash = body.get("file_hash")
    if not isinstance(file_hash, str) or not file_hash:
        raise_error("ERR_INVALID_REQUEST", "file_hash required")

    # (creator_id, file_hash) uniqueness — priority 13.
    for d in db.designs.all():
        if d["creator_id"] == cid and d["file_hash"] == file_hash:
            raise_error("ERR_DESIGN_DUPLICATE_HASH", "duplicate hash for this creator")

    row = db.new_common_fields()
    row.update(
        {
            "creator_id": cid,
            "file_hash": file_hash,
            "status": "UPLOADED",
            "mockup_url": None,
        }
    )
    db.designs.insert(row)
    return created(serialize(row))


@bp.get("/pod/designs/<did>")
@require_auth(["Creator", "PlatformAdmin"])
def read_design(did):
    return ok(serialize(_get_design_or_404(did)))


@bp.get("/pod/creators/<cid>/designs")
@require_auth(["Creator", "PlatformAdmin"])
def list_creator_designs(cid):
    _get_creator_or_404(cid)
    rows = [d for d in db.designs.all() if d["creator_id"] == cid]
    rows = db.sorted_rows(rows)
    return paginate_and_serialize(rows, serialize)


@bp.post("/pod/designs/<did>/mockup")
@require_auth(["Creator"])
def generate_mockup(did):
    row = _get_design_or_404(did)
    if row["status"] != "UPLOADED":
        raise_error("ERR_INVALID_STATE", "design must be UPLOADED")
    if not row.get("file_hash"):
        raise_error("ERR_INVALID_STATE", "file_hash missing")
    row["status"] = "MOCKUP_READY"
    row["mockup_url"] = f"https://mockups.example.com/{row['id']}.png"
    db.bump(row)
    return ok(serialize(row))


@bp.post("/pod/designs/<did>/approve")
@require_auth(["PlatformAdmin"])
def approve_design(did):
    row = _get_design_or_404(did)
    if row["status"] != "MOCKUP_READY":
        raise_error("ERR_INVALID_STATE", "design must be MOCKUP_READY to approve")
    # Priority 8: strike threshold.
    creator = db.creators.get(row["creator_id"])
    if creator and creator.get("reprint_strike_count", 0) >= STRIKE_THRESHOLD:
        raise_error("ERR_STRIKE_THRESHOLD_EXCEEDED", "creator strike count >= threshold")
    row["status"] = "APPROVED"
    db.bump(row)
    return ok(serialize(row))


@bp.post("/pod/designs/<did>/reject")
@require_auth(["PlatformAdmin"])
def reject_design(did):
    row = _get_design_or_404(did)
    prev = row["status"]
    if prev not in ("MOCKUP_READY", "APPROVED"):
        raise_error("ERR_INVALID_STATE", "design must be MOCKUP_READY or APPROVED to reject")
    row["status"] = "REJECTED"
    db.bump(row)

    if prev == "APPROVED":
        # Cascade level 2 — archive dependent listings.
        affected_listings = []
        for lst in db.listings.all():
            if lst["design_id"] == did and lst["status"] in ("DRAFT", "PUBLISHED"):
                lst["status"] = "ARCHIVED"
                db.bump(lst)
                affected_listings.append(lst["id"])

        if affected_listings:
            # Cascade level 3 — cancel PENDING orders (with allowed payment states).
            for order in db.orders.all():
                if (
                    order["listing_id"] in affected_listings
                    and order["fulfillment_status"] == "PENDING"
                    and order["payment_status"] in ("DRAFT", "AUTHORIZED")
                ):
                    if order["payment_status"] == "AUTHORIZED":
                        order["payment_status"] = "VOIDED"
                    order["fulfillment_status"] = "CANCELLED"
                    db.bump(order)

    return ok(serialize(row))
