"""SettlementProposal endpoints (PRD 3.5): OCC-guarded create-with-supersede."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_CASE_STATE,
    ERR_INVALID_PROPOSAL_STATE,
    ERR_PROPOSAL_NOT_SUPERSEDABLE,
    ERR_SETTLEMENT_ABOVE_FILED,
    ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import (
    new_record,
    proposals_of_case,
    public,
    recompute_proposal_counts,
    touch,
)
from validate import (
    get_body,
    no_unknown_fields,
    req_int,
    req_str,
    require_fk,
    require_path_resource,
)

bp = Blueprint("settlement_proposals", __name__)


@bp.post("/settlement-proposals")
def create_proposal():
    body = get_body()
    no_unknown_fields(body, {
        "rate_case_id", "proposed_revenue_requirement_cents", "terms",
        "expected_rate_case_version",
    })
    rate_case_id = req_str(body, "rate_case_id")
    proposed_rr = req_int(body, "proposed_revenue_requirement_cents")
    terms = req_str(body, "terms")
    expected_version = req_int(body, "expected_rate_case_version")
    authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    # State guards (p6): phase, then supersede-ability of the incumbent
    if case["status"] != "SETTLEMENT":
        raise_error(ERR_INVALID_CASE_STATE, "settlement rounds require the case in SETTLEMENT")
    for p in proposals_of_case(case["id"]):
        if p["status"] in ("ASSENTED", "RECOMMENDED", "ADOPTED"):
            raise_error(ERR_PROPOSAL_NOT_SUPERSEDABLE,
                        "a proposal in ASSENTED, RECOMMENDED, or ADOPTED blocks a new round")
    # Fiscal (p11)
    if proposed_rr > case["proposed_revenue_requirement_cents"]:
        raise_error(ERR_SETTLEMENT_ABOVE_FILED,
                    "settlement revenue requirement exceeds the filed claim")
    # OCC (p12)
    if expected_version != case["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_rate_case_version does not match the case's current version")
    # Supersede the incumbent DRAFT / UNDER_NEGOTIATION round
    for p in proposals_of_case(case["id"]):
        if p["status"] in ("DRAFT", "UNDER_NEGOTIATION"):
            p["status"] = "SUPERSEDED"
            touch(p)
            for sig in db["settlement_signatories"].values():
                if sig["settlement_proposal_id"] == p["id"] and sig["status"] in ("PENDING", "SIGNED"):
                    sig["status"] = "VOID"
                    touch(sig)
            recompute_proposal_counts(p)
    existing_rounds = [p["round_number"] for p in proposals_of_case(case["id"])]
    rec = new_record("settlement_proposals", {
        "rate_case_id": rate_case_id,
        "round_number": (max(existing_rounds) + 1) if existing_rounds else 1,
        "proposed_revenue_requirement_cents": proposed_rr,
        "terms": terms,
        "signature_count": 0,
        "required_signature_count": 0,
        "status": "DRAFT",
    })
    touch(case)
    return success_object(public(rec), status=201)


@bp.get("/settlement-proposals")
def list_proposals():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "status": query_arg("status"),
    }
    return list_response("settlement_proposals", filters)


@bp.get("/settlement-proposals/<proposal_id>")
def get_proposal(proposal_id):
    return get_one("settlement_proposals", proposal_id)


@bp.post("/settlement-proposals/<proposal_id>/circulate")
def circulate_proposal(proposal_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["UtilityFiler"])
    proposal = require_path_resource("settlement_proposals", proposal_id)
    if proposal["status"] != "DRAFT":
        raise_error(ERR_INVALID_PROPOSAL_STATE, "circulate requires DRAFT")
    case = db["rate_cases"].get(proposal["rate_case_id"])
    if case is None or case["status"] != "SETTLEMENT":
        raise_error(ERR_INVALID_CASE_STATE, "circulate requires the case in SETTLEMENT")
    parties = [
        i for i in db["intervenors"].values()
        if i["rate_case_id"] == proposal["rate_case_id"] and i["status"] == "PARTY"
    ]
    parties.sort(key=lambda i: (i["created_at"], i["party_name"]))
    for party in parties:
        new_record("settlement_signatories", {
            "settlement_proposal_id": proposal["id"],
            "intervenor_id": party["id"],
            "signed_at": None,
            "status": "PENDING",
        })
    proposal["required_signature_count"] = len(parties)
    proposal["signature_count"] = 0
    proposal["status"] = "UNDER_NEGOTIATION"
    touch(proposal)
    return success_object(public(proposal))


@bp.post("/settlement-proposals/<proposal_id>/recommend")
def recommend_proposal(proposal_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["ALJ"])
    proposal = require_path_resource("settlement_proposals", proposal_id)
    if proposal["status"] != "ASSENTED":
        raise_error(ERR_INVALID_PROPOSAL_STATE, "recommend requires ASSENTED")
    proposal["status"] = "RECOMMENDED"
    touch(proposal)
    return success_object(public(proposal))


@bp.post("/settlement-proposals/<proposal_id>/remand")
def remand_proposal(proposal_id):
    body = get_body()
    no_unknown_fields(body, {"remand_reason"})
    req_str(body, "remand_reason")
    authorized(["ALJ"])
    proposal = require_path_resource("settlement_proposals", proposal_id)
    if proposal["status"] != "ASSENTED":
        raise_error(ERR_INVALID_PROPOSAL_STATE, "remand requires ASSENTED")
    proposal["status"] = "REMANDED"
    touch(proposal)
    return success_object(public(proposal))
