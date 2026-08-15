"""DistributionRequest workflow: create, review loop, voting, disbursement."""

from flask import Blueprint, request

import clock
import db
import serialize
from errors import (ApiError, ERR_NOT_OWN_RESOURCE, ERR_RESOURCE_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_TRUST_NOT_ACTIVE, ERR_STALE_VERSION,
                    ERR_REQUEST_NOT_VOTING, ERR_REQUEST_NOT_APPROVED,
                    ERR_MEMBER_NOT_ACTIVE, ERR_PURPOSE_OUTSIDE_STANDARD,
                    ERR_BENEFICIARY_NOT_ACTIVE, ERR_COMMITTEE_QUORUM_UNAVAILABLE,
                    ERR_INSUFFICIENT_AVAILABLE_BALANCE, ERR_CROSS_TRUST_REFERENCE,
                    ERR_DUPLICATE_VOTE)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import distribution_request_json, vote_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("distributions", __name__)

ALLOCATION_SOURCES = {"INCOME_ONLY", "PRINCIPAL_ONLY", "INCOME_FIRST", "PRINCIPAL_FIRST"}
PURPOSE_CATEGORIES = {"HEALTH", "EDUCATION", "MAINTENANCE", "SUPPORT",
                      "TRAVEL", "LUXURY", "OTHER"}
VOTE_VALUES = {"APPROVE", "DECLINE", "ABSTAIN"}
LIST_ROLES = {"TrustOfficer", "TrustExecutive", "TrustOperationsOfficer",
              "CommitteeMember"}
GET_ROLES = LIST_ROLES | {"Beneficiary"}

REVIEW_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFORMATION_REQUESTED")


def _recompute_and_serialize(r):
    calc.recount_tallies(r)
    return distribution_request_json(r)


@bp.route("/trusts/distribution-requests", methods=["POST"])
def create_request():
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("beneficiary_id", "str", True),
        ("amount_cents", "pint", True),
        ("allocation_source", "str", True, ALLOCATION_SOURCES),
        ("purpose_category", "str", True, PURPOSE_CATEGORIES),
        ("purpose_note", "str", False),
        ("expected_trust_account_version", "int", True),
    ])
    require_role(role, {"Beneficiary", "TrustOfficer"})
    # [4] a Beneficiary may file only for themselves
    if role == "Beneficiary" and user_id != v["beneficiary_id"]:
        raise ApiError(ERR_NOT_OWN_RESOURCE, 403,
                       "Beneficiary may only file own distribution requests")
    # [5] existence (body FK ids -> ERR_RESOURCE_NOT_FOUND)
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    bene = find_or_404(db.beneficiaries, v["beneficiary_id"], "Beneficiary")
    # [6] state + OCC
    if trust["status"] != "ACTIVE":
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust must be ACTIVE to file a distribution request")
    if v["expected_trust_account_version"] != trust["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_trust_account_version does not match")
    # [9] cross-entity references
    if bene["trust_id"] != trust["id"]:
        raise ApiError(ERR_CROSS_TRUST_REFERENCE, 422,
                       "Beneficiary belongs to a different trust")
    if bene["status"] != "ACTIVE":
        raise ApiError(ERR_BENEFICIARY_NOT_ACTIVE, 409,
                       "Beneficiary must be ACTIVE")
    r = workflow.new_entity()
    r.update({
        "trust_id": trust["id"],
        "beneficiary_id": bene["id"],
        "amount_cents": v["amount_cents"],
        "allocation_source": v["allocation_source"],
        "purpose_category": v["purpose_category"],
        "purpose_note": v.get("purpose_note"),
        "status": "SUBMITTED",
        "income_portion_cents": 0,
        "principal_portion_cents": 0,
        "approve_count": 0,
        "decline_count": 0,
        "abstain_count": 0,
        "committee_size_snapshot": None,
        "opened_by_user_id": None,
        "decision_at": None,
        "disbursed_at": None,
        "cancelled_reason": None,
    })
    db.distribution_requests[r["id"]] = r
    # pending_distribution_count derives from status; bump trust version
    workflow.bump_trust(trust)
    return ok(_recompute_and_serialize(r), status=201)


