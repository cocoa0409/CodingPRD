"""IndividualApplicant endpoints."""
import re

from flask import Blueprint

from db import store
from middleware import auth
from common import body, get_or_404, required, new_entity, serialize, list_page
from response import success_obj, success_list
from errors import err_duplicate, err_invalid_request
from timeutil import parse_date
from services import fingerprint_required

bp = Blueprint("applicants", __name__)

CRD_RE = re.compile(r"^\d{1,7}$")
READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")


def applicant_out(a):
    return serialize(a, {"fingerprint_required": fingerprint_required(a["id"])})


@bp.post("/registration-desk/applicants")
def create_applicant():
    auth("RegistrationPrincipal")
    data = body()
    crd = data.get("crd_number")
    if isinstance(crd, str) and any(a["crd_number"] == crd for a in store.applicants.values()):
        raise err_duplicate("crd_number must be unique across applicants")
    crd = required(data, "crd_number")
    full_name = required(data, "full_name")
    dob = required(data, "date_of_birth")
    if not isinstance(crd, str) or not CRD_RE.match(crd):
        raise err_invalid_request("crd_number must be 1-7 digits")
    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 120):
        raise err_invalid_request("full_name must be 1-120 characters")
    if parse_date(dob) is None:
        raise err_invalid_request("date_of_birth must be an ISO YYYY-MM-DD date")
    a = new_entity()
    a.update({
        "crd_number": crd,
        "full_name": full_name,
        "date_of_birth": dob,
    })
    store.applicants[a["id"]] = a
    return success_obj(applicant_out(a), 201)


@bp.get("/registration-desk/applicants/<id>")
def get_applicant(id):
    auth(*READ_ROLES)
    a = get_or_404(store.applicants, id)
    return success_obj(applicant_out(a), 200)


@bp.get("/registration-desk/applicants")
def list_applicants():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(store.applicants)
    return success_list([applicant_out(a) for a in page], limit, offset, total)
