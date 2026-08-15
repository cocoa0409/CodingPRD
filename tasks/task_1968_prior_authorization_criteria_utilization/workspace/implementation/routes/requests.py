"""PriorAuthRequest endpoints: intake, review ladder, withdraw, P2P scheduling."""

from flask import request as flask_request

import clock
from db import db, base_record, touch
from errors import (
    ApiError,
    ERR_CRITERIA_SET_NOT_ACTIVE,
    ERR_DELEGATION_SUSPENDED,
    ERR_NO_ACTIVE_GUIDELINE,
    ERR_NOT_ASSIGNED_MD,
    ERR_P2P_CONFERENCE_OUTSTANDING,
    ERR_P2P_SCHEDULE_CONFLICT,
    ERR_REQUEST_NOT_ESCALATED,
    ERR_REQUEST_NOT_PENDING,
    ERR_REQUEST_NOT_WITHDRAWABLE,
    ERR_SEGREGATION_OF_DUTIES,
    invalid_request,
)
from middleware import (
    ALL_ROLES,
    ROLE_INTAKE,
    ROLE_MD,
    ROLE_REVIEWER,
    authorize,
    get_or_404,
    json_body,
    req_bool,
    req_dt,
    req_enum,
    req_str,
)
from response import list_response, ok, serialize
from services import (
    DENIAL_REASONS,
    EV_AUTO_APPROVAL_FIRED,
    add_event,
    create_determination,
    mark_late_determination,
    recompute_provider_stats,
    request_due_at,
)
from . import make_blueprint

bp = make_blueprint("requests")

URGENCY_DOMAIN = ("STANDARD", "URGENT")
CHANNEL_DOMAIN = ("PORTAL", "FAX", "PHONE", "EDI")
REVIEWER_DECISIONS = ("APPROVE", "DENY", "ESCALATE")
MD_DECISIONS = ("APPROVE", "DENY", "SEND_BACK")
APPROVE_REASON = "MEDICAL_NECESSITY_MET"


def _q(name):
    v = flask_request.args.get(name)
    return v if v not in (None, "") else None


def _validate_reason_mapping(body, decision, escalate_word):
    """reason_code/decision mapping (priority 4, ERR_INVALID_REQUEST):
    APPROVE <-> MEDICAL_NECESSITY_MET; DENY <-> one of the three denial codes;
    reason_code must be omitted on ESCALATE / SEND_BACK."""
    reason = body.get("reason_code")
    if decision == "APPROVE":
        if reason != APPROVE_REASON:
            raise invalid_request(
                "APPROVE requires reason_code MEDICAL_NECESSITY_MET"
            )
    elif decision == "DENY":
        if reason not in DENIAL_REASONS:
            raise invalid_request(
                "DENY requires one of " + ", ".join(DENIAL_REASONS)
            )
    else:  # ESCALATE / SEND_BACK
        if reason is not None:
            raise invalid_request(
                f"reason_code must be omitted on {escalate_word}"
            )
    return reason


# --------------------------------------------------------------------- intake

