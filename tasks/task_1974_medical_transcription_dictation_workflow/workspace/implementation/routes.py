"""All API endpoints (SCAFFOLD §1.5 / PRD §4), each following the §2.6 pipeline."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import store
import services as svc
from errors import *
from helpers import (
    ApiError,
    authenticate,
    require_role,
    ALL_ROLES,
    body,
    req_str,
    opt_str,
    req_int,
    opt_int,
    req_enum,
    req_dt,
    paginate,
    truthy_param,
    ok_object,
    ok_list,
    base_entity,
    touch,
    sorted_created,
    serialize,
    fmt_dt,
    CLINIC_FIELDS,
    SLA_POLICY_FIELDS,
    PROVIDER_FIELDS,
    EDITOR_FIELDS,
    SHIFT_WINDOW_FIELDS,
    JOB_FIELDS,
    TRANSCRIPT_FIELDS,
    QA_REVIEW_FIELDS,
    TEMPLATE_FIELDS,
    MACRO_FIELDS,
    BILLING_PERIOD_FIELDS,
    LINE_ITEM_FIELDS,
)

bp = Blueprint("api", __name__)


def _get(mapping, key, error_id):
    e = store.db[mapping].get(key)
    if e is None:
        raise ApiError(error_id, f"{mapping[:-1]} {key} does not exist", 404)
    return e


def get_clinic(cid):
    return _get("clinics", cid, ERR_CLINIC_NOT_FOUND)


def get_provider(pid):
    return _get("providers", pid, ERR_PROVIDER_NOT_FOUND)


def get_editor(eid):
    return _get("editors", eid, ERR_EDITOR_NOT_FOUND)


def get_job(jid):
    return _get("jobs", jid, ERR_JOB_NOT_FOUND)


def get_transcript(tid):
    return _get("transcripts", tid, ERR_TRANSCRIPT_NOT_FOUND)


def get_template(tid):
    return _get("templates", tid, ERR_TEMPLATE_NOT_FOUND)


def get_macro(mid):
    return _get("macros", mid, ERR_MACRO_NOT_FOUND)


def get_period(bid):
    return _get("billing_periods", bid, ERR_BILLING_PERIOD_NOT_FOUND)


# ===========================================================================
# System / logical clock
# ===========================================================================

@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    b = body()
    to = req_dt(b, "to_iso8601")
    store.set_now(to)
    svc.run_sweep(to)
    return ok_object({"current_utc": fmt_dt(to)})


# ===========================================================================
# ClinicAccount
# ===========================================================================

@bp.post("/clinic-accounts")
def create_clinic():
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    b = body()
    name = req_str(b, "name")
    threshold = opt_int(b, "unsigned_report_threshold", 3, min_v=1)
    tier1 = opt_int(b, "aging_tier1_hours", 24, min_v=1)
    tier2 = opt_int(b, "aging_tier2_hours", 72, min_v=1)
    grace = opt_int(b, "payment_grace_days", 14, min_v=0)
    if tier1 >= tier2:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "aging_tier1_hours must be strictly less than aging_tier2_hours",
            400,
        )
    c = base_entity()
    c.update(
        {
            "name": name,
            "unsigned_report_threshold": threshold,
            "aging_tier1_hours": tier1,
            "aging_tier2_hours": tier2,
            "payment_grace_days": grace,
            "billing_hold": False,
            "suspended_provider_count": 0,
        }
    )
    store.db["clinics"][c["id"]] = c
    return ok_object(serialize(c, CLINIC_FIELDS), 201)


@bp.get("/clinic-accounts/<cid>")
def get_clinic_route(cid):
    authenticate()
    c = get_clinic(cid)
    return ok_object(serialize(c, CLINIC_FIELDS))


@bp.get("/clinic-accounts/<cid>/providers")
def list_clinic_providers(cid):
    authenticate()
    c = get_clinic(cid)
    items = sorted_created(
        p for p in store.db["providers"].values() if p["clinic_account_id"] == c["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(p, PROVIDER_FIELDS) for p in page], limit, offset, total)


@bp.get("/clinic-accounts/<cid>/sla-policies")
def list_clinic_sla_policies(cid):
    authenticate()
    c = get_clinic(cid)
    items = sorted_created(
        p for p in store.db["sla_policies"].values() if p["clinic_account_id"] == c["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(p, SLA_POLICY_FIELDS) for p in page], limit, offset, total)


@bp.get("/clinic-accounts/<cid>/billing-periods")
def list_clinic_billing_periods(cid):
    authenticate()
    c = get_clinic(cid)
    items = sorted_created(
        p for p in store.db["billing_periods"].values() if p["clinic_account_id"] == c["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serialize(p, BILLING_PERIOD_FIELDS) for p in page], limit, offset, total
    )


# ===========================================================================
# SLAPolicy
# ===========================================================================

@bp.post("/sla-policies")
def create_sla_policy():
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    b = body()
    clinic_account_id = req_str(b, "clinic_account_id")
    priority = req_enum(b, "priority", svc.PRIORITIES)
    tat_minutes = req_int(b, "tat_minutes", min_v=1)
    rate = req_int(b, "rate_per_line_cents", min_v=1)
    pct = req_int(b, "breach_credit_pct", min_v=0, max_v=100)
    basis = req_enum(b, "measurement_basis", svc.MEASUREMENT_BASES)
    get_clinic(clinic_account_id)
    if svc.policy_for(clinic_account_id, priority) is not None:
        raise ApiError(
            ERR_DUPLICATE_SLA_POLICY,
            "an SLA policy already exists for this clinic and priority",
            409,
        )
    p = base_entity()
    p.update(
        {
            "clinic_account_id": clinic_account_id,
            "priority": priority,
            "tat_minutes": tat_minutes,
            "rate_per_line_cents": rate,
            "breach_credit_pct": pct,
            "measurement_basis": basis,
        }
    )
    store.db["sla_policies"][p["id"]] = p
    return ok_object(serialize(p, SLA_POLICY_FIELDS), 201)


# ===========================================================================
# Provider
# ===========================================================================

@bp.post("/providers")
def create_provider():
    _, role = authenticate()
    require_role(role, "ClientAdmin")
    b = body()
    clinic_account_id = req_str(b, "clinic_account_id")
    full_name = req_str(b, "full_name")
    specialty = req_enum(b, "specialty", svc.SPECIALTIES)
    get_clinic(clinic_account_id)
    p = base_entity()
    p.update(
        {
            "clinic_account_id": clinic_account_id,
            "full_name": full_name,
            "specialty": specialty,
            "status": "ACTIVE",
            "unsigned_tier1_count": 0,
            "unsigned_aged_count": 0,
            "suspension_reason": None,
        }
    )
    store.db["providers"][p["id"]] = p
    return ok_object(serialize(p, PROVIDER_FIELDS), 201)


@bp.get("/providers/<pid>")
def get_provider_route(pid):
    authenticate()
    p = get_provider(pid)
    return ok_object(serialize(p, PROVIDER_FIELDS))


@bp.post("/providers/<pid>/reinstate")
def reinstate_provider(pid):
    _, role = authenticate()
    require_role(role, "ClientAdmin")
    p = get_provider(pid)
    if p["unsigned_aged_count"] > 0:
        raise ApiError(
            ERR_UNSIGNED_REPORTS_REMAIN,
            "provider still has aged unsigned reports",
            409,
        )
    p["status"] = "ACTIVE"
    p["suspension_reason"] = None
    touch(p)
    clinic = store.db["clinics"][p["clinic_account_id"]]
    svc.recompute_clinic_counters(clinic)
    return ok_object(serialize(p, PROVIDER_FIELDS))


@bp.get("/providers/<pid>/templates")
def list_provider_templates(pid):
    authenticate()
    p = get_provider(pid)
    items = sorted_created(
        t for t in store.db["templates"].values() if t["provider_id"] == p["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(t, TEMPLATE_FIELDS) for t in page], limit, offset, total)


@bp.get("/providers/<pid>/macros")
def list_provider_macros(pid):
    authenticate()
    p = get_provider(pid)
    include_archived = truthy_param("include_archived")
    items = [
        m for m in store.db["macros"].values() if m["provider_id"] == p["id"]
    ]
    if not include_archived:
        items = [m for m in items if m["status"] == "ACTIVE"]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(m, MACRO_FIELDS) for m in page], limit, offset, total)


# ===========================================================================
# Editor
# ===========================================================================

@bp.post("/editors")
def create_editor():
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    b = body()
    display_name = req_str(b, "display_name")
    e = base_entity()
    e.update(
        {
            "display_name": display_name,
            "status": "ACTIVE",
            "rolling_quality_score": Decimal("100.00"),
            "qa_review_count": 0,
            "skill_tier": "TIER_2",
            "max_concurrent_claims": 3,
            "active_claim_count": 0,
        }
    )
    store.db["editors"][e["id"]] = e
    return ok_object(serialize(e, EDITOR_FIELDS), 201)


@bp.get("/editors/<eid>")
def get_editor_route(eid):
    authenticate()
    e = get_editor(eid)
    return ok_object(serialize(e, EDITOR_FIELDS))


@bp.post("/editors/<eid>/reinstate")
def reinstate_editor(eid):
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    e = get_editor(eid)
    if e["status"] != "SUSPENDED":
        raise ApiError(ERR_EDITOR_NOT_ACTIVE, "editor is not SUSPENDED", 409)
    e["status"] = "ACTIVE"
    # Rolling score preserved; tier and capacity re-derived from the current score.
    e["skill_tier"] = svc.derive_skill_tier(e["rolling_quality_score"], e["qa_review_count"])
    e["max_concurrent_claims"] = svc.TIER_MAX[e["skill_tier"]]
    touch(e)
    return ok_object(serialize(e, EDITOR_FIELDS))


@bp.get("/editors/<eid>/shift-windows")
def list_editor_shift_windows(eid):
    authenticate()
    e = get_editor(eid)
    items = sorted_created(
        w for w in store.db["shift_windows"].values() if w["editor_id"] == e["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list(
        [serialize(w, SHIFT_WINDOW_FIELDS) for w in page], limit, offset, total
    )


# ===========================================================================
# EditorShiftWindow
# ===========================================================================

@bp.post("/editor-shift-windows")
def create_shift_window():
    uid, role = authenticate()
    require_role(role, "Editor", "VendorAdmin")
    b = body()
    editor_id = req_str(b, "editor_id")
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    get_editor(editor_id)
    if role == "Editor" and editor_id != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "editors declare only their own windows", 403
        )
    if end_at <= start_at:
        raise ApiError(ERR_INVALID_WINDOW, "end_at must be strictly after start_at", 422)
    for w in store.db["shift_windows"].values():
        if w["editor_id"] != editor_id:
            continue
        # Half-open [start_at, end_at): overlap iff new.start < ex.end AND ex.start < new.end
        if start_at < w["end_at"] and w["start_at"] < end_at:
            raise ApiError(
                ERR_SHIFT_WINDOW_OVERLAP,
                "window overlaps an existing window of this editor",
                422,
            )
    w = base_entity()
    w.update({"editor_id": editor_id, "start_at": start_at, "end_at": end_at})
    store.db["shift_windows"][w["id"]] = w
    return ok_object(serialize(w, SHIFT_WINDOW_FIELDS), 201)


# ===========================================================================
# DictationJob
# ===========================================================================

@bp.post("/dictation-jobs")
def create_dictation_job():
    uid, role = authenticate()
    require_role(role, "Provider")
    b = body()
    provider_id = req_str(b, "provider_id")
    work_type = req_enum(b, "work_type", svc.WORK_TYPES)
    priority = req_enum(b, "priority", svc.PRIORITIES)
    duration = req_int(b, "audio_duration_seconds", min_v=1)
    template_id = opt_str(b, "template_id")
    provider = get_provider(provider_id)
    template = get_template(template_id) if template_id is not None else None
    if provider_id != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "provider_id must equal the caller's X-User-ID", 403
        )
    if provider["status"] == "SUSPENDED":
        raise ApiError(
            ERR_PROVIDER_SUSPENDED,
            "provider is suspended from uploading new dictations",
            409,
        )
    policy = svc.policy_for(provider["clinic_account_id"], priority)
    if policy is None:
        raise ApiError(
            ERR_SLA_POLICY_MISSING,
            "no SLA policy exists for this clinic and priority",
            422,
        )
    if template is not None:
        if template["provider_id"] != provider_id:
            raise ApiError(
                ERR_TEMPLATE_PROVIDER_MISMATCH,
                "template_id belongs to a different provider",
                422,
            )
        if template["work_type"] != work_type:
            raise ApiError(
                ERR_TEMPLATE_WORK_TYPE_MISMATCH,
                "template work_type differs from the job's work_type",
                422,
            )
    clinic = store.db["clinics"][provider["clinic_account_id"]]
    svc.recompute_billing_hold(clinic, store.now())
    if clinic["billing_hold"]:
        raise ApiError(
            ERR_CLINIC_BILLING_HOLD,
            "clinic has an overdue finalized billing period; new dictations blocked",
            402,
        )
    now = store.now()
    j = base_entity()
    j.update(
        {
            "provider_id": provider_id,
            "clinic_account_id": provider["clinic_account_id"],
            "work_type": work_type,
            "priority": priority,
            "audio_duration_seconds": duration,
            "template_id": template_id,
            "workflow_status": "QUEUED",
            "escalation_level": "NONE",
            "claimed_by_editor_id": None,
            "first_claimed_at": None,
            "claimed_at": None,
            "submitted_at": None,
            "delivered_at": None,
            "due_at": now + timedelta(minutes=policy["tat_minutes"]),
            "asr_char_estimate": duration * svc.ASR_CHARS_PER_SECOND,
            "rework_count": 0,
            "preempted_count": 0,
        }
    )
    store.db["jobs"][j["id"]] = j
    if priority == "STAT":
        svc.stat_preemption(j, now)
    return ok_object(serialize(j, JOB_FIELDS), 201)


@bp.get("/dictation-jobs/<jid>")
def get_job_route(jid):
    authenticate()
    j = get_job(jid)
    return ok_object(serialize(j, JOB_FIELDS))


@bp.get("/dictation-jobs")
def list_jobs():
    authenticate()
    from flask import request

    items = list(store.db["jobs"].values())
    for f in ("provider_id", "clinic_account_id", "claimed_by_editor_id", "template_id", "workflow_status"):
        v = request.args.get(f)
        if v is not None:
            items = [j for j in items if j.get(f) == v]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(j, JOB_FIELDS) for j in page], limit, offset, total)


@bp.post("/dictation-jobs/<jid>/claim")
def claim_job(jid):
    uid, role = authenticate()
    require_role(role, "Editor")
    b = body()
    editor_id = req_str(b, "editor_id")
    j = get_job(jid)
    editor = get_editor(editor_id)
    if editor_id != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "editor_id must equal the caller's X-User-ID", 403
        )
    if j["workflow_status"] != "QUEUED":
        raise ApiError(ERR_JOB_NOT_QUEUED, "job is not QUEUED", 409)
    if editor["status"] == "SUSPENDED":
        raise ApiError(ERR_EDITOR_NOT_ACTIVE, "editor is SUSPENDED", 409)
    if j["priority"] == "STAT" and editor["status"] != "ACTIVE":
        raise ApiError(
            ERR_PROBATION_STAT_FORBIDDEN,
            "a PROBATION editor may not claim a STAT job",
            403,
        )
    if editor["active_claim_count"] >= editor["max_concurrent_claims"]:
        raise ApiError(ERR_EDITOR_CAPACITY_FULL, "editor is at claim capacity", 409)
    now = store.now()
    in_window = any(
        w["editor_id"] == editor_id and w["start_at"] <= now < w["end_at"]
        for w in store.db["shift_windows"].values()
    )
    if not in_window:
        raise ApiError(
            ERR_OUTSIDE_SHIFT_WINDOW,
            "current time is outside every declared shift window of this editor",
            422,
        )
    j["workflow_status"] = "EDITING"
    j["claimed_by_editor_id"] = editor_id
    j["claimed_at"] = now
    if j["first_claimed_at"] is None:
        j["first_claimed_at"] = now
    touch(j)
    editor["active_claim_count"] += 1
    touch(editor)
    return ok_object(serialize(j, JOB_FIELDS))


@bp.post("/dictation-jobs/<jid>/release")
def release_job(jid):
    uid, role = authenticate()
    require_role(role, "Editor", "VendorAdmin")
    j = get_job(jid)
    if role == "Editor":
        claimed = j["claimed_by_editor_id"]
        if claimed is not None and claimed != uid:
            raise ApiError(
                ERR_FORBIDDEN_OWNERSHIP, "job is claimed by another editor", 403
            )
    if j["workflow_status"] != "EDITING":
        raise ApiError(ERR_JOB_NOT_EDITING, "job is not EDITING", 409)
    editor = store.db["editors"].get(j["claimed_by_editor_id"])
    j["workflow_status"] = "QUEUED"
    j["claimed_by_editor_id"] = None
    j["claimed_at"] = None
    touch(j)
    if editor is not None:
        editor["active_claim_count"] -= 1
        touch(editor)
    return ok_object(serialize(j, JOB_FIELDS))


@bp.post("/dictation-jobs/<jid>/submit")
def submit_job(jid):
    uid, role = authenticate()
    require_role(role, "Editor")
    b = body()
    final_text = req_str(b, "final_text")
    j = get_job(jid)
    claimed = j["claimed_by_editor_id"]
    if claimed is not None and claimed != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "job is claimed by another editor", 403
        )
    if j["workflow_status"] != "EDITING":
        raise ApiError(ERR_JOB_NOT_EDITING, "job is not EDITING", 409)
    now = store.now()
    vcc, line_count = svc.visible_chars_and_line_count(final_text)
    prior = [t for t in store.db["transcripts"].values() if t["dictation_job_id"] == j["id"]]
    version_number = len(prior) + 1
    t = base_entity()
    t.update(
        {
            "dictation_job_id": j["id"],
            "editor_id": claimed,
            "version_number": version_number,
            "final_text": final_text,
            "visible_char_count": vcc,
            "line_count": line_count,
            "status": "SUBMITTED",
            "aging_tier": "NONE",
            "delivered_at": None,
            "signed_at": None,
            "addendum_text": None,
        }
    )
    store.db["transcripts"][t["id"]] = t
    j["submitted_at"] = now
    j["workflow_status"] = "SUBMITTED"
    touch(j)
    return ok_object(serialize(j, JOB_FIELDS))


@bp.post("/dictation-jobs/<jid>/cancel")
def cancel_job(jid):
    uid, role = authenticate()
    require_role(role, "Provider", "VendorAdmin")
    j = get_job(jid)
    if role == "Provider" and j["provider_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "provider does not own this job", 403)
    if j["workflow_status"] not in ("QUEUED", "EDITING"):
        raise ApiError(
            ERR_JOB_NOT_CANCELLABLE, "only QUEUED or EDITING jobs may be cancelled", 409
        )
    if j["workflow_status"] == "EDITING":
        editor = store.db["editors"].get(j["claimed_by_editor_id"])
        j["claimed_by_editor_id"] = None
        j["claimed_at"] = None
        if editor is not None:
            editor["active_claim_count"] -= 1
            touch(editor)
    j["workflow_status"] = "CANCELLED"
    touch(j)
    return ok_object(serialize(j, JOB_FIELDS))


# ===========================================================================
# Transcript
# ===========================================================================

@bp.get("/transcripts/<tid>")
def get_transcript_route(tid):
    authenticate()
    t = get_transcript(tid)
    return ok_object(serialize(t, TRANSCRIPT_FIELDS))


@bp.get("/transcripts")
def list_transcripts():
    authenticate()
    from flask import request

    items = list(store.db["transcripts"].values())
    for f in ("dictation_job_id", "editor_id"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(t, TRANSCRIPT_FIELDS) for t in page], limit, offset, total)


def _transcript_owner_job(t):
    job = svc.job_of_transcript(t)
    return job


@bp.post("/transcripts/<tid>/sign")
def sign_transcript(tid):
    uid, role = authenticate()
    require_role(role, "Provider")
    t = get_transcript(tid)
    job = _transcript_owner_job(t)
    if job["provider_id"] != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "transcript belongs to another provider's job", 403
        )
    if t["status"] != "DELIVERED":
        raise ApiError(ERR_TRANSCRIPT_NOT_DELIVERED, "transcript is not DELIVERED", 409)
    t["status"] = "SIGNED"
    t["signed_at"] = store.now()
    touch(t)
    provider = store.db["providers"][job["provider_id"]]
    svc.recompute_provider(provider)
    return ok_object(serialize(t, TRANSCRIPT_FIELDS))


@bp.post("/transcripts/<tid>/return")
def return_transcript(tid):
    uid, role = authenticate()
    require_role(role, "Provider")
    t = get_transcript(tid)
    job = _transcript_owner_job(t)
    if job["provider_id"] != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "transcript belongs to another provider's job", 403
        )
    if t["status"] != "DELIVERED":
        raise ApiError(ERR_TRANSCRIPT_NOT_DELIVERED, "transcript is not DELIVERED", 409)
    now = store.now()
    t["status"] = "RETURNED"
    touch(t)
    # Parent job DELIVERED -> EDITING; system re-claim to the authoring editor
    # bypasses the capacity ceiling and shift-window gate and fires no preemption.
    job["workflow_status"] = "EDITING"
    job["rework_count"] += 1
    job["claimed_by_editor_id"] = t["editor_id"]
    job["claimed_at"] = now
    touch(job)
    editor = store.db["editors"].get(t["editor_id"])
    if editor is not None:
        editor["active_claim_count"] += 1
        touch(editor)
    provider = store.db["providers"][job["provider_id"]]
    svc.recompute_provider(provider)
    return ok_object(serialize(t, TRANSCRIPT_FIELDS))


@bp.post("/transcripts/<tid>/addend")
def addend_transcript(tid):
    uid, role = authenticate()
    require_role(role, "Provider")
    b = body()
    addendum_text = req_str(b, "addendum_text")
    t = get_transcript(tid)
    job = _transcript_owner_job(t)
    if job["provider_id"] != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "transcript belongs to another provider's job", 403
        )
    if t["status"] != "SIGNED":
        raise ApiError(ERR_TRANSCRIPT_NOT_SIGNED, "transcript is not SIGNED", 409)
    t["status"] = "AMENDED"
    t["addendum_text"] = addendum_text
    touch(t)
    return ok_object(serialize(t, TRANSCRIPT_FIELDS))


# ===========================================================================
# QAReview
# ===========================================================================

@bp.post("/qa-reviews")
def create_qa_review():
    uid, role = authenticate()
    require_role(role, "QASupervisor")
    b = body()
    dictation_job_id = req_str(b, "dictation_job_id")
    critical = req_int(b, "critical_error_count", min_v=0)
    major = req_int(b, "major_error_count", min_v=0)
    minor = req_int(b, "minor_error_count", min_v=0)
    job = get_job(dictation_job_id)
    if job["workflow_status"] != "SUBMITTED":
        raise ApiError(ERR_JOB_NOT_SUBMITTED, "job is not SUBMITTED", 409)
    transcript = svc.current_transcript(job)
    if transcript["editor_id"] == uid:
        raise ApiError(
            ERR_SELF_REVIEW_FORBIDDEN,
            "the reviewer may not review a transcript they authored",
            403,
        )
    now = store.now()
    score_val = max(0, 100 - 25 * critical - 5 * major - 1 * minor)
    accuracy = Decimal(score_val).quantize(Decimal("0.01"))
    outcome = "PASS" if (accuracy >= svc.PASS_THRESHOLD and critical == 0) else "FAIL"
    editor = store.db["editors"][transcript["editor_id"]]
    review = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
        "dictation_job_id": job["id"],
        "transcript_id": transcript["id"],
        "reviewer_user_id": uid,
        "critical_error_count": critical,
        "major_error_count": major,
        "minor_error_count": minor,
        "accuracy_score": accuracy,
        "outcome": outcome,
        "editor_sequence": len(svc.reviews_of_editor(editor["id"])) + 1,
    }
    store.db["qa_reviews"][review["id"]] = review
    if outcome == "PASS":
        transcript["status"] = "DELIVERED"
        transcript["delivered_at"] = now
        transcript["aging_tier"] = "NONE"
        touch(transcript)
        job["workflow_status"] = "DELIVERED"
        job["delivered_at"] = now
        job["claimed_by_editor_id"] = None
        job["claimed_at"] = None
        touch(job)
        editor["active_claim_count"] -= 1
    else:
        transcript["status"] = "REJECTED"
        touch(transcript)
        job["workflow_status"] = "EDITING"
        job["rework_count"] += 1
        touch(job)
    svc.editor_standing_cascade(editor, review)
    return ok_object(serialize(review, QA_REVIEW_FIELDS), 201)


@bp.get("/dictation-jobs/<jid>/qa-reviews")
def list_job_qa_reviews(jid):
    authenticate()
    j = get_job(jid)
    items = sorted_created(
        r for r in store.db["qa_reviews"].values() if r["dictation_job_id"] == j["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(r, QA_REVIEW_FIELDS) for r in page], limit, offset, total)


@bp.get("/transcripts/<tid>/qa-reviews")
def list_transcript_qa_reviews(tid):
    authenticate()
    t = get_transcript(tid)
    items = sorted_created(
        r for r in store.db["qa_reviews"].values() if r["transcript_id"] == t["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(r, QA_REVIEW_FIELDS) for r in page], limit, offset, total)


# ===========================================================================
# ProviderTemplate
# ===========================================================================

@bp.post("/provider-templates")
def create_template():
    uid, role = authenticate()
    require_role(role, "Provider")
    b = body()
    provider_id = req_str(b, "provider_id")
    work_type = req_enum(b, "work_type", svc.WORK_TYPES)
    name = req_str(b, "name")
    body_text = req_str(b, "body_text")
    expected_provider_version = req_int(b, "expected_provider_version")
    provider = get_provider(provider_id)
    if provider_id != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "provider_id must equal the caller's X-User-ID", 403
        )
    if expected_provider_version != provider["version"]:
        raise ApiError(
            ERR_STALE_PROVIDER_VERSION,
            "expected_provider_version does not match the provider's current version",
            412,
        )
    prior = None
    for t in store.db["templates"].values():
        if (
            t["provider_id"] == provider_id
            and t["work_type"] == work_type
            and t["is_active"]
        ):
            prior = t
            break
    if prior is not None:
        prior["is_active"] = False
        touch(prior)
    t = base_entity()
    t.update(
        {
            "provider_id": provider_id,
            "work_type": work_type,
            "name": name,
            "body_text": body_text,
            "is_active": True,
        }
    )
    store.db["templates"][t["id"]] = t
    # Supersession is a mutation of the provider itself.
    touch(provider)
    return ok_object(serialize(t, TEMPLATE_FIELDS), 201)


@bp.put("/provider-templates/<tid>")
def update_template(tid):
    uid, role = authenticate()
    require_role(role, "Provider")
    b = body()
    name = opt_str(b, "name")
    body_text = opt_str(b, "body_text")
    expected_template_version = req_int(b, "expected_template_version")
    t = get_template(tid)
    if t["provider_id"] != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "template belongs to another provider", 403
        )
    if expected_template_version != t["version"]:
        raise ApiError(
            ERR_STALE_TEMPLATE_VERSION,
            "expected_template_version does not match the template's current version",
            412,
        )
    if name is not None:
        t["name"] = name
    if body_text is not None:
        t["body_text"] = body_text
    touch(t)
    return ok_object(serialize(t, TEMPLATE_FIELDS))


# ===========================================================================
# Macro
# ===========================================================================

@bp.post("/macros")
def create_macro():
    uid, role = authenticate()
    require_role(role, "Provider")
    b = body()
    provider_id = req_str(b, "provider_id")
    shortcut = req_str(b, "shortcut")
    expansion_text = req_str(b, "expansion_text")
    get_provider(provider_id)
    if provider_id != uid:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP, "provider_id must equal the caller's X-User-ID", 403
        )
    for m in store.db["macros"].values():
        if (
            m["provider_id"] == provider_id
            and m["status"] == "ACTIVE"
            and m["shortcut"] == shortcut
        ):
            raise ApiError(
                ERR_DUPLICATE_MACRO_SHORTCUT,
                "an ACTIVE macro with this shortcut already exists for this provider",
                409,
            )
    m = base_entity()
    m.update(
        {
            "provider_id": provider_id,
            "shortcut": shortcut,
            "expansion_text": expansion_text,
            "status": "ACTIVE",
        }
    )
    store.db["macros"][m["id"]] = m
    return ok_object(serialize(m, MACRO_FIELDS), 201)


@bp.post("/macros/<mid>/archive")
def archive_macro(mid):
    uid, role = authenticate()
    require_role(role, "Provider")
    m = get_macro(mid)
    if m["provider_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "macro belongs to another provider", 403)
    m["status"] = "ARCHIVED"
    touch(m)
    return ok_object(serialize(m, MACRO_FIELDS))


# ===========================================================================
# BillingPeriod / LineItem
# ===========================================================================

@bp.post("/billing-periods")
def create_billing_period():
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    b = body()
    clinic_account_id = req_str(b, "clinic_account_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    get_clinic(clinic_account_id)
    if period_end <= period_start:
        raise ApiError(
            ERR_INVALID_WINDOW, "period_end must be strictly after period_start", 422
        )
    for p in store.db["billing_periods"].values():
        if p["clinic_account_id"] != clinic_account_id:
            continue
        # Closed interval [start, end]: touching endpoints ARE a conflict.
        if period_start <= p["period_end"] and p["period_start"] <= period_end:
            raise ApiError(
                ERR_BILLING_PERIOD_OVERLAP,
                "period overlaps an existing billing period of this clinic",
                422,
            )
    p = base_entity()
    p.update(
        {
            "clinic_account_id": clinic_account_id,
            "period_start": period_start,
            "period_end": period_end,
            "status": "OPEN",
            "gross_amount_cents": 0,
            "credit_amount_cents": 0,
            "net_amount_cents": 0,
            "finalized_at": None,
        }
    )
    store.db["billing_periods"][p["id"]] = p
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS), 201)


@bp.get("/billing-periods/<bid>")
def get_billing_period(bid):
    authenticate()
    p = get_period(bid)
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS))


@bp.post("/billing-periods/<bid>/close")
def close_billing_period(bid):
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    p = get_period(bid)
    if p["status"] != "OPEN":
        raise ApiError(ERR_BILLING_PERIOD_NOT_OPEN, "period is not OPEN", 409)
    svc.generate_line_items(p)
    p["status"] = "CLOSED"
    touch(p)
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS))


@bp.post("/billing-periods/<bid>/finalize")
def finalize_billing_period(bid):
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    p = get_period(bid)
    if p["status"] != "CLOSED":
        raise ApiError(ERR_BILLING_PERIOD_NOT_CLOSED, "period is not CLOSED", 409)
    svc.finalize_line_items(p, store.now())
    clinic = store.db["clinics"][p["clinic_account_id"]]
    svc.recompute_billing_hold(clinic, store.now())
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS))


@bp.post("/billing-periods/<bid>/dispute")
def dispute_billing_period(bid):
    _, role = authenticate()
    require_role(role, "ClientAdmin")
    p = get_period(bid)
    if p["status"] != "FINALIZED":
        raise ApiError(ERR_BILLING_PERIOD_NOT_FINALIZED, "period is not FINALIZED", 409)
    p["status"] = "DISPUTED"
    touch(p)
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS))


@bp.post("/billing-periods/<bid>/resolve-dispute")
def resolve_dispute(bid):
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    b = body()
    outcome = req_enum(b, "outcome", svc.DISPUTE_OUTCOMES)
    p = get_period(bid)
    if p["status"] != "DISPUTED":
        raise ApiError(ERR_BILLING_PERIOD_NOT_DISPUTED, "period is not DISPUTED", 409)
    if outcome == "REVERSED":
        for item in store.db["line_items"].values():
            if item["billing_period_id"] != p["id"]:
                continue
            item["credit_cents"] = 0
            item["status"] = "CREDIT_REVERSED"
            touch(item)
        p["credit_amount_cents"] = 0
        p["net_amount_cents"] = p["gross_amount_cents"]
    p["status"] = "FINALIZED"
    touch(p)
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS))


@bp.post("/billing-periods/<bid>/settle")
def settle_billing_period(bid):
    _, role = authenticate()
    require_role(role, "VendorAdmin")
    p = get_period(bid)
    if p["status"] != "FINALIZED":
        raise ApiError(ERR_BILLING_PERIOD_NOT_FINALIZED, "period is not FINALIZED", 409)
    p["status"] = "SETTLED"
    touch(p)
    clinic = store.db["clinics"][p["clinic_account_id"]]
    svc.recompute_billing_hold(clinic, store.now())
    return ok_object(serialize(p, BILLING_PERIOD_FIELDS))


@bp.get("/billing-periods/<bid>/line-items")
def list_period_line_items(bid):
    authenticate()
    p = get_period(bid)
    items = sorted_created(
        i for i in store.db["line_items"].values() if i["billing_period_id"] == p["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(i, LINE_ITEM_FIELDS) for i in page], limit, offset, total)


@bp.get("/transcripts/<tid>/line-items")
def list_transcript_line_items(tid):
    authenticate()
    t = get_transcript(tid)
    items = sorted_created(
        i for i in store.db["line_items"].values() if i["transcript_id"] == t["id"]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([serialize(i, LINE_ITEM_FIELDS) for i in page], limit, offset, total)
