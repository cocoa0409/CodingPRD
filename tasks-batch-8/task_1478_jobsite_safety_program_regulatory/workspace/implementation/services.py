"""Domain logic: posture, cascades, scores, conflicts, sweep, OSHA summary,
serializers. All state lives in db.store (in-memory only)."""

from datetime import timedelta, timezone, datetime
from decimal import Decimal, ROUND_HALF_UP

from db import store, now
from helpers import fmt3, fmt_ts, end_of_day

# ---------------------------------------------------------------------------
# Constants (from scaffold calculations)
# ---------------------------------------------------------------------------

SEVERITY_SLA_DAYS = {
    "MINOR": 14,
    "MAJOR": 7,
    "CRITICAL": 3,
    "IMMINENT_DANGER": 0,
}

SEVERITY_DEDUCTION = {
    "MINOR": 5,
    "MAJOR": 15,
    "CRITICAL": 30,
    "IMMINENT_DANGER": 50,
}

RECORDABLE_INCIDENT_DEDUCTION = 25
DEMOTE_THRESHOLD = 80
HOT_WORK_BUFFER_MINUTES = 60
POST_INCIDENT_WINDOW_HOURS = 32
OSHA_BASE_HOURS = 200000


# ---------------------------------------------------------------------------
# Generic mutation helper: refreshes updated_at and increments version.
# ---------------------------------------------------------------------------

def bump(entity):
    entity["updated_at"] = now()
    entity["version"] += 1


def project_bump(project):
    """Project.version increments only where the spec lists it explicitly
    (plan activation; permit issue/close/suspend/reinstate/expire-from-ISSUED;
    deficiency verify-close)."""
    bump(project)


# ---------------------------------------------------------------------------
# Fetch-or-404 helpers (validation priority 3)
# ---------------------------------------------------------------------------

def _get(table, rid, error_id):
    rec = table.get(rid)
    if rec is None:
        from errors import ApiError

        raise ApiError(error_id, 404, f"Resource not found: {rid}")
    return rec


def get_project(rid):
    return _get(store.projects, rid, "ERR_PROJECT_NOT_FOUND")


def get_plan(rid):
    return _get(store.plans, rid, "ERR_SAFETY_PLAN_NOT_FOUND")


def get_worker(rid):
    return _get(store.workers, rid, "ERR_WORKER_NOT_FOUND")


def get_certificate(rid):
    return _get(store.certificates, rid, "ERR_CERTIFICATE_NOT_FOUND")


def get_subcontractor(rid):
    return _get(store.subcontractors, rid, "ERR_SUBCONTRACTOR_NOT_FOUND")


def get_huddle(rid):
    return _get(store.huddles, rid, "ERR_HUDDLE_NOT_FOUND")


def get_jha(rid):
    return _get(store.jhas, rid, "ERR_JHA_NOT_FOUND")


def get_inspection(rid):
    return _get(store.inspections, rid, "ERR_INSPECTION_NOT_FOUND")


def get_deficiency(rid):
    return _get(store.deficiencies, rid, "ERR_DEFICIENCY_NOT_FOUND")


def get_incident(rid):
    return _get(store.incidents, rid, "ERR_INCIDENT_NOT_FOUND")


def get_permit(rid):
    return _get(store.permits, rid, "ERR_PERMIT_NOT_FOUND")


def get_drugtest(rid):
    return _get(store.drugtests, rid, "ERR_DRUG_TEST_NOT_FOUND")


# ---------------------------------------------------------------------------
# Project posture (derived; recomputed at the documented triggers)
# ---------------------------------------------------------------------------

def compute_posture(project_id):
    for d in store.deficiencies.values():
        if (
            d["project_id"] == project_id
            and d["severity"] == "IMMINENT_DANGER"
            and d["status"] in ("OPEN", "OVERDUE")
        ):
            return "FROZEN"
    for i in store.incidents.values():
        if (
            i["project_id"] == project_id
            and i["severity"] in ("CRITICAL", "FATALITY")
            and i["status"] in ("REPORTED", "UNDER_INVESTIGATION", "DETERMINATION_MADE")
        ):
            return "FROZEN"
    overdue = [
        d
        for d in store.deficiencies.values()
        if d["project_id"] == project_id and d["status"] == "OVERDUE"
    ]
    if any(d["severity"] in ("MAJOR", "CRITICAL") for d in overdue):
        return "RESTRICTED"
    if len(overdue) >= 3:
        return "RESTRICTED"
    return "NORMAL"


