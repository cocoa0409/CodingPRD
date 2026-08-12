"""JurisdictionSelection endpoints."""
import re

from flask import Blueprint

from db import store
from middleware import auth
from common import (
    body, get_or_404, fk_or_404, required, require_enum, new_entity, touch,
    serialize, list_page,
)
from response import success_obj, success_list
from errors import err_invalid_state, err_invalid_request, err_referential
from services import (
    SRO_CODES, STATE_JURISDICTION_FEE_CENTS, SRO_JURISDICTION_FEE_CENTS,
    recompute_issued_invoice_jurisdiction_fees,
)

bp = Blueprint("jurisdictions", __name__)

READ_ROLES = ("SystemOperator", "ComplianceOfficer", "RegistrationPrincipal", "Regulator")
STATE_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/registration-desk/jurisdiction-selections")
def create_selection():
    auth("RegistrationPrincipal")
    data = body()
    # Priority 3: body FK existence.
    req = fk_or_404(store.registration_requests, data.get("registration_request_id"))
    # Priority 9: field shape — jurisdiction_code pattern consistent with jurisdiction_type.
    required(data, "registration_request_id")
    code = required(data, "jurisdiction_code")
    jtype = require_enum(required(data, "jurisdiction_type"), {"STATE", "SRO"}, "jurisdiction_type")
    if not isinstance(code, str):
        raise err_invalid_request("jurisdiction_code must be a string")
    if jtype == "STATE":
        if not STATE_RE.match(code):
            raise err_invalid_request("jurisdiction_code for STATE must be a 2-letter uppercase state code")
    else:
        if code not in SRO_CODES:
            raise err_invalid_request("jurisdiction_code for SRO must be one of FINRA, NYSE, NASDAQ")
    # Priority 11: parent request must be editable (DRAFT or DEFICIENT).
    if req["status"] not in ("DRAFT", "DEFICIENT"):
        raise err_referential("jurisdiction selections require the parent request in DRAFT or DEFICIENT")
    sel = new_entity()
    sel.update({
        "registration_request_id": req["id"],
        "jurisdiction_code": code,
        "jurisdiction_type": jtype,
        "status": "SELECTED",
        "annual_fee_cents": STATE_JURISDICTION_FEE_CENTS if jtype == "STATE" else SRO_JURISDICTION_FEE_CENTS,
    })
    store.jurisdiction_selections[sel["id"]] = sel
    return success_obj(serialize(sel), 201)


@bp.get("/registration-desk/jurisdiction-selections")
def list_selections():
    auth(*READ_ROLES)
    page, limit, offset, total = list_page(
        store.jurisdiction_selections,
        (
            ("registration_request_id", "registration_request_id", str),
            ("status", "status", str),
        ),
    )
    return success_list([serialize(s) for s in page], limit, offset, total)


@bp.get("/registration-desk/jurisdiction-selections/<id>")
def get_selection(id):
    auth(*READ_ROLES)
    sel = get_or_404(store.jurisdiction_selections, id)
    return success_obj(serialize(sel), 200)


@bp.post("/registration-desk/jurisdiction-selections/<id>/relinquish")
def relinquish_selection(id):
    auth("RegistrationPrincipal")
    sel = get_or_404(store.jurisdiction_selections, id)
    if sel["status"] != "APPROVED":
        raise err_invalid_state("only an APPROVED selection may be relinquished")
    parent = get_or_404(store.registration_requests, sel["registration_request_id"])
    if parent["status"] != "ACTIVE":
        raise err_invalid_state("relinquishment requires an ACTIVE registration")
    sel["status"] = "RELINQUISHED"
    touch(sel)
    recompute_issued_invoice_jurisdiction_fees(sel["registration_request_id"])
    return success_obj(serialize(sel), 200)
