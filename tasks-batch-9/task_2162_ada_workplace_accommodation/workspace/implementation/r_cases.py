"""Accommodation cases: intake, stage machine, decisions, renewal, disclosures."""
from datetime import timedelta

from flask import Blueprint, g, request as flask_request

import calc
import domain
from authz import (ALL_ROLES, endpoint, need_absence, need_employee, need_option,
                   need_request, require_case_owner, require_case_owner_id,
                   require_not_sealed)
from envelope import bool_arg, created, listing, ok, read_pagination, touch
from errors import ApiError
from store import by_created, parse_date, store
from validation import F, MEDICAL_FIELDS, bad, raw_body, validate

bp = Blueprint("cases", __name__)

STAGES_ALLOWING_WITHDRAWAL = (
    "INTAKE", "DOC_PENDING", "FUNCTION_ANALYSIS", "OPTION_EXPLORATION",
    "HARDSHIP_REVIEW", "DECISION_PENDING", "TRIAL_SETUP", "TRIAL_ACTIVE",
)
DENIAL_BASES = ("UNDUE_HARDSHIP", "DIRECT_THREAT", "NOT_QUALIFIED",
                "NO_DISABILITY_NEXUS", "INSUFFICIENT_DOCUMENTATION",
                "FAILURE_TO_COOPERATE")
DISCLOSURE_ROLES = ("Manager", "AccommodationCoordinator", "MedicalReviewOfficer",
                    "FinanceOfficer", "AppealOfficer", "ComplianceAuditor", "EXTERNAL")
DISCLOSURE_PURPOSES = ("FUNCTION_ANALYSIS", "HARDSHIP_ASSESSMENT", "APPEAL_REVIEW",
                       "AUDIT", "SAFETY_EMERGENCY", "OTHER")

INVALID_STAGE = "ERR_INVALID_STAGE_TRANSITION"


def new_case(employee, profile, data, renewal_of=None):
    row = store.new_row("AccommodationRequest", {
        "employee_id": employee["id"],
        "job_profile_id": profile["id"],
        "pinned_profile_version_label": profile["profile_version_label"],
        "request_channel": data["request_channel"],
        "requested_accommodation_text": data["requested_accommodation_text"],
        "disability_obvious": data["disability_obvious"],
        "absence_record_id": data["absence_record_id"],
        "renewal_of_request_id": renewal_of,
        "selected_option_id": None,
        "stage": "INTAKE",
        "confidentiality_posture": "STANDARD",
        "interactive_round_count": 0,
        "medical_doc_request_count": 0,
        "medical_doc_request_limit": calc.BASE_DOC_REQUEST_LIMIT,
        "documentation_budget_remaining": calc.BASE_DOC_REQUEST_LIMIT,
        "cleared_option_count": 0,
        "blocked_option_count": 0,
        "interactive_process_integrity_score": calc.INTEGRITY_BASE,
        "review_cadence_days": None,
        "review_due_date": None,
        "review_cycle_index": 0,
        "decision": "PENDING",
    })
    store.requests[row["id"]] = row
    calc.apply_documentation_budget(row)
    return row


CASE_SPEC = [
    F("employee_id", "id", required=True),
    F("request_channel", "enum", required=True,
      enum=("WRITTEN", "VERBAL", "MANAGER_OBSERVED", "HR_INITIATED")),
    F("requested_accommodation_text", "string", required=True, non_empty=True),
    F("disability_obvious", "boolean", default=False, has_default=True),
    F("absence_record_id", "id", default=None, has_default=True, nullable=True),
]


@bp.post("/accommodation-requests")
@endpoint(["Employee", "AccommodationCoordinator", "Manager"])
def create_case():
    data = validate(raw_body(), CASE_SPEC)
    employee = need_employee(data["employee_id"])
    if data["absence_record_id"] is not None:
        need_absence(data["absence_record_id"])
    require_case_owner_id(data["employee_id"])
    profile = store.job_profiles.get(employee["job_profile_id"])
    if profile is None or profile["status"] != "PUBLISHED":
        raise ApiError("ERR_PROFILE_NOT_PUBLISHED",
                       "The employee's job profile is not PUBLISHED.")
    if employee["open_case_count"] + 1 > calc.MAX_OPEN_CASES_PER_EMPLOYEE:
        raise ApiError("ERR_OPEN_CASE_LIMIT",
                       "The employee already holds the maximum number of open cases.")
    row = new_case(employee, profile, data)
    domain.recompute_open_case_count(employee)
    return created(row)


