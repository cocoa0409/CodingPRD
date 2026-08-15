"""Sample requests, committee votes, fulfillment, cancellation."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from clock import now
from errors import raise_error
from middleware import (
    require_roles,
    get_json_body,
    check_known_fields,
    require_fields,
    validate_enum,
    validate_string,
    validate_use_list,
    validate_positive_number,
    parse_pagination,
    ALL_ROLES,
)
from response import success_object, success_list
from serializers import request_out, vote_out
from services.common import make_record, make_audit_record, get_or_404, touch, round3, round0
from services.specimen import consent_is_effective, scope_covers, recompute_volumes

bp = Blueprint("requests", __name__)

SPECIMEN_TYPES = {"BLOOD", "SALIVA", "TISSUE", "PLASMA"}
MAX_REVISION_ROUNDS = 2
COMMITTEE_SIZE = 5
QUORUM_COUNT = 3  # ceil(5 * 0.6)
REJECT_THRESHOLD = COMMITTEE_SIZE - QUORUM_COUNT + 1  # 3
SURCHARGE_UTILIZATION = 0.8
SURCHARGE_MULT = 1.25
BASE_FEE_CENTS = 500
RATE_CENTS_PER_ML = 2.5


@bp.route("/biobank/sample-requests", methods=["POST"])
def create_request():
    user_id, _ = require_roles({"Researcher"})
    body = get_json_body()
    check_known_fields(body, {
        "title", "required_uses", "specimen_type", "volume_needed_ml", "sharing_agreement_id",
    })
    require_fields(body, ["title", "required_uses", "specimen_type", "volume_needed_ml", "sharing_agreement_id"])
    title = validate_string(body["title"], "title")
    required_uses = validate_use_list(body["required_uses"], "required_uses", non_empty=True)
    specimen_type = validate_enum(body["specimen_type"], SPECIMEN_TYPES, "specimen_type")
    volume_needed_ml = validate_positive_number(body["volume_needed_ml"], "volume_needed_ml")
    agreement_id = validate_string(body["sharing_agreement_id"], "sharing_agreement_id")
    agreement = db.sharing_agreements.get(agreement_id)
    if agreement is None:
        raise_error("ERR_NOT_FOUND", f"sharing agreement not found: {agreement_id}")
    if not set(required_uses).issubset(set(agreement["scope_uses"])):
        raise_error("ERR_AGREEMENT_SCOPE_INSUFFICIENT", "Agreement scope does not cover required uses")
    req = make_record(db.sample_requests, {
        "requester_user_id": user_id,
        "title": title,
        "required_uses": list(required_uses),
        "specimen_type": specimen_type,
        "volume_needed_ml": volume_needed_ml,
        "sharing_agreement_id": agreement_id,
        "status": "DRAFT",
        "revision_round": 0,
        "votes_for": 0,
        "votes_against": 0,
        "charged_volume_ml": 0,
        "fulfilled_volume_ml": 0,
        "handling_fee_cents": 0,
        "recall_required": False,
    })
    return success_object(request_out(req), status=201)


@bp.route("/biobank/sample-requests", methods=["GET"])
def list_requests():
    require_roles(ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.sample_requests.values())
    agreement_id = request.args.get("sharing_agreement_id")
    status = request.args.get("status")
    if agreement_id is not None:
        items = [r for r in items if r["sharing_agreement_id"] == agreement_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([request_out(r) for r in page], limit, offset, total)


@bp.route("/biobank/sample-requests/<requestId>", methods=["GET"])
def get_request(requestId):
    require_roles(ALL_ROLES)
    req = get_or_404(db.sample_requests, requestId, "sample request")
    return success_object(request_out(req))


@bp.route("/biobank/sample-requests/<requestId>/submit", methods=["POST"])
def submit_request(requestId):
    user_id, _ = require_roles({"Researcher"})
    req = get_or_404(db.sample_requests, requestId, "sample request")
    get_json_body()
    if req["requester_user_id"] != user_id:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS", "Only the requester may submit this request")
    if req["status"] == "DRAFT":
        req["status"] = "UNDER_REVIEW"
    elif req["status"] == "REVISION_REQUESTED":
        if req["revision_round"] >= MAX_REVISION_ROUNDS:
            raise_error("ERR_MAX_REVISION_ROUNDS", "Revision round cap reached")
        req["revision_round"] += 1
        req["status"] = "UNDER_REVIEW"
    else:
        raise_error("ERR_INVALID_STATE", "Request must be DRAFT or REVISION_REQUESTED to submit")
    touch(req)
    return success_object(request_out(req))


@bp.route("/biobank/sample-requests/<id>/votes", methods=["POST"])
def cast_vote(id):
    user_id, _ = require_roles({"CommitteeReviewer"})
    req = get_or_404(db.sample_requests, id, "sample request")
    body = get_json_body()
    check_known_fields(body, {"decision", "rationale"})
    require_fields(body, ["decision", "rationale"])
    decision = validate_enum(body["decision"], {"APPROVE", "REJECT"}, "decision")
    rationale = body["rationale"]
    if not isinstance(rationale, str):
        raise_error("ERR_INVALID_REQUEST", "rationale must be a string")
    # Order: UNDER_REVIEW -> SoD -> duplicate -> rationale length.
    if req["status"] != "UNDER_REVIEW":
        raise_error("ERR_REQUEST_NOT_UNDER_REVIEW", "Request is not UNDER_REVIEW")
    if req["requester_user_id"] == user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "Reviewer may not vote on own request")
    current_round = req["revision_round"]
    for v in db.review_votes.values():
        if (
            v["sample_request_id"] == req["id"]
            and v["reviewer_user_id"] == user_id
            and v["round"] == current_round
        ):
            raise_error("ERR_DUPLICATE_VOTE", "Reviewer already voted in this round")
    if len(rationale) < 20:
        raise_error("ERR_JUSTIFICATION_TOO_SHORT", "rationale must be at least 20 characters")
    vote = make_audit_record(db.review_votes, {
        "sample_request_id": req["id"],
        "reviewer_user_id": user_id,
        "decision": decision,
        "rationale": rationale,
        "round": current_round,
    })
    if decision == "APPROVE":
        req["votes_for"] += 1
    else:
        req["votes_against"] += 1
    if req["votes_for"] >= QUORUM_COUNT:
        req["status"] = "APPROVED"
    elif req["votes_against"] >= REJECT_THRESHOLD:
        req["status"] = "REJECTED"
    touch(req)
    return success_object(vote_out(vote), status=201)


@bp.route("/biobank/sample-requests/<id>/votes", methods=["GET"])
def list_votes(id):
    require_roles(ALL_ROLES)
    req = get_or_404(db.sample_requests, id, "sample request")
    limit, offset = parse_pagination()
    current_round = req["revision_round"]
    items = [
        v for v in db.review_votes.values()
        if v["sample_request_id"] == req["id"] and v["round"] == current_round
    ]
    items.sort(key=lambda v: v["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([vote_out(v) for v in page], limit, offset, total)


@bp.route("/biobank/sample-requests/<requestId>/request-revision", methods=["POST"])
def request_revision(requestId):
    user_id, _ = require_roles({"CommitteeReviewer"})
    req = get_or_404(db.sample_requests, requestId, "sample request")
    body = get_json_body()
    check_known_fields(body, {"rationale"})
    require_fields(body, ["rationale"])
    rationale = body["rationale"]
    if not isinstance(rationale, str):
        raise_error("ERR_INVALID_REQUEST", "rationale must be a string")
    if req["status"] != "UNDER_REVIEW":
        raise_error("ERR_REQUEST_NOT_UNDER_REVIEW", "Request is not UNDER_REVIEW")
    if req["revision_round"] >= MAX_REVISION_ROUNDS:
        raise_error("ERR_MAX_REVISION_ROUNDS", "Revision round cap reached")
    if len(rationale) < 20:
        raise_error("ERR_JUSTIFICATION_TOO_SHORT", "rationale must be at least 20 characters")
    req["status"] = "REVISION_REQUESTED"
    req["votes_for"] = 0
    req["votes_against"] = 0
    touch(req)
    return success_object(request_out(req))


@bp.route("/biobank/sample-requests/<requestId>/fulfill", methods=["POST"])
def fulfill_request(requestId):
    require_roles({"BiobankAdmin"})
    req = get_or_404(db.sample_requests, requestId, "sample request")
    get_json_body()
    if req["status"] != "APPROVED":
        raise_error("ERR_REQUEST_NOT_APPROVED", "Request is not APPROVED")

    # Consent checks across the candidate pool first (priority 5/6), then
    # agreement effectiveness (10), inventory (16), quota (17).
    candidate_consents = []
    for a in db.aliquots.values():
        if a["status"] != "IN_STORAGE":
            continue
        sp = db.specimens.get(a["specimen_id"])
        if sp is None:
            continue
        if sp["lifecycle_status"] != "IN_STORAGE" or sp["viability_status"] != "USABLE":
            continue
        if sp["specimen_type"] != req["specimen_type"]:
            continue
        consent = db.consent_records.get(sp["consent_record_id"])
        if consent is None:
            continue
        candidate_consents.append(consent)
    for consent in candidate_consents:
        if not consent_is_effective(consent):
            raise_error("ERR_CONSENT_NOT_ACTIVE", "A candidate specimen's consent is not ACTIVE")
    for consent in candidate_consents:
        if not scope_covers(consent, req["required_uses"]):
            raise_error("ERR_CONSENT_SCOPE_VIOLATION", "Consent scope does not cover required uses")

    agreement = db.sharing_agreements.get(req["sharing_agreement_id"])
    if agreement is None:
        raise_error("ERR_NOT_FOUND", f"sharing agreement not found: {req['sharing_agreement_id']}")
    current = now()
    if (
        agreement["status"] != "ACTIVE"
        or current < agreement["effective_from"]
        or current >= agreement["effective_to"]
    ):
        raise_error("ERR_AGREEMENT_NOT_EFFECTIVE", "Agreement is not ACTIVE or outside its effective window")

    # Deterministic selector.
    eligible = []
    for a in db.aliquots.values():
        if a["status"] != "IN_STORAGE":
            continue
        sp = db.specimens.get(a["specimen_id"])
        if sp is None:
            continue
        if sp["lifecycle_status"] != "IN_STORAGE" or sp["viability_status"] != "USABLE":
            continue
        if sp["specimen_type"] != req["specimen_type"]:
            continue
        consent = db.consent_records.get(sp["consent_record_id"])
        if consent is None or not consent_is_effective(consent):
            continue
        if not scope_covers(consent, req["required_uses"]):
            continue
        eligible.append((sp["collected_at"], a["created_at"], a))
    eligible.sort(key=lambda t: (t[0], t[1]))

    selected = []
    cumulative = Decimal("0")
    needed = Decimal(str(req["volume_needed_ml"]))
    for _, _, a in eligible:
        if cumulative >= needed:
            break
        selected.append(a)
        cumulative += Decimal(str(a["initial_volume_ml"]))
    if cumulative < needed:
        raise_error("ERR_INSUFFICIENT_INVENTORY", "Eligible pool cannot cover volume_needed_ml")

    # Quota charge in pinned order.
    V = sum(Decimal(str(a["initial_volume_ml"])) for a in selected)
    total = Decimal(str(agreement["total_committed_volume_ml"]))
    U_pre = Decimal(str(agreement["fulfilled_volume_ml"])) / total if total > 0 else Decimal("0")
    M = Decimal("1.25") if U_pre >= Decimal("0.8") else Decimal("1.0")
    charge = (V * M).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    remaining = Decimal(str(agreement["remaining_volume_ml"]))
    if charge > remaining:
        raise_error("ERR_INSUFFICIENT_QUOTA", "Computed charge exceeds agreement remaining volume")

    # Handling fee: round per aliquot, then sum.
    fee_total = 0
    for a in selected:
        raw = Decimal(str(BASE_FEE_CENTS)) + Decimal(str(a["initial_volume_ml"])) * Decimal(str(RATE_CENTS_PER_ML))
        fee_total += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Commit: reservations + ledger debit.
    charge_f = float(charge)
    for a in selected:
        a["status"] = "RESERVED"
        a["reserved_for_request_id"] = req["id"]
        a["fulfill_request_id"] = req["id"]
        touch(a)
        sp = db.specimens[a["specimen_id"]]
        recompute_volumes(sp)
    agreement["reserved_volume_ml"] = round(agreement["reserved_volume_ml"] + charge_f, 3)
    agreement["remaining_volume_ml"] = round(agreement["remaining_volume_ml"] - charge_f, 3)
    touch(agreement)
    req["charged_volume_ml"] = charge_f
    req["handling_fee_cents"] = fee_total
    touch(req)
    return success_object(request_out(req))


@bp.route("/biobank/sample-requests/<requestId>/cancel", methods=["POST"])
def cancel_request(requestId):
    user_id, _ = require_roles({"Researcher"})
    req = get_or_404(db.sample_requests, requestId, "sample request")
    get_json_body()
    if req["requester_user_id"] != user_id:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS", "Only the requester may cancel this request")
    if req["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED"):
        raise_error("ERR_INVALID_STATE", "Request cannot be cancelled from its current state")
    if req["status"] == "APPROVED":
        # Release compensation.
        for a in db.aliquots.values():
            if a["status"] == "RESERVED" and a["reserved_for_request_id"] == req["id"]:
                a["status"] = "IN_STORAGE"
                a["reserved_for_request_id"] = None
                a.pop("fulfill_request_id", None)
                touch(a)
                sp = db.specimens.get(a["specimen_id"])
                if sp is not None:
                    recompute_volumes(sp)
        agreement = db.sharing_agreements.get(req["sharing_agreement_id"])
        if agreement is not None and req["charged_volume_ml"]:
            charge = req["charged_volume_ml"]
            agreement["reserved_volume_ml"] = round(agreement["reserved_volume_ml"] - charge, 3)
            agreement["remaining_volume_ml"] = round(agreement["remaining_volume_ml"] + charge, 3)
            touch(agreement)
        req["charged_volume_ml"] = 0
    req["status"] = "CANCELLED"
    touch(req)
    return success_object(request_out(req))
