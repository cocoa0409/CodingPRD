"""Warranty claims and dealer behaviour monitoring (PRD 3.9)."""
from flask import Blueprint

import calc
import cascades as cas
import enums
import helpers as h
import serializers as ser
from db import cfg, db, new_id
from errors import ApiError

bp = Blueprint("claims", __name__)

READ_ROLES = ("ProgramAdministrator", "ProgramAuditor", "DealerPrincipal")
LIVE_STATUSES = ("ACTIVE", "UNDER_AUDIT")
PAYABLE_STATUSES = ("ACTIVE", "UNDER_AUDIT", "DECERTIFIED")


def claim_or_404(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "No warranty claim with that id.")
    return row


@bp.route("/warranty-claims", methods=["POST"])
def file_claim():
    _uid, _role, dealer = h.authorize(("DealerPrincipal",))
    config = cfg()
    body = h.body_dict()
    certification_id = h.f_string(body, "certification_id")
    component_category = h.f_enum(body, "component_category", enums.COMPONENT_CATEGORIES)
    repair_date = h.f_date(body, "repair_date")
    repair_odometer = h.f_int(body, "repair_odometer_miles", minimum=0)
    claimed = h.f_int(body, "claimed_amount_cents", minimum=1)

    certification = db.certifications.get(certification_id)
    if certification is None:
        raise ApiError(
            "ERR_REFERENCED_ENTITY_NOT_FOUND", "certification_id does not resolve."
        )
    if certification["dealer_id"] != dealer["id"]:
        raise ApiError(
            "ERR_DEALER_SCOPE_VIOLATION",
            "That certification belongs to another dealership.",
        )
    if certification["status"] not in LIVE_STATUSES:
        raise ApiError(
            "ERR_CERTIFICATION_NOT_ACTIVE",
            "A claim may only be filed against a live certification.",
        )

    # rung 32 — the repair must sit inside the half-open coverage interval
    start = certification["warranty_start_date"]
    end = certification["warranty_end_date"]
    end_miles = certification["warranty_end_miles"]
    inside = (
        start is not None
        and end is not None
        and end_miles is not None
        and start <= repair_date < end
        and repair_odometer <= end_miles
    )
    if not inside:
        raise ApiError(
            "ERR_OUTSIDE_WARRANTY_WINDOW",
            "The repair falls outside the certification's coverage.",
        )

    # rung 33 — the per-claim ceiling
    if claimed > config["claim_per_claim_cap_cents"]:
        raise ApiError(
            "ERR_CLAIM_AMOUNT_EXCEEDS_CAP",
            "claimed_amount_cents exceeds the programme's per-claim ceiling.",
        )

    row = h.new_common(
        {
            "id": new_id(),
            "certification_id": certification_id,
            "component_category": component_category,
            "repair_date": repair_date,
            "repair_odometer_miles": repair_odometer,
            "claimed_amount_cents": claimed,
            "status": "SUBMITTED",
            "dealer_ratio_snapshot_before": None,
            "approved_amount_cents": 0,
            "denial_reason": None,
            "adjudicated_at": None,
        }
    )
    db.claims[row["id"]] = row
    return h.object_response(ser.warranty_claim(row), 201)


@bp.route("/certifications/<certification_id>/warranty-claims", methods=["GET"])
def list_claims(certification_id):
    user_id, role, _principal = h.authorize(READ_ROLES)
    status = h.q_enum("status", enums.CLAIM_STATUSES)
    component_category = h.q_enum("component_category", enums.COMPONENT_CATEGORIES)
    limit, offset = h.pagination()
    if certification_id not in db.certifications:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "No certification with that id.")
    # 3.9: the claim collection is readable by an administrator, an auditor,
    # "and the owning `DealerPrincipal`".
    h.require_dealer_scope(
        user_id, role, db.certifications[certification_id]["dealer_id"]
    )
    rows = cas.certification_claims(certification_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    if component_category:
        rows = [r for r in rows if r["component_category"] == component_category]
    return h.paged(rows, limit, offset, ser.warranty_claim)


@bp.route("/warranty-claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate_claim(claim_id):
    h.authorize(("ProgramAdministrator",))
    config = cfg()
    body = h.body_dict()
    decision = h.f_enum(body, "decision", enums.CLAIM_DECISIONS)
    denial_reason = h.f_enum(
        body, "denial_reason", enums.DENIAL_REASONS, required=False
    )
    if decision == "DENY" and denial_reason is None:
        h.bad_request("A DENY decision requires a denial_reason.")

    claim = claim_or_404(claim_id)
    certification = db.certifications.get(claim["certification_id"])

    if claim["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_CLAIM_ALREADY_ADJUDICATED", "That claim has already been adjudicated."
        )

    if decision == "DENY":
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
        claim["adjudicated_at"] = db.clock
        h.touch(claim)
        return h.object_response(ser.warranty_claim(claim))

    if certification is None or certification["status"] not in PAYABLE_STATUSES:
        raise ApiError(
            "ERR_CERTIFICATION_NOT_ACTIVE",
            "The certification is not in a status that permits a payout.",
        )
    dealer = db.dealers.get(certification["dealer_id"])

    # step 1 — pin the ratio as it stands before this claim is counted anywhere
    snapshot = dealer["claim_ratio_effective"] if dealer is not None else 0.0
    claim["dealer_ratio_snapshot_before"] = snapshot

    # step 2 — trim to the certification's remaining headroom, before the share
    already = sum(
        c["approved_amount_cents"]
        for c in cas.certification_claims(certification["id"])
        if c["status"] == "APPROVED"
    )
    remaining = max(0, config["claim_per_claim_cap_cents"] - already)
    capped = min(claim["claimed_amount_cents"], remaining)

    # step 3 — the share follows the snapshot, not the post-claim ratio
    share = (
        config["probation_claim_share"]
        if snapshot >= config["claim_ratio_probation_threshold"]
        else 1.0
    )

    # step 4 — floor the payout to whole cents
    claim["approved_amount_cents"] = calc.floor_mul(capped, share)

    # step 5 — only now does the claim count towards the dealer's behaviour
    claim["status"] = "APPROVED"
    claim["adjudicated_at"] = db.clock
    h.touch(claim)
    h.touch(certification)
    if dealer is not None:
        cas.recompute_dealer_claim_counts(dealer)
        cas.recompute_dealer_ratio(dealer)
        h.touch(dealer)
        # step 6 — and only after that are the privilege thresholds re-evaluated
        cas.evaluate_privilege_thresholds(dealer)
    return h.object_response(ser.warranty_claim(claim))
