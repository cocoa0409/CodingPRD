from flask import Blueprint, request

from clock import clock
from db import db, stamp_create, touch, new_id, now_iso
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services import calc
from validate import (
    get_body, req_str, req_int, pagination_params,
)

bp = Blueprint("proposals", __name__)

NAMED_SET_ASIDES = {"EIGHT_A", "SDVOSB", "WOSB", "HUBZONE"}


@bp.route("/proposals", methods=["POST"])
def create_proposal():
    auth(["Vendor"])
    body = get_body()
    solicitation_id = req_str(body, "solicitation_id")
    vendor_id = req_str(body, "vendor_id")
    total_price = req_int(body, "total_price_cents", minimum=0)

    # Existence sweep left-to-right.
    get_or_404(db.solicitations, solicitation_id)
    get_or_404(db.vendors, vendor_id)

    entity = {
        "solicitation_id": solicitation_id,
        "vendor_id": vendor_id,
        "total_price_cents": total_price,
        "pinned_vendor_version": None,
        "status": "DRAFT",
        "merit_score": None,
        "value_score": None,
        "_scores_revised": False,
    }
    stamp_create(entity)
    db.proposals[entity["id"]] = entity
    return object_response(entity, status=201)


@bp.route("/proposals/<prop_id>", methods=["GET"])
def get_proposal(prop_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.proposals, prop_id))


@bp.route("/proposals", methods=["GET"])
def list_proposals():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    sol = request.args.get("solicitation_id")
    vendor = request.args.get("vendor_id")
    status = request.args.get("status")
    limit, offset = pagination_params()
    items = list(db.proposals.values())
    if sol is not None:
        items = [p for p in items if p["solicitation_id"] == sol]
    if vendor is not None:
        items = [p for p in items if p["vendor_id"] == vendor]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---- FactorScores ----

@bp.route("/proposals/<prop_id>/scores", methods=["POST"])
def add_score(prop_id):
    auth(["Vendor", "ContractingOfficer"])
    proposal = get_or_404(db.proposals, prop_id)
    body = get_body()
    # Existence of the body-referenced factor (priority 4) precedes the
    # raw_score range check (priority 19, ERR_INVALID_REQUEST), per PRD §3.8.
    factor_id = req_str(body, "factor_id")
    factor = get_or_404(db.factors, factor_id)

    # Scores are attached while the proposal is DRAFT (initial scoring), and revised
    # while it is UNACCEPTABLE to feed the re-evaluation loop (PRD §3.3: re-evaluation
    # is "permitted only when ... the factor scores have been revised since the prior
    # scoring"). Any other status cannot accept scores.
    if proposal["status"] not in ("DRAFT", "UNACCEPTABLE"):
        raise err("ERR_INVALID_STATE", "Factor scores can only be attached to a DRAFT or UNACCEPTABLE proposal.")

    raw_score = req_int(body, "raw_score", minimum=0, maximum=100)

    # A factor is scored at most once per proposal: revising a factor's score
    # replaces the prior one so merit/acceptability read the revised value.
    existing = next(
        (fs for fs in db.factor_scores.values()
         if fs["proposal_id"] == prop_id and fs["factor_id"] == factor_id),
        None,
    )
    if existing is not None:
        existing["raw_score"] = raw_score
        touch(existing)
        if proposal["status"] == "UNACCEPTABLE":
            proposal["_scores_revised"] = True
        return object_response(existing, status=201)

    score = {
        "proposal_id": prop_id,
        "factor_id": factor_id,
        "raw_score": raw_score,
    }
    stamp_create(score)
    db.factor_scores[score["id"]] = score
    if proposal["status"] == "UNACCEPTABLE":
        proposal["_scores_revised"] = True
    return object_response(score, status=201)


