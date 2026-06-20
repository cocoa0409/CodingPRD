"""Benefit-trigger certification endpoints (PRD §3.3)."""
from flask import Blueprint, request

import errors
from db import STORE, new_id
from middleware import authenticate, authorize
from response import object_response, array_response, now_iso
from services import common, serialize, lookup, calc

bp = Blueprint("triggers", __name__)


@bp.route("/policies/<rid>/trigger-certifications", methods=["POST"])
def create_certification(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor"])
    pol = lookup.policy_or_404(rid)
    body = common.get_json_body()

    if "adl_deficiencies" not in body or body["adl_deficiencies"] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "adl_deficiencies required")
    adl = body["adl_deficiencies"]
    if not isinstance(adl, list):
        raise errors.err(errors.ERR_INVALID_REQUEST, "adl_deficiencies must be an array")
    cognitive = common.optional_bool(body, "cognitive_impairment", False)

    supersedes_id = body.get("supersedes_id")
    if supersedes_id is not None:
        if not isinstance(supersedes_id, str):
            raise errors.err(errors.ERR_INVALID_REQUEST, "supersedes_id must be a string")
        lookup.trigger_cert_or_404(supersedes_id)

    decision = calc.trigger_decision(adl, cognitive)

    cid = new_id()
    rec = {
        "id": cid,
        "policy_id": rid,
        "adl_deficiencies": adl,
        "cognitive_impairment": cognitive,
        "decision": decision,
        "assessed_by_id": caller.user_id,
        "supersedes_id": supersedes_id,
        "created_at": now_iso(),
        "_seq": STORE.next_seq(),
    }
    STORE.trigger_certifications[cid] = rec
    return object_response(serialize.trigger_certification(rec), 201)


@bp.route("/policies/<rid>/trigger-certifications", methods=["GET"])
def list_policy_certifications(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor", "ClaimsExaminer", "Underwriter"])
    lookup.policy_or_404(rid)
    records = [c for c in STORE.trigger_certifications.values() if c["policy_id"] == rid]
    # Newest first (PRD §2.3 exception).
    records = sorted(records, key=lambda c: c["_seq"], reverse=True)
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.trigger_certification(c) for c in page],
                          limit, offset, total)


@bp.route("/trigger-certifications/<rid>", methods=["GET"])
def get_certification(rid):
    caller = authenticate()
    authorize(caller, ["CareAssessor", "ClaimsExaminer", "Underwriter"])
    rec = lookup.trigger_cert_or_404(rid)
    return object_response(serialize.trigger_certification(rec), 200)


@bp.route("/trigger-certifications", methods=["GET"])
def list_certifications():
    caller = authenticate()
    authorize(caller, ["CareAssessor", "ClaimsExaminer"])
    records = list(STORE.trigger_certifications.values())
    policy_id = request.args.get("policy_id")
    supersedes_id = request.args.get("supersedes_id")
    if policy_id is not None:
        records = [c for c in records if c["policy_id"] == policy_id]
    if supersedes_id is not None:
        records = [c for c in records if c["supersedes_id"] == supersedes_id]
    records = sorted(records, key=lambda c: c["_seq"])
    page, limit, offset, total = common.paginate(records)
    return array_response([serialize.trigger_certification(c) for c in page],
                          limit, offset, total)
