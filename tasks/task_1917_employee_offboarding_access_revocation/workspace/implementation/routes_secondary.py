"""Routes: ExitInterview, KnowledgeTransferPlan/Session, BenefitsNotice,
RestrictiveCovenantAck, RehireEligibilityReview."""
from datetime import timedelta

from flask import g

from core import (
    COVENANT_KINDS,
    DB,
    INTERVIEW_HARD_LIMIT_DAYS,
    MAX_INTERVIEW_RESCHEDULES,
    MAX_NOTICE_FAILURES,
    NOTICE_KINDS,
    REHIRE_CODES,
    app,
    authenticate,
    bump,
    err_bad_request,
    err_case_terminal,
    err_deadline,
    err_invalid_state,
    err_not_found,
    err_overlap,
    err_referential,
    err_retry_cap,
    err_sod,
    err_temporal,
    get_body,
    is_int,
    new_record,
    now_dt,
    ok_object,
    paginate,
    parse_dt,
    req_str,
    ser,
)
from domain import (
    acks_of,
    after_session_mutation,
    calc_benefits_deadline,
    interviews_of,
    notices_of,
    plan_of,
    reconcile_case,
    review_of,
    sessions_of,
)
from routes_cases import _q, get_case_or_404
from routes_work import _reject_if_case_terminal

INTERVIEW_ROLES = {"HRPartner", "HRDirector", "Manager"}
PLAN_ROLES = {"Manager", "HRPartner", "HRDirector"}
NOTICE_ROLES = {"BenefitsAdministrator", "HRPartner", "HRDirector"}
ACK_ROLES = {"HRPartner", "HRDirector", "Manager"}
REVIEW_ROLES = {"HRReviewer", "HRDirector", "HRPartner"}

CASE_STATES_FOR_PLAN_ACTIVATE = {"APPROVED", "REVOCATION_IN_PROGRESS", "PAYROLL_PENDING"}
CASE_STATES_FOR_REVIEW_SUBMIT = {"CLEARANCE_IN_PROGRESS", "READY_TO_CLOSE"}


def get_interview_or_404(iid):
    iv = DB["interviews"].get(iid)
    if iv is None:
        raise err_not_found("ExitInterview %s not found" % iid)
    return iv


def get_plan_or_404(pid):
    pl = DB["plans"].get(pid)
    if pl is None:
        raise err_not_found("KnowledgeTransferPlan %s not found" % pid)
    return pl


def get_session_or_404(sid):
    s = DB["sessions"].get(sid)
    if s is None:
        raise err_not_found("KnowledgeTransferSession %s not found" % sid)
    return s


def get_notice_or_404(nid):
    n = DB["notices"].get(nid)
    if n is None:
        raise err_not_found("BenefitsNotice %s not found" % nid)
    return n


def get_ack_or_404(aid):
    k = DB["acks"].get(aid)
    if k is None:
        raise err_not_found("RestrictiveCovenantAck %s not found" % aid)
    return k


def get_review_or_404(rid):
    r = DB["reviews"].get(rid)
    if r is None:
        raise err_not_found("RehireEligibilityReview %s not found" % rid)
    return r


# --------------------------------------------------------------------------
# ExitInterview
# --------------------------------------------------------------------------
@app.post("/offboarding/exit-interviews")
def create_exit_interview():
    authenticate({"HRPartner"})
    body = get_body()
    start = parse_dt(body.get("scheduled_start"))
    end = parse_dt(body.get("scheduled_end"))
    if start is None or end is None:
        raise err_bad_request("scheduled_start and scheduled_end must be ISO 8601 UTC instants")
    if end <= start:
        raise err_temporal("scheduled_end must be strictly after scheduled_start")
    case_id = body.get("offboarding_case_id")
    case = DB["cases"].get(case_id) if isinstance(case_id, str) else None
    if case is None:
        if not isinstance(case_id, str) or not case_id:
            raise err_bad_request("offboarding_case_id is required")
        raise err_referential("offboarding_case_id does not reference an existing case")
    _reject_if_case_terminal(case)
    # OVERLAP-A: half-open [start, end) against other SCHEDULED interviews of the case
    for other in interviews_of(case["id"]):
        if other["status"] == "SCHEDULED" and start < other["scheduled_end"] and other["scheduled_start"] < end:
            raise err_overlap("Interview window overlaps another SCHEDULED interview of the case")
    req_str(body, "interviewer_ref")

    iv = new_record()
    iv.update({
        "offboarding_case_id": case["id"],
        "interviewer_ref": body["interviewer_ref"],
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "completion_notes_ref": None,
        "declined_reason": None,
    })
    DB["interviews"][iv["id"]] = iv
    return ok_object(ser(iv), status=201)