def recompute_posture(project, bump_version_on_change=True):
    """Recompute safety_posture from deficiency/incident sets only. On a
    transition INTO FROZEN, suspend every ISSUED permit (POSTURE_FROZEN) and
    cascade to JHAs. No automatic reinstatement when leaving FROZEN."""
    old = project["safety_posture"]
    new = compute_posture(project["id"])
    if new == old:
        return
    project["safety_posture"] = new
    if bump_version_on_change:
        bump(project)
    else:
        project["updated_at"] = now()
    if new == "FROZEN":
        for permit in list(store.permits.values()):
            if permit["project_id"] == project["id"] and permit["status"] == "ISSUED":
                suspend_permit(permit, "POSTURE_FROZEN")


# ---------------------------------------------------------------------------
# Three-link enforcement cascade
# ---------------------------------------------------------------------------

def suspend_permit(permit, reason):
    """Link 2: ISSUED permit -> SUSPENDED; project counter/version; link 3."""
    permit["status"] = "SUSPENDED"
    permit["suspension_reason"] = reason
    bump(permit)
    project = store.projects.get(permit["project_id"])
    if project is not None:
        project_bump(project)  # issued_permit_count decrements; version increments
    jha = store.jhas.get(permit["jha_id"])
    if jha is not None and jha["status"] == "APPROVED":
        jha["status"] = "RE_REVIEW_REQUIRED"
        bump(jha)


def cascade_worker_permits(worker_id, reason):
    """Link 2/3 for a workforce event: every ISSUED permit listing the worker."""
    for permit in list(store.permits.values()):
        if (
            permit["status"] == "ISSUED"
            and worker_id in permit["authorized_worker_ids"]
        ):
            suspend_permit(permit, reason)


def cascade_subcontractor_removed(sub):
    """Subcontractor PROBATION -> REMOVED: ORIENTED/CLEARED workers -> REMOVED;
    CLEARED workers additionally fire link 2/3 with CREW_MEMBER_REMOVED."""
    for worker in list(store.workers.values()):
        if worker["subcontractor_id"] != sub["id"]:
            continue
        if worker["status"] == "CLEARED":
            worker["status"] = "REMOVED"
            bump(worker)
            cascade_worker_permits(worker["id"], "CREW_MEMBER_REMOVED")
        elif worker["status"] == "ORIENTED":
            worker["status"] = "REMOVED"
            bump(worker)


def cascade_positive_drug_test(worker):
    """POSITIVE result: worker -> SUSPENDED (from ORIENTED or CLEARED) with
    reason POSITIVE_DRUG_TEST, then link 2/3 with CREW_MEMBER_SUSPENDED."""
    if worker["status"] in ("ORIENTED", "CLEARED"):
        worker["status"] = "SUSPENDED"
        worker["suspension_reason"] = "POSITIVE_DRUG_TEST"
        bump(worker)
        cascade_worker_permits(worker["id"], "CREW_MEMBER_SUSPENDED")


# ---------------------------------------------------------------------------
# Subcontractor compliance scores (recomputed on every read)
# ---------------------------------------------------------------------------

def _worker_belongs_to_sub(worker_id, sub_id):
    if worker_id is None:
        return False
    w = store.workers.get(worker_id)
    return w is not None and w["subcontractor_id"] == sub_id


def _recordable_incidents_for_sub(sub_id):
    return [
        i
        for i in store.incidents.values()
        if i["is_osha_recordable"] is True
        and i["status"] in ("DETERMINATION_MADE", "CLOSED")
        and _worker_belongs_to_sub(i["worker_id"], sub_id)
    ]


def _clamp_score(s):
    return max(0, min(100, s))


def compliance_score_realtime(sub_id):
    """Open deficiencies only (OVERDUE doubles); VERIFIED_CLOSED contribute 0;
    recordable incidents in DETERMINATION_MADE/CLOSED."""
    score = 100
    for d in store.deficiencies.values():
        if d["assigned_subcontractor_id"] != sub_id:
            continue
        if d["status"] in ("OPEN", "OVERDUE", "CORRECTION_SUBMITTED"):
            score -= SEVERITY_DEDUCTION[d["severity"]]
            if d["status"] == "OVERDUE":
                score -= SEVERITY_DEDUCTION[d["severity"]]
    for _ in _recordable_incidents_for_sub(sub_id):
        score -= RECORDABLE_INCIDENT_DEDUCTION
    return _clamp_score(score)


