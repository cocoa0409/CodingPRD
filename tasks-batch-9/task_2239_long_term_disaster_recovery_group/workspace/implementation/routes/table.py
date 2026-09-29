"""The unmet needs table: member orgs, sessions, presentations, pledges (PRD 3.4, 3.5)."""

from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    COMMITMENT_STATUSES,
    DECISIONS,
    MAX_DEFERRALS,
    ORG_SETTABLE_STATUSES,
    ORG_TYPES,
    PRESENTATION_STATUSES,
    PURPOSE_CODES,
    ROLE_ADMIN,
    ROLE_CASE_MANAGER,
    ROLE_CHAIR,
    ROLE_DELEGATE,
    ROLE_OFFICER,
)
from errors import ApiError
from services import calculations as calc
from services import rollups

bp = Blueprint("table", __name__)


# ---------------------------------------------------------------------------
# MemberOrganization
# ---------------------------------------------------------------------------
@bp.post("/member-organizations")
def create_member_org():
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    cap = mw.req_int(body, "annual_pledge_cap_cents", minimum=0)
    record = db.base_record()
    record.update(
        {
            "org_name": mw.req_str(body, "org_name"),
            "org_type": mw.req_enum(body, "org_type", ORG_TYPES),
            "contact_email": mw.req_str(body, "contact_email"),
            "annual_pledge_cap_cents": cap,
            "status": "ACTIVE",
            "committed_cents": 0,
            "disbursed_cents": 0,
            "remaining_pledge_capacity_cents": cap,
            "suspension_reason": None,
        }
    )
    db.member_orgs[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/member-organizations/<oid>")
def get_member_org(oid):
    mw.authorize((ROLE_CHAIR, ROLE_DELEGATE, ROLE_CASE_MANAGER, ROLE_ADMIN))
    return response.object_response(lookups.member_org(oid))


@bp.post("/member-organizations/<oid>/status")
def set_member_org_status(oid):
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    status = mw.req_enum(body, "status", ORG_SETTABLE_STATUSES)
    reason = mw.opt_str(body, "suspension_reason")

    org = lookups.member_org(oid)
    db.set_field(org, "status", status)
    if reason is not None:
        db.set_field(org, "suspension_reason", reason)
    db.mark(org)
    return response.object_response(org)


# ---------------------------------------------------------------------------
# TableSession
# ---------------------------------------------------------------------------
@bp.post("/table-sessions")
def create_session():
    mw.authorize((ROLE_CHAIR, ROLE_ADMIN))
    body = mw.get_body()
    record = db.base_record()
    record.update(
        {
            "session_label": mw.req_str(body, "session_label"),
            "scheduled_for": mw.req_date(body, "scheduled_for"),
            "quorum_min_member_orgs": mw.opt_int(
                body, "quorum_min_member_orgs", 3, minimum=1
            ),
            "attending_member_org_ids": [],
            "status": "SCHEDULED",
            "chaired_by_user_id": None,
            "awarded_total_cents": 0,
            "queued_count": 0,
        }
    )
    db.table_sessions[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/table-sessions/<sid>")
def get_session(sid):
    mw.authorize((ROLE_CHAIR, ROLE_CASE_MANAGER, ROLE_DELEGATE, ROLE_ADMIN))
    return response.object_response(lookups.session(sid))


@bp.post("/table-sessions/<sid>/open")
def open_session(sid):
    user_id, _role = mw.authorize((ROLE_CHAIR, ROLE_ADMIN))
    body = mw.get_body()
    attending = mw.req_list(body, "attending_member_org_ids")

    session = lookups.session(sid)
    orgs = [lookups.member_org(org_id) for org_id in attending]

    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_NOT_IN_SESSION")
    if len(attending) < session["quorum_min_member_orgs"]:
        raise ApiError("ERR_QUORUM_NOT_MET")
    for org in orgs:
        if org["status"] not in ("ACTIVE", "CAPPED"):
            raise ApiError("ERR_MEMBER_ORG_NOT_ACTIVE")

    db.set_field(session, "attending_member_org_ids", list(attending))
    db.set_field(session, "chaired_by_user_id", user_id)
    db.set_field(session, "status", "IN_SESSION")
    db.mark(session)
    return response.object_response(session)


@bp.post("/table-sessions/<sid>/adjourn")
def adjourn_session(sid):
    mw.authorize((ROLE_CHAIR, ROLE_ADMIN))
    body = mw.get_body()
    cancel_instead = mw.opt_bool(body, "cancel_instead", False)
    mw.opt_str(body, "minutes_note")

    session = lookups.session(sid)
    if cancel_instead:
        if session["status"] != "SCHEDULED":
            raise ApiError("ERR_SESSION_NOT_IN_SESSION")
    else:
        if session["status"] != "IN_SESSION":
            raise ApiError("ERR_SESSION_NOT_IN_SESSION")
        if rollups.session_has_active_presentation(session["id"]):
            raise ApiError("ERR_SESSION_HAS_ACTIVE_PRESENTATION")

    db.set_field(session, "status", "CANCELLED" if cancel_instead else "ADJOURNED")
    rollups.adjourn_queue_cascade(session)
    db.mark(session)
    return response.object_response(session)


# ---------------------------------------------------------------------------
# CasePresentation
# ---------------------------------------------------------------------------
@bp.post("/case-presentations")
def create_presentation():
    user_id, _role = mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    case_id = mw.req_id(body, "case_id")
    session_id = mw.req_id(body, "session_id")
    assessment_id = mw.req_id(body, "assessment_id")
    prepared_by = mw.req_str(body, "prepared_by_user_id")
    narrative = mw.req_str(body, "narrative")

    case = lookups.case(case_id)
    session = lookups.session(session_id)
    assessment = lookups.assessment(assessment_id)

    if assessment["case_id"] != case["id"]:
        raise ApiError("ERR_ASSESSMENT_CASE_MISMATCH")
    if (
        prepared_by != case["assigned_case_manager_user_id"]
        or prepared_by != user_id
    ):
        raise ApiError("ERR_CASE_MANAGER_MISMATCH")
    if case["case_status"] not in ("ASSESSED", "PRESENTED"):
        raise ApiError("ERR_CASE_INVALID_STATE")
    if session["status"] not in ("SCHEDULED", "IN_SESSION"):
        raise ApiError("ERR_SESSION_NOT_ACCEPTING_QUEUE")
    if rollups.case_live_presentations(case["id"]):
        raise ApiError("ERR_PRESENTATION_ALREADY_ACTIVE")
    if assessment["variant"] != "PURPOSE_MATCHED":
        raise ApiError("ERR_ASSESSMENT_VARIANT_NOT_ELIGIBLE")
    if (
        assessment["verified_damage_total_cents"]
        != case["verified_damage_total_cents"]
    ):
        raise ApiError("ERR_ASSESSMENT_STALE")

    survivor = db.survivors.get(case["survivor_id"])
    record = db.base_record()
    record.update(
        {
            "case_id": case["id"],
            "session_id": session["id"],
            "assessment_id": assessment["id"],
            "prepared_by_user_id": prepared_by,
            "narrative": narrative,
            "status": "QUEUED",
            "queue_position": 0,
            "priority_score_snapshot": survivor["priority_score"] if survivor else 0,
            "pledged_total_cents": 0,
            "bridge_tier": None,
            "bridge_authorized_cents": 0,
            "awarded_cents": 0,
            "shortfall_cents": 0,
            "deferral_count": 0,
            "decided_at": None,
            "decided_by_user_id": None,
            "decision_note": None,
        }
    )
    db.presentations[record["id"]] = record

    rollups.recompute_queue(session["id"])
    db.set_field(case, "case_status", "PRESENTED")
    db.mark(case)
    db.mark(session)
    return response.object_response(record, 201)


@bp.get("/case-presentations/<pid>")
def get_presentation(pid):
    mw.authorize(
        (ROLE_CASE_MANAGER, ROLE_CHAIR, ROLE_DELEGATE, ROLE_OFFICER, ROLE_ADMIN)
    )
    return response.object_response(lookups.presentation(pid))


@bp.get("/case-presentations")
def list_presentations():
    mw.authorize(
        (ROLE_CASE_MANAGER, ROLE_CHAIR, ROLE_DELEGATE, ROLE_OFFICER, ROLE_ADMIN)
    )
    limit, offset = mw.pagination()
    case_id = mw.query_str("case_id")
    session_id = mw.query_str("session_id")
    assessment_id = mw.query_str("assessment_id")
    status = mw.query_enum("status", PRESENTATION_STATUSES)

    rows = db.sorted_records(list(db.presentations.values()))
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if assessment_id is not None:
        rows = [r for r in rows if r["assessment_id"] == assessment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


def _session_of(presentation):
    return db.table_sessions.get(presentation["session_id"])


@bp.post("/case-presentations/<pid>/present")
def present_presentation(pid):
    mw.authorize((ROLE_CHAIR, ROLE_ADMIN))
    mw.get_body()

    presentation = lookups.presentation(pid)
    if presentation["status"] != "QUEUED":
        raise ApiError("ERR_PRESENTATION_INVALID_STATE")
    session = _session_of(presentation)
    if session is None or session["status"] != "IN_SESSION":
        raise ApiError("ERR_SESSION_NOT_IN_SESSION")
    if presentation["queue_position"] != 1:
        raise ApiError("ERR_NOT_AT_QUEUE_HEAD")

    db.set_field(presentation, "status", "PRESENTING")
    db.set_field(presentation, "queue_position", 0)
    rollups.recompute_queue(session["id"])
    db.mark(presentation)
    return response.object_response(presentation)


@bp.post("/case-presentations/<pid>/deliberate")
def deliberate_presentation(pid):
    mw.authorize((ROLE_CHAIR, ROLE_ADMIN))
    mw.get_body()

    presentation = lookups.presentation(pid)
    if presentation["status"] != "PRESENTING":
        raise ApiError("ERR_PRESENTATION_INVALID_STATE")
    session = _session_of(presentation)
    if session is None or session["status"] != "IN_SESSION":
        raise ApiError("ERR_SESSION_NOT_IN_SESSION")

    db.set_field(presentation, "status", "DELIBERATING")
    db.mark(presentation)
    return response.object_response(presentation)


def _presentation_commitments(presentation_id, statuses):
    return [
        c
        for c in db.sorted_records(list(db.commitments.values()))
        if c["presentation_id"] == presentation_id and c["status"] in statuses
    ]


@bp.post("/case-presentations/<pid>/decision")
def decide_presentation(pid):
    user_id, _role = mw.authorize((ROLE_CHAIR, ROLE_ADMIN))
    body = mw.get_body()
    decision = mw.req_enum(body, "decision", DECISIONS)
    note = mw.opt_str(body, "decision_note")

    presentation = lookups.presentation(pid)
    case = db.recovery_cases.get(presentation["case_id"])
    if case is not None and user_id == case["assigned_case_manager_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if presentation["status"] != "DELIBERATING":
        raise ApiError("ERR_PRESENTATION_INVALID_STATE")
    session = _session_of(presentation)
    if session is None or session["status"] != "IN_SESSION":
        raise ApiError("ERR_SESSION_NOT_IN_SESSION")

    if decision == "DEFER":
        if presentation["deferral_count"] >= MAX_DEFERRALS:
            raise ApiError("ERR_MAX_DEFERRALS_REACHED")
    elif decision == "AWARD":
        assembly = calc.table_award_assembly(presentation)
        if assembly["pledged_total_cents"] > assembly["unmet"]:
            raise ApiError("ERR_AWARD_EXCEEDS_UNMET_NEED")
        if assembly["awarded_cents"] <= 0:
            raise ApiError("ERR_AWARD_ZERO")

    if note is not None:
        db.set_field(presentation, "decision_note", note)
    db.set_field(presentation, "decided_at", db.clock_iso())
    db.set_field(presentation, "decided_by_user_id", user_id)

    if decision == "AWARD":
        db.set_field(presentation, "status", "AWARDED")
        db.set_field(presentation, "bridge_tier", assembly["bridge_tier"])
        db.set_field(
            presentation, "bridge_authorized_cents", assembly["bridge_authorized_cents"]
        )
        for commitment in _presentation_commitments(presentation["id"], ("PLEDGED",)):
            db.set_field(commitment, "status", "CONFIRMED")
            rollups.recompute_member_org(db.member_orgs.get(commitment["member_org_id"]))
        rollups.recompute_presentation_pledged(presentation)
        rollups.recompute_presentation_award(presentation)
        if case is not None:
            rollups.recompute_case_funding(case)
            if case["case_status"] == "PRESENTED":
                db.set_field(case, "case_status", "ACTIVE_RECOVERY")
            db.mark(case)
        rollups.recompute_session_totals(session)
        db.mark(session)
    elif decision == "DEFER":
        db.set_field(presentation, "status", "DEFERRED")
        db.set_field(presentation, "deferral_count", presentation["deferral_count"] + 1)
    else:
        db.set_field(presentation, "status", "DENIED")
        db.set_field(presentation, "awarded_cents", 0)
        for commitment in _presentation_commitments(presentation["id"], ("PLEDGED",)):
            rollups.rescind_commitment(commitment, "PRESENTATION_DENIED")
        rollups.recompute_presentation_pledged(presentation)
        db.set_field(
            presentation,
            "shortfall_cents",
            rollups.pinned_unmet(presentation),
        )
        if case is not None:
            rollups.rewind_presented_to_assessed(case)
            db.mark(case)

    db.mark(presentation)
    return response.object_response(presentation)


@bp.post("/case-presentations/<pid>/requeue")
def requeue_presentation(pid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    new_session_id = mw.req_id(body, "new_session_id")

    presentation = lookups.presentation(pid)
    new_session = lookups.session(new_session_id)

    if presentation["status"] != "DEFERRED":
        raise ApiError("ERR_PRESENTATION_INVALID_STATE")
    if new_session["status"] not in ("SCHEDULED", "IN_SESSION"):
        raise ApiError("ERR_SESSION_NOT_ACCEPTING_QUEUE")

    case = db.recovery_cases.get(presentation["case_id"])
    assessment = db.assessments.get(presentation["assessment_id"])
    if (
        case is not None
        and assessment is not None
        and assessment["verified_damage_total_cents"]
        != case["verified_damage_total_cents"]
    ):
        raise ApiError("ERR_ASSESSMENT_STALE")

    old_session_id = presentation["session_id"]
    db.set_field(presentation, "session_id", new_session["id"])
    db.set_field(presentation, "status", "QUEUED")

    rollups.recompute_queue(new_session["id"])
    if old_session_id != new_session["id"]:
        rollups.recompute_queue(old_session_id)
        old_session = db.table_sessions.get(old_session_id)
        if old_session is not None:
            db.mark(old_session)
    db.mark(new_session)
    db.mark(presentation)
    return response.object_response(presentation)


# ---------------------------------------------------------------------------
# FundingCommitment
# ---------------------------------------------------------------------------
@bp.post("/funding-commitments")
def create_commitment():
    user_id, role = mw.authorize((ROLE_DELEGATE, ROLE_ADMIN))
    body = mw.get_body()
    presentation_id = mw.req_id(body, "presentation_id")
    member_org_id = mw.req_id(body, "member_org_id")
    pledged_cents = mw.req_int(body, "pledged_cents", minimum=1)
    purpose_code = mw.req_enum(body, "purpose_code", PURPOSE_CODES)
    expected_version = mw.req_int(body, "expected_presentation_version")

    presentation = lookups.presentation(presentation_id)
    org = lookups.member_org(member_org_id)

    if role == ROLE_DELEGATE and user_id != member_org_id:
        raise ApiError("ERR_ORG_IDENTITY_MISMATCH")
    if presentation["status"] != "DELIBERATING":
        raise ApiError("ERR_PRESENTATION_NOT_ACCEPTING_PLEDGES")
    session = _session_of(presentation)
    if session is None or session["status"] != "IN_SESSION":
        raise ApiError("ERR_SESSION_NOT_IN_SESSION")
    if org["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_ORG_NOT_ACTIVE")
    if expected_version != presentation["version"]:
        raise ApiError("ERR_STALE_PRESENTATION_VERSION")
    if org["id"] not in (session["attending_member_org_ids"] or []):
        raise ApiError("ERR_ORG_NOT_IN_SESSION")
    if pledged_cents > org["remaining_pledge_capacity_cents"]:
        raise ApiError("ERR_PLEDGE_CAP_EXCEEDED")

    record = db.base_record()
    record.update(
        {
            "presentation_id": presentation["id"],
            "member_org_id": org["id"],
            "pledged_cents": pledged_cents,
            "purpose_code": purpose_code,
            "status": "PLEDGED",
            "pledged_by_user_id": user_id,
            "rescission_reason": None,
        }
    )
    db.commitments[record["id"]] = record

    rollups.recompute_member_org(org)
    rollups.recompute_presentation_pledged(presentation)
    db.mark(presentation)
    return response.object_response(record, 201)


@bp.get("/funding-commitments/<cid>")
def get_commitment(cid):
    mw.authorize(
        (ROLE_CHAIR, ROLE_DELEGATE, ROLE_OFFICER, ROLE_CASE_MANAGER, ROLE_ADMIN)
    )
    return response.object_response(lookups.commitment(cid))


@bp.get("/funding-commitments")
def list_commitments():
    mw.authorize(
        (ROLE_CHAIR, ROLE_DELEGATE, ROLE_OFFICER, ROLE_CASE_MANAGER, ROLE_ADMIN)
    )
    limit, offset = mw.pagination()
    presentation_id = mw.query_str("presentation_id")
    member_org_id = mw.query_str("member_org_id")
    status = mw.query_enum("status", COMMITMENT_STATUSES)

    rows = db.sorted_records(list(db.commitments.values()))
    if presentation_id is not None:
        rows = [r for r in rows if r["presentation_id"] == presentation_id]
    if member_org_id is not None:
        rows = [r for r in rows if r["member_org_id"] == member_org_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/funding-commitments/<cid>/rescind")
def rescind_commitment_endpoint(cid):
    user_id, role = mw.authorize((ROLE_DELEGATE, ROLE_ADMIN))
    body = mw.get_body()
    reason = mw.req_str(body, "rescission_reason")

    commitment = lookups.commitment(cid)
    if role == ROLE_DELEGATE and user_id != commitment["member_org_id"]:
        raise ApiError("ERR_ORG_IDENTITY_MISMATCH")
    if commitment["status"] not in ("PLEDGED", "CONFIRMED"):
        raise ApiError("ERR_COMMITMENT_INVALID_STATE")
    was_confirmed = commitment["status"] == "CONFIRMED"
    if was_confirmed:
        blocking = [
            d
            for d in db.disbursements.values()
            if d["commitment_id"] == commitment["id"]
            and d["status"] in ("APPROVED", "PAID")
        ]
        if blocking:
            raise ApiError("ERR_COMMITMENT_INVALID_STATE")

    rollups.rescind_commitment(commitment, reason)

    presentation = db.presentations.get(commitment["presentation_id"])
    if presentation is not None:
        rollups.recompute_presentation_pledged(presentation)
        rollups.recompute_presentation_award(presentation)
        if was_confirmed:
            case = db.recovery_cases.get(presentation["case_id"])
            if case is not None:
                rollups.recompute_case_funding(case)
                if case["funding_status"] != "SATISFIED":
                    rollups.rewind_closure_pending(case)
        session = db.table_sessions.get(presentation["session_id"])
        if session is not None:
            rollups.recompute_session_totals(session)

    db.mark(commitment)
    return response.object_response(commitment)
