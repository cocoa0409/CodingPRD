"""LiabilityClaim endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    compute_liability_allocation,
    get_agreement_or_404,
    mint_common_fields,
    touch,
)
from util import (
    as_iso_date,
    as_pct,
    as_positive_int,
    as_str,
    body,
    pagination_args,
    required,
)


def _get_claim_or_404(claim_id):
    c = DB["liability_claims"].get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "LiabilityClaim not found")
    return c


def register(app):
    @app.route("/liability-claims", methods=["POST"])
    def create_claim():
        auth(["RailroadContractsManager"])
        data = body()
        agreement_id = as_str(required(data, "agreement_id"), "agreement_id")
        agreement = get_agreement_or_404(agreement_id)
        apply_expiry_sweep_to_agreement(agreement)

        claimant_name = as_str(required(data, "claimant_name"), "claimant_name")
        incident_date = as_iso_date(required(data, "incident_date"), "incident_date")
        claim_amount_cents = as_positive_int(
            required(data, "claim_amount_cents"), "claim_amount_cents"
        )

        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )

        claim = {
            "agreement_id": agreement["id"],
            "claimant_name": claimant_name,
            "incident_date": incident_date,
            "claim_amount_cents": claim_amount_cents,
            "shipper_fault_pct": None,
            "shipper_liability_cents": None,
            "railroad_liability_cents": None,
            "status": "FILED",
        }
        mint_common_fields(claim)
        DB["liability_claims"][claim["id"]] = claim
        return ok(claim, 201)

    @app.route("/liability-claims", methods=["GET"])
    def list_claims():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        status = request.args.get("status")
        items = list(DB["liability_claims"].values())
        if agreement_id is not None:
            items = [c for c in items if c.get("agreement_id") == agreement_id]
        if status is not None:
            items = [c for c in items if c.get("status") == status]
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/liability-claims/<claimId>", methods=["GET"])
    def get_claim(claimId):
        auth(ALL_ROLES)
        return ok(_get_claim_or_404(claimId))

    @app.route("/liability-claims/<claimId>/apportion", methods=["POST"])
    def apportion_claim(claimId):
        auth(["RailroadContractsManager"])
        c = _get_claim_or_404(claimId)
        agreement = get_agreement_or_404(c["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        data = body()
        if "shipper_fault_pct" in data and data["shipper_fault_pct"] is not None:
            fault_pct = as_pct(data["shipper_fault_pct"], "shipper_fault_pct")
        else:
            fault_pct = agreement["shipper_indemnity_default_pct"]

        if c["status"] not in ("FILED", "DISPUTED"):
            raise ApiError(
                "ERR_CLAIM_INVALID_STATE",
                409,
                "Claim must be FILED or DISPUTED to apportion",
            )
        shipper, railroad = compute_liability_allocation(c, agreement, fault_pct)
        c["shipper_fault_pct"] = fault_pct
        c["shipper_liability_cents"] = shipper
        c["railroad_liability_cents"] = railroad
        c["status"] = "APPORTIONED"
        touch(c)
        return ok(c)

    @app.route("/liability-claims/<claimId>/accept", methods=["POST"])
    def accept_claim(claimId):
        user_id, role = auth(["ShipperFacilityManager"])
        c = _get_claim_or_404(claimId)
        agreement = get_agreement_or_404(c["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)
        if c["status"] != "APPORTIONED":
            raise ApiError(
                "ERR_CLAIM_INVALID_STATE", 409, "Claim must be APPORTIONED to accept"
            )
        c["status"] = "ACCEPTED"
        touch(c)
        return ok(c)

    @app.route("/liability-claims/<claimId>/dispute", methods=["POST"])
    def dispute_claim(claimId):
        user_id, role = auth(["ShipperFacilityManager"])
        c = _get_claim_or_404(claimId)
        agreement = get_agreement_or_404(c["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)
        if c["status"] != "APPORTIONED":
            raise ApiError(
                "ERR_CLAIM_INVALID_STATE", 409, "Claim must be APPORTIONED to dispute"
            )
        c["status"] = "DISPUTED"
        touch(c)
        return ok(c)
