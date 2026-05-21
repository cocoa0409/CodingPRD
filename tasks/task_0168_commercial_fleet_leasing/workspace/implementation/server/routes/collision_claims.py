"""CollisionClaim routes — file / start-review / request-revision / patch / approve / reject (§3.7)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..calculations import compute_collision_deductible
from ..clock import iso_format, parse_iso
from ..common import as_int, bump, check_occ, get_json_body, require_fields, stamp_new
from ..constants import MAX_REVISION_ROUNDS
from ..errors import ApiError
from ..response import respond
from ..serializers import collision_view
from ..store import store


bp = Blueprint("collision_claims", __name__)


@bp.post("/lease-agreements/<lease_id>/collision-claims")
@require_auth("FleetManager", "VendorOps")
def file_claim(lease_id: str):
    body = get_json_body()
    require_fields(body, "incident_ts", "estimate_cents")
    try:
        incident_ts = parse_iso(body["incident_ts"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    estimate = as_int(body["estimate_cents"], "estimate_cents", min_value=0)

    with store.lock:
        la = store.lease_agreements.get(lease_id)
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")

        claim = {
            "lease_agreement_id": lease_id,
            "vehicle_id": la["vehicle_id"],
            "incident_ts": iso_format(incident_ts),
            "estimate_cents": estimate,
            "revised_estimate_cents": 0,
            "lessee_deductible_cents": 0,
            "claim_status": "FILED",
            "revision_round": 0,
        }
        stamp_new(claim)
        store.collision_claims[claim["id"]] = claim

        la["collision_open_count"] = int(la.get("collision_open_count", 0)) + 1
        bump(la)
    return respond(collision_view(claim), 201)


@bp.post("/collision-claims/<claim_id>/start-review")
@require_auth("ClaimAdjuster")
def start_review(claim_id: str):
    with store.lock:
        c = store.collision_claims.get(claim_id)
        if c is None:
            raise ApiError("ERR_NOT_FOUND", "CollisionClaim not found")
        if c["claim_status"] != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Claim is not FILED")
        la = store.lease_agreements.get(c["lease_agreement_id"])
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        if la["lease_state"] not in ("ACTIVE", "IN_RETURN"):
            raise ApiError("ERR_INVALID_STATE", "Lease must be ACTIVE or IN_RETURN")
        c["claim_status"] = "UNDER_REVIEW"
        bump(c)
    return respond(collision_view(c), 200)


@bp.post("/collision-claims/<claim_id>/request-revision")
@require_auth("ClaimAdjuster")
def request_revision(claim_id: str):
    with store.lock:
        c = store.collision_claims.get(claim_id)
        if c is None:
            raise ApiError("ERR_NOT_FOUND", "CollisionClaim not found")
        if c["claim_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
        if int(c.get("revision_round", 0)) >= MAX_REVISION_ROUNDS:
            raise ApiError("ERR_REVISION_LIMIT_REACHED", "Max revision rounds reached")
        c["claim_status"] = "REVISION_REQUESTED"
        c["revision_round"] = int(c.get("revision_round", 0)) + 1
        bump(c)
    return respond(collision_view(c), 200)


@bp.patch("/collision-claims/<claim_id>")
@require_auth("VendorOps")
def patch_claim(claim_id: str):
    body = get_json_body()
    require_fields(body, "revised_estimate_cents")
    revised = as_int(body["revised_estimate_cents"], "revised_estimate_cents", min_value=1)

    with store.lock:
        c = store.collision_claims.get(claim_id)
        if c is None:
            raise ApiError("ERR_NOT_FOUND", "CollisionClaim not found")
        if c["claim_status"] != "REVISION_REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "Claim is not REVISION_REQUESTED")
        check_occ(c, body.get("version"))

        c["revised_estimate_cents"] = revised
        c["claim_status"] = "UNDER_REVIEW"
        bump(c)
    return respond(collision_view(c), 200)


@bp.post("/collision-claims/<claim_id>/approve")
@require_auth("ClaimAdjuster")
def approve_claim(claim_id: str):
    with store.lock:
        c = store.collision_claims.get(claim_id)
        if c is None:
            raise ApiError("ERR_NOT_FOUND", "CollisionClaim not found")
        if c["claim_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")

        deductible = compute_collision_deductible(c)
        c["lessee_deductible_cents"] = deductible
        c["claim_status"] = "APPROVED"
        bump(c)

        la = store.lease_agreements.get(c["lease_agreement_id"])
        if la is not None:
            la["collision_open_count"] = max(0, int(la.get("collision_open_count", 0)) - 1)
            bump(la)
            lessee = store.lessees.get(la["lessee_id"])
            if lessee is not None:
                lessee["outstanding_balance_cents"] = int(lessee.get("outstanding_balance_cents", 0)) + deductible
                bump(lessee)
    return respond(collision_view(c), 200)


@bp.post("/collision-claims/<claim_id>/reject")
@require_auth("ClaimAdjuster")
def reject_claim(claim_id: str):
    with store.lock:
        c = store.collision_claims.get(claim_id)
        if c is None:
            raise ApiError("ERR_NOT_FOUND", "CollisionClaim not found")
        if c["claim_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
        c["claim_status"] = "REJECTED"
        bump(c)

        la = store.lease_agreements.get(c["lease_agreement_id"])
        if la is not None:
            la["collision_open_count"] = max(0, int(la.get("collision_open_count", 0)) - 1)
            bump(la)
    return respond(collision_view(c), 200)