def compliance_score_period_90d(sub_id):
    """All deficiencies created within trailing 90 days (no doubling);
    NOT_SUB_FAULT closures refunded; recordable incidents occurred within
    trailing 90 days."""
    score = 100
    t = now()
    cutoff = t - timedelta(days=90)
    for d in store.deficiencies.values():
        if d["assigned_subcontractor_id"] != sub_id:
            continue
        if not (cutoff <= d["created_at"] <= t):
            continue
        if d["status"] == "VERIFIED_CLOSED" and d["closed_disposition"] == "NOT_SUB_FAULT":
            continue
        score -= SEVERITY_DEDUCTION[d["severity"]]
    for i in _recordable_incidents_for_sub(sub_id):
        if cutoff <= i["occurred_at"] <= t:
            score -= RECORDABLE_INCIDENT_DEDUCTION
    return _clamp_score(score)


# ---------------------------------------------------------------------------
# Training clearance check
# ---------------------------------------------------------------------------

def training_clearance_ok(worker):
    candidates = [
        c
        for c in store.certificates.values()
        if c["worker_id"] == worker["id"]
        and c["status"] == "VERIFIED"
        and now() <= end_of_day(c["expires_date"])
    ]
    if worker["is_supervisor"]:
        return any(c["cert_type"] == "OSHA_30" for c in candidates)
    return any(c["cert_type"] in ("OSHA_10", "OSHA_30") for c in candidates)


# ---------------------------------------------------------------------------
# Certificate window overlap (day-granularity half-open on the expiry edge)
# ---------------------------------------------------------------------------

def certificate_window_conflicts(worker_id, cert_type, issued_date, expires_date):
    for c in store.certificates.values():
        if c["worker_id"] != worker_id or c["cert_type"] != cert_type:
            continue
        if c["status"] == "EXPIRED":
            continue
        if issued_date < c["expires_date"] and c["issued_date"] < expires_date:
            return True
    return False


# ---------------------------------------------------------------------------
# Permit temporal conflict rules
# ---------------------------------------------------------------------------

def permit_time_conflicts(project_id, permit_type, work_start, work_end, crew, exclude_id=None):
    others = [
        p
        for p in store.permits.values()
        if p["project_id"] == project_id and p["id"] != exclude_id
    ]
    # (1) EXCAVATION project rule — half-open [start, end)
    if permit_type == "EXCAVATION":
        for o in others:
            if o["permit_type"] != "EXCAVATION":
                continue
            if o["status"] not in ("REQUESTED", "ISSUED", "SUSPENDED"):
                continue
            if work_start < o["work_end"] and o["work_start"] < work_end:
                return True
    # (2) HOT_WORK buffer rule — 60 minute gap
    if permit_type == "HOT_WORK":
        buf = timedelta(minutes=HOT_WORK_BUFFER_MINUTES)
        for o in others:
            if o["permit_type"] != "HOT_WORK":
                continue
            if o["status"] not in ("REQUESTED", "ISSUED", "SUSPENDED"):
                continue
            if not (work_start >= o["work_end"] + buf or work_end + buf <= o["work_start"]):
                return True
    # (3) Crew rule — closed-interval overlap against ISSUED/SUSPENDED permits
    crew_set = set(crew)
    for o in others:
        if o["status"] not in ("ISSUED", "SUSPENDED"):
            continue
        if not crew_set.intersection(o["authorized_worker_ids"]):
            continue
        if work_start <= o["work_end"] and o["work_start"] <= work_end:
            return True
    return False


# ---------------------------------------------------------------------------
# Clock sweep (pinned order, then posture recompute per project)
# ---------------------------------------------------------------------------