@bp.get("/accommodation-requests/<case_id>")
@endpoint(ALL_ROLES)
def get_case(case_id):
    return ok(need_request(case_id))


@bp.get("/accommodation-requests")
@endpoint(["AccommodationCoordinator", "ComplianceAuditor", "AppealOfficer",
           "FinanceOfficer", "MedicalReviewOfficer"])
def list_cases():
    limit, offset = read_pagination()
    rows = list(store.requests.values())
    for key in ("employee_id", "job_profile_id", "renewal_of_request_id",
                "absence_record_id", "selected_option_id", "stage"):
        value = flask_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return listing(by_created(rows), limit, offset)


@bp.patch("/accommodation-requests/<case_id>")
@endpoint(["AccommodationCoordinator"])
def patch_case(case_id):
    data = validate(raw_body(), [
        F("requested_accommodation_text", "string", non_empty=True),
        F("disability_obvious", "boolean"),
        F("absence_record_id", "id", nullable=True),
    ])
    req = need_request(case_id)
    if data.get("absence_record_id") is not None:
        need_absence(data["absence_record_id"])
    require_not_sealed(req)
    for key in ("requested_accommodation_text", "disability_obvious", "absence_record_id"):
        if key in data:
            req[key] = data[key]
    touch(req)
    return ok(req)


@bp.post("/accommodation-requests/<case_id>/confidentiality")
@endpoint(["ComplianceAuditor"])
def override_confidentiality(case_id):
    data = validate(raw_body(), [F("to_posture", "enum", required=True,
                                   enum=("RESTRICTED",))])
    req = need_request(case_id)
    if req["confidentiality_posture"] != "SEALED":
        raise ApiError(INVALID_STAGE, "The case is not SEALED.")
    req["confidentiality_posture"] = data["to_posture"]
    touch(req)
    return ok(req)


# =========================== Stage machine ===============================
@bp.post("/accommodation-requests/<case_id>/advance")
@endpoint(["AccommodationCoordinator", "Employee"])
def advance_case(case_id):
    data = validate(raw_body(), [F("target_stage", "enum", required=True,
                                   enum=("FUNCTION_ANALYSIS", "OPTION_EXPLORATION",
                                         "HARDSHIP_REVIEW", "DECISION_PENDING",
                                         "WITHDRAWN"))])
    req = need_request(case_id)
    require_case_owner(req)
    target = data["target_stage"]
    stage = req["stage"]

    if target == "WITHDRAWN":
        # The employee's own abandonment; the guard is the ownership comparison.
        if stage not in STAGES_ALLOWING_WITHDRAWAL or g.user_id != req["employee_id"]:
            raise ApiError(INVALID_STAGE, "Withdrawal is not available here.")
        require_not_sealed(req)
        domain.withdraw_case(req)
        return ok(req)

    if g.role != "AccommodationCoordinator":
        raise ApiError(INVALID_STAGE, "WITHDRAWN is the only stage an Employee may name.")

    if target == "FUNCTION_ANALYSIS":
        if stage == "INTAKE":
            if req["disability_obvious"] is not True:
                raise ApiError(INVALID_STAGE,
                               "Documentation may not be skipped on this case.")
        elif stage == "DOC_PENDING":
            sufficient = any(d["status"] == "ACCEPTED_SUFFICIENT"
                             for d in calc.doc_rounds_of(req["id"]))
            if not sufficient:
                raise ApiError(INVALID_STAGE,
                               "No documentation round has been accepted as sufficient.")
        else:
            raise ApiError(INVALID_STAGE, "That transition is not declared.")
        require_not_sealed(req)
        domain.assign(req, stage="FUNCTION_ANALYSIS")
        return ok(req)

    if target == "OPTION_EXPLORATION":
        if stage == "FUNCTION_ANALYSIS":
            require_not_sealed(req)
            _require_analysis_complete(req)
            domain.assign(req, stage="OPTION_EXPLORATION")
            return ok(req)
        if stage == "HARDSHIP_REVIEW":
            pending = [o for o in domain.options_of(req["id"]) if o["status"] == "PROPOSED"]
            if req["cleared_option_count"] != 0 or pending:
                raise ApiError(INVALID_STAGE, "That transition is not declared.")
            require_not_sealed(req)
            _require_interactive_round_room(req)
            domain.assign(req, stage="OPTION_EXPLORATION",
                          interactive_round_count=req["interactive_round_count"] + 1)
            return ok(req)
        raise ApiError(INVALID_STAGE, "That transition is not declared.")

    if target == "HARDSHIP_REVIEW":
        if stage != "OPTION_EXPLORATION":
            raise ApiError(INVALID_STAGE, "That transition is not declared.")
        require_not_sealed(req)
        live = [o for o in domain.options_of(req["id"])
                if o["status"] in ("PROPOSED", "CLEARED")]
        if not live:
            raise ApiError("ERR_NO_OPTIONS_PROPOSED", "No option has been proposed.")
        domain.assign(req, stage="HARDSHIP_REVIEW")
        return ok(req)

    # DECISION_PENDING
    if stage != "HARDSHIP_REVIEW":
        raise ApiError(INVALID_STAGE, "That transition is not declared.")
    require_not_sealed(req)
    pending = [o for o in domain.options_of(req["id"]) if o["status"] == "PROPOSED"]
    if pending or req["cleared_option_count"] < 1:
        raise ApiError("ERR_OPTION_ASSESSMENT_PENDING",
                       "An option is still awaiting assessment.")
    domain.assign(req, stage="DECISION_PENDING")
    return ok(req)


