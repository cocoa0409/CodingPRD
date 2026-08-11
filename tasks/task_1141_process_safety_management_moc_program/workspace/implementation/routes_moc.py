"""MocRequest lifecycle and TechnicalReview endpoints."""
from flask import Blueprint, g

from db import store
from errors import (
    ApiError, ERR_MOC_INVALID_STATE, ERR_REVIEW_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER, ERR_QUALIFICATION_MISSING,
    ERR_SOD_REVIEWER_IS_REQUESTER, ERR_SOD_APPROVER_IS_REQUESTER,
    ERR_UNIT_POSTURE_FROZEN, ERR_UNIT_POSTURE_RESTRICTED,
    ERR_REVIEW_CHECKLIST_INCOMPLETE, ERR_PHA_NOT_CURRENT,
    ERR_TEMP_DURATION_EXCEEDS_MAX, ERR_PSSR_NOT_APPROVED,
    ERR_OPEN_P1_ACTION_ITEMS, ERR_PROCEDURES_NOT_PUBLISHED,
    ERR_TRAINING_COVERAGE_INSUFFICIENT, ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, f_bool, f_enum, f_list, f_day,
)
from services import (
    OPEN_ACTION_STATUSES, new_entity, touch, get_unit, get_person, get_moc,
    get_review, study_of_unit, recompute_unit, screening_score, definitive_score,
    risk_rank, moc_coverage, spawn_action_item, ser_moc, ser_review, sorted_rows,
    validate_assignee,
)

bp = Blueprint("moc", __name__)

DISCIPLINES = ["MECHANICAL", "CHEMICAL", "ELECTRICAL", "PROCESS"]
CHANGE_CLASSES = ["REPLACEMENT_IN_KIND", "TEMPORARY", "PERMANENT"]


def _new_review(moc):
    r = new_entity()
    r.update({
        "moc_id": moc["id"],
        "round_number": moc["review_round"],
        "reviewer_id": None,
        "status": "OPEN",
        "design_basis_ok": None,
        "codes_standards_ok": None,
        "relief_systems_ok": None,
        "materials_compat_ok": None,
        "severity_score": None,
        "likelihood_score": None,
        "detection_score": None,
        "verdict": None,
        "notes": None,
    })
    store.reviews[r["id"]] = r
    return r


# ---------------------------------------------------------------------------
# CRUD + lists
# ---------------------------------------------------------------------------

@bp.post("/psm/units/<unit_id>/moc-requests")
@require_roles("Requester")
def create_moc(unit_id):
    unit = get_unit(unit_id)
    # Posture gate (business safety) precedes body-constraint validation.
    if unit["psm_posture"] == "FROZEN":
        raise ApiError(ERR_UNIT_POSTURE_FROZEN, "Unit posture FROZEN blocks MOC creation", 403)
    b = body_json()
    title = f_str(b, "title")
    description = f_str(b, "description")
    discipline = f_enum(b, "discipline", DISCIPLINES)
    m = new_entity()
    m.update({
        "unit_id": unit["id"],
        "title": title,
        "description": description,
        "discipline": discipline,
        "requester_id": g.user_id,
        "approver_id": None,
        "status": "DRAFT",
        "change_class": None,
        "screening_severity": None,
        "screening_likelihood": None,
        "screening_risk_score": None,
        "definitive_risk_score": None,
        "risk_rank": None,
        "review_round": 0,
        "requires_pssr": None,
        "temporary_start_date": None,
        "temporary_duration_days": None,
        "temporary_end_date": None,
        "extension_count": 0,
        "total_approved_extension_days": 0,
        "implemented_at": None,
        "closed_at": None,
    })
    store.mocs[m["id"]] = m
    return ok(ser_moc(m), 201)


@bp.get("/psm/moc-requests/<mid>")
@require_roles(*ALL_ROLES)
def get_one_moc(mid):
    return ok(ser_moc(get_moc(mid)), 200)


