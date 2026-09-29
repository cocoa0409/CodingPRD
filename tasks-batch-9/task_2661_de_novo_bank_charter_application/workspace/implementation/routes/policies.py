"""Policy document writes: drafting, board adoption, examiner review."""
from flask import Blueprint, g

import calc
import cascade
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate, require_organizer_identity
from routes.helpers import must_get

bp = Blueprint("policies", __name__)

DOMAINS = ("LENDING", "COMPLIANCE_BSA_AML", "INFORMATION_SECURITY", "RISK_MANAGEMENT")
REVIEW_OUTCOMES = ("ACCEPTED", "REJECTED")


@bp.post("/de-novo/policy-documents")
def create_policy():
    authenticate(("LeadOrganizer", "IndependentDirector"))
    data = v.body()
    group_id = v.req_id(data, "group_id")
    domain = v.req_enum(data, "domain", DOMAINS)
    drafted_by_organizer_id = v.req_id(data, "drafted_by_organizer_id")
    document_title = v.req_str(data, "document_title", 1, 160)
    group = must_get("groups", group_id)
    drafter = must_get("organizers", drafted_by_organizer_id)
    require_organizer_identity(group["id"])
    if group["stage"] in ("OPEN", "ABANDONED"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    if drafter["group_id"] != group["id"]:
        raise err("ERR_DRAFTER_NOT_IN_GROUP")
    policy = db.insert("policies", {
        "group_id": group["id"],
        "domain": domain,
        "drafted_by_organizer_id": drafter["id"],
        "adopted_by_organizer_id": None,
        "document_title": document_title,
        "status": "DRAFT",
        "adopted_at": None,
        "finding_note": None,
    })
    db.touch(group)
    db.commit()
    return response.object_response(serialize.policy(policy), 201)


@bp.post("/de-novo/policy-documents/<policy_id>/adopt")
def adopt_policy(policy_id):
    authenticate(("LeadOrganizer", "IndependentDirector"))
    v.body()
    policy = must_get("policies", policy_id)
    actor = require_organizer_identity(policy["group_id"])
    if policy["status"] != "DRAFT":
        raise err("ERR_POLICY_NOT_ADOPTABLE")
    if actor is None or actor["qualification_status"] not in calc.GOOD_QUALIFICATION:
        raise err("ERR_ORGANIZER_NOT_QUALIFIED")
    if g.user_id == policy["drafted_by_organizer_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES_VIOLATION")
    for row in calc.policies_of(policy["group_id"]):
        if (row["id"] != policy["id"] and row["domain"] == policy["domain"]
                and row["status"] in ("BOARD_ADOPTED", "EXAMINER_ACCEPTED")):
            raise err("ERR_POLICY_DOMAIN_ALREADY_ADOPTED")
    policy["status"] = "BOARD_ADOPTED"
    policy["adopted_by_organizer_id"] = g.user_id
    policy["adopted_at"] = db.clock()
    db.touch(policy)
    db.commit()
    return response.object_response(serialize.policy(policy))


@bp.post("/de-novo/policy-documents/<policy_id>/examiner-review")
def review_policy(policy_id):
    authenticate(("CharteringExaminer",))
    data = v.body()
    outcome = v.req_enum(data, "outcome", REVIEW_OUTCOMES)
    finding_note = v.opt_str(data, "finding_note", 1, None)
    policy = must_get("policies", policy_id)
    if policy["status"] not in ("BOARD_ADOPTED", "EXAMINER_ACCEPTED"):
        raise err("ERR_POLICY_NOT_REVIEWABLE")
    if finding_note is not None:
        policy["finding_note"] = finding_note
    if outcome == "ACCEPTED":
        policy["status"] = "EXAMINER_ACCEPTED"
        db.touch(policy)
    else:
        policy["status"] = "REJECTED"
        db.touch(policy)
        cascade.policy_rejected_cascade(policy)
    db.commit()
    return response.object_response(serialize.policy(policy))