def _require_analysis_complete(req):
    duties = calc.pinned_denominator_functions(req["job_profile_id"])
    analyses = domain.analyses_of(req["id"])
    for duty in duties:
        recorded = [a for a in analyses
                    if a["essential_function_id"] == duty["id"] and a["status"] == "RECORDED"]
        if len(recorded) != 1:
            raise ApiError("ERR_FUNCTION_ANALYSIS_INCOMPLETE",
                           "Every active essential duty needs exactly one recorded analysis.")


def _require_interactive_round_room(req):
    if req["interactive_round_count"] + 1 > calc.MAX_INTERACTIVE_ROUNDS:
        raise ApiError("ERR_INTERACTIVE_ROUND_LIMIT",
                       "The interactive-round allowance is exhausted.")


# ============================= Decision ==================================
DECIDE_SPEC = [
    F("decision", "enum", required=True,
      enum=("GRANT_WITH_TRIAL", "GRANT_PERMANENT", "DENY")),
    F("selected_option_id", "id"),
    F("denial_basis", "enum", enum=DENIAL_BASES),
    F("rationale_text", "string"),
    F("alternative_option_id", "id", nullable=True),
]


@bp.post("/accommodation-requests/<case_id>/decide")
@endpoint(["AccommodationCoordinator"])
def decide_case(case_id):
    data = validate(raw_body(), DECIDE_SPEC)
    decision = data["decision"]
    if decision in ("GRANT_WITH_TRIAL", "GRANT_PERMANENT"):
        if data.get("selected_option_id") is None:
            bad("selected_option_id is required for a grant decision.")
    else:
        if data.get("denial_basis") is None:
            bad("denial_basis is required for a denial.")
        text = data.get("rationale_text")
        if not isinstance(text, str) or text.strip() == "":
            bad("rationale_text is required for a denial.")

    req = need_request(case_id)
    alternative = None
    if data.get("alternative_option_id") is not None:
        alternative = need_option(data["alternative_option_id"])
    selected = None
    if data.get("selected_option_id") is not None:
        selected = need_option(data["selected_option_id"])

    stage = req["stage"]
    if decision in ("GRANT_WITH_TRIAL", "GRANT_PERMANENT"):
        if stage != "DECISION_PENDING":
            raise ApiError(INVALID_STAGE, "That decision is not declared from this stage.")
        if selected["request_id"] != req["id"] or \
                selected["status"] not in ("CLEARED", "HARDSHIP_BLOCKED"):
            raise ApiError(INVALID_STAGE, "The selected option cannot be granted.")
        require_not_sealed(req)
        if calc.dec(selected["coverage_ratio"]) < calc.MIN_COVERAGE_RATIO:
            raise ApiError("ERR_ESSENTIAL_FUNCTION_UNCOVERED",
                           "The option leaves too much essential weight uncovered.")
        if selected["status"] == "HARDSHIP_BLOCKED":
            raise ApiError("ERR_OPTION_HARDSHIP_BLOCKED",
                           "The option was ruled an undue hardship.")
        _apply_grant(req, selected, decision)
        return ok(req)

    # DENY
    if stage == "DOC_PENDING":
        sufficient = any(d["status"] == "ACCEPTED_SUFFICIENT"
                         for d in calc.doc_rounds_of(req["id"]))
        if req["documentation_budget_remaining"] != 0 or sufficient or \
                data["denial_basis"] not in ("INSUFFICIENT_DOCUMENTATION",
                                             "FAILURE_TO_COOPERATE"):
            raise ApiError(INVALID_STAGE, "That denial is not declared from this stage.")
    elif stage == "DECISION_PENDING":
        if alternative is not None and (alternative["request_id"] != req["id"]
                                        or alternative["status"] != "CLEARED"):
            raise ApiError(INVALID_STAGE,
                           "alternative_option_id must name a CLEARED option on this case.")
    else:
        raise ApiError(INVALID_STAGE, "That decision is not declared from this stage.")
    require_not_sealed(req)
    _apply_denial(req, data, alternative)
    return ok(req)