@bp.get("/psm/units/<uid>/moc-requests")
@require_roles(*ALL_ROLES)
def list_unit_mocs(uid):
    unit = get_unit(uid)
    limit, offset = pagination_params()
    rows = [ser_moc(m) for m in sorted_rows(store.mocs.values()) if m["unit_id"] == unit["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/personnel/<pid>/moc-requests")
@require_roles(*ALL_ROLES)
def list_personnel_mocs(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [
        ser_moc(m) for m in sorted_rows(store.mocs.values())
        if m["requester_id"] == p["id"] or m["approver_id"] == p["id"]
    ]
    return ok_list(rows, limit, offset)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@bp.post("/psm/moc-requests/<mid>/classify")
@require_roles("PsmManager")
def classify_moc(mid):
    m = get_moc(mid)
    if m["status"] != "DRAFT":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only a DRAFT MOC can be classified", 409)
    b = body_json()
    change_class = f_enum(b, "change_class", CHANGE_CLASSES)
    sev = f_int(b, "screening_severity", lo=1, hi=5)
    lik = f_int(b, "screening_likelihood", lo=1, hi=5)
    override = f_bool(b, "requires_pssr_override", required=False)
    unit = store.units[m["unit_id"]]
    if change_class == "TEMPORARY":
        start = f_day(b, "temporary_start_date")
        duration = f_int(b, "temporary_duration_days")
        if duration < 1 or duration > unit["temp_moc_max_days"]:
            raise ApiError(
                ERR_TEMP_DURATION_EXCEEDS_MAX,
                f"temporary_duration_days must be 1..{unit['temp_moc_max_days']}",
                422,
            )
        m["temporary_start_date"] = start
        m["temporary_duration_days"] = duration
        from datetime import timedelta
        m["temporary_end_date"] = start + timedelta(days=duration)
    m["change_class"] = change_class
    m["screening_severity"] = sev
    m["screening_likelihood"] = lik
    score = screening_score(sev, lik, change_class)
    m["screening_risk_score"] = score
    m["risk_rank"] = risk_rank(score)
    m["requires_pssr"] = (change_class != "REPLACEMENT_IN_KIND") or (override is True)
    m["status"] = "CLASSIFIED"
    touch(m)
    return ok(ser_moc(m), 200)


# ---------------------------------------------------------------------------
# Submit / resubmit (class-driven branch)
# ---------------------------------------------------------------------------

def _submit_gates(m):
    if m["requester_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the requester may submit", 403)
    unit = store.units[m["unit_id"]]
    recompute_unit(unit)
    if unit["psm_posture"] == "FROZEN":
        raise ApiError(ERR_UNIT_POSTURE_FROZEN, "Unit posture FROZEN blocks submission", 403)
    if unit["psm_posture"] == "RESTRICTED":
        raise ApiError(ERR_UNIT_POSTURE_RESTRICTED, "Unit posture RESTRICTED blocks submission", 403)
    study = study_of_unit(unit["id"])
    if study is None or study["status"] not in ("CURRENT", "DUE_SOON"):
        raise ApiError(ERR_PHA_NOT_CURRENT, "Unit has no PHA study in CURRENT/DUE_SOON", 409)
    return unit


@bp.post("/psm/moc-requests/<mid>/submit")
@require_roles("Requester")
def submit_moc(mid):
    m = get_moc(mid)
    if m["status"] != "CLASSIFIED":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only a CLASSIFIED MOC can be submitted", 409)
    _submit_gates(m)
    if m["change_class"] == "REPLACEMENT_IN_KIND":
        m["status"] = "APPROVAL_PENDING"
    else:
        m["status"] = "TECHNICAL_REVIEW"
        m["review_round"] += 1
        _new_review(m)
    touch(m)
    return ok(ser_moc(m), 200)


@bp.post("/psm/moc-requests/<mid>/resubmit")
@require_roles("Requester")
def resubmit_moc(mid):
    m = get_moc(mid)
    if m["status"] != "RETURNED_FOR_REVISION":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only a RETURNED_FOR_REVISION MOC can be resubmitted", 409)
    if m["requester_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the requester may resubmit", 403)
    m["status"] = "TECHNICAL_REVIEW"
    m["review_round"] += 1
    _new_review(m)
    touch(m)
    return ok(ser_moc(m), 200)


# ---------------------------------------------------------------------------
# Approval / rejection / withdrawal
# ---------------------------------------------------------------------------

@bp.post("/psm/moc-requests/<mid>/approve")
@require_roles("OpsApprover")
def approve_moc(mid):
    m = get_moc(mid)
    if m["status"] != "APPROVAL_PENDING":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only an APPROVAL_PENDING MOC can be approved", 409)
    if g.user_id == m["requester_id"]:
        raise ApiError(ERR_SOD_APPROVER_IS_REQUESTER, "Approver must differ from requester", 403)
    b = body_json()
    conditions = b.get("conditions")
    if conditions is not None and not isinstance(conditions, list):
        raise ApiError("ERR_INVALID_REQUEST", "conditions must be an array", 400)
    # Validate every condition before spawning any (atomicity).
    parsed = []
    for c in (conditions or []):
        if not isinstance(c, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each condition must be an object", 400)
        title = f_str(c, "title")
        priority = f_enum(c, "priority", ["P1", "P2", "P3"])
        assignee_id = f_str(c, "assignee_id")
        due_in_days = f_int(c, "due_in_days", required=False, lo=1)
        validate_assignee(assignee_id)  # 404 unknown / 403 inactive
        parsed.append((title, priority, assignee_id, due_in_days))
    m["approver_id"] = g.user_id
    m["status"] = "APPROVED_IMPLEMENTATION"
    touch(m)
    for title, priority, assignee_id, due_in_days in parsed:
        spawn_action_item(m["unit_id"], "MOC_CONDITION", m["id"], title, priority,
                          assignee_id, due_in_days=due_in_days)
    recompute_unit(store.units[m["unit_id"]])
    return ok(ser_moc(m), 200)


@bp.post("/psm/moc-requests/<mid>/reject")
@require_roles("OpsApprover")
def reject_moc(mid):
    m = get_moc(mid)
    if m["status"] != "APPROVAL_PENDING":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only an APPROVAL_PENDING MOC can be rejected", 409)
    m["status"] = "REJECTED"
    touch(m)
    return ok(ser_moc(m), 200)


@bp.post("/psm/moc-requests/<mid>/withdraw")
@require_roles("Requester")
def withdraw_moc(mid):
    m = get_moc(mid)
    if m["status"] not in ("DRAFT", "CLASSIFIED"):
        raise ApiError(ERR_MOC_INVALID_STATE, "Only DRAFT or CLASSIFIED MOCs can be withdrawn", 409)
    if m["requester_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the requester may withdraw", 403)
    m["status"] = "WITHDRAWN"
    touch(m)
    return ok(ser_moc(m), 200)


# ---------------------------------------------------------------------------
# Implementation, PSSR gate, activation, closure
# ---------------------------------------------------------------------------

@bp.post("/psm/moc-requests/<mid>/mark-implemented")
@require_roles("Requester")
def mark_implemented(mid):
    m = get_moc(mid)
    if m["status"] != "APPROVED_IMPLEMENTATION":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only an APPROVED_IMPLEMENTATION MOC can be marked implemented", 409)
    if m["requester_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the requester may mark implemented", 403)
    published = [
        p for p in store.procedures.values()
        if p["moc_id"] == m["id"] and p["status"] == "PUBLISHED"
    ]
    if not published:
        raise ApiError(ERR_PROCEDURES_NOT_PUBLISHED, "At least one PUBLISHED ProcedureUpdate is required", 409)
    unit = store.units[m["unit_id"]]
    coverage = moc_coverage(m)
    if coverage is None or coverage < unit["training_coverage_threshold_pct"]:
        raise ApiError(ERR_TRAINING_COVERAGE_INSUFFICIENT, "Training coverage below unit threshold", 409)
    m["implemented_at"] = store.clock
    m["status"] = "IMPLEMENTED_PSSR_PENDING"
    touch(m)
    return ok(ser_moc(m), 200)


@bp.post("/psm/moc-requests/<mid>/authorize-startup")
@require_roles("PsmManager")
def authorize_startup(mid):
    m = get_moc(mid)
    if m["status"] != "IMPLEMENTED_PSSR_PENDING":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only an IMPLEMENTED_PSSR_PENDING MOC can be authorized", 409)
    unit = store.units[m["unit_id"]]
    recompute_unit(unit)
    if unit["psm_posture"] == "FROZEN":
        raise ApiError(ERR_UNIT_POSTURE_FROZEN, "Unit posture FROZEN blocks startup authorization", 403)
    if m["requires_pssr"]:
        approved = any(
            p["moc_id"] == m["id"] and p["status"] == "APPROVED"
            for p in store.pssrs.values()
        )
        if not approved:
            raise ApiError(ERR_PSSR_NOT_APPROVED, "An APPROVED PSSR is required", 409)
    pssr_ids = {p["id"] for p in store.pssrs.values() if p["moc_id"] == m["id"]}
    open_p1 = any(
        a["priority"] == "P1"
        and a["status"] in OPEN_ACTION_STATUSES
        and (
            (a["source_type"] == "MOC_CONDITION" and a["source_id"] == m["id"])
            or (a["source_type"] == "PSSR" and a["source_id"] in pssr_ids)
        )
        for a in store.action_items.values()
    )
    if open_p1:
        raise ApiError(ERR_OPEN_P1_ACTION_ITEMS, "Open P1 action items block startup authorization", 409)
    m["status"] = "STARTUP_AUTHORIZED"
    touch(m)
    return ok(ser_moc(m), 200)


@bp.post("/psm/moc-requests/<mid>/activate")
@require_roles("OpsApprover")
def activate_moc(mid):
    m = get_moc(mid)
    if m["status"] != "STARTUP_AUTHORIZED":
        raise ApiError(ERR_MOC_INVALID_STATE, "Only a STARTUP_AUTHORIZED MOC can be activated", 409)
    m["status"] = "IN_SERVICE"
    touch(m)
    return ok(ser_moc(m), 200)


@bp.post("/psm/moc-requests/<mid>/close")
@require_roles("PsmManager")
def close_moc(mid):
    m = get_moc(mid)
    if m["status"] != "IN_SERVICE" or m["change_class"] == "TEMPORARY":
        raise ApiError(
            ERR_MOC_INVALID_STATE,
            "Only an IN_SERVICE PERMANENT/REPLACEMENT_IN_KIND MOC can be closed",
            409,
        )
    open_conditions = any(
        a["source_type"] == "MOC_CONDITION"
        and a["source_id"] == m["id"]
        and a["status"] in OPEN_ACTION_STATUSES
        for a in store.action_items.values()
    )
    if open_conditions:
        raise ApiError(ERR_OPEN_ACTION_ITEMS_BLOCK_CLOSE, "Open MOC_CONDITION items block closure", 409)
    m["closed_at"] = store.clock
    m["status"] = "CLOSED"
    touch(m)
    return ok(ser_moc(m), 200)


# ---------------------------------------------------------------------------
# Technical reviews
# ---------------------------------------------------------------------------

@bp.get("/psm/moc-requests/<mid>/technical-reviews")
@require_roles(*ALL_ROLES)
def list_moc_reviews(mid):
    m = get_moc(mid)
    limit, offset = pagination_params()
    rounds = sorted(
        (r for r in store.reviews.values() if r["moc_id"] == m["id"]),
        key=lambda r: (r["round_number"], r["_seq"]),
    )
    return ok_list([ser_review(r) for r in rounds], limit, offset)


@bp.get("/psm/personnel/<pid>/technical-reviews")
@require_roles(*ALL_ROLES)
def list_personnel_reviews(pid):
    p = get_person(pid)
    limit, offset = pagination_params()
    rows = [
        ser_review(r) for r in sorted_rows(store.reviews.values())
        if r["reviewer_id"] == p["id"]
    ]
    return ok_list(rows, limit, offset)


@bp.post("/psm/technical-reviews/<rid>/submit-verdict")
@require_roles("TechnicalReviewer")
def submit_verdict(rid):
    r = get_review(rid)
    if r["status"] != "OPEN":
        raise ApiError(ERR_REVIEW_INVALID_STATE, "Review is not OPEN", 409)
    m = store.mocs[r["moc_id"]]
    if m["status"] != "TECHNICAL_REVIEW":
        raise ApiError(ERR_MOC_INVALID_STATE, "MOC is not in TECHNICAL_REVIEW", 409)
    reviewer = store.personnel.get(g.user_id)
    if reviewer is None or m["discipline"] not in reviewer["qualifications"]:
        raise ApiError(ERR_QUALIFICATION_MISSING, "Reviewer lacks the MOC discipline qualification", 403)
    if g.user_id == m["requester_id"]:
        raise ApiError(ERR_SOD_REVIEWER_IS_REQUESTER, "Reviewer must differ from requester", 403)
    b = body_json()
    verdict = f_enum(b, "verdict", ["ACCEPT", "RETURN"])
    d1 = f_bool(b, "design_basis_ok")
    d2 = f_bool(b, "codes_standards_ok")
    d3 = f_bool(b, "relief_systems_ok")
    d4 = f_bool(b, "materials_compat_ok")
    if verdict == "ACCEPT" and not (d1 and d2 and d3 and d4):
        raise ApiError(ERR_REVIEW_CHECKLIST_INCOMPLETE, "ACCEPT requires all four checklist booleans true", 422)
    sev = f_int(b, "severity_score", lo=1, hi=5)
    lik = f_int(b, "likelihood_score", lo=1, hi=5)
    det = f_int(b, "detection_score", lo=1, hi=5)
    notes = f_str(b, "notes", required=False)

    r["design_basis_ok"] = d1
    r["codes_standards_ok"] = d2
    r["relief_systems_ok"] = d3
    r["materials_compat_ok"] = d4
    r["severity_score"] = sev
    r["likelihood_score"] = lik
    r["detection_score"] = det
    r["verdict"] = verdict
    r["notes"] = notes
    r["reviewer_id"] = g.user_id
    r["status"] = "SUBMITTED"
    touch(r)

    unit = store.units[m["unit_id"]]
    recompute_unit(unit)
    score = definitive_score(sev, lik, det, m["change_class"], unit["process_safety_index"])
    m["definitive_risk_score"] = score
    m["risk_rank"] = risk_rank(score)
    m["status"] = "APPROVAL_PENDING" if verdict == "ACCEPT" else "RETURNED_FOR_REVISION"
    touch(m)
    return ok(ser_review(r), 200)
