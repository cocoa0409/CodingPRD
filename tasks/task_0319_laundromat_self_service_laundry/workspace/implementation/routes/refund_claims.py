"""RefundClaim endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_ALREADY_REFUNDED,
)
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
    parse_pagination,
    paginate,
    get_or_404,
    write_ledger,
)
from services.shift_calc import recompute_and_touch
from services.serialize import view

bp = Blueprint("refund_claims", __name__)

REASONS = {"MACHINE_FAULT", "NO_CYCLE", "DOUBLE_CHARGE"}
DESTINATIONS = {"WALLET", "CASH", "ORIGINAL_TENDER"}


@bp.post("/refund-claims")
def file_claim():
    _, role = get_identity()
    require_roles(role, {"Member", "Attendant"})
    body = get_body()
    require_fields(body, ["vend_id", "reported_by_id", "reason"])
    vend_id = require_str(body["vend_id"], "vend_id")
    reported_by_id = require_str(body["reported_by_id"], "reported_by_id")
    reason = body["reason"]
    require_enum(reason, REASONS, "reason")
    refund_destination = body.get("refund_destination", "WALLET")
    if refund_destination is None:
        refund_destination = "WALLET"
    require_enum(refund_destination, DESTINATIONS, "refund_destination")
    with db.lock:
        vend = get_or_404(db.vends, vend_id, "VendTransaction")
        # NOTE: the ERR_ALREADY_REFUNDED guard (validations priority 15) is
        # enforced at approval time (POST /refund-claims/{id}/approve), not at
        # filing time: the authoritative §1.8 test recipe files a second claim
        # against an already-REFUNDED vend successfully and only rejects the
        # approve. A claim may therefore be filed; it cannot be approved.
        # requested_cents derived from the vend: 0 if charged was 0.
        if vend["charged_amount_cents"] == 0:
            requested = 0
        else:
            requested = vend["charged_amount_cents"]
        claim = {
            "vend_id": vend_id,
            "reported_by_id": reported_by_id,
            "reason": reason,
            "refund_destination": refund_destination,
            "requested_cents": requested,
            "approved_cents": 0,
            "status": "SUBMITTED",
        }
        stamp_create(claim)
        db.refund_claims[claim["id"]] = claim
    return object_response(view(claim), status=201)


@bp.get("/refund-claims")
def list_claims():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    vend_id = request.args.get("vend_id")
    reported_by_id = request.args.get("reported_by_id")
    items = list(db.refund_claims.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if vend_id is not None:
        items = [c for c in items if c["vend_id"] == vend_id]
    if reported_by_id is not None:
        items = [c for c in items if c["reported_by_id"] == reported_by_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(c) for c in window], limit, offset, total)


@bp.get("/refund-claims/<claim_id>")
def get_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant", "Member"})
    claim = get_or_404(db.refund_claims, claim_id, "RefundClaim")
    return object_response(view(claim))


@bp.post("/refund-claims/<claim_id>/approve")
def approve_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        claim = get_or_404(db.refund_claims, claim_id, "RefundClaim")
        body = get_body()
        # Well-formedness (priority 4): expected_claim_version required.
        require_fields(body, ["expected_claim_version"])
        expected_version = require_int(body["expected_claim_version"], "expected_claim_version")
        vend = db.vends.get(claim["vend_id"])
        # State (priority 6): claim must be SUBMITTED.
        if claim["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Claim is not SUBMITTED")
        # OCC (priority 7).
        if expected_version != claim["version"]:
            raise err(ERR_STALE_VERSION, "Stale claim version")
        # Vend must still be CAPTURED, not already REFUNDED (priority 15).
        if vend is None:
            raise err(ERR_INVALID_STATE, "Referenced vend missing")
        if vend["payment_status"] == "REFUNDED":
            raise err(ERR_ALREADY_REFUNDED, "Vend is already REFUNDED")

        # ---- Approval + cascade ------------------------------------------
        claim["approved_cents"] = claim["requested_cents"]
        claim["status"] = "APPROVED"
        touch(claim)  # increments claim.version by 1

        vend["payment_status"] = "REFUNDED"
        touch(vend)

        member = db.members.get(vend.get("member_id"))
        approved = claim["approved_cents"]
        if member is not None:
            member_touched = False
            # Wallet credit if APP_WALLET vend + WALLET destination.
            if vend["payment_method"] == "APP_WALLET" and claim["refund_destination"] == "WALLET":
                member["wallet_cents"] += approved
                member_touched = True
            # Loyalty reversal of the vend's loyalty_points_earned (floored at 0).
            reversal_pts = vend["loyalty_points_earned"]
            if reversal_pts > 0:
                actual = min(reversal_pts, member["loyalty_points"])
                member["loyalty_points"] -= actual
                member_touched = True
            # lifetime_spend reduced by charged_amount_cents (floored at 0).
            member["lifetime_spend_cents"] = max(
                0, member["lifetime_spend_cents"] - vend["charged_amount_cents"]
            )
            member_touched = True
            if member_touched:
                touch(member)
            # Ledger REVERSAL entry of -loyalty_points_earned (signed full amount).
            if reversal_pts > 0:
                write_ledger(member, "REVERSAL", -reversal_pts, vend["id"])

        # CASH destination + vend's shift is OPEN: bump that shift's drawer.
        if claim["refund_destination"] == "CASH":
            shift_id = vend.get("shift_id")
            if shift_id is not None:
                shift = db.shifts.get(shift_id)
                if shift is not None and shift["status"] == "OPEN":
                    recompute_and_touch(shift)

    return object_response(view(claim))


@bp.post("/refund-claims/<claim_id>/deny")
def deny_claim(claim_id):
    _, role = get_identity()
    require_roles(role, {"Manager"})
    with db.lock:
        claim = get_or_404(db.refund_claims, claim_id, "RefundClaim")
        if claim["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Claim is not SUBMITTED")
        claim["status"] = "DENIED"
        # approved_cents stays 0; vend unchanged.
        touch(claim)
    return object_response(view(claim))