def _apply_grant(req, selected, decision):
    target_status = "SELECTED" if decision == "GRANT_WITH_TRIAL" else "IMPLEMENTED"
    domain.assign(selected, status=target_status)
    domain.ledger_commit(selected, req)
    for option in by_created(domain.options_of(req["id"])):
        if option["id"] != selected["id"] and option["status"] == "CLEARED":
            domain.assign(option, status="SHELVED")
    domain.recompute_option_counts(req)
    domain.assign(req,
                  decision=decision,
                  selected_option_id=selected["id"],
                  stage="TRIAL_SETUP" if decision == "GRANT_WITH_TRIAL"
                  else "GRANTED_PERMANENT")
    cadence, due = calc.renewal_cadence(req)
    domain.assign(req, review_cadence_days=cadence, review_due_date=due)


def _apply_denial(req, data, alternative):
    issued_at = store.now()
    rejected = [o["id"] for o in by_created(domain.options_of(req["id"]))
                if o["status"] in ("CLEARED", "HARDSHIP_BLOCKED")]
    denial = store.new_row("DenialRecord", {
        "request_id": req["id"],
        "denial_basis": data["denial_basis"],
        "rationale_text": data["rationale_text"],
        "alternative_option_id": alternative["id"] if alternative else None,
        "rejected_option_ids": rejected,
        "issued_by_user_id": g.user_id,
        "issued_at": store.now_iso(),
        "appeal_deadline_date": (issued_at.date()
                                 + timedelta(days=calc.APPEAL_WINDOW_DAYS)).isoformat(),
        "appeal_count": 0,
        "status": "ISSUED",
    })
    store.denials[denial["id"]] = denial
    domain.assign(req, stage="DENIED", decision="DENY")
    employee = store.employees.get(req["employee_id"])
    if employee is not None:
        domain.recompute_denial_count(employee)


# ========================== Renewal review ===============================
@bp.post("/accommodation-requests/<case_id>/renewal-review")
@endpoint(["AccommodationCoordinator"])
def renewal_review(case_id):
    data = validate(raw_body(), [
        F("outcome", "enum", required=True,
          enum=("CONTINUE", "MODIFY", "CLOSE", "RENEW_SUCCESSOR")),
        F("expected_request_version", "integer", required=True),
    ])
    req = need_request(case_id)
    if req["stage"] != "RENEWAL_DUE":
        raise ApiError(INVALID_STAGE, "The case is not due for renewal review.")
    if data["expected_request_version"] != req["version"]:
        raise ApiError("ERR_STALE_VERSION")
    require_not_sealed(req)

    outcome = data["outcome"]
    employee = store.employees.get(req["employee_id"])
    if outcome == "MODIFY":
        _require_interactive_round_room(req)
    if outcome == "RENEW_SUCCESSOR":
        if employee["open_case_count"] + 1 > calc.MAX_OPEN_CASES_PER_EMPLOYEE:
            raise ApiError("ERR_OPEN_CASE_LIMIT",
                           "The employee already holds the maximum number of open cases.")

    req["review_cycle_index"] = req["review_cycle_index"] + 1
    touch(req)

    if outcome == "CONTINUE":
        due = store.today() + timedelta(days=req["review_cadence_days"])
        req["review_due_date"] = due.isoformat()
        req["stage"] = "GRANTED_PERMANENT"
    elif outcome == "MODIFY":
        req["stage"] = "OPTION_EXPLORATION"
        req["interactive_round_count"] = req["interactive_round_count"] + 1
    elif outcome == "CLOSE":
        req["stage"] = "CLOSED"
        option = store.options.get(req.get("selected_option_id") or "")
        if option is not None:
            domain.assign(option, status="IMPLEMENTED")
            domain.ledger_release(option, req)
        if employee is not None:
            domain.recompute_open_case_count(employee)
    else:
        _create_successor(req, employee)
        if employee is not None:
            domain.recompute_open_case_count(employee)
    return ok(req)


