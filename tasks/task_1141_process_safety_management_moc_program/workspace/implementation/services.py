"""Domain services: calculations, derived-field reconciliation, clock sweep,
bubble-ups, serializers, and existence lookups."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import store
from errors import (
    ApiError, not_found,
    ERR_UNIT_NOT_FOUND, ERR_PERSONNEL_NOT_FOUND, ERR_MOC_NOT_FOUND,
    ERR_REVIEW_NOT_FOUND, ERR_PHA_STUDY_NOT_FOUND, ERR_REVALIDATION_NOT_FOUND,
    ERR_PSSR_NOT_FOUND, ERR_ACTION_ITEM_NOT_FOUND, ERR_INCIDENT_NOT_FOUND,
    ERR_AUDIT_NOT_FOUND, ERR_PROCEDURE_UPDATE_NOT_FOUND,
    ERR_TRAINING_ASSIGNMENT_NOT_FOUND, ERR_EXTENSION_NOT_FOUND,
)
from helpers import now_iso, fmt_day

OPEN_ACTION_STATUSES = ("OPEN", "IN_PROGRESS", "SUBMITTED_FOR_VERIFICATION", "REJECTED")
SLA_DAYS = {"P1": 30, "P2": 90, "P3": 180}
CLASS_MULT = {
    "PERMANENT": Decimal("1.0"),
    "TEMPORARY": Decimal("1.2"),
    "REPLACEMENT_IN_KIND": Decimal("0.5"),
}
HIGH_SEVERITY = ("HIGH", "CATASTROPHIC")
DAYS_PER_MONTH = 30


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity():
    store.seq += 1
    return {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": store.seq,
    }


def touch(e):
    """Refresh updated_at and bump version on any mutation (cascades included)."""
    e["updated_at"] = now_iso()
    e["version"] = e.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Existence lookups (path ids, left-to-right)
# ---------------------------------------------------------------------------

def get_unit(uid):
    u = store.units.get(uid)
    if u is None:
        raise not_found(ERR_UNIT_NOT_FOUND, "PlantUnit")
    return u


def get_person(pid):
    p = store.personnel.get(pid)
    if p is None:
        raise not_found(ERR_PERSONNEL_NOT_FOUND, "Personnel")
    return p


def get_moc(mid):
    m = store.mocs.get(mid)
    if m is None:
        raise not_found(ERR_MOC_NOT_FOUND, "MocRequest")
    return m


def get_review(rid):
    r = store.reviews.get(rid)
    if r is None:
        raise not_found(ERR_REVIEW_NOT_FOUND, "TechnicalReview")
    return r


def get_study(sid):
    s = store.studies.get(sid)
    if s is None:
        raise not_found(ERR_PHA_STUDY_NOT_FOUND, "PhaStudy")
    return s


def get_revalidation(rid):
    r = store.revalidations.get(rid)
    if r is None:
        raise not_found(ERR_REVALIDATION_NOT_FOUND, "PhaRevalidation")
    return r


def get_pssr(pid):
    p = store.pssrs.get(pid)
    if p is None:
        raise not_found(ERR_PSSR_NOT_FOUND, "Pssr")
    return p


def get_action_item(aid):
    a = store.action_items.get(aid)
    if a is None:
        raise not_found(ERR_ACTION_ITEM_NOT_FOUND, "ActionItem")
    return a


def get_incident(iid):
    i = store.incidents.get(iid)
    if i is None:
        raise not_found(ERR_INCIDENT_NOT_FOUND, "IncidentInvestigation")
    return i


def get_audit(aid):
    a = store.audits.get(aid)
    if a is None:
        raise not_found(ERR_AUDIT_NOT_FOUND, "Audit")
    return a


def get_procedure(pid):
    p = store.procedures.get(pid)
    if p is None:
        raise not_found(ERR_PROCEDURE_UPDATE_NOT_FOUND, "ProcedureUpdate")
    return p


def get_training(tid):
    t = store.trainings.get(tid)
    if t is None:
        raise not_found(ERR_TRAINING_ASSIGNMENT_NOT_FOUND, "TrainingAssignment")
    return t


def get_extension(eid):
    e = store.extensions.get(eid)
    if e is None:
        raise not_found(ERR_EXTENSION_NOT_FOUND, "ExtensionRequest")
    return e


def study_of_unit(unit_id):
    for s in store.studies.values():
        if s["unit_id"] == unit_id:
            return s
    return None


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def round2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def risk_rank(score):
    """Band mapping, inclusive-low: <5 LOW, <12 MEDIUM, <20 HIGH, >=20 CRITICAL."""
    if score < Decimal("5"):
        return "LOW"
    if score < Decimal("12"):
        return "MEDIUM"
    if score < Decimal("20"):
        return "HIGH"
    return "CRITICAL"


def screening_score(sev, lik, change_class):
    """Provisional variant: sev * lik * class multiplier, 2dp half-up."""
    return round2(Decimal(sev) * Decimal(lik) * CLASS_MULT[change_class])


def definitive_score(sev, lik, det, change_class, unit_index):
    """Final variant: min(25, sev*lik) * class * detection ramp * posture branch."""
    base = min(25, sev * lik)
    detection_factor = Decimal("1") + (Decimal(det) - 1) * Decimal("0.25")
    posture_factor = Decimal("1.25") if unit_index >= 70 else Decimal("1.0")
    return round2(Decimal(base) * CLASS_MULT[change_class] * detection_factor * posture_factor)


def compute_study_dues(study, unit):
    """nominal = last_validated + cycle*30d; risk-accelerated compresses the cycle
    by closed HIGH/CATASTROPHIC incidents on/after last_validated_at (25% floor)."""
    cycle_days = unit["pha_cycle_months"] * DAYS_PER_MONTH
    n = sum(
        1
        for i in store.incidents.values()
        if i["unit_id"] == unit["id"]
        and i["status"] == "CLOSED"
        and i["severity_class"] in HIGH_SEVERITY
        and i["occurred_at"] >= study["last_validated_at"]
    )
    mult = max(Decimal("0.25"), Decimal("1") - Decimal("0.1") * n)
    accel_days = int((Decimal(cycle_days) * mult).to_integral_value(rounding=ROUND_FLOOR))
    study["nominal_next_due"] = study["last_validated_at"] + timedelta(days=cycle_days)
    study["risk_accelerated_due"] = study["last_validated_at"] + timedelta(days=accel_days)
    study["effective_next_due"] = min(study["nominal_next_due"], study["risk_accelerated_due"])


def moc_coverage(moc):
    """Pinned rounding: per-update round2 FIRST, then average and round2 again.
    DRAFT updates excluded. None when no PUBLISHED updates exist."""
    pubs = [
        p for p in store.procedures.values()
        if p["moc_id"] == moc["id"] and p["status"] == "PUBLISHED"
    ]
    if not pubs:
        return None
    vals = []
    for p in pubs:
        tas = [t for t in store.trainings.values() if t["procedure_update_id"] == p["id"]]
        comp = [t for t in tas if t["status"] == "COMPLETED"]
        vals.append(round2(Decimal("100") * Decimal(len(comp)) / Decimal(len(tas))))
    return round2(sum(vals) / Decimal(len(vals)))


# ---------------------------------------------------------------------------
# Unit aggregate + posture (two pinned phases, fresh snapshot every time)
# ---------------------------------------------------------------------------

def recompute_unit(unit):
    items = [a for a in store.action_items.values() if a["unit_id"] == unit["id"]]
    open_items = [a for a in items if a["status"] in OPEN_ACTION_STATUSES]
    unit["open_action_count"] = len(open_items)
    overdue = [a for a in open_items if a["due_date"] < store.clock]
    unit["overdue_action_count"] = len(overdue)

    study = study_of_unit(unit["id"])
    study_overdue = 1 if study and study["status"] == "OVERDUE" else 0
    study_forced = 1 if study and study["status"] == "REVALIDATION_REQUIRED" else 0
    open_high_inc = sum(
        1
        for i in store.incidents.values()
        if i["unit_id"] == unit["id"]
        and i["status"] != "CLOSED"
        and i["severity_class"] in HIGH_SEVERITY
    )
    audit_unit = {a_id: a["unit_id"] for a_id, a in store.audits.items()}
    open_major_nc = sum(
        1
        for f in store.findings.values()
        if f["severity"] == "MAJOR_NC"
        and f["status"] != "CLOSED"
        and audit_unit.get(f["audit_id"]) == unit["id"]
    )
    index = min(
        100,
        15 * len(overdue)
        + 25 * study_overdue
        + 20 * study_forced
        + 10 * open_high_inc
        + 5 * open_major_nc,
    )
    unit["process_safety_index"] = index
    unit["psm_posture"] = "NORMAL" if index < 40 else ("RESTRICTED" if index < 70 else "FROZEN")


def punch_open_count(pssr):
    return sum(
        1
        for a in store.action_items.values()
        if a["source_type"] == "PSSR"
        and a["source_id"] == pssr["id"]
        and a["status"] not in ("VERIFIED_CLOSED", "VOID")
    )


def open_finding_count(audit):
    return sum(
        1
        for f in store.findings.values()
        if f["audit_id"] == audit["id"] and f["status"] != "CLOSED"
    )


def evidence_count(item):
    return sum(1 for e in store.evidence.values() if e["action_item_id"] == item["id"])


# ---------------------------------------------------------------------------
# Action-item spawning and verification bubble-ups
# ---------------------------------------------------------------------------

def spawn_action_item(unit_id, source_type, source_id, title, priority, assignee_id,
                      due_in_days=None):
    days = due_in_days if due_in_days is not None else SLA_DAYS[priority]
    item = new_entity()
    item.update({
        "unit_id": unit_id,
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "priority": priority,
        "assignee_id": assignee_id,
        "due_date": store.clock + timedelta(days=days),
        "status": "OPEN",
        "completer_id": None,
        "verifier_id": None,
        "reopen_count": 0,
    })
    store.action_items[item["id"]] = item
    return item


def bubble_on_verify(item):
    """Source bubble-ups when an item becomes VERIFIED_CLOSED."""
    st, sid = item["source_type"], item["source_id"]
    if st == "PSSR":
        p = store.pssrs.get(sid)
        if p is not None:
            touch(p)  # punch_open_count derives from item states
    elif st == "AUDIT":
        f = store.findings.get(sid)
        if f is not None and f["status"] == "ACTION_ASSIGNED":
            f["status"] = "CLOSED"
            touch(f)
            a = store.audits.get(f["audit_id"])
            if a is not None:
                touch(a)  # open_finding_count derives from finding states
    elif st == "REVERT":
        m = store.mocs.get(sid)
        if m is not None and m["status"] == "EXPIRED_REVERT_REQUIRED":
            m["status"] = "CLOSED"
            m["closed_at"] = store.clock
            touch(m)


def bubble_on_reopen(item):
    """Reverse bubble-ups when a VERIFIED_CLOSED item is reopened."""
    st, sid = item["source_type"], item["source_id"]
    if st == "AUDIT":
        f = store.findings.get(sid)
        if f is not None and f["status"] == "CLOSED":
            f["status"] = "ACTION_ASSIGNED"
            touch(f)
            a = store.audits.get(f["audit_id"])
            if a is not None:
                touch(a)
    elif st == "PSSR":
        p = store.pssrs.get(sid)
        if p is not None:
            touch(p)


# ---------------------------------------------------------------------------
# Logical-clock sweep: PHA aging, temporary-MOC expiry, posture recompute
# ---------------------------------------------------------------------------

def sweep():
    for unit in store.units.values():
        study = study_of_unit(unit["id"])
        if study is not None and study["status"] in ("CURRENT", "DUE_SOON"):
            eff = study["effective_next_due"]
            if store.clock > eff:
                study["status"] = "OVERDUE"
                touch(study)
            elif eff - timedelta(days=60) <= store.clock <= eff:
                if study["status"] != "DUE_SOON":
                    study["status"] = "DUE_SOON"
                    touch(study)
        for moc in store.mocs.values():
            if (
                moc["unit_id"] == unit["id"]
                and moc["status"] == "IN_SERVICE"
                and moc["change_class"] == "TEMPORARY"
                and moc["temporary_end_date"] is not None
                and store.clock > moc["temporary_end_date"]
            ):
                moc["status"] = "EXPIRED_REVERT_REQUIRED"
                touch(moc)
                spawn_action_item(
                    unit["id"], "REVERT", moc["id"],
                    f"Revert temporary change: {moc['title']}",
                    "P1", moc["requester_id"], due_in_days=30,
                )
        recompute_unit(unit)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_unit(u):
    recompute_unit(u)
    d = _common(u)
    d.update({
        "name": u["name"],
        "unit_code": u["unit_code"],
        "pha_cycle_months": u["pha_cycle_months"],
        "temp_moc_max_days": u["temp_moc_max_days"],
        "max_extensions": u["max_extensions"],
        "extension_max_days": u["extension_max_days"],
        "total_temp_cap_days": u["total_temp_cap_days"],
        "training_coverage_threshold_pct": u["training_coverage_threshold_pct"],
        "open_action_count": u["open_action_count"],
        "overdue_action_count": u["overdue_action_count"],
        "process_safety_index": u["process_safety_index"],
        "psm_posture": u["psm_posture"],
    })
    return d


def ser_personnel(p):
    d = _common(p)
    d.update({
        "full_name": p["full_name"],
        "employee_ref": p["employee_ref"],
        "qualifications": p["qualifications"],
        "active": p["active"],
    })
    return d


def _f2(v):
    return float(v) if v is not None else None


def ser_moc(m):
    d = _common(m)
    d.update({
        "unit_id": m["unit_id"],
        "title": m["title"],
        "description": m["description"],
        "discipline": m["discipline"],
        "requester_id": m["requester_id"],
        "approver_id": m["approver_id"],
        "status": m["status"],
        "change_class": m["change_class"],
        "screening_severity": m["screening_severity"],
        "screening_likelihood": m["screening_likelihood"],
        "screening_risk_score": _f2(m["screening_risk_score"]),
        "definitive_risk_score": _f2(m["definitive_risk_score"]),
        "risk_rank": m["risk_rank"],
        "review_round": m["review_round"],
        "requires_pssr": m["requires_pssr"],
        "temporary_start_date": fmt_day(m["temporary_start_date"]),
        "temporary_duration_days": m["temporary_duration_days"],
        "temporary_end_date": fmt_day(m["temporary_end_date"]),
        "extension_count": m["extension_count"],
        "total_approved_extension_days": m["total_approved_extension_days"],
        "training_coverage_pct": _f2(moc_coverage(m)),
        "implemented_at": fmt_day(m["implemented_at"]),
        "closed_at": fmt_day(m["closed_at"]),
    })
    return d


def ser_review(r):
    d = _common(r)
    d.update({
        "moc_id": r["moc_id"],
        "round_number": r["round_number"],
        "reviewer_id": r["reviewer_id"],
        "status": r["status"],
        "design_basis_ok": r["design_basis_ok"],
        "codes_standards_ok": r["codes_standards_ok"],
        "relief_systems_ok": r["relief_systems_ok"],
        "materials_compat_ok": r["materials_compat_ok"],
        "severity_score": r["severity_score"],
        "likelihood_score": r["likelihood_score"],
        "detection_score": r["detection_score"],
        "verdict": r["verdict"],
        "notes": r["notes"],
    })
    return d


def ser_study(s):
    d = _common(s)
    d.update({
        "unit_id": s["unit_id"],
        "method": s["method"],
        "status": s["status"],
        "last_validated_at": fmt_day(s["last_validated_at"]),
        "nominal_next_due": fmt_day(s["nominal_next_due"]),
        "risk_accelerated_due": fmt_day(s["risk_accelerated_due"]),
        "effective_next_due": fmt_day(s["effective_next_due"]),
        "revalidation_count": s["revalidation_count"],
        "status_before_revalidation": s["status_before_revalidation"],
    })
    return d


def ser_revalidation(r):
    d = _common(r)
    d.update({
        "study_id": r["study_id"],
        "leader_id": r["leader_id"],
        "status": r["status"],
        "findings_summary": r["findings_summary"],
        "findings": r["findings"],
    })
    return d


def ser_pssr(p):
    d = _common(p)
    d.update({
        "moc_id": p["moc_id"],
        "lead_id": p["lead_id"],
        "status": p["status"],
        "field_window_start": fmt_day(p["field_window_start"]),
        "field_window_end": fmt_day(p["field_window_end"]),
        "punch_open_count": punch_open_count(p),
        "approved_at": fmt_day(p["approved_at"]),
    })
    return d


def ser_action_item(a):
    d = _common(a)
    d.update({
        "unit_id": a["unit_id"],
        "source_type": a["source_type"],
        "source_id": a["source_id"],
        "title": a["title"],
        "priority": a["priority"],
        "assignee_id": a["assignee_id"],
        "due_date": fmt_day(a["due_date"]),
        "status": a["status"],
        "completer_id": a["completer_id"],
        "verifier_id": a["verifier_id"],
        "evidence_count": evidence_count(a),
        "reopen_count": a["reopen_count"],
    })
    return d


def ser_evidence(e):
    return {
        "id": e["id"],
        "action_item_id": e["action_item_id"],
        "file_ref": e["file_ref"],
        "description": e["description"],
        "uploaded_by": e["uploaded_by"],
        "created_at": e["created_at"],
    }


def ser_incident(i):
    d = _common(i)
    d.update({
        "unit_id": i["unit_id"],
        "title": i["title"],
        "severity_class": i["severity_class"],
        "occurred_at": fmt_day(i["occurred_at"]),
        "investigator_id": i["investigator_id"],
        "status": i["status"],
        "feeds_pha": i["feeds_pha"],
    })
    return d


def ser_audit(a):
    d = _common(a)
    d.update({
        "unit_id": a["unit_id"],
        "title": a["title"],
        "lead_auditor_id": a["lead_auditor_id"],
        "field_window_start": fmt_day(a["field_window_start"]),
        "field_window_end": fmt_day(a["field_window_end"]),
        "status": a["status"],
        "open_finding_count": open_finding_count(a),
    })
    return d


def ser_finding(f):
    d = _common(f)
    d.update({
        "audit_id": f["audit_id"],
        "title": f["title"],
        "severity": f["severity"],
        "status": f["status"],
        "corrective_action_id": f["corrective_action_id"],
    })
    return d


def ser_procedure(p):
    d = _common(p)
    d.update({
        "moc_id": p["moc_id"],
        "document_ref": p["document_ref"],
        "status": p["status"],
        "published_at": fmt_day(p["published_at"]),
    })
    return d


def ser_training(t):
    d = _common(t)
    d.update({
        "procedure_update_id": t["procedure_update_id"],
        "personnel_id": t["personnel_id"],
        "status": t["status"],
        "completed_at": fmt_day(t["completed_at"]),
    })
    return d


def ser_extension(e):
    d = _common(e)
    d.update({
        "moc_id": e["moc_id"],
        "requested_days": e["requested_days"],
        "status": e["status"],
        "decided_by": e["decided_by"],
    })
    return d


# ---------------------------------------------------------------------------
# Shared validation helpers used across routes
# ---------------------------------------------------------------------------

def require_active_person(pid, what="Personnel"):
    """Body-referenced Personnel: existence 404 first, then active 403."""
    p = get_person(pid)  # 404 ERR_PERSONNEL_NOT_FOUND
    if not p["active"]:
        raise ApiError("ERR_QUALIFICATION_MISSING", f"{what} is not active", 403)
    return p


def validate_assignee(pid):
    return require_active_person(pid, "Assignee")


def sorted_rows(rows, key=None):
    if key is None:
        return sorted(rows, key=lambda e: e["_seq"])
    return sorted(rows, key=key)
