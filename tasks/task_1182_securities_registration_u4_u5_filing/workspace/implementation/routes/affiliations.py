"""AffiliationRequest (dual registration) endpoints."""
from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, new_entity, touch, serialize, list_page,
)
from response import success_obj, success_list
from errors import (
    err_duplicate, err_invalid_state, err_referential, err_invalid_request,
)

bp = Blueprint("affiliations", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")


def _competitor_exists(applicant_id, second_firm_id, exclude_id=None):
    return any(
        a["applicant_id"] == applicant_id
        and a["second_firm_id"] == second_firm_id
        and a["status"] in ("PENDING", "APPROVED")
        and a["id"] != exclude_id
        for a in store.affiliation_requests.values()
    )


@bp.post("/registration-desk/affiliation-requests")
def create_affiliation():
    auth("RegistrationPrincipal")
    data = body()
    # Priority 3: body FKs in input order.
    applicant = fk_or_404(store.applicants, data.get("applicant_id"))
    second_firm = fk_or_404(store.firms, data.get("second_firm_id"))
    first_req = fk_or_404(store.registration_requests, data.get("first_registration_request_id"))
    # Priority 4: one PENDING/APPROVED affiliation per (applicant, second firm).
    if (
        data.get("applicant_id") is not None
        and data.get("second_firm_id") is not None
        and _competitor_exists(data.get("applicant_id"), data.get("second_firm_id"))
    ):
        raise err_duplicate("an affiliation in PENDING or APPROVED already exists for this applicant and firm")
    # Priority 9: required fields.
    required(data, "applicant_id")
    required(data, "second_firm_id")
    required(data, "first_registration_request_id")
    # Priority 11: the second firm must differ from the first registration's firm.
    if second_firm["id"] == first_req["firm_id"]:
        raise err_referential("second_firm_id must differ from the first registration's firm")
    a = new_entity()
    a.update({
        "applicant_id": applicant["id"],
        "second_firm_id": second_firm["id"],
        "first_registration_request_id": first_req["id"],
        "status": "PENDING",
        "denial_reason": None,
    })
    store.affiliation_requests[a["id"]] = a
    return success_obj(serialize(a), 201)


@bp.get("/registration-desk/affiliation-requests")
def list_affiliations():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.affiliation_requests,
        (
            ("applicant_id", "applicant_id", str),
            ("second_firm_id", "second_firm_id", str),
            ("first_registration_request_id", "first_registration_request_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.get("/registration-desk/affiliation-requests/<id>")
def get_affiliation(id):
    auth(*READ_ROLES)
    a = get_or_404(store.affiliation_requests, id)
    return success_obj(serialize(a), 200)


@bp.post("/registration-desk/affiliation-requests/<id>/approve")
def approve_affiliation(id):
    auth("ComplianceOfficer")
    a = get_or_404(store.affiliation_requests, id)
    if a["status"] != "PENDING":
        raise err_invalid_state("only a PENDING affiliation may be approved")
    first_req = get_or_404(store.registration_requests, a["first_registration_request_id"])
    if first_req["status"] != "ACTIVE":
        raise err_invalid_state("the first registration must be ACTIVE at decision time")
    if a["second_firm_id"] == first_req["firm_id"]:
        raise err_referential("second_firm_id must differ from the first registration's firm")
    if _competitor_exists(a["applicant_id"], a["second_firm_id"], exclude_id=a["id"]):
        raise err_duplicate("a competing PENDING or APPROVED affiliation exists for this applicant and firm")
    a["status"] = "APPROVED"
    touch(a)
    return success_obj(serialize(a), 200)


@bp.post("/registration-desk/affiliation-requests/<id>/deny")
def deny_affiliation(id):
    auth("ComplianceOfficer")
    a = get_or_404(store.affiliation_requests, id)
    if a["status"] != "PENDING":
        raise err_invalid_state("only a PENDING affiliation may be denied")
    data = body()
    reason = required(data, "denial_reason")
    if not isinstance(reason, str):
        raise err_invalid_request("denial_reason must be a string")
    a["status"] = "DENIED"
    a["denial_reason"] = reason
    touch(a)
    return success_obj(serialize(a), 200)


@bp.post("/registration-desk/affiliation-requests/<id>/revoke")
def revoke_affiliation(id):
    auth("ComplianceOfficer")
    a = get_or_404(store.affiliation_requests, id)
    if a["status"] != "APPROVED":
        raise err_invalid_state("only an APPROVED affiliation may be revoked")
    a["status"] = "REVOKED"
    touch(a)
    return success_obj(serialize(a), 200)