@app.get("/offboarding/exit-interviews")
def list_exit_interviews():
    authenticate(INTERVIEW_ROLES)
    records = list(DB["interviews"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [i for i in records if i["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    return paginate(records)


@app.get("/offboarding/exit-interviews/<iid>")
def get_exit_interview(iid):
    authenticate(INTERVIEW_ROLES)
    return ok_object(ser(get_interview_or_404(iid)))


@app.get("/offboarding/offboarding-cases/<case_id>/exit-interviews")
def list_case_exit_interviews(case_id):
    authenticate(INTERVIEW_ROLES)
    get_case_or_404(case_id)
    records = interviews_of(case_id)
    status = _q("status")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    return paginate(records)


@app.post("/offboarding/exit-interviews/<iid>/request-reschedule")
def request_reschedule_interview(iid):
    authenticate({"HRPartner"})
    iv = get_interview_or_404(iid)
    if iv["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview can request reschedule")
    case = get_case_or_404(iv["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if iv["reschedule_count"] >= MAX_INTERVIEW_RESCHEDULES:
        raise err_retry_cap("Interview reschedule cap reached")
    iv["reschedule_count"] += 1
    iv["status"] = "RESCHEDULE_REQUESTED"
    bump(iv)
    return ok_object(ser(iv))


@app.post("/offboarding/exit-interviews/<iid>/reschedule")
def reschedule_interview(iid):
    authenticate({"HRPartner"})
    iv = get_interview_or_404(iid)
    if iv["status"] not in ("RESCHEDULE_REQUESTED", "NO_SHOW"):
        raise err_invalid_state("Only a RESCHEDULE_REQUESTED or NO_SHOW interview can be rescheduled")
    case = get_case_or_404(iv["offboarding_case_id"])
    _reject_if_case_terminal(case)
    body = get_body()
    start = parse_dt(body.get("scheduled_start"))
    end = parse_dt(body.get("scheduled_end"))
    if start is None or end is None:
        raise err_bad_request("scheduled_start and scheduled_end must be ISO 8601 UTC instants")
    if end <= start:
        raise err_temporal("scheduled_end must be strictly after scheduled_start")
    dl = case["determined_last_day"]
    if dl is not None and end > dl + timedelta(days=INTERVIEW_HARD_LIMIT_DAYS):
        raise err_temporal("Interview window exceeds the hard limit past the determined last day")
    for other in interviews_of(case["id"]):
        if other["id"] == iv["id"]:
            continue
        if other["status"] == "SCHEDULED" and start < other["scheduled_end"] and other["scheduled_start"] < end:
            raise err_overlap("Interview window overlaps another SCHEDULED interview of the case")
    if iv["status"] == "NO_SHOW":
        if iv["reschedule_count"] >= MAX_INTERVIEW_RESCHEDULES:
            raise err_retry_cap("Interview reschedule cap reached")
        iv["reschedule_count"] += 1
    iv["scheduled_start"] = start
    iv["scheduled_end"] = end
    iv["status"] = "SCHEDULED"
    bump(iv)
    return ok_object(ser(iv))


@app.post("/offboarding/exit-interviews/<iid>/complete")
def complete_interview(iid):
    authenticate({"HRPartner"})
    iv = get_interview_or_404(iid)
    if iv["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview can be completed")
    case = get_case_or_404(iv["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if now_dt() < iv["scheduled_start"]:
        raise err_invalid_state("Interview cannot be completed before it begins")
    body = get_body()
    iv["completion_notes_ref"] = req_str(body, "completion_notes_ref")
    iv["status"] = "COMPLETED"
    bump(iv)
    reconcile_case(case)
    return ok_object(ser(iv))


@app.post("/offboarding/exit-interviews/<iid>/decline")
def decline_interview(iid):
    authenticate({"HRPartner"})
    iv = get_interview_or_404(iid)
    if iv["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview can be declined")
    case = get_case_or_404(iv["offboarding_case_id"])
    _reject_if_case_terminal(case)
    body = get_body()
    iv["declined_reason"] = req_str(body, "declined_reason")
    iv["status"] = "DECLINED"
    bump(iv)
    reconcile_case(case)
    return ok_object(ser(iv))


@app.post("/offboarding/exit-interviews/<iid>/cancel")
def cancel_interview(iid):
    authenticate({"HRPartner"})
    iv = get_interview_or_404(iid)
    if iv["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED interview can be cancelled")
    case = get_case_or_404(iv["offboarding_case_id"])
    _reject_if_case_terminal(case)
    iv["status"] = "CANCELLED"
    bump(iv)
    reconcile_case(case)
    return ok_object(ser(iv))


# --------------------------------------------------------------------------
# KnowledgeTransferPlan
# --------------------------------------------------------------------------
@app.get("/offboarding/knowledge-transfer-plans")
def list_kt_plans():
    authenticate(PLAN_ROLES)
    records = list(DB["plans"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [p for p in records if p["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paginate(records)


@app.get("/offboarding/knowledge-transfer-plans/<pid>")
def get_kt_plan(pid):
    authenticate(PLAN_ROLES)
    return ok_object(ser(get_plan_or_404(pid)))


@app.get("/offboarding/offboarding-cases/<case_id>/knowledge-transfer-plans")
def list_case_kt_plans(case_id):
    authenticate(PLAN_ROLES)
    get_case_or_404(case_id)
    records = [p for p in DB["plans"].values() if p["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paginate(records)


@app.post("/offboarding/knowledge-transfer-plans/<pid>/activate")
def activate_kt_plan(pid):
    authenticate({"Manager"})
    pl = get_plan_or_404(pid)
    if pl["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT plan can be activated")
    case = get_case_or_404(pl["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_PLAN_ACTIVATE:
        raise err_invalid_state("Parent case state does not allow plan activation")
    body = get_body()
    if body.get("owner_manager_ref") is not None:
        if not isinstance(body["owner_manager_ref"], str) or not body["owner_manager_ref"]:
            raise err_bad_request("owner_manager_ref must be a non-empty string")
        pl["owner_manager_ref"] = body["owner_manager_ref"]
    if body.get("required_session_count") is not None:
        rsc = body["required_session_count"]
        if not is_int(rsc) or rsc < 0:
            raise err_bad_request("required_session_count must be an integer >= 0")
        pl["required_session_count"] = rsc
    pl["status"] = "ACTIVE"
    bump(pl)
    return ok_object(ser(pl))


@app.post("/offboarding/knowledge-transfer-plans/<pid>/complete")
def complete_kt_plan(pid):
    authenticate({"Manager"})
    pl = get_plan_or_404(pid)
    if pl["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE plan can be completed")
    case = get_case_or_404(pl["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if pl["completed_session_count"] < pl["required_session_count"]:
        raise err_invalid_state("Required sessions are not all completed")
    pl["status"] = "COMPLETE"
    bump(pl)
    reconcile_case(case)
    return ok_object(ser(pl))


@app.post("/offboarding/knowledge-transfer-plans/<pid>/waive")
def waive_kt_plan(pid):
    authenticate({"Manager"})
    pl = get_plan_or_404(pid)
    if pl["status"] not in ("DRAFT", "ACTIVE"):
        raise err_invalid_state("Only a DRAFT or ACTIVE plan can be waived")
    case = get_case_or_404(pl["offboarding_case_id"])
    _reject_if_case_terminal(case)
    body = get_body()
    pl["waived_reason"] = req_str(body, "waived_reason")
    pl["status"] = "WAIVED"
    bump(pl)
    reconcile_case(case)
    return ok_object(ser(pl))


# --------------------------------------------------------------------------
# KnowledgeTransferSession
# --------------------------------------------------------------------------
@app.post("/offboarding/knowledge-transfer-sessions")
def create_kt_session():
    authenticate({"Manager"})
    body = get_body()
    plan_id = body.get("knowledge_transfer_plan_id")
    pl = DB["plans"].get(plan_id) if isinstance(plan_id, str) else None
    if pl is None:
        if not isinstance(plan_id, str) or not plan_id:
            raise err_bad_request("knowledge_transfer_plan_id is required")
        raise err_referential("knowledge_transfer_plan_id does not reference an existing plan")
    case = get_case_or_404(pl["offboarding_case_id"])
    _reject_if_case_terminal(case)
    start = parse_dt(body.get("scheduled_start"))
    end = parse_dt(body.get("scheduled_end"))
    if start is None or end is None:
        raise err_bad_request("scheduled_start and scheduled_end must be ISO 8601 UTC instants")
    if end <= start:
        raise err_temporal("scheduled_end must be strictly after scheduled_start")
    # OVERLAP-B: closed [start, end]; zero-minute adjacency is a conflict
    for other in sessions_of(pl["id"]):
        if other["status"] == "SCHEDULED" and start <= other["scheduled_end"] and other["scheduled_start"] <= end:
            raise err_overlap("Session window overlaps another SCHEDULED session of the plan")
    req_str(body, "topic")
    req_str(body, "successor_ref")

    s = new_record()
    s.update({
        "knowledge_transfer_plan_id": pl["id"],
        "topic": body["topic"],
        "scheduled_start": start,
        "scheduled_end": end,
        "successor_ref": body["successor_ref"],
        "status": "SCHEDULED",
    })
    DB["sessions"][s["id"]] = s
    return ok_object(ser(s), status=201)


@app.get("/offboarding/knowledge-transfer-sessions")
def list_kt_sessions():
    authenticate(PLAN_ROLES)
    records = list(DB["sessions"].values())
    plan_id = _q("knowledge_transfer_plan_id")
    if plan_id is not None:
        records = [s for s in records if s["knowledge_transfer_plan_id"] == plan_id]
    status = _q("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginate(records)


@app.get("/offboarding/knowledge-transfer-plans/<pid>/knowledge-transfer-sessions")
def list_plan_kt_sessions(pid):
    authenticate(PLAN_ROLES)
    get_plan_or_404(pid)
    records = sessions_of(pid)
    status = _q("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    return paginate(records)


@app.post("/offboarding/knowledge-transfer-sessions/<sid>/complete")
def complete_kt_session(sid):
    authenticate({"Manager"})
    s = get_session_or_404(sid)
    if s["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED session can be completed")
    pl = get_plan_or_404(s["knowledge_transfer_plan_id"])
    if pl["status"] != "ACTIVE":
        raise err_invalid_state("Parent plan must be ACTIVE to complete a session")
    case = get_case_or_404(pl["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if now_dt() < s["scheduled_start"]:
        raise err_invalid_state("Session cannot be completed before it begins")
    s["status"] = "COMPLETED"
    bump(s)
    after_session_mutation(pl)
    return ok_object(ser(s))


@app.post("/offboarding/knowledge-transfer-sessions/<sid>/cancel")
def cancel_kt_session(sid):
    authenticate({"Manager"})
    s = get_session_or_404(sid)
    if s["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED session can be cancelled")
    pl = get_plan_or_404(s["knowledge_transfer_plan_id"])
    case = get_case_or_404(pl["offboarding_case_id"])
    _reject_if_case_terminal(case)
    s["status"] = "CANCELLED"
    bump(s)
    after_session_mutation(pl)
    return ok_object(ser(s))


# --------------------------------------------------------------------------
# BenefitsNotice
# --------------------------------------------------------------------------
@app.post("/offboarding/benefits-notices")
def create_benefits_notice():
    authenticate({"BenefitsAdministrator"})
    body = get_body()
    case_id = body.get("offboarding_case_id")
    case = DB["cases"].get(case_id) if isinstance(case_id, str) else None
    if case is None:
        if not isinstance(case_id, str) or not case_id:
            raise err_bad_request("offboarding_case_id is required")
        raise err_referential("offboarding_case_id does not reference an existing case")
    _reject_if_case_terminal(case)
    if body.get("notice_kind") not in NOTICE_KINDS:
        raise err_bad_request("notice_kind must be one of %s" % sorted(NOTICE_KINDS))

    n = new_record()
    n.update({
        "offboarding_case_id": case["id"],
        "notice_kind": body["notice_kind"],
        "status": "DRAFT",
        "send_by": None,
        "sent_at": None,
        "acknowledged_at": None,
        "failure_count": 0,
    })
    DB["notices"][n["id"]] = n
    return ok_object(ser(n), status=201)


@app.get("/offboarding/benefits-notices")
def list_benefits_notices():
    authenticate(NOTICE_ROLES)
    records = list(DB["notices"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [n for n in records if n["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [n for n in records if n["status"] == status]
    kind = _q("notice_kind")
    if kind is not None:
        records = [n for n in records if n["notice_kind"] == kind]
    return paginate(records)


@app.get("/offboarding/benefits-notices/<nid>")
def get_benefits_notice(nid):
    authenticate(NOTICE_ROLES)
    return ok_object(ser(get_notice_or_404(nid)))


@app.get("/offboarding/offboarding-cases/<case_id>/benefits-notices")
def list_case_benefits_notices(case_id):
    authenticate(NOTICE_ROLES)
    get_case_or_404(case_id)
    records = notices_of(case_id)
    status = _q("status")
    if status is not None:
        records = [n for n in records if n["status"] == status]
    return paginate(records)


@app.post("/offboarding/benefits-notices/<nid>/send")
def send_benefits_notice(nid):
    authenticate({"BenefitsAdministrator"})
    n = get_notice_or_404(nid)
    if n["status"] != "QUEUED":
        raise err_invalid_state("Only a QUEUED notice can be sent")
    case = get_case_or_404(n["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if now_dt() > n["send_by"]:
        raise err_deadline("Notice send deadline has passed; requeue the notice instead")
    n["status"] = "SENT"
    n["sent_at"] = now_dt()
    bump(n)
    return ok_object(ser(n))


@app.post("/offboarding/benefits-notices/<nid>/acknowledge")
def acknowledge_benefits_notice(nid):
    authenticate({"BenefitsAdministrator"})
    n = get_notice_or_404(nid)
    if n["status"] != "SENT":
        raise err_invalid_state("Only a SENT notice can be acknowledged")
    case = get_case_or_404(n["offboarding_case_id"])
    _reject_if_case_terminal(case)
    n["status"] = "ACKNOWLEDGED"
    n["acknowledged_at"] = now_dt()
    bump(n)
    return ok_object(ser(n))


@app.post("/offboarding/benefits-notices/<nid>/report-failure")
def report_failure_benefits_notice(nid):
    authenticate({"BenefitsAdministrator"})
    n = get_notice_or_404(nid)
    if n["status"] != "SENT":
        raise err_invalid_state("Only a SENT notice can be reported failed")
    case = get_case_or_404(n["offboarding_case_id"])
    _reject_if_case_terminal(case)
    n["status"] = "FAILED"
    n["failure_count"] += 1
    bump(n)
    return ok_object(ser(n))


@app.post("/offboarding/benefits-notices/<nid>/requeue")
def requeue_benefits_notice(nid):
    authenticate({"BenefitsAdministrator"})
    n = get_notice_or_404(nid)
    if n["status"] != "FAILED":
        raise err_invalid_state("Only a FAILED notice can be requeued")
    case = get_case_or_404(n["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if n["failure_count"] >= MAX_NOTICE_FAILURES:
        raise err_retry_cap("Notice failure cap reached; escalate instead")
    n["status"] = "QUEUED"
    n["send_by"] = calc_benefits_deadline(n["notice_kind"], now_dt())
    bump(n)
    return ok_object(ser(n))


@app.post("/offboarding/benefits-notices/<nid>/escalate")
def escalate_benefits_notice(nid):
    authenticate({"BenefitsAdministrator"})
    n = get_notice_or_404(nid)
    if n["status"] != "FAILED":
        raise err_invalid_state("Only a FAILED notice can be escalated")
    case = get_case_or_404(n["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if n["failure_count"] < MAX_NOTICE_FAILURES:
        raise err_invalid_state("Notice may be escalated only at the failure cap")
    n["status"] = "ESCALATED"
    bump(n)
    return ok_object(ser(n))


# --------------------------------------------------------------------------
# RestrictiveCovenantAck
# --------------------------------------------------------------------------
@app.post("/offboarding/restrictive-covenant-acks")
def create_covenant_ack():
    authenticate({"HRPartner"})
    body = get_body()
    case_id = body.get("offboarding_case_id")
    case = DB["cases"].get(case_id) if isinstance(case_id, str) else None
    if case is None:
        if not isinstance(case_id, str) or not case_id:
            raise err_bad_request("offboarding_case_id is required")
        raise err_referential("offboarding_case_id does not reference an existing case")
    _reject_if_case_terminal(case)
    if body.get("covenant_kind") not in COVENANT_KINDS:
        raise err_bad_request("covenant_kind must be one of %s" % sorted(COVENANT_KINDS))

    k = new_record()
    k.update({
        "offboarding_case_id": case["id"],
        "covenant_kind": body["covenant_kind"],
        "status": "PENDING",
        "remind_at": None,
        "acknowledged_at": None,
        "acknowledgment_text_version": None,
    })
    DB["acks"][k["id"]] = k
    return ok_object(ser(k), status=201)


@app.get("/offboarding/restrictive-covenant-acks")
def list_covenant_acks():
    authenticate(ACK_ROLES)
    records = list(DB["acks"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [k for k in records if k["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [k for k in records if k["status"] == status]
    return paginate(records)


@app.get("/offboarding/offboarding-cases/<case_id>/restrictive-covenant-acks")
def list_case_covenant_acks(case_id):
    authenticate(ACK_ROLES)
    get_case_or_404(case_id)
    records = acks_of(case_id)
    status = _q("status")
    if status is not None:
        records = [k for k in records if k["status"] == status]
    return paginate(records)


@app.post("/offboarding/restrictive-covenant-acks/<aid>/acknowledge")
def acknowledge_covenant(aid):
    authenticate({"HRPartner"})
    k = get_ack_or_404(aid)
    if k["status"] not in ("PENDING", "REMINDED"):
        raise err_invalid_state("Only a PENDING or REMINDED acknowledgment can be acknowledged")
    case = get_case_or_404(k["offboarding_case_id"])
    if case["status"] in ("CLOSED", "VOIDED"):
        raise err_temporal("Covenant acknowledgment is accepted only while the case is open")
    body = get_body()
    k["acknowledgment_text_version"] = req_str(body, "acknowledgment_text_version")
    k["status"] = "ACKNOWLEDGED"
    k["acknowledged_at"] = now_dt()
    bump(k)
    return ok_object(ser(k))


@app.post("/offboarding/restrictive-covenant-acks/<aid>/mark-not-applicable")
def mark_covenant_not_applicable(aid):
    authenticate({"HRPartner"})
    k = get_ack_or_404(aid)
    if k["status"] != "PENDING":
        raise err_invalid_state("Only a PENDING acknowledgment can be marked not applicable")
    case = get_case_or_404(k["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in ("INTAKE", "APPROVED"):
        raise err_invalid_state("Covenant can be marked not applicable only in INTAKE or APPROVED")
    k["status"] = "NOT_APPLICABLE"
    bump(k)
    return ok_object(ser(k))


# --------------------------------------------------------------------------
# RehireEligibilityReview
# --------------------------------------------------------------------------
@app.get("/offboarding/rehire-eligibility-reviews")
def list_rehire_reviews():
    authenticate(REVIEW_ROLES)
    records = list(DB["reviews"].values())
    case_id = _q("offboarding_case_id")
    if case_id is not None:
        records = [r for r in records if r["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate(records)


@app.get("/offboarding/rehire-eligibility-reviews/<rid>")
def get_rehire_review(rid):
    authenticate(REVIEW_ROLES)
    return ok_object(ser(get_review_or_404(rid)))


@app.get("/offboarding/offboarding-cases/<case_id>/rehire-eligibility-reviews")
def list_case_rehire_reviews(case_id):
    authenticate(REVIEW_ROLES)
    get_case_or_404(case_id)
    records = [r for r in DB["reviews"].values() if r["offboarding_case_id"] == case_id]
    status = _q("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate(records)


@app.post("/offboarding/rehire-eligibility-reviews/<rid>/submit")
def submit_rehire_review(rid):
    authenticate({"HRReviewer"})
    r = get_review_or_404(rid)
    if r["status"] not in ("DRAFT", "RETURNED"):
        raise err_invalid_state("Only a DRAFT or RETURNED review can be submitted")
    case = get_case_or_404(r["offboarding_case_id"])
    _reject_if_case_terminal(case)
    if case["status"] not in CASE_STATES_FOR_REVIEW_SUBMIT:
        raise err_invalid_state(
            "Review may be submitted only once the case is in clearance or ready to close")
    # §2.7: reviewer must differ from the case's intake approver
    if g.user_id == case.get("_approved_by"):
        raise err_sod("Reviewer must differ from the case intake approver")
    body = get_body()
    if body.get("recommended_code") not in REHIRE_CODES:
        raise err_bad_request("recommended_code must be one of %s" % sorted(REHIRE_CODES))
    rationale = req_str(body, "rationale")
    r["reviewer_hr_ref"] = g.user_id
    r["recommended_code"] = body["recommended_code"]
    r["rationale"] = rationale
    r["status"] = "SUBMITTED"
    bump(r)
    return ok_object(ser(r))


@app.post("/offboarding/rehire-eligibility-reviews/<rid>/finalize")
def finalize_rehire_review(rid):
    authenticate({"HRDirector"})
    r = get_review_or_404(rid)
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED review can be finalized")
    case = get_case_or_404(r["offboarding_case_id"])
    _reject_if_case_terminal(case)
    # SoD-4: finalizer must differ from the reviewer
    if g.user_id == r.get("reviewer_hr_ref"):
        raise err_sod("Finalizer must differ from the reviewer (SoD-4)")
    r["status"] = "FINALIZED"
    r["finalized_at"] = now_dt()
    bump(r)
    return ok_object(ser(r))


@app.post("/offboarding/rehire-eligibility-reviews/<rid>/return")
def return_rehire_review(rid):
    authenticate({"HRDirector"})
    r = get_review_or_404(rid)
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED review can be returned")
    case = get_case_or_404(r["offboarding_case_id"])
    _reject_if_case_terminal(case)
    body = get_body()
    r["_return_reason"] = req_str(body, "return_reason")
    r["status"] = "RETURNED"
    bump(r)
    return ok_object(ser(r))
