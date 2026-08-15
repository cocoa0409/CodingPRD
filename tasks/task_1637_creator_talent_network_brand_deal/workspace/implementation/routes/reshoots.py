"""Reshoot endpoints: list, get, respond (accept resets the deliverable)."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import helpers as H, lifecycle

bp = Blueprint("reshoots", __name__)


@bp.route("/reshoots", methods=["GET"])
@require_roles("BrandManager", "Creator", "TalentManager")
def list_reshoots(actor):
    items = list(db.reshoots.values())
    if actor.role == "Creator":
        scoped = []
        for r in items:
            d = db.deliverables.get(r["deliverable_id"])
            deal = db.deals.get(d["deal_id"]) if d else None
            if deal is not None and deal["creator_id"] == actor.user_id:
                scoped.append(r)
        items = scoped
    dispute_id = request.args.get("dispute_id")
    deliverable_id = request.args.get("deliverable_id")
    status = request.args.get("status")
    if dispute_id is not None:
        items = [r for r in items if r.get("dispute_id") == dispute_id]
    if deliverable_id is not None:
        items = [r for r in items if r["deliverable_id"] == deliverable_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/reshoots/<rid>", methods=["GET"])
@require_roles("BrandManager", "Creator", "TalentManager")
def get_reshoot(actor, rid):
    reshoot = H.get_or_404(db.reshoots, rid, "reshoot")
    if actor.role == "Creator":
        d = db.deliverables.get(reshoot["deliverable_id"])
        deal = db.deals.get(d["deal_id"]) if d else None
        if deal is not None:
            require_owner(actor, deal["creator_id"], "reshoot")
    return resp.ok(reshoot)


@bp.route("/reshoots/<rid>/respond", methods=["POST"])
@require_roles("Creator")
def respond_reshoot(actor, rid):
    reshoot = H.get_or_404(db.reshoots, rid, "reshoot")

    deliverable = db.deliverables.get(reshoot["deliverable_id"])
    deal = db.deals.get(deliverable["deal_id"]) if deliverable else None
    if deal is not None:
        require_owner(actor, deal["creator_id"], "deal")

    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action", {"ACCEPT", "DECLINE"})

    if reshoot["status"] in ("ACCEPTED", "DECLINED"):
        raise err.already_terminal(f"Reshoot is {reshoot['status']}")
    if reshoot["status"] != "REQUESTED":
        raise err.invalid_state("Reshoot response requires REQUESTED")

    if action == "DECLINE":
        reshoot["status"] = "DECLINED"
        reshoot["responded_at"] = db.now_iso()
        H.touch(reshoot)
        return resp.ok(reshoot)

    # ACCEPT — reset the deliverable.
    if deliverable is None:
        raise err.not_found("deliverable not found: "
                            f"{reshoot['deliverable_id']}")
    if deliverable["status"] not in ("APPROVED", "PUBLISHED", "VERIFIED"):
        raise err.invalid_state(
            "Reshoot accept requires deliverable APPROVED, PUBLISHED, or "
            "VERIFIED")

    was_verified = deliverable["status"] == "VERIFIED"

    reshoot["status"] = "ACCEPTED"
    reshoot["responded_at"] = db.now_iso()
    H.touch(reshoot)

    deliverable["status"] = "PENDING_SUBMISSION"
    deliverable["content_url"] = None
    deliverable["published_at"] = None
    deliverable["verified_at"] = None
    deliverable["reshoot_count"] = int(deliverable.get("reshoot_count", 0)) + 1
    H.touch(deliverable)

    # Void this deliverable's QUEUED/FAILED checks and recompute the creator's
    # pending count.
    lifecycle.void_checks_of_deliverable(deliverable)

    # Reopening a VERIFIED deliverable on a COMPLETED deal breaks the "every
    # deliverable VERIFIED" invariant, so the deal reverts to ACTIVE.
    if (was_verified and deal is not None
            and deal["status"] == "COMPLETED"):
        deal["status"] = "ACTIVE"
        H.touch(deal)

    return resp.ok(reshoot)