@bp.route("/trusts/distribution-requests", methods=["GET"])
def list_requests():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, LIST_ROLES)
    filters = []
    for param in ("trust_id", "beneficiary_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.distribution_requests, filters,
                                      distribution_request_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/distribution-requests/<rid>", methods=["GET"])
def get_request(rid):
    user_id, role = authenticate()
    require_role(role, GET_ROLES)
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    if role == "Beneficiary" and r["beneficiary_id"] != user_id:
        raise ApiError(ERR_NOT_OWN_RESOURCE, 403,
                       "Beneficiary may only read own requests")
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/start-review", methods=["POST"])
def start_review(rid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Request must be SUBMITTED")
    r["status"] = "UNDER_REVIEW"
    workflow.touch(r)
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/request-information", methods=["POST"])
def request_information(rid):
    _, role = authenticate()
    data = get_body()
    validate(data, [("info_request_note", "str", True)])
    require_role(role, {"TrustOfficer"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    if r["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Request must be UNDER_REVIEW")
    r["status"] = "INFORMATION_REQUESTED"
    workflow.touch(r)
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/provide-information", methods=["POST"])
def provide_information(rid):
    user_id, role = authenticate()
    data = get_body()
    validate(data, [("info_response_note", "str", True)])
    require_role(role, {"Beneficiary"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    if r["beneficiary_id"] != user_id:
        raise ApiError(ERR_NOT_OWN_RESOURCE, 403,
                       "Only the requesting beneficiary may provide information")
    if r["status"] != "INFORMATION_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Request must be INFORMATION_REQUESTED")
    r["status"] = "UNDER_REVIEW"
    workflow.touch(r)
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/open-voting", methods=["POST"])
def open_voting(rid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    # [6] state
    if r["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Request must be UNDER_REVIEW")
    trust = db.trusts.get(r["trust_id"])
    if trust is None or trust["status"] != "ACTIVE":
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409, "Trust must be ACTIVE")
    # [7] purpose standard
    if not calc.purpose_permitted(trust["distribution_standard"], r["purpose_category"]):
        raise ApiError(ERR_PURPOSE_OUTSIDE_STANDARD, 422,
                       "purpose_category not permitted by distribution_standard")
    # [9] beneficiary active
    bene = db.beneficiaries.get(r["beneficiary_id"])
    if bene is None or bene["status"] != "ACTIVE":
        raise ApiError(ERR_BENEFICIARY_NOT_ACTIVE, 409,
                       "Beneficiary must be ACTIVE")
    # [10] quorum
    active_members = [m for m in db.committee_members.values()
                      if m["status"] == "ACTIVE"]
    if len(active_members) < calc.QUORUM:
        raise ApiError(ERR_COMMITTEE_QUORUM_UNAVAILABLE, 422,
                       "Fewer than 3 ACTIVE committee members")
    # [11] reservation waterfall (funds last)
    avail_i = serialize.income_balance(trust["id"]) - serialize.reserved_income(trust["id"])
    avail_p = serialize.principal_balance(trust["id"]) - serialize.reserved_principal(trust["id"])
    portions = calc.reservation_waterfall(r["allocation_source"], r["amount_cents"],
                                          avail_i, avail_p)
    if portions is None:
        raise ApiError(ERR_INSUFFICIENT_AVAILABLE_BALANCE, 422,
                       "Reservation waterfall exceeds available balances")
    r["income_portion_cents"], r["principal_portion_cents"] = portions
    r["committee_size_snapshot"] = len(active_members)
    r["approve_count"] = 0
    r["decline_count"] = 0
    r["abstain_count"] = 0
    r["opened_by_user_id"] = user_id
    r["status"] = "VOTING"
    workflow.touch(r)
    workflow.bump_trust(trust)
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/vote", methods=["POST"])
def cast_vote(rid):
    user_id, role = authenticate()
    data = get_body()
    v = validate(data, [("vote", "str", True, VOTE_VALUES)])
    require_role(role, {"CommitteeMember"})
    # [5] existence
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    member = find_or_404(db.committee_members, user_id, "CommitteeMember")
    # [6] state
    if r["status"] != "VOTING":
        raise ApiError(ERR_REQUEST_NOT_VOTING, 409, "Request is not in VOTING")
    if member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409, "Committee member is not ACTIVE")
    # [10] one vote per member per request
    for existing in db.votes.values():
        if (existing["distribution_request_id"] == rid
                and existing["committee_member_id"] == user_id):
            raise ApiError(ERR_DUPLICATE_VOTE, 409,
                           "Member has already voted on this request")
    vote = workflow.new_lean_entity()
    vote.update({
        "distribution_request_id": rid,
        "committee_member_id": user_id,
        "vote": v["vote"],
    })
    db.votes[vote["id"]] = vote
    approve, decline, abstain = calc.recount_tallies(r)
    decision = None
    if approve >= calc.QUORUM:
        decision = "APPROVED"
    elif decline >= calc.QUORUM:
        decision = "DECLINED"
    elif (approve + decline + abstain) == (r["committee_size_snapshot"] or 0) \
            and approve < calc.QUORUM:
        decision = "DECLINED"
    if decision is not None:
        r["status"] = decision
        r["decision_at"] = workflow.now_stamp()
        workflow.touch(r)
        trust = db.trusts.get(r["trust_id"])
        if trust is not None:
            workflow.bump_trust(trust)
    else:
        workflow.touch(r)
    return ok(vote_json(vote), status=201)


@bp.route("/trusts/distribution-requests/<rid>/disburse", methods=["POST"])
def disburse(rid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOperationsOfficer"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    # [6] trust-gate first, then request state (PRD 2.8 ordering)
    trust = db.trusts.get(r["trust_id"])
    if trust is None or trust["status"] != "ACTIVE":
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409, "Trust must be ACTIVE")
    if r["status"] != "APPROVED":
        raise ApiError(ERR_REQUEST_NOT_APPROVED, 409,
                       "Request must be APPROVED to disburse")
    value_date = clock.now_date().isoformat()
    if r["income_portion_cents"] > 0:
        workflow.append_ledger(
            trust["id"], "DISTRIBUTION", "INCOME", -r["income_portion_cents"],
            value_date, source_entity_type="DISTRIBUTION_REQUEST",
            source_entity_id=r["id"])
    if r["principal_portion_cents"] > 0:
        workflow.append_ledger(
            trust["id"], "DISTRIBUTION", "PRINCIPAL", -r["principal_portion_cents"],
            value_date, source_entity_type="DISTRIBUTION_REQUEST",
            source_entity_id=r["id"])
    r["status"] = "DISBURSED"
    r["disbursed_at"] = workflow.now_stamp()
    workflow.touch(r)
    workflow.bump_trust(trust)
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/withdraw", methods=["POST"])
def withdraw(rid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"Beneficiary"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    if r["beneficiary_id"] != user_id:
        raise ApiError(ERR_NOT_OWN_RESOURCE, 403,
                       "Only the owning beneficiary may withdraw")
    if r["status"] not in REVIEW_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Request cannot be withdrawn from its current state")
    r["status"] = "WITHDRAWN"
    workflow.touch(r)
    trust = db.trusts.get(r["trust_id"])
    if trust is not None:
        workflow.bump_trust(trust)
    return ok(_recompute_and_serialize(r))


@bp.route("/trusts/distribution-requests/<rid>/cancel", methods=["POST"])
def cancel(rid):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [("cancelled_reason", "str", True)])
    require_role(role, {"TrustOfficer"})
    r = find_or_404(db.distribution_requests, rid, "DistributionRequest")
    if r["status"] not in serialize.PENDING_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Request cannot be cancelled from its current state")
    r["status"] = "CANCELLED"
    r["cancelled_reason"] = v["cancelled_reason"]
    workflow.touch(r)
    trust = db.trusts.get(r["trust_id"])
    if trust is not None:
        workflow.bump_trust(trust)
    return ok(_recompute_and_serialize(r))