@bp.route("/prior-auth-requests", methods=["POST"])
def intake_request():
    authorize(ROLE_INTAKE)
    body = json_body()

    # priority 4: body well-formedness + body FK existence
    provider_id = req_str(body, "provider_id")
    if provider_id not in db.providers:
        raise invalid_request(f"provider_id {provider_id} does not exist")
    member_ref = req_str(body, "member_ref", nonempty=True)
    criteria_set_id = req_str(body, "criteria_set_id")
    if criteria_set_id not in db.criteria_sets:
        raise invalid_request(f"criteria_set_id {criteria_set_id} does not exist")
    service_code = req_str(body, "service_code")
    urgency = req_enum(body, "urgency", URGENCY_DOMAIN)
    intake_channel = req_enum(body, "intake_channel", CHANNEL_DOMAIN)
    documentation_complete = req_bool(body, "documentation_complete")

    criteria_set = db.criteria_sets[criteria_set_id]
    provider = db.providers[provider_id]

    # priority 6 (state), narrative order: set ACTIVE -> delegation -> pinning
    if criteria_set["status"] != "ACTIVE":
        raise ApiError(
            ERR_CRITERIA_SET_NOT_ACTIVE,
            409,
            "Intake references a criteria set that is not ACTIVE",
        )
    arrangement = next(
        (
            a
            for a in db.arrangements.values()
            if a["criteria_set_id"] == criteria_set_id
        ),
        None,
    )
    if arrangement is not None and arrangement["status"] == "SUSPENDED":
        raise ApiError(
            ERR_DELEGATION_SUSPENDED,
            409,
            "Intake blocked: the criteria set's delegation arrangement is "
            "SUSPENDED",
        )

    now = clock.now()
    # Pinning: PUBLISHED version whose closed window contains received_at;
    # rank effective_from DESC, tie-break created_at DESC. Never re-pinned.
    candidates = [
        gv
        for gv in db.guideline_versions.values()
        if gv["criteria_set_id"] == criteria_set_id
        and gv["status"] == "PUBLISHED"
        and gv["effective_from"] <= now
        and (gv["effective_until"] is None or now <= gv["effective_until"])
    ]
    if not candidates:
        raise ApiError(
            ERR_NO_ACTIVE_GUIDELINE,
            409,
            "No PUBLISHED guideline version's closed window contains "
            "received_at",
        )
    candidates.sort(key=lambda g: (g["effective_from"], g["_seq"]), reverse=True)
    pinned = candidates[0]

    rec = base_record()
    rec.update(
        {
            "provider_id": provider_id,
            "member_ref": member_ref,
            "criteria_set_id": criteria_set_id,
            "guideline_version_id": pinned["id"],
            "service_code": service_code,
            "urgency": urgency,
            "intake_channel": intake_channel,
            "documentation_complete": documentation_complete,
            "status": "RECEIVED",  # transient inside this call
            "received_at": now,
            "due_at": request_due_at(
                now, urgency, criteria_set["line_of_business"]
            ),
            "determined_at": None,
            "escalated_by_user_id": None,
            "is_tat_breached": False,
        }
    )
    db.requests[rec["id"]] = rec

    # auto_approval_decision: gold lane first, then rules lane
    gold_lane = (
        provider["gold_card_status"] == "GOLD_CARDED"
        and provider["gold_card_service_category"]
        == criteria_set["service_category"]
    )
    rules_lane = (
        pinned["auto_approve_eligible"]
        and intake_channel in ("PORTAL", "EDI")
        and documentation_complete
    )
    if gold_lane or rules_lane:
        reason_code = "GOLD_CARD_AUTO" if gold_lane else "AUTO_RULE"
        rec["status"] = "AUTO_APPROVED"
        rec["determined_at"] = now
        create_determination(
            rec, "APPROVED", reason_code, "SYSTEM_RULE", None, now
        )
        add_event(
            EV_AUTO_APPROVAL_FIRED,
            rec["id"],
            provider_id,
            f"Auto-approval fired for request {rec['id']} via {reason_code}",
        )
        recompute_provider_stats(provider_id, run_suspend_check=False)
    else:
        rec["status"] = "PENDED_REVIEW"

    return ok(serialize(rec), status=201)


# -------------------------------------------------------------------- reads

@bp.route("/prior-auth-requests/<rid>", methods=["GET"])
def get_request(rid):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.requests, rid, "prior-auth request")
    return ok(serialize(rec))


@bp.route("/prior-auth-requests", methods=["GET"])
def list_requests():
    authorize(*ALL_ROLES)
    provider_id = _q("provider_id")
    criteria_set_id = _q("criteria_set_id")
    guideline_version_id = _q("guideline_version_id")
    status = _q("status")
    urgency = _q("urgency")
    items = [
        r
        for r in db.requests.values()
        if (provider_id is None or r["provider_id"] == provider_id)
        and (criteria_set_id is None or r["criteria_set_id"] == criteria_set_id)
        and (
            guideline_version_id is None
            or r["guideline_version_id"] == guideline_version_id
        )
        and (status is None or r["status"] == status)
        and (urgency is None or r["urgency"] == urgency)
    ]
    return list_response(items)


# ------------------------------------------------------------------ withdraw

@bp.route("/prior-auth-requests/<rid>/withdraw", methods=["POST"])
def withdraw_request(rid):
    authorize(ROLE_INTAKE)
    rec = get_or_404(db.requests, rid, "prior-auth request")
    if rec["status"] not in ("PENDED_REVIEW", "ESCALATED_MD"):
        raise ApiError(
            ERR_REQUEST_NOT_WITHDRAWABLE,
            409,
            "withdraw requires status PENDED_REVIEW or ESCALATED_MD",
        )
    rec["status"] = "WITHDRAWN"
    touch(rec)
    # conditional cascade: any still-SCHEDULED conference is cancelled
    for conf in db.conferences.values():
        if conf["request_id"] == rid and conf["status"] == "SCHEDULED":
            conf["status"] = "CANCELLED"
            touch(conf)
    return ok(serialize(rec))


# --------------------------------------------------------- reviewer decisions

