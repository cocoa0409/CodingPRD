"""Audit endpoints: get, assign, reschedule, cancel, start, nonconformities,
submit-report, decision, certificate."""

from flask import Blueprint, request

import db
from db import days, get_now, touch
from errors import (
    ApiError,
    ERR_AUDIT_NOT_FOUND,
    ERR_INVALID_AUDIT_STATE,
    ERR_INVALID_APPLICATION_STATE,
    ERR_OUTSIDE_AUDIT_WINDOW,
    ERR_AUDIT_UNASSIGNED,
    ERR_REFERENCE_NOT_FOUND,
    ERR_AUDITOR_CONFLICT_OF_INTEREST,
    ERR_AUDITOR_COMPETENCY_GAP,
    ERR_AUDITOR_NOT_CALIBRATED,
    ERR_AUDITOR_ROTATION_LIMIT,
    ERR_DECISION_NOT_INDEPENDENT,
    ERR_OPEN_NCS_REMAIN,
    ERR_SCORE_BELOW_PASS,
)
from middleware import (
    get_auth,
    require_role,
    forbid_ownership,
    invalid_request,
    body_preflight,
    get_body,
    req_string,
    req_enum,
)
from response import success_object, success_list, parse_pagination, paginate
from services.core import (
    application_of,
    scheme_of_audit,
    compute_calibration,
    compute_reported_score,
    compute_resolved_score,
    compute_audit_fee,
    validate_window,
    check_auditor_window_overlap,
    check_min_gap,
    create_next_audit,
    issue_certificate,
    withdraw_certificate,
    find_certificate_for_client_scheme,
    ncs_of_audit,
)

bp = Blueprint("audits", __name__)


def _get_audit_or_404(audit_id):
    audit = db.audits.get(audit_id)
    if not audit:
        raise ApiError(ERR_AUDIT_NOT_FOUND, "Audit path id does not exist", 404)
    return audit


def _check_audit_read_ownership(user_id, role, audit):
    application = application_of(audit)
    if role == "ClientAdmin" and application and application["client_id"] != user_id:
        forbid_ownership("ClientAdmin may read only its own audits")
    if role == "Auditor":
        # A null assignee does NOT fail the ownership check.
        if audit.get("auditor_id") is not None and audit["auditor_id"] != user_id:
            forbid_ownership("Auditor may read only its own audits")


