"""Consult responses: get, dual-record documentation, finalize, revise."""

from flask import Blueprint

import clock
import db
import services
import util
from errors import (
    ApiError,
    ERR_DOCUMENTATION_INCOMPLETE,
    ERR_NOT_ASSIGNED_SPECIALIST,
    ERR_NOT_CONSULT_OWNER,
    ERR_RESPONSE_NOT_REBUKED,
    ERR_RESPONSE_NOT_SUBMITTED,
    ERR_REVIEW_REQUIRED_NOT_PASSED,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from util import serialize

bp = Blueprint("responses", __name__)


@bp.route("/econsult/consult-responses/<rid>", methods=["GET"])
def get_response(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("consult_response", services.get_response(rid)), 200)


@bp.route("/econsult/consult-responses/<rid>/documentation", methods=["POST"])
def mark_documentation(rid):
    uid, role = require_roles("ReferringProvider", "Specialist")
    data = util.json_body()
    record_type = util.req_enum(data, "record_type", util.RECORD_TYPES)

    resp = services.get_response(rid)
    consult = db.store["consult_requests"][resp["consult_id"]]

    if record_type == "PCP_NOTE":
        if role != "ReferringProvider" or consult["referring_provider_id"] != uid:
            raise ApiError(
                ERR_NOT_CONSULT_OWNER, 403,
                "Marking the PCP note is the owning referring provider's act",
            )
    else:
        if role != "Specialist" or resp["specialist_id"] != uid:
            raise ApiError(
                ERR_NOT_ASSIGNED_SPECIALIST, 403,
                "Marking the specialist note is the responding specialist's act",
            )

    if resp["status"] != "SUBMITTED":
        raise ApiError(
            ERR_RESPONSE_NOT_SUBMITTED, 409,
            "Documentation requires response status SUBMITTED",
        )

    if record_type == "PCP_NOTE":
        resp["pcp_note_documented"] = True
    else:
        resp["specialist_note_documented"] = True
    resp["documentation_complete"] = (
        resp["pcp_note_documented"] and resp["specialist_note_documented"]
    )
    services.touch(resp)
    return ok(serialize("consult_response", resp), 200)


@bp.route("/econsult/consult-responses/<rid>/finalize", methods=["POST"])
def finalize_response(rid):
    uid, _role = require_roles("Specialist")
    resp = services.get_response(rid)
    if resp["specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_SPECIALIST, 403,
            "Finalization is the responding specialist's act",
        )
    if resp["status"] != "SUBMITTED":
        raise ApiError(
            ERR_RESPONSE_NOT_SUBMITTED, 409,
            "Finalize requires response status SUBMITTED",
        )
    if not resp["documentation_complete"]:
        raise ApiError(
            ERR_DOCUMENTATION_INCOMPLETE, 409,
            "Both the PCP note and the specialist note must be documented",
        )
    if resp["review_required"]:
        passed = any(
            review["response_id"] == resp["id"]
            and review["status"] == "COMPLETED"
            and review["verdict"] == "PASS"
            and review["created_at"] >= resp["last_submitted_at"]
            for review in db.store["quality_reviews"].values()
        )
        if not passed:
            raise ApiError(
                ERR_REVIEW_REQUIRED_NOT_PASSED, 409,
                "A COMPLETED PASS review at or after the latest submission is required",
            )

    consult = db.store["consult_requests"][resp["consult_id"]]
    track = db.store["specialty_tracks"][consult["specialty_track_id"]]
    membership = db.store["panel_memberships"][resp["_membership_id"]]
    final_amount = services.final_response_amount(track, membership, resp)

    for entry in db.store["compensation_entries"].values():
        if entry["consult_id"] != consult["id"] or entry["posture"] != "PROVISIONAL":
            continue
        membership["provisional_balance_cents"] -= entry["amount_cents"]
        if entry["entry_type"] == "RESPONSE_FEE":
            entry["amount_cents"] = final_amount
        entry["posture"] = "POSTED"
        membership["posted_balance_cents"] += entry["amount_cents"]
        services.touch(entry)

    resp["status"] = "FINALIZED"
    services.touch(resp)

    consult["billing_status"] = "CHARGEABLE"
    services.touch(consult)
    services.touch(membership)
    return ok(serialize("consult_response", resp), 200)


@bp.route("/econsult/consult-responses/<rid>/revise", methods=["POST"])
def revise_response(rid):
    uid, _role = require_roles("Specialist")
    data = util.json_body()
    recommendation_text = util.req_str(data, "recommendation_text", min_len=20)
    disposition = util.opt_enum(data, "disposition", util.DISPOSITIONS)

    resp = services.get_response(rid)
    if resp["specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_SPECIALIST, 403,
            "Revision is the responding specialist's act",
        )
    if resp["status"] != "REBUKED":
        raise ApiError(
            ERR_RESPONSE_NOT_REBUKED, 409,
            "Revise requires response status REBUKED",
        )

    resp["recommendation_text"] = recommendation_text
    if disposition is not None:
        resp["disposition"] = disposition
    resp["revision_count"] += 1
    resp["last_submitted_at"] = clock.now()
    resp["pcp_note_documented"] = False
    resp["specialist_note_documented"] = False
    resp["documentation_complete"] = False
    resp["status"] = "SUBMITTED"
    services.touch(resp)

    consult = db.store["consult_requests"][resp["consult_id"]]
    track = db.store["specialty_tracks"][consult["specialty_track_id"]]
    membership = db.store["panel_memberships"][resp["_membership_id"]]
    base = services.provisional_response_base(track, resp["disposition"])
    services.append_entry(membership["id"], consult["id"], "RESPONSE_FEE", base)
    membership["provisional_balance_cents"] += base
    services.touch(membership)
    return ok(serialize("consult_response", resp), 200)
