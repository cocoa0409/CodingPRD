"""Consult requests: create/list/get, OCC-guarded patch and reroute, cancel,
close, clarifications, routing decisions, and responses beneath a consult."""

from flask import Blueprint, request

import clock
import db
import services
import util
from errors import (
    ApiError,
    ERR_CONSULT_ALREADY_TERMINAL,
    ERR_CONSULT_NOT_ASSIGNED,
    ERR_CONSULT_NOT_ANSWERED,
    ERR_CONSULT_NOT_AWAITING_CLARIFICATION,
    ERR_CONSULT_NOT_QUEUED,
    ERR_DUPLICATE_OPEN_CONSULT,
    ERR_MAX_CLARIFICATION_ROUNDS_REACHED,
    ERR_MEMBERSHIP_SUSPENDED,
    ERR_NO_ELIGIBLE_SPECIALIST,
    ERR_NOT_ASSIGNED_SPECIALIST,
    ERR_NOT_CONSULT_OWNER,
    ERR_NOT_FOUND,
    ERR_PROVIDER_INACTIVE,
    ERR_RESPONSE_NOT_FINALIZED,
    ERR_STALE_CONSULT_VERSION,
)
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("consults", __name__)

CANCELLABLE_STATES = ("SUBMITTED", "QUEUED", "ASSIGNED", "CLARIFICATION_REQUESTED")


@bp.route("/econsult/consult-requests", methods=["POST"])
def create_consult():
    uid, _role = require_roles("ReferringProvider")
    data = util.json_body()
    patient_ref = util.req_str(data, "patient_ref")
    track_id = util.req_str(data, "specialty_track_id")
    question_text = util.req_str(data, "question_text", min_len=20)
    icd10_primary = util.req_str(data, "icd10_primary")
    comorbidity_flags = util.opt_str_list(data, "comorbidity_flags", default=[])
    urgency = util.opt_enum(data, "urgency", util.URGENCIES, default="ROUTINE")

    services.get_track(track_id)
    provider = db.store["referring_providers"].get(uid)
    if provider is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Referring provider not found: %s" % uid)

    for existing in db.store["consult_requests"].values():
        if (existing["patient_ref"] == patient_ref
                and existing["specialty_track_id"] == track_id
                and existing["status"] not in services.TERMINAL_CONSULT_STATES):
            raise ApiError(
                ERR_DUPLICATE_OPEN_CONSULT, 409,
                "A non-terminal consult already exists for this patient and track",
            )

    if provider["status"] != "ACTIVE":
        raise ApiError(ERR_PROVIDER_INACTIVE, 409, "Referring provider is not ACTIVE")

    rec = services.base_record()
    rec.update({
        "referring_provider_id": uid,
        "patient_ref": patient_ref,
        "specialty_track_id": track_id,
        "question_text": question_text,
        "icd10_primary": icd10_primary,
        "comorbidity_flags": comorbidity_flags,
        "urgency": urgency,
        "status": "SUBMITTED",
        "billing_status": "UNBILLABLE",
        "assigned_specialist_id": None,
        "assigned_membership_id": None,
        "sla_due_at": None,
        "sla_breached": False,
        "clarification_rounds": 0,
    })
    db.store["consult_requests"][rec["id"]] = rec
    # Inline routing pass: lands ASSIGNED or QUEUED and increments the version.
    services.route_consult(rec)
    return ok(serialize("consult_request", rec), 201)


@bp.route("/econsult/consult-requests", methods=["GET"])
def list_consults():
    require_roles(*ANY_ROLE)
    records = list(db.store["consult_requests"].values())
    for param, field in (
        ("referring_provider_id", "referring_provider_id"),
        ("specialty_track_id", "specialty_track_id"),
        ("assigned_specialist_id", "assigned_specialist_id"),
        ("assigned_membership_id", "assigned_membership_id"),
        ("status", "status"),
    ):
        value = request.args.get(param)
        if value is not None:
            records = [c for c in records if c[field] == value]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("consult_request", page), total, limit, offset)


@bp.route("/econsult/consult-requests/<rid>", methods=["GET"])
def get_consult(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("consult_request", services.get_consult(rid)), 200)


@bp.route("/econsult/consult-requests/<rid>", methods=["PATCH"])
def patch_consult(rid):
    uid, _role = require_roles("ReferringProvider")
    data = util.json_body()
    expected = util.req_int(data, "expected_consult_version")
    question_text = util.opt_str(data, "question_text", min_len=20)
    icd10_primary = util.opt_str(data, "icd10_primary")
    comorbidity_flags = util.opt_str_list(data, "comorbidity_flags")
    urgency = util.opt_enum(data, "urgency", util.URGENCIES)

    consult = services.get_consult(rid)
    if expected != consult["version"]:
        raise ApiError(
            ERR_STALE_CONSULT_VERSION, 412,
            "expected_consult_version does not match the consult's current version",
        )
    if consult["referring_provider_id"] != uid:
        raise ApiError(ERR_NOT_CONSULT_OWNER, 403, "Caller does not own this consult")
    if consult["status"] in services.TERMINAL_CONSULT_STATES:
        raise ApiError(
            ERR_CONSULT_ALREADY_TERMINAL, 409,
            "Operation attempted on a terminal consult",
        )

    if question_text is not None:
        consult["question_text"] = question_text
    if icd10_primary is not None:
        consult["icd10_primary"] = icd10_primary
    if comorbidity_flags is not None:
        consult["comorbidity_flags"] = comorbidity_flags
    if urgency is not None:
        consult["urgency"] = urgency
    services.touch(consult)
    return ok(serialize("consult_request", consult), 200)