@bp.get("/audits/<audit_id>")
def get_audit(audit_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    audit = _get_audit_or_404(audit_id)
    _check_audit_read_ownership(user_id, role, audit)
    return success_object(db.serialize(audit, "audits"))


@bp.post("/audits/<audit_id>/assign")
def assign_audit(audit_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body_preflight()
    audit = _get_audit_or_404(audit_id)
    # State check precedes body-reference resolution (priority 5 before 6).
    if audit["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Audit status does not permit assignment",
            409,
        )
    body = get_body()
    auditor_id = req_string(body, "auditor_id")
    auditor = db.auditors.get(auditor_id)
    if not auditor:
        raise ApiError(
            ERR_REFERENCE_NOT_FOUND,
            "Body foreign-key reference does not exist: auditor_id",
            422,
        )

    application = application_of(audit)
    scheme = scheme_of_audit(audit)

    # Priority 7 — independence and conflicts.
    if application["client_id"] in auditor.get("conflicted_client_ids", []):
        raise ApiError(
            ERR_AUDITOR_CONFLICT_OF_INTEREST,
            "Auditor has declared a conflict with the client",
            422,
        )

    # Priority 8 — temporal: no window intersection with the auditor's other
    # SCHEDULED/IN_PROGRESS audits.
    check_auditor_window_overlap(
        auditor_id, audit["window_start"], audit["window_end"], audit["id"]
    )

    # Priority 9 — competency, calibration, rotation.
    competency = set(auditor.get("competency_categories", []))
    for cat in application["product_categories"]:
        if cat.get("category_code") not in competency:
            raise ApiError(
                ERR_AUDITOR_COMPETENCY_GAP,
                "Auditor competency does not cover category %s"
                % cat.get("category_code"),
                422,
            )
    calibration, _ = compute_calibration(auditor_id)
    if calibration != "CURRENT":
        raise ApiError(
            ERR_AUDITOR_NOT_CALIBRATED,
            "Auditor has no PASS witness audit within the scheme's witness_validity_days",
            422,
        )
    # Rotation: barred after performing rotation_limit most-recent consecutive
    # audits for the same client+scheme. Only performed (DECIDED) audits count.
    decided_chain = [
        a
        for a in db.audits.values()
        if a["id"] != audit["id"]
        and a["status"] == "DECIDED"
        and a.get("auditor_id") is not None
    ]
    decided_chain = [
        a
        for a in decided_chain
        if (application_of(a) or {}).get("client_id") == application["client_id"]
        and (application_of(a) or {}).get("scheme_id") == application["scheme_id"]
    ]
    decided_chain.sort(key=lambda a: a["sequence_number"], reverse=True)
    recent = decided_chain[: scheme["rotation_limit"]]
    if (
        len(recent) == scheme["rotation_limit"]
        and all(a["auditor_id"] == auditor_id for a in recent)
    ):
        raise ApiError(
            ERR_AUDITOR_ROTATION_LIMIT,
            "Auditor performed the rotation_limit most recent consecutive audits for this client+scheme",
            422,
        )

    audit["auditor_id"] = auditor_id
    touch(audit)
    auditor["active_audit_count"] = int(auditor.get("active_audit_count", 0)) + 1
    return success_object(db.serialize(audit, "audits"))


@bp.post("/audits/<audit_id>/reschedule")
def reschedule_audit(audit_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    body_preflight()
    audit = _get_audit_or_404(audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Only a SCHEDULED audit may be rescheduled",
            409,
        )
    body = get_body()
    window_start = db.parse_iso(req_string(body, "window_start"))
    window_end = db.parse_iso(req_string(body, "window_end"))
    scheme = scheme_of_audit(audit)
    application = application_of(audit)

    # Priority 8 — temporal rules.
    validate_window(
        audit["audit_type"], scheme, window_start, window_end, check_past=True
    )
    if audit.get("auditor_id") is not None:
        check_auditor_window_overlap(
            audit["auditor_id"], window_start, window_end, audit["id"]
        )
    check_min_gap(application, window_start, window_end, audit["id"])

    audit["window_start"] = window_start
    audit["window_end"] = window_end
    touch(audit)
    return success_object(db.serialize(audit, "audits"))


@bp.post("/audits/<audit_id>/cancel")
def cancel_audit(audit_id):
    _, role = get_auth()
    require_role(role, ("SchemeAdmin",))
    audit = _get_audit_or_404(audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Only a SCHEDULED audit may be cancelled",
            409,
        )
    if audit.get("auditor_id") is not None:
        auditor = db.auditors.get(audit["auditor_id"])
        if auditor:
            auditor["active_audit_count"] = max(
                0, int(auditor.get("active_audit_count", 0)) - 1
            )
    audit["status"] = "CANCELLED"
    touch(audit)
    return success_object(db.serialize(audit, "audits"))


@bp.post("/audits/<audit_id>/start")
def start_audit(audit_id):
    user_id, role = get_auth()
    require_role(role, ("Auditor",))
    audit = _get_audit_or_404(audit_id)
    # Ownership first: a non-null assignee different from the caller fails.
    # A null assignee does NOT fail ownership — caught later by
    # ERR_AUDIT_UNASSIGNED at priority 9.
    if audit.get("auditor_id") is not None and audit["auditor_id"] != user_id:
        forbid_ownership("Caller is not the assigned auditor")
    if audit["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Audit status does not permit start",
            409,
        )
    application = application_of(audit)
    if not application or application["status"] != "ACCEPTED":
        raise ApiError(
            ERR_INVALID_APPLICATION_STATE,
            "The parent application is not ACCEPTED",
            409,
        )
    now = get_now()
    if not (audit["window_start"] <= now <= audit["window_end"]):
        raise ApiError(
            ERR_OUTSIDE_AUDIT_WINDOW,
            "Current logical time is not within the audit window",
            422,
        )
    if audit.get("auditor_id") is None:
        raise ApiError(
            ERR_AUDIT_UNASSIGNED,
            "Start attempted on an audit with no assigned auditor",
            422,
        )
    audit["status"] = "IN_PROGRESS"
    audit["started_at"] = now
    touch(audit)
    return success_object(db.serialize(audit, "audits"))


@bp.post("/audits/<audit_id>/nonconformities")
def create_nonconformity(audit_id):
    user_id, role = get_auth()
    require_role(role, ("Auditor",))
    body_preflight()
    audit = _get_audit_or_404(audit_id)
    if audit.get("auditor_id") is not None and audit["auditor_id"] != user_id:
        forbid_ownership("Caller is not the assigned auditor")
    if audit["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Findings may be recorded only while the audit is IN_PROGRESS",
            409,
        )
    body = get_body()
    grade = req_enum(body, "grade", ("CRITICAL", "MAJOR", "MINOR"))
    clause_ref = req_string(body, "clause_ref")
    description = req_string(body, "description")

    scheme = scheme_of_audit(audit)
    grade_days = {
        "CRITICAL": scheme["critical_nc_days"],
        "MAJOR": scheme["major_nc_days"],
        "MINOR": scheme["minor_nc_days"],
    }[grade]
    now = get_now()
    nc = {
        "id": db.new_id(),
        "audit_id": audit["id"],
        "grade": grade,
        "clause_ref": clause_ref,
        "description": description,
        "status": "OPEN",
        "deadline": now + days(grade_days),
        "cap_text": None,
        "submitted_at": None,
        "rejection_count": 0,
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.nonconformities[nc["id"]] = nc
    return success_object(db.serialize(nc, "nonconformities"), status=201)


@bp.get("/audits/<audit_id>/nonconformities")
def list_audit_nonconformities(audit_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    audit = _get_audit_or_404(audit_id)
    _check_audit_read_ownership(user_id, role, audit)
    limit, offset = parse_pagination()
    items = ncs_of_audit(audit_id)
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [n for n in items if n["status"] == status_filter]
    # created_at ASC (PRD §3.5); stable sort keeps creation order on ties.
    items.sort(key=lambda n: n["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(n, "nonconformities") for n in page], total, limit, offset
    )


@bp.post("/audits/<audit_id>/submit-report")
def submit_report(audit_id):
    user_id, role = get_auth()
    require_role(role, ("Auditor",))
    body_preflight()
    audit = _get_audit_or_404(audit_id)
    if audit.get("auditor_id") is not None and audit["auditor_id"] != user_id:
        forbid_ownership("Caller is not the assigned auditor")
    if audit["status"] != "IN_PROGRESS":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Audit status does not permit report submission",
            409,
        )
    body = get_body()
    if "actual_days" not in body or body["actual_days"] is None:
        invalid_request("Missing required field: actual_days")
    actual_days = body["actual_days"]
    if (
        isinstance(actual_days, bool)
        or not isinstance(actual_days, int)
        or actual_days < 1
    ):
        invalid_request("actual_days must be an integer >= 1")

    scheme = scheme_of_audit(audit)
    audit["actual_days"] = actual_days
    audit["reported_score"] = compute_reported_score(audit["id"])
    audit["audit_fee"] = compute_audit_fee(scheme, actual_days, audit["audit_type"])
    audit["status"] = "REPORT_SUBMITTED"
    audit["reported_at"] = get_now()
    touch(audit)
    return success_object(db.serialize(audit, "audits"))


@bp.post("/audits/<audit_id>/decision")
def decide_audit(audit_id):
    user_id, role = get_auth()
    require_role(role, ("DecisionMaker",))
    body_preflight()
    audit = _get_audit_or_404(audit_id)
    if audit["status"] != "REPORT_SUBMITTED":
        raise ApiError(
            ERR_INVALID_AUDIT_STATE,
            "Audit status does not permit a certification decision",
            409,
        )
    body = get_body()
    outcome = req_enum(body, "outcome", ("GRANT", "DENY"))

    dm = db.decision_makers.get(user_id)
    application = application_of(audit)
    scheme = scheme_of_audit(audit)

    # Priority 7 — segregation of duties: the decision maker must not be the
    # auditor of record.
    if dm and dm.get("linked_auditor_id") is not None and audit.get("auditor_id") is not None:
        if dm["linked_auditor_id"] == audit["auditor_id"]:
            raise ApiError(
                ERR_DECISION_NOT_INDEPENDENT,
                "Acting decision maker is linked to the auditor of the audit being decided",
                403,
            )

    resolved = compute_resolved_score(audit["id"])

    # Priority 9 — GRANT gates.
    if outcome == "GRANT":
        open_ncs = [n for n in ncs_of_audit(audit["id"]) if n["status"] != "CLOSED"]
        if open_ncs:
            raise ApiError(
                ERR_OPEN_NCS_REMAIN,
                "GRANT requires every nonconformity of the audit to be CLOSED",
                422,
            )
        if resolved < scheme["pass_score"]:
            raise ApiError(
                ERR_SCORE_BELOW_PASS,
                "Resolved score %d is below the scheme pass_score %d"
                % (resolved, scheme["pass_score"]),
                422,
            )

    now = get_now()
    audit["resolved_score"] = resolved
    audit["decision_outcome"] = outcome
    audit["decision_maker_id"] = user_id
    audit["decided_at"] = now
    audit["status"] = "DECIDED"
    touch(audit)

    # The assigned auditor's active_audit_count drops by one.
    if audit.get("auditor_id") is not None:
        auditor = db.auditors.get(audit["auditor_id"])
        if auditor:
            auditor["active_audit_count"] = max(
                0, int(auditor.get("active_audit_count", 0)) - 1
            )

    if outcome == "GRANT":
        if audit["audit_type"] == "INITIAL":
            issue_certificate(scheme, application, audit, now)
        create_next_audit(scheme, audit)
    else:  # DENY
        if audit["audit_type"] == "INITIAL":
            # No certificate and no successor audit.
            pass
        else:
            # Withdraw the existing ACTIVE certificate and unlist its listing.
            active = find_certificate_for_client_scheme(
                application["client_id"],
                application["scheme_id"],
                statuses={"ACTIVE"},
            )
            if active:
                withdraw_certificate(active[0], now)

    return success_object(db.serialize(audit, "audits"))


@bp.get("/audits/<audit_id>/certificate")
def get_audit_certificate(audit_id):
    user_id, role = get_auth()
    require_role(role, ("SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker"))
    audit = _get_audit_or_404(audit_id)
    _check_audit_read_ownership(user_id, role, audit)
    limit, offset = parse_pagination()
    items = [c for c in db.certificates.values() if c["audit_id"] == audit_id]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list(
        [db.serialize(c, "certificates") for c in page], total, limit, offset
    )