def run_sweep():
    t = now()
    # 1) deficiency OPEN -> OVERDUE (strictly greater)
    for d in list(store.deficiencies.values()):
        if d["status"] == "OPEN" and t > d["due_at"]:
            d["status"] = "OVERDUE"
            bump(d)
    # 2) inspection DUE -> OVERDUE (strictly greater)
    for i in list(store.inspections.values()):
        if i["status"] == "DUE" and t > i["due_date"]:
            i["status"] = "OVERDUE"
            bump(i)
    # 3) huddle SCHEDULED -> MISSED (current later than huddle_date + 1 day)
    for h in list(store.huddles.values()):
        if h["status"] == "SCHEDULED":
            threshold = datetime.combine(
                h["huddle_date"] + timedelta(days=1),
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            if t > threshold:
                h["status"] = "MISSED"
                bump(h)
    # 4) certificates UNVERIFIED/VERIFIED -> EXPIRED once expiry fully passed
    for c in list(store.certificates.values()):
        if c["status"] in ("UNVERIFIED", "VERIFIED") and t > end_of_day(c["expires_date"]):
            c["status"] = "EXPIRED"
            bump(c)
    # 5) permits REQUESTED/ISSUED/SUSPENDED -> EXPIRED (strictly past work_end)
    for p in list(store.permits.values()):
        if p["status"] in ("REQUESTED", "ISSUED", "SUSPENDED") and t > p["work_end"]:
            was_issued = p["status"] == "ISSUED"
            p["status"] = "EXPIRED"
            bump(p)
            if was_issued:
                project = store.projects.get(p["project_id"])
                if project is not None:
                    project_bump(project)
    # 6) posture recompute per project
    for project in list(store.projects.values()):
        recompute_posture(project)


# ---------------------------------------------------------------------------
# OSHA incident rates (pinned rounding order: round each rate first)
# ---------------------------------------------------------------------------

def _rate(count, hours):
    return (Decimal(count * OSHA_BASE_HOURS) / Decimal(hours)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def osha_summary(project, year):
    incidents = [
        i
        for i in store.incidents.values()
        if i["project_id"] == project["id"] and i["occurred_at"].year == year
    ]
    final_recordable = [
        i
        for i in incidents
        if i["status"] in ("DETERMINATION_MADE", "CLOSED")
        and i["is_osha_recordable"] is True
    ]
    open_incidents = [
        i for i in incidents if i["status"] in ("REPORTED", "UNDER_INVESTIGATION")
    ]
    recordable_count_final = len(final_recordable)
    recordable_count_provisional = recordable_count_final + len(open_incidents)
    dart_count_final = len(
        [
            i
            for i in final_recordable
            if i["days_away_from_work"] > 0 or i["restricted_duty"]
        ]
    )
    dart_count_provisional = dart_count_final + len(open_incidents)
    hours = project["annual_hours_worked"]
    trir_final = _rate(recordable_count_final, hours)
    dart_rate_final = _rate(dart_count_final, hours)
    trir_provisional = _rate(recordable_count_provisional, hours)
    dart_rate_provisional = _rate(dart_count_provisional, hours)
    rate_spread_final = trir_final - dart_rate_final
    return {
        "year": year,
        "hours_worked": hours,
        "recordable_count_final": recordable_count_final,
        "recordable_count_provisional": recordable_count_provisional,
        "dart_count_final": dart_count_final,
        "dart_count_provisional": dart_count_provisional,
        "trir_final": float(trir_final),
        "trir_provisional": float(trir_provisional),
        "dart_rate_final": float(dart_rate_final),
        "dart_rate_provisional": float(dart_rate_provisional),
        "rate_spread_final": float(rate_spread_final),
    }


# ---------------------------------------------------------------------------
# Serializers (internal datetimes/dates -> wire format)
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "created_at": fmt3(e["created_at"]),
        "updated_at": fmt3(e["updated_at"]),
        "version": e["version"],
    }


def _dt_or_none(v):
    return None if v is None else fmt_ts(v)


def ser_project(p):
    issued = len(
        [
            x
            for x in store.permits.values()
            if x["project_id"] == p["id"] and x["status"] == "ISSUED"
        ]
    )
    open_def = len(
        [
            x
            for x in store.deficiencies.values()
            if x["project_id"] == p["id"]
            and x["status"] in ("OPEN", "OVERDUE", "CORRECTION_SUBMITTED")
        ]
    )
    out = {
        "id": p["id"],
        "name": p["name"],
        "location": p["location"],
        "annual_hours_worked": p["annual_hours_worked"],
        "safety_posture": p["safety_posture"],
        "current_active_plan_id": p["current_active_plan_id"],
        "issued_permit_count": issued,
        "open_deficiency_count": open_def,
    }
    out.update(_common(p))
    return out


def ser_plan(p):
    out = {
        "id": p["id"],
        "project_id": p["project_id"],
        "effective_date": p["effective_date"].isoformat(),
        "revision_notes": p["revision_notes"],
        "revision_no": p["revision_no"],
        "status": p["status"],
        "activated_at": _dt_or_none(p["activated_at"]),
    }
    out.update(_common(p))
    return out


def ser_worker(w):
    out = {
        "id": w["id"],
        "project_id": w["project_id"],
        "full_name": w["full_name"],
        "employer_type": w["employer_type"],
        "subcontractor_id": w["subcontractor_id"],
        "is_supervisor": w["is_supervisor"],
        "status": w["status"],
        "orientation_completed_at": _dt_or_none(w["orientation_completed_at"]),
        "suspension_reason": w["suspension_reason"],
    }
    out.update(_common(w))
    return out


def ser_certificate(c):
    out = {
        "id": c["id"],
        "worker_id": c["worker_id"],
        "cert_type": c["cert_type"],
        "issued_date": c["issued_date"].isoformat(),
        "expires_date": c["expires_date"].isoformat(),
        "status": c["status"],
        "verified_by_user_id": c["verified_by_user_id"],
    }
    out.update(_common(c))
    return out


def ser_subcontractor(s):
    out = {
        "id": s["id"],
        "project_id": s["project_id"],
        "company_name": s["company_name"],
        "trade": s["trade"],
        "standing": s["standing"],
        "compliance_score_realtime": compliance_score_realtime(s["id"]),
        "compliance_score_period_90d": compliance_score_period_90d(s["id"]),
    }
    out.update(_common(s))
    return out


def ser_huddle(h):
    out = {
        "id": h["id"],
        "project_id": h["project_id"],
        "huddle_date": h["huddle_date"].isoformat(),
        "topics": h["topics"],
        "status": h["status"],
        "attendee_worker_ids": list(h["attendee_worker_ids"]),
        "conducted_at": _dt_or_none(h["conducted_at"]),
    }
    out.update(_common(h))
    return out


def ser_jha(j):
    out = {
        "id": j["id"],
        "project_id": j["project_id"],
        "huddle_id": j["huddle_id"],
        "task_description": j["task_description"],
        "hazards": j["hazards"],
        "controls": j["controls"],
        "status": j["status"],
    }
    out.update(_common(j))
    return out


def ser_inspection(i):
    out = {
        "id": i["id"],
        "project_id": i["project_id"],
        "inspection_type": i["inspection_type"],
        "due_date": fmt_ts(i["due_date"]),
        "status": i["status"],
        "completed_at": _dt_or_none(i["completed_at"]),
        "findings_summary": i["findings_summary"],
    }
    out.update(_common(i))
    return out


def ser_deficiency(d):
    out = {
        "id": d["id"],
        "inspection_id": d["inspection_id"],
        "project_id": d["project_id"],
        "description": d["description"],
        "severity": d["severity"],
        "assigned_subcontractor_id": d["assigned_subcontractor_id"],
        "due_at": fmt_ts(d["due_at"]),
        "status": d["status"],
        "correction_notes": d["correction_notes"],
        "created_by_user_id": d["created_by_user_id"],
        "verified_by_user_id": d["verified_by_user_id"],
        "closed_disposition": d["closed_disposition"],
    }
    out.update(_common(d))
    return out


def ser_incident(i):
    out = {
        "id": i["id"],
        "project_id": i["project_id"],
        "worker_id": i["worker_id"],
        "incident_type": i["incident_type"],
        "severity": i["severity"],
        "occurred_at": fmt_ts(i["occurred_at"]),
        "work_related": i["work_related"],
        "description": i["description"],
        "status": i["status"],
        "investigator_user_id": i["investigator_user_id"],
        "investigation_notes": i["investigation_notes"],
        "medical_treatment_beyond_first_aid": i["medical_treatment_beyond_first_aid"],
        "days_away_from_work": i["days_away_from_work"],
        "restricted_duty": i["restricted_duty"],
        "loss_of_consciousness": i["loss_of_consciousness"],
        "significant_diagnosis": i["significant_diagnosis"],
        "is_osha_recordable": i["is_osha_recordable"],
    }
    out.update(_common(i))
    return out


def ser_permit(p):
    out = {
        "id": p["id"],
        "project_id": p["project_id"],
        "jha_id": p["jha_id"],
        "permit_type": p["permit_type"],
        "work_start": fmt_ts(p["work_start"]),
        "work_end": fmt_ts(p["work_end"]),
        "authorized_worker_ids": list(p["authorized_worker_ids"]),
        "status": p["status"],
        "suspension_reason": p["suspension_reason"],
    }
    out.update(_common(p))
    return out


def ser_drugtest(d):
    out = {
        "id": d["id"],
        "worker_id": d["worker_id"],
        "test_type": d["test_type"],
        "incident_id": d["incident_id"],
        "collected_at": fmt_ts(d["collected_at"]),
        "status": d["status"],
        "window_compliant": d["window_compliant"],
    }
    out.update(_common(d))
    return out


def new_entity():
    """Base fields for a freshly created entity (in-memory only)."""
    import uuid

    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": store.next_seq(),
    }