@bp.route("/econsult/consult-requests/<rid>/reroute", methods=["POST"])
def reroute_consult(rid):
    require_roles("ProgramCoordinator")
    data = util.json_body()
    expected = util.req_int(data, "expected_consult_version")

    consult = services.get_consult(rid)
    if expected != consult["version"]:
        raise ApiError(
            ERR_STALE_CONSULT_VERSION, 412,
            "expected_consult_version does not match the consult's current version",
        )
    if consult["status"] != "QUEUED":
        raise ApiError(ERR_CONSULT_NOT_QUEUED, 409, "Consult is not QUEUED")

    pool = services.eligible_pool(consult)
    if not pool:
        raise ApiError(ERR_NO_ELIGIBLE_SPECIALIST, 409, "No eligible specialist found")

    services.assign_consult(consult, pool)
    services.touch(consult)
    return ok(serialize("consult_request", consult), 200)


@bp.route("/econsult/consult-requests/<rid>/cancel", methods=["POST"])
def cancel_consult(rid):
    uid, _role = require_roles("ReferringProvider")
    consult = services.get_consult(rid)
    if consult["referring_provider_id"] != uid:
        raise ApiError(ERR_NOT_CONSULT_OWNER, 403, "Caller does not own this consult")
    if consult["status"] not in CANCELLABLE_STATES:
        raise ApiError(
            ERR_CONSULT_ALREADY_TERMINAL, 409,
            "Cancellation is not available once a consult is ANSWERED or terminal",
        )

    if consult["status"] in ("ASSIGNED", "CLARIFICATION_REQUESTED"):
        membership = db.store["panel_memberships"].get(consult["assigned_membership_id"])
        if membership is not None:
            membership["open_consult_count"] -= 1
            services.touch(membership)
        services.reverse_provisional_entries(consult["id"])

    consult["status"] = "CANCELLED"
    consult["billing_status"] = "VOID"
    services.touch(consult)
    return ok(serialize("consult_request", consult), 200)


@bp.route("/econsult/consult-requests/<rid>/close", methods=["POST"])
def close_consult(rid):
    uid, _role = require_roles("ReferringProvider")
    consult = services.get_consult(rid)
    if consult["referring_provider_id"] != uid:
        raise ApiError(ERR_NOT_CONSULT_OWNER, 403, "Caller does not own this consult")
    if consult["status"] != "ANSWERED":
        raise ApiError(ERR_CONSULT_NOT_ANSWERED, 409, "Consult is not ANSWERED")
    resp = services.response_for_consult(consult["id"])
    if resp is None or resp["status"] != "FINALIZED":
        raise ApiError(
            ERR_RESPONSE_NOT_FINALIZED, 409,
            "Consult close requires the response to be FINALIZED",
        )
    consult["status"] = "CLOSED"
    services.touch(consult)
    return ok(serialize("consult_request", consult), 200)


# --- clarifications ------------------------------------------------------------

@bp.route("/econsult/consult-requests/<rid>/clarifications", methods=["POST"])
def post_clarification(rid):
    uid, role = require_roles("ReferringProvider", "Specialist")
    data = util.json_body()
    body = util.req_str(data, "body")

    consult = services.get_consult(rid)
    if role == "Specialist":
        if consult["assigned_specialist_id"] != uid:
            raise ApiError(
                ERR_NOT_ASSIGNED_SPECIALIST, 403,
                "Caller is not the assigned specialist",
            )
        if consult["status"] != "ASSIGNED":
            raise ApiError(
                ERR_CONSULT_NOT_ASSIGNED, 409,
                "Specialist clarification requires status ASSIGNED",
            )
        if consult["clarification_rounds"] >= services.MAX_CLARIFICATION_ROUNDS:
            raise ApiError(
                ERR_MAX_CLARIFICATION_ROUNDS_REACHED, 409,
                "Maximum clarification rounds reached",
            )
        author_role = "SPECIALIST"
        consult["clarification_rounds"] += 1
        consult["status"] = "CLARIFICATION_REQUESTED"
    else:
        if consult["referring_provider_id"] != uid:
            raise ApiError(ERR_NOT_CONSULT_OWNER, 403, "Caller does not own this consult")
        if consult["status"] != "CLARIFICATION_REQUESTED":
            raise ApiError(
                ERR_CONSULT_NOT_AWAITING_CLARIFICATION, 409,
                "Provider clarification reply requires status CLARIFICATION_REQUESTED",
            )
        author_role = "REFERRING_PROVIDER"
        membership = db.store["panel_memberships"].get(consult["assigned_membership_id"])
        if membership is not None:
            track = db.store["specialty_tracks"][consult["specialty_track_id"]]
            services.append_entry(
                membership["id"], consult["id"],
                "CLARIFICATION_FEE", track["clarification_fee_cents"],
            )
            membership["provisional_balance_cents"] += track["clarification_fee_cents"]
            services.touch(membership)
        consult["status"] = "ASSIGNED"

    prior_count = sum(
        1 for message in db.store["clarification_messages"].values()
        if message["consult_id"] == consult["id"]
    )
    rec = services.append_only_record()
    rec.update({
        "consult_id": consult["id"],
        "author_role": author_role,
        "body": body,
        "sequence_no": prior_count + 1,
    })
    db.store["clarification_messages"][rec["id"]] = rec
    services.touch(consult)
    return ok(serialize("clarification_message", rec), 201)