@bp.route("/proposals/<prop_id>/scores", methods=["GET"])
def list_proposal_scores(prop_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    get_or_404(db.proposals, prop_id)
    limit, offset = pagination_params()
    items = [fs for fs in db.factor_scores.values() if fs["proposal_id"] == prop_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/factor-scores/<score_id>", methods=["GET"])
def get_factor_score(score_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.factor_scores, score_id))


@bp.route("/factor-scores", methods=["GET"])
def list_factor_scores():
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    proposal_id = request.args.get("proposal_id")
    factor_id = request.args.get("factor_id")
    limit, offset = pagination_params()
    items = list(db.factor_scores.values())
    if proposal_id is not None:
        items = [fs for fs in items if fs["proposal_id"] == proposal_id]
    if factor_id is not None:
        items = [fs for fs in items if fs["factor_id"] == factor_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


# ---- transitions ----

@bp.route("/proposals/<prop_id>/submit", methods=["POST"])
def submit_proposal(prop_id):
    auth(["Vendor"])
    proposal = get_or_404(db.proposals, prop_id)
    if proposal["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT proposal can be submitted.")

    sol = db.solicitations.get(proposal["solicitation_id"])
    vendor = db.vendors.get(proposal["vendor_id"])
    # These were validated on create; guard anyway.
    if sol is None or vendor is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")

    # State precondition: parent solicitation OPEN or AMENDED.
    if sol["status"] not in ("OPEN", "AMENDED"):
        raise err("ERR_INVALID_STATE", "Parent solicitation is not accepting proposals.")

    # Business rules, in priority order (set-aside #7, registration #8, deadline #9).
    # Set-aside eligibility.
    if sol["set_aside_type"] == "SMALL_BUSINESS":
        if vendor["employee_count"] > sol["naics_size_threshold"]:
            raise err("ERR_SET_ASIDE_INELIGIBLE", "Vendor exceeds the small-business size standard.")
    elif sol["set_aside_type"] in NAMED_SET_ASIDES:
        if sol["set_aside_type"] not in vendor["set_aside_certifications"]:
            raise err("ERR_SET_ASIDE_INELIGIBLE", "Vendor lacks the required set-aside certification.")

    # Registration active and not expired.
    if vendor["sam_status"] != "ACTIVE" or not (vendor["_expires_dt"] > clock.now()):
        raise err("ERR_REGISTRATION_NOT_ACTIVE", "Vendor registration is not active or has lapsed.")

    # Deadline (inclusive).
    if not (clock.now() <= sol["_close_dt"]):
        raise err("ERR_DEADLINE_PASSED", "Submission past the deadline.")

    # A factor score must exist for every evaluation factor of the solicitation.
    sol_factor_ids = {f["id"] for f in db.factors.values()
                      if f["solicitation_id"] == sol["id"]}
    scored_factor_ids = {fs["factor_id"] for fs in db.factor_scores.values()
                         if fs["proposal_id"] == prop_id}
    if not sol_factor_ids.issubset(scored_factor_ids):
        raise err("ERR_VALIDATION", "A factor score is required for every evaluation factor.")

    proposal["status"] = "SUBMITTED"
    proposal["pinned_vendor_version"] = vendor["version"]
    touch(proposal)
    return object_response(proposal)


@bp.route("/proposals/<prop_id>/begin-evaluation", methods=["POST"])
def begin_evaluation(prop_id):
    auth(["ContractingOfficer"])
    proposal = get_or_404(db.proposals, prop_id)
    sol = db.solicitations.get(proposal["solicitation_id"])

    if proposal["status"] == "SUBMITTED":
        if sol is None or sol["status"] != "CLOSED":
            raise err("ERR_INVALID_STATE", "Parent solicitation must be CLOSED.")
    elif proposal["status"] == "UNACCEPTABLE":
        if sol is None or sol["status"] != "CLOSED":
            raise err("ERR_INVALID_STATE", "Parent solicitation must be CLOSED.")
        if not proposal.get("_scores_revised"):
            raise err("ERR_INVALID_STATE", "Factor scores must be revised before re-evaluation.")
    else:
        raise err("ERR_INVALID_STATE", "Proposal is not in a state that can begin evaluation.")

    proposal["status"] = "UNDER_EVALUATION"
    proposal["_scores_revised"] = False
    touch(proposal)
    return object_response(proposal)


@bp.route("/proposals/<prop_id>/score", methods=["POST"])
def score_proposal(prop_id):
    auth(["ContractingOfficer"])
    proposal = get_or_404(db.proposals, prop_id)
    if proposal["status"] != "UNDER_EVALUATION":
        raise err("ERR_INVALID_STATE", "Only a proposal under evaluation can be scored.")

    sol = db.solicitations.get(proposal["solicitation_id"])

    if calc.is_acceptable(prop_id):
        merit = calc.compute_merit_score(prop_id)
        proposal["status"] = "ACCEPTABLE"
        proposal["merit_score"] = merit
        if sol is not None and sol["evaluation_method"] == "TRADEOFF":
            proposal["value_score"] = calc.compute_value_score(proposal, sol, merit)
        else:
            proposal["value_score"] = None
    else:
        proposal["status"] = "UNACCEPTABLE"
        proposal["merit_score"] = None
        proposal["value_score"] = None

    touch(proposal)
    return object_response(proposal)