def _create_successor(req, employee):
    profile = store.job_profiles.get(employee["job_profile_id"]) if employee else None
    if profile is None or profile["status"] != "PUBLISHED":
        profile = store.job_profiles.get(req["job_profile_id"])
    successor = store.new_row("AccommodationRequest", {
        "employee_id": req["employee_id"],
        "job_profile_id": profile["id"] if profile else req["job_profile_id"],
        "pinned_profile_version_label": (profile["profile_version_label"] if profile
                                         else req["pinned_profile_version_label"]),
        "request_channel": req["request_channel"],
        "requested_accommodation_text": req["requested_accommodation_text"],
        "disability_obvious": req["disability_obvious"],
        "absence_record_id": req["absence_record_id"],
        "renewal_of_request_id": req["id"],
        "selected_option_id": None,
        "stage": "INTAKE",
        "confidentiality_posture": "STANDARD",
        "interactive_round_count": 0,
        "medical_doc_request_count": 0,
        "medical_doc_request_limit": calc.BASE_DOC_REQUEST_LIMIT + calc.RENEWAL_BONUS,
        "documentation_budget_remaining": calc.BASE_DOC_REQUEST_LIMIT + calc.RENEWAL_BONUS,
        "cleared_option_count": 0,
        "blocked_option_count": 0,
        "interactive_process_integrity_score": calc.INTEGRITY_BASE,
        "review_cadence_days": None,
        "review_due_date": None,
        "review_cycle_index": 0,
        "decision": "PENDING",
    })
    store.requests[successor["id"]] = successor
    calc.apply_documentation_budget(successor)
    return successor


# ========================= Disclosure log ================================
DISCLOSURE_SPEC = [
    F("disclosed_to_role", "enum", required=True, enum=DISCLOSURE_ROLES),
    F("disclosed_to_user_id", "string", required=True, non_empty=True),
    F("disclosure_purpose", "enum", required=True, enum=DISCLOSURE_PURPOSES),
    F("fields_disclosed", "enum_array", required=True, non_empty=True,
      enum=tuple(MEDICAL_FIELDS)),
]


@bp.post("/accommodation-requests/<case_id>/medical-disclosures")
@endpoint(["AccommodationCoordinator", "MedicalReviewOfficer", "ComplianceAuditor"])
def append_disclosure(case_id):
    data = validate(raw_body(), DISCLOSURE_SPEC)
    req = need_request(case_id)
    authorized = calc.disclosure_authorized(data["disclosed_to_role"],
                                            data["fields_disclosed"])
    row = store.new_row("MedicalDisclosure", {
        "request_id": req["id"],
        "disclosed_to_role": data["disclosed_to_role"],
        "disclosed_to_user_id": data["disclosed_to_user_id"],
        "disclosure_purpose": data["disclosure_purpose"],
        "fields_disclosed": data["fields_disclosed"],
        "authorized": authorized,
        "logged_by_user_id": g.user_id,
    })
    store.disclosures[row["id"]] = row
    if not authorized:
        domain.seal_case(req)
    return created(row)


@bp.get("/accommodation-requests/<case_id>/medical-disclosures")
@endpoint(["AccommodationCoordinator", "MedicalReviewOfficer", "ComplianceAuditor"])
def list_disclosures(case_id):
    limit, offset = read_pagination()
    need_request(case_id)
    rows = [d for d in store.disclosures.values() if d["request_id"] == case_id]
    authorized = bool_arg("authorized")
    if authorized is not None:
        rows = [d for d in rows if d["authorized"] is authorized]
    return listing(by_created(rows), limit, offset)
