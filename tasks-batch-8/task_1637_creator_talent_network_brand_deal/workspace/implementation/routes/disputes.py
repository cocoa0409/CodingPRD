"""Dispute endpoints: list, get, review, resolve (DISMISS / UPHOLD with
remedy / ESCALATE), including deal resume/terminate cascades."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import helpers as H, lifecycle

bp = Blueprint("disputes", __name__)


@bp.route("/disputes", methods=["GET"])
@require_roles("BrandManager", "Creator", "Brand", "FinanceAdmin")
def list_disputes(actor):
    items = list(db.disputes.values())
    if actor.role in ("Creator", "Brand"):
        scoped = []
        for d in items:
            deal = db.deals.get(d["deal_id"])
            if deal is None:
                continue
            if actor.role == "Creator" and deal["creator_id"] == actor.user_id:
                scoped.append(d)
            elif actor.role == "Brand" and deal["brand_id"] == actor.user_id:
                scoped.append(d)
        items = scoped
    deal_id = request.args.get("deal_id")
    deliverable_id = request.args.get("deliverable_id")
    status = request.args.get("status")
    if deal_id is not None:
        items = [d for d in items if d["deal_id"] == deal_id]
    if deliverable_id is not None:
        items = [d for d in items if d.get("deliverable_id") == deliverable_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/disputes/<did>", methods=["GET"])
@require_roles("BrandManager", "Creator", "Brand", "FinanceAdmin")
def get_dispute(actor, did):
    dispute = H.get_or_404(db.disputes, did, "dispute")
    deal = db.deals.get(dispute["deal_id"])
    if deal is not None:
        if actor.role == "Creator":
            require_owner(actor, deal["creator_id"], "dispute")
        elif actor.role == "Brand":
            require_owner(actor, deal["brand_id"], "dispute")
    return resp.ok(dispute)


@bp.route("/disputes/<did>/review", methods=["POST"])
@require_roles("BrandManager")
def review_dispute(actor, did):
    dispute = H.get_or_404(db.disputes, did, "dispute")
    H.body()
    if dispute["status"] in ("RESOLVED_UPHELD", "RESOLVED_DISMISSED"):
        raise err.already_terminal(f"Dispute is {dispute['status']}")
    if dispute["status"] != "OPEN":
        raise err.invalid_state("Review requires dispute OPEN")
    dispute["status"] = "UNDER_REVIEW"
    H.touch(dispute)
    return resp.ok(dispute)


@bp.route("/disputes/<did>/resolve", methods=["POST"])
@require_roles("BrandManager")
def resolve_dispute(actor, did):
    dispute = H.get_or_404(db.disputes, did, "dispute")
    payload = H.body()
    H.req_fields(payload, ["action"])
    action = H.require_enum(payload, "action",
                            {"DISMISS", "UPHOLD", "ESCALATE"})
    remedy = H.opt_enum(payload, "remedy", H.DISPUTE_REMEDY_ENUM, default=None)
    reduction_pct = payload.get("reduction_pct")
    resolution_note = H.opt_str(payload, "resolution_note", default=None)

    if dispute["status"] in ("RESOLVED_UPHELD", "RESOLVED_DISMISSED"):
        raise err.already_terminal(f"Dispute is {dispute['status']}")

    if action == "ESCALATE":
        if dispute["status"] != "UNDER_REVIEW":
            raise err.invalid_state("Escalation requires dispute UNDER_REVIEW")
        if resolution_note is not None:
            dispute["resolution_note"] = resolution_note
        dispute["status"] = "ESCALATED"
        H.touch(dispute)
        return resp.ok(dispute)

    # DISMISS / UPHOLD require UNDER_REVIEW or ESCALATED.
    if dispute["status"] not in ("UNDER_REVIEW", "ESCALATED"):
        raise err.invalid_state(
            "Resolution requires dispute UNDER_REVIEW or ESCALATED")

    if action == "UPHOLD":
        if remedy is None:
            raise err.validation("remedy is required when action is UPHOLD")
        if dispute["status"] == "ESCALATED" and remedy not in (
                "TERMINATE", "FEE_REDUCTION"):
            raise err.validation(
                "From ESCALATED only remedies TERMINATE or FEE_REDUCTION "
                "are allowed")
        if remedy == "FEE_REDUCTION":
            if not H.is_num(reduction_pct) or not (0 < reduction_pct < 1):
                raise err.validation(
                    "reduction_pct must be strictly between 0 and 1")
        if remedy == "RESHOOT":
            if not dispute.get("deliverable_id"):
                raise err.validation(
                    "remedy RESHOOT requires dispute.deliverable_id to be set")
            deliverable = db.deliverables.get(dispute["deliverable_id"])
            if deliverable is None:
                raise err.not_found("deliverable not found: "
                                    f"{dispute['deliverable_id']}")
            if int(deliverable.get("reshoot_count", 0)) >= (
                    H.MAX_RESHOOTS_PER_DELIVERABLE):
                raise err.ApiError(err.ERR_RESHOOT_LIMIT_EXCEEDED,
                                   "Reshoot limit reached for this "
                                   "deliverable", 422)
    else:  # DISMISS
        remedy = None

    deal = db.deals.get(dispute["deal_id"])

    dispute["status"] = ("RESOLVED_DISMISSED" if action == "DISMISS"
                         else "RESOLVED_UPHELD")
    dispute["remedy"] = remedy
    if remedy == "FEE_REDUCTION":
        dispute["reduction_pct"] = reduction_pct
    if resolution_note is not None:
        dispute["resolution_note"] = resolution_note
    H.touch(dispute)

    if deal is not None and deal["status"] == "IN_DISPUTE":
        if remedy == "TERMINATE":
            deal["status"] = "TERMINATED"
            H.touch(deal)
            lifecycle.terminate_deal_cascade(deal)
        else:
            # DISMISS or lighter remedies: deal back to ACTIVE, unhold
            # payouts, apply remedy effects.
            deal["status"] = "ACTIVE"
            H.touch(deal)
            lifecycle.unhold_payouts_of_deal(deal["id"])
            if remedy == "FEE_REDUCTION":
                deal["reduction_pct"] = reduction_pct
                H.touch(deal)
            elif remedy == "RESHOOT":
                reshoot = H.new_entity()
                reshoot.update({
                    "deliverable_id": dispute["deliverable_id"],
                    "dispute_id": dispute["id"],
                    "reason": dispute.get("note") or "RESHOOT remedy",
                    "status": "REQUESTED",
                    "responded_at": None,
                })
                db.reshoots[reshoot["id"]] = reshoot
    elif deal is not None:
        # Deal stayed COMPLETED. TERMINATE is impossible (already terminal);
        # anything else unholds the payouts the dispute held, and an upheld
        # remedy still applies its effects.
        if remedy == "TERMINATE":
            raise err.already_terminal("Deal is COMPLETED")
        lifecycle.unhold_payouts_of_deal(deal["id"])
        if remedy == "FEE_REDUCTION":
            deal["reduction_pct"] = reduction_pct
            H.touch(deal)
        elif remedy == "RESHOOT":
            reshoot = H.new_entity()
            reshoot.update({
                "deliverable_id": dispute["deliverable_id"],
                "dispute_id": dispute["id"],
                "reason": dispute.get("note") or "RESHOOT remedy",
                "status": "REQUESTED",
                "responded_at": None,
            })
            db.reshoots[reshoot["id"]] = reshoot

    return resp.ok(dispute)