@bp.route("/prior-auth-requests/<rid>/reviewer-decision", methods=["POST"])
def reviewer_decision(rid):
    authorize(ROLE_REVIEWER)
    rec = get_or_404(db.requests, rid, "prior-auth request")
    body = json_body()
    decision = req_enum(body, "decision", REVIEWER_DECISIONS)
    reason_code = _validate_reason_mapping(body, decision, "ESCALATE")

    if rec["status"] != "PENDED_REVIEW":
        raise ApiError(
            ERR_REQUEST_NOT_PENDING,
            409,
            "reviewer-decision requires status PENDED_REVIEW",
        )

    uid = flask_request.headers.get("X-User-ID")
    now = clock.now()
    if decision == "ESCALATE":
        rec["status"] = "ESCALATED_MD"
        rec["escalated_by_user_id"] = uid
        touch(rec)
        return ok(serialize(rec))

    outcome = "APPROVED" if decision == "APPROVE" else "DENIED"
    create_determination(rec, outcome, reason_code, "CLINICAL_REVIEWER", uid, now)
    rec["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    rec["determined_at"] = now
    mark_late_determination(rec, now)
    touch(rec)
    recompute_provider_stats(rec["provider_id"], run_suspend_check=True)
    return ok(serialize(rec))


# ----------------------------------------------------------------- md decisions

@bp.route("/prior-auth-requests/<rid>/md-decision", methods=["POST"])
def md_decision(rid):
    authorize(ROLE_MD)
    rec = get_or_404(db.requests, rid, "prior-auth request")
    body = json_body()
    decision = req_enum(body, "decision", MD_DECISIONS)
    reason_code = _validate_reason_mapping(body, decision, "SEND_BACK")

    if rec["status"] != "ESCALATED_MD":
        raise ApiError(
            ERR_REQUEST_NOT_ESCALATED,
            409,
            "md-decision requires status ESCALATED_MD",
        )

    uid = flask_request.headers.get("X-User-ID")
    if uid == rec["escalated_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "A MedicalDirector may not decide a case they escalated",
        )

    if decision == "DENY":
        outstanding = any(
            c["request_id"] == rid and c["status"] == "SCHEDULED"
            for c in db.conferences.values()
        )
        if outstanding:
            raise ApiError(
                ERR_P2P_CONFERENCE_OUTSTANDING,
                409,
                "MD DENY blocked while a conference is SCHEDULED for the "
                "request",
            )

    now = clock.now()
    if decision == "SEND_BACK":
        rec["status"] = "PENDED_REVIEW"
        rec["escalated_by_user_id"] = None
        touch(rec)
        return ok(serialize(rec))

    outcome = "APPROVED" if decision == "APPROVE" else "DENIED"
    create_determination(rec, outcome, reason_code, "MEDICAL_DIRECTOR", uid, now)
    rec["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    rec["determined_at"] = now
    mark_late_determination(rec, now)
    touch(rec)
    recompute_provider_stats(rec["provider_id"], run_suspend_check=True)
    return ok(serialize(rec))


# ------------------------------------------------------ peer-to-peer conferences

@bp.route("/prior-auth-requests/<rid>/peer-to-peer-conferences", methods=["POST"])
def schedule_conference(rid):
    authorize(ROLE_MD)
    rec = get_or_404(db.requests, rid, "prior-auth request")
    body = json_body()
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    if not scheduled_end > scheduled_start:
        raise invalid_request("scheduled_end must be after scheduled_start")

    if rec["status"] != "ESCALATED_MD":
        raise ApiError(
            ERR_REQUEST_NOT_ESCALATED,
            409,
            "P2P scheduling requires status ESCALATED_MD",
        )

    uid = flask_request.headers.get("X-User-ID")
    for conf in db.conferences.values():
        if conf["status"] != "SCHEDULED":
            continue
        # at most one SCHEDULED conference per request
        if conf["request_id"] == rid:
            raise ApiError(
                ERR_P2P_SCHEDULE_CONFLICT,
                409,
                "The request already has a SCHEDULED conference",
            )
        # half-open overlap among the same MD's SCHEDULED conferences;
        # touching endpoints allowed
        if conf["md_user_id"] == uid and (
            scheduled_start < conf["scheduled_end"]
            and conf["scheduled_start"] < scheduled_end
        ):
            raise ApiError(
                ERR_P2P_SCHEDULE_CONFLICT,
                409,
                "Conference interval intersects another SCHEDULED conference "
                "of this medical director",
            )

    conf = base_record()
    conf.update(
        {
            "request_id": rid,
            "md_user_id": uid,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "status": "SCHEDULED",
        }
    )
    db.conferences[conf["id"]] = conf
    return ok(serialize(conf), status=201)


@bp.route("/prior-auth-requests/<rid>/peer-to-peer-conferences", methods=["GET"])
def list_conferences(rid):
    authorize(*ALL_ROLES)
    get_or_404(db.requests, rid, "prior-auth request")
    items = [c for c in db.conferences.values() if c["request_id"] == rid]
    return list_response(items)


@bp.route("/prior-auth-requests/<rid>/compliance-events", methods=["GET"])
def list_request_compliance_events(rid):
    authorize(*ALL_ROLES)
    get_or_404(db.requests, rid, "prior-auth request")
    event_type = _q("event_type")
    items = [
        e
        for e in db.events.values()
        if e["request_id"] == rid
        and (event_type is None or e["event_type"] == event_type)
    ]
    return list_response(items)
