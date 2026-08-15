"""Novation / sublease requests: create, list, two-stage SoD review."""
from flask import Blueprint, g

from db import STORE, base_entity, touch
from errors import (
    ERR_LESSEE_NOT_ACTIVE,
    ERR_SOD_VIOLATION,
    ApiError,
    bad_request,
    forbidden,
    invalid_state,
    not_found,
)
from middleware import require_lease_ownership, require_roles
from response import paginated, success
from validators import get_body, req_enum, req_str

bp = Blueprint("novation", __name__)


@bp.post("/leasing/leases/<lease_id>/novation-requests")
@require_roles("LesseeRep")
def create_novation_request(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    b = get_body()
    request_type = req_enum(b, "request_type", {"NOVATION", "SUBLEASE"})
    proposed_lessee_id = req_str(b, "proposed_lessee_id")
    if proposed_lessee_id not in STORE["lessees"]:
        raise bad_request("proposed_lessee_id does not reference an existing lessee")
    if proposed_lessee_id == lease["lessee_id"]:
        raise bad_request("proposed_lessee_id must differ from the current lessee")
    n = base_entity()
    n.update(
        {
            "lease_id": lease["id"],
            "request_type": request_type,
            "proposed_lessee_id": proposed_lessee_id,
            "status": "SUBMITTED",
            "credit_reviewed_by": None,
            "legal_reviewed_by": None,
        }
    )
    STORE["novation_requests"][n["id"]] = n
    return success(n, status=201)


@bp.get("/leasing/leases/<lease_id>/novation-requests")
@require_roles("LessorAdmin", "CreditOfficer", "LegalApprover", "LesseeRep")
def list_lease_novation_requests(lease_id):
    lease = STORE["leases"].get(lease_id)
    if lease is None:
        raise not_found("Lease not found")
    require_lease_ownership(lease)
    items = [n for n in STORE["novation_requests"].values() if n["lease_id"] == lease["id"]]
    items.sort(key=lambda n: n["created_at"])
    return paginated(items)


@bp.post("/leasing/novation-requests/<request_id>/review")
@require_roles("CreditOfficer", "LegalApprover")
def review_novation_request(request_id):
    n = STORE["novation_requests"].get(request_id)
    if n is None:
        raise not_found("Novation request not found")
    b = get_body()
    decision = req_enum(b, "decision", {"APPROVE", "REJECT"})

    if n["status"] == "SUBMITTED":
        # Credit stage.
        if g.role != "CreditOfficer":
            raise forbidden("The credit stage of a SUBMITTED request requires a CreditOfficer")
        n["credit_reviewed_by"] = g.user_id
        n["status"] = "CREDIT_APPROVED" if decision == "APPROVE" else "REJECTED"
        touch(n)
        return success(n)

    if n["status"] == "CREDIT_APPROVED":
        # Legal stage.
        if g.role != "LegalApprover":
            raise forbidden("The legal stage of a CREDIT_APPROVED request requires a LegalApprover")
        if g.user_id == n["credit_reviewed_by"]:
            raise ApiError(
                ERR_SOD_VIOLATION,
                "The legal reviewer must differ from the credit reviewer",
                409,
            )
        if decision == "APPROVE":
            proposed = STORE["lessees"][n["proposed_lessee_id"]]
            if proposed["status"] != "ACTIVE":
                raise ApiError(
                    ERR_LESSEE_NOT_ACTIVE,
                    "The proposed lessee is not ACTIVE",
                    409,
                )
            lease = STORE["leases"][n["lease_id"]]
            if n["request_type"] == "NOVATION":
                lease["lessee_id"] = n["proposed_lessee_id"]
            else:
                lease["approved_sublessee_id"] = n["proposed_lessee_id"]
            touch(lease)
            n["status"] = "APPROVED"
        else:
            n["status"] = "REJECTED"
        n["legal_reviewed_by"] = g.user_id
        touch(n)
        return success(n)

    raise invalid_state("This novation request is already terminal")