@bp.route("/econsult/consult-requests/<rid>/clarifications", methods=["GET"])
def list_clarifications(rid):
    require_roles(*ANY_ROLE)
    consult = services.get_consult(rid)
    records = [
        m for m in db.store["clarification_messages"].values()
        if m["consult_id"] == consult["id"]
    ]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("clarification_message", page), total, limit, offset)


# --- routing decisions -----------------------------------------------------------

@bp.route("/econsult/consult-requests/<rid>/routing-decisions", methods=["GET"])
def list_routing_decisions(rid):
    require_roles(*ANY_ROLE)
    consult = services.get_consult(rid)
    records = [
        d for d in db.store["routing_decisions"].values()
        if d["consult_id"] == consult["id"]
    ]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("routing_decision", page), total, limit, offset)


# --- responses beneath a consult -------------------------------------------------

@bp.route("/econsult/consult-requests/<rid>/responses", methods=["POST"])
def submit_response(rid):
    uid, _role = require_roles("Specialist")
    data = util.json_body()
    disposition = util.req_enum(data, "disposition", util.DISPOSITIONS)
    recommendation_text = util.req_str(data, "recommendation_text", min_len=20)

    consult = services.get_consult(rid)
    if consult["assigned_specialist_id"] != uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_SPECIALIST, 403,
            "Caller is not the assigned specialist",
        )
    if consult["status"] in services.TERMINAL_CONSULT_STATES:
        raise ApiError(
            ERR_CONSULT_ALREADY_TERMINAL, 409,
            "Operation attempted on a terminal consult",
        )
    if consult["status"] != "ASSIGNED":
        raise ApiError(
            ERR_CONSULT_NOT_ASSIGNED, 409,
            "Response submission requires status ASSIGNED",
        )
    membership = db.store["panel_memberships"][consult["assigned_membership_id"]]
    if membership["standing"] == "SUSPENDED":
        raise ApiError(
            ERR_MEMBERSHIP_SUSPENDED, 403,
            "A SUSPENDED membership cannot submit responses",
        )

    track = db.store["specialty_tracks"][consult["specialty_track_id"]]
    moment = clock.now()
    on_time = moment <= consult["sla_due_at"]
    response_minutes = int((moment - consult["created_at"]).total_seconds() // 60)
    review_required = (
        membership["standing"] == "PROBATION"
        or disposition == "CONVERT_TO_VISIT"
        or not on_time
    )

    resp = services.base_record()
    resp.update({
        "consult_id": consult["id"],
        "specialist_id": uid,
        "disposition": disposition,
        "recommendation_text": recommendation_text,
        "on_time": on_time,
        "response_minutes": response_minutes,
        "pcp_note_documented": False,
        "specialist_note_documented": False,
        "documentation_complete": False,
        "review_required": review_required,
        "last_submitted_at": moment,
        "revision_count": 0,
        "status": "SUBMITTED",
        "_membership_id": membership["id"],
    })
    db.store["consult_responses"][resp["id"]] = resp

    provisional = services.provisional_response_base(track, disposition)
    services.append_entry(membership["id"], consult["id"], "RESPONSE_FEE", provisional)
    membership["provisional_balance_cents"] += provisional
    membership["responded_count"] += 1
    if on_time:
        membership["on_time_count"] += 1
    membership["open_consult_count"] -= 1

    consult["status"] = "ANSWERED"
    if not on_time:
        consult["sla_breached"] = True
    consult["billing_status"] = "PENDING_DOCUMENTATION"
    services.touch(consult)

    services.recompute_quality(membership)
    return ok(serialize("consult_response", resp), 201)


@bp.route("/econsult/consult-requests/<rid>/responses", methods=["GET"])
def list_consult_responses(rid):
    require_roles(*ANY_ROLE)
    consult = services.get_consult(rid)
    records = [
        resp for resp in db.store["consult_responses"].values()
        if resp["consult_id"] == consult["id"]
    ]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("consult_response", page), total, limit, offset)
