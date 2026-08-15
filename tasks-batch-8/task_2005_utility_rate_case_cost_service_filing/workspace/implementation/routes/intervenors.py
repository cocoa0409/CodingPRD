"""Intervenor endpoints (PRD 3.9)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_INTERVENOR_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import new_record, public, recompute_proposal_counts, touch
from validate import get_body, no_unknown_fields, req_str, require_fk, require_path_resource

bp = Blueprint("intervenors", __name__)


@bp.post("/intervenors")
def create_intervenor():
    body = get_body()
    no_unknown_fields(body, {"rate_case_id", "party_name", "representative_name", "contact_email"})
    rate_case_id = req_str(body, "rate_case_id")
    party_name = req_str(body, "party_name")
    representative_name = req_str(body, "representative_name")
    contact_email = req_str(body, "contact_email")
    authorized(["IntervenorRep"])
    require_fk("rate_cases", rate_case_id, "rate_case_id")
    rec = new_record("intervenors", {
        "rate_case_id": rate_case_id,
        "party_name": party_name,
        "representative_name": representative_name,
        "contact_email": contact_email,
        "status": "PARTY",
    })
    return success_object(public(rec), status=201)


@bp.get("/intervenors")
def list_intervenors():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
    }
    return list_response("intervenors", filters)


@bp.get("/intervenors/<intervenor_id>")
def get_intervenor(intervenor_id):
    return get_one("intervenors", intervenor_id)


@bp.post("/intervenors/<intervenor_id>/withdraw")
def withdraw_intervenor(intervenor_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["IntervenorRep", "CommissionStaff"])
    # Ownership (p3): an IntervenorRep may withdraw only their own party; the
    # party id is the path parameter, so the check needs no load.
    if caller.role == "IntervenorRep" and caller.user_id != intervenor_id:
        raise_error(ERR_FORBIDDEN_OWNERSHIP, "an IntervenorRep may withdraw only their own party")
    party = require_path_resource("intervenors", intervenor_id)
    if party["status"] != "PARTY":
        raise_error(ERR_INVALID_INTERVENOR_STATE, "intervenor is not PARTY")
    # Hop 1: party -> WITHDRAWN
    party["status"] = "WITHDRAWN"
    touch(party)
    # Hop 2: its open data requests -> WITHDRAWN; hop 3: leaving OVERDUE
    # decrements the case counter
    for dr in db["data_requests"].values():
        if (
            dr.get("issuing_intervenor_id") == party["id"]
            and dr["status"] in ("ISSUED", "OBJECTED", "RESPOND_REQUIRED", "OVERDUE")
        ):
            was_overdue = dr["status"] == "OVERDUE"
            dr["status"] = "WITHDRAWN"
            touch(dr)
            if was_overdue:
                case = db["rate_cases"].get(dr["rate_case_id"])
                if case is not None:
                    case["overdue_data_request_count"] -= 1
                    touch(case)
    # Hop 4: its PENDING signatory rows -> VOID; affected proposals recompute
    affected = set()
    for sig in db["settlement_signatories"].values():
        if sig["intervenor_id"] == party["id"] and sig["status"] == "PENDING":
            sig["status"] = "VOID"
            touch(sig)
            affected.add(sig["settlement_proposal_id"])
    for pid in affected:
        proposal = db["settlement_proposals"].get(pid)
        if proposal is not None:
            recompute_proposal_counts(proposal)
    return success_object(public(party))
