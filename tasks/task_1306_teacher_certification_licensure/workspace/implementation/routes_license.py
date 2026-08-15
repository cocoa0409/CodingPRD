"""Routes: licenses, endorsements, CE credits, CE audits, misconduct cases,
disciplinary actions."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import services as svc
import util
from db import db
from middleware import require_roles, check_applicant_ownership
from response import success_object, success_list

bp = Blueprint("license", __name__)

ALL_READ = ("Applicant", "IntakeOfficer", "CredentialEvaluator", "BackgroundInvestigator",
            "LegalOfficer", "ProgramApprovalOfficer", "AgencyAdmin")

SUBJECT_AREAS = svc.SUBJECT_AREAS
GRADE_BANDS = svc.GRADE_BANDS


def _get_license_or_404(license_id):
    lic = db.licenses.get(license_id)
    if lic is None:
        raise errors.err_not_found("License not found")
    return lic


def _has_open_case(license_id):
    return any(c["status"] in svc.CASE_OPEN for c in svc.misconduct_cases_of(license_id))


# ---------------------------------------------------------------------------
# Licenses
# ---------------------------------------------------------------------------

def license_view(l):
    return dict(l)


@bp.route("/licensure/licenses/<licenseId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_license(actor, licenseId):
    lic = _get_license_or_404(licenseId)
    check_applicant_ownership(actor, "license", lic)
    return success_object(license_view(lic))


@bp.route("/licensure/licenses", methods=["GET"])
@require_roles(*ALL_READ)
def list_licenses(actor):
    applicant_id = request.args.get("applicant_id")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(db.licenses.values())
    if actor.role == "Applicant":
        items = [l for l in items if l["applicant_id"] == actor.user_id]
    if applicant_id is not None:
        items = [l for l in items if l["applicant_id"] == applicant_id]
    if application_id is not None:
        items = [l for l in items if l["application_id"] == application_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = util.sorted_by_created(items)
    page, limit, offset, total = util.paginate(items)
    return success_list([license_view(l) for l in page], limit, offset, total)


@bp.route("/licensure/licenses/<licenseId>/renew", methods=["POST"])
@require_roles("Applicant")
def renew_license(actor, licenseId):
    lic = _get_license_or_404(licenseId)
    check_applicant_ownership(actor, "license", lic)
    body = util.get_body()
    util.require_fields(body, ["payment_token"])
    if lic["status"] != "ACTIVE":
        raise errors.err_invalid_state("License is not ACTIVE")
    # safety: open misconduct case
    if _has_open_case(licenseId):
        raise errors.err_open_misconduct_case()
    # temporal: renewal window [expires_on - 180d, expires_on)
    now = db.now()
    expires = util.parse_iso(lic["expires_on"])
    window_open = expires - timedelta(days=180)
    if not (window_open <= now < expires):
        raise errors.err_renewal_window_closed()
    # audit gate: PASSED STANDARD audit for the current cycle
    if not any(a["audit_variant"] == "STANDARD" and a["status"] == "PASSED"
               and a.get("cycle_start") == lic["issued_on"]
               for a in svc.ce_audits_of(licenseId)):
        raise errors.err_audit_not_passed()
    lic["expires_on"] = util.to_iso(util.add_months(util.parse_iso(lic["expires_on"]), 60))
    util.touch(lic)
    return success_object(license_view(lic))


@bp.route("/licensure/licenses/<licenseId>/reinstate", methods=["POST"])
@require_roles("Applicant")
def reinstate_license(actor, licenseId):
    lic = _get_license_or_404(licenseId)
    check_applicant_ownership(actor, "license", lic)
    body = util.get_body()
    util.require_fields(body, ["pays_amount_cents"])
    pays = util.require_int(body["pays_amount_cents"], "pays_amount_cents", 0)
    if lic["status"] != "EXPIRED":
        raise errors.err_invalid_state("License is not EXPIRED")
    now = db.now()
    expires = util.parse_iso(lic["expires_on"])
    if now > expires + timedelta(days=730):
        raise errors.err_reinstate_grace_expired()
    # audit gate: PASSED RESTORATION audit
    if not any(a["audit_variant"] == "RESTORATION" and a["status"] == "PASSED"
               for a in svc.ce_audits_of(licenseId)):
        raise errors.err_audit_not_passed()
    # fiscal: exact amount
    due = svc.compute_reinstatement_fee(lic)
    if pays != due:
        raise errors.err_fee_amount_mismatch()
    lic["status"] = "ACTIVE"
    lic["expires_on"] = util.to_iso(util.add_months(now, 60))
    util.touch(lic)
    return success_object(license_view(lic))


@bp.route("/licensure/licenses/<licenseId>/surrender", methods=["POST"])
@require_roles("Applicant")
def surrender_license(actor, licenseId):
    lic = _get_license_or_404(licenseId)
    check_applicant_ownership(actor, "license", lic)
    if lic["status"] != "ACTIVE":
        raise errors.err_invalid_state("License is not ACTIVE")
    if _has_open_case(licenseId):
        raise errors.err_open_misconduct_case()
    lic["status"] = "SURRENDERED"
    for e in svc.endorsements_of(licenseId):
        if e["status"] in ("PENDING_EVALUATION", "ACTIVE"):
            e["status"] = "REMOVED"
            util.touch(e)
    util.touch(lic)
    return success_object(license_view(lic))


# ---------------------------------------------------------------------------
# Endorsements
# ---------------------------------------------------------------------------

def endorsement_view(e):
    return dict(e)


@bp.route("/licensure/licenses/<id>/endorsements", methods=["POST"])
@require_roles("Applicant")
def create_endorsement(actor, id):
    lic = _get_license_or_404(id)
    check_applicant_ownership(actor, "license", lic)
    body = util.get_body()
    util.require_fields(body, ["subject_area", "grade_band"])
    subject_area = util.require_enum(body["subject_area"], SUBJECT_AREAS, "subject_area")
    grade_band = util.require_enum(body["grade_band"], GRADE_BANDS, "grade_band")
    if lic["status"] != "ACTIVE":
        raise errors.err_invalid_state("License is not ACTIVE")
    # duplicate: base subject or PENDING_EVALUATION/ACTIVE endorsement
    if subject_area == lic["subject_area"]:
        raise errors.err_endorsement_duplicate()
    for e in svc.endorsements_of(id):
        if e["subject_area"] == subject_area and e["status"] in ("PENDING_EVALUATION", "ACTIVE"):
            raise errors.err_endorsement_duplicate()
    endorsement = util.stamp_new({
        "id": util.new_id(),
        "license_id": id,
        "subject_area": subject_area,
        "grade_band": grade_band,
        "status": "PENDING_EVALUATION",
    })
    db.endorsements[endorsement["id"]] = endorsement
    return success_object(endorsement_view(endorsement), 201)


@bp.route("/licensure/licenses/<id>/endorsements", methods=["GET"])
@require_roles(*ALL_READ)
def list_endorsements(actor, id):
    lic = _get_license_or_404(id)
    check_applicant_ownership(actor, "license", lic)
    items = util.sorted_by_created(svc.endorsements_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([endorsement_view(e) for e in page], limit, offset, total)


@bp.route("/licensure/endorsements/<endorsementId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_endorsement(actor, endorsementId):
    e = db.endorsements.get(endorsementId)
    if e is None:
        raise errors.err_not_found("Endorsement not found")
    check_applicant_ownership(actor, "endorsement", e)
    return success_object(endorsement_view(e))


ENDORSEMENT_TRANSITIONS = {
    "PENDING_EVALUATION": {"ACTIVE", "DENIED"},
    "ACTIVE": {"REMOVED"},
    "DENIED": set(),
    "REMOVED": set(),
    "REVOKED": set(),
}

ENDORSEMENT_ROLE_TARGETS = {
    "CredentialEvaluator": {"ACTIVE", "DENIED"},
    "Applicant": {"REMOVED"},
}


@bp.route("/licensure/endorsements/<endorsementId>/state", methods=["POST"])
@require_roles("CredentialEvaluator", "Applicant")
def endorsement_state(actor, endorsementId):
    e = db.endorsements.get(endorsementId)
    if e is None:
        raise errors.err_not_found("Endorsement not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, set(ENDORSEMENT_TRANSITIONS.keys()), "to_status")
    if to_status not in ENDORSEMENT_ROLE_TARGETS.get(actor.role, set()):
        raise errors.err_forbidden()
    if actor.role == "Applicant":
        check_applicant_ownership(actor, "endorsement", e)
    if to_status not in ENDORSEMENT_TRANSITIONS[e["status"]]:
        raise errors.err_invalid_state()
    if to_status == "ACTIVE":
        lic = db.licenses.get(e["license_id"])
        if lic is None or lic["status"] != "ACTIVE":
            raise errors.err_invalid_state("License is not ACTIVE")
    e["status"] = to_status
    util.touch(e)
    return success_object(endorsement_view(e))


# ---------------------------------------------------------------------------
# CE credits
# ---------------------------------------------------------------------------

def ce_credit_view(c):
    return dict(c)


CE_CATEGORIES = {"PEDAGOGY", "CONTENT", "ETHICS", "TECHNOLOGY"}


@bp.route("/licensure/licenses/<id>/ce-credits", methods=["POST"])
@require_roles("Applicant")
def create_ce_credit(actor, id):
    lic = _get_license_or_404(id)
    check_applicant_ownership(actor, "license", lic)
    body = util.get_body()
    util.require_fields(body, ["provider_name", "category", "hours", "earned_on"])
    provider = util.require_string(body["provider_name"], "provider_name")
    category = util.require_enum(body["category"], CE_CATEGORIES, "category")
    hours = util.require_number(body["hours"], "hours", gt=0)
    earned_on = util.parse_iso(body["earned_on"], "earned_on")
    credit = util.stamp_new({
        "id": util.new_id(),
        "license_id": id,
        "provider_name": provider,
        "category": category,
        "hours": hours,
        "earned_on": util.to_iso(earned_on),
        "status": "SUBMITTED",
    })
    db.ce_credits[credit["id"]] = credit
    return success_object(ce_credit_view(credit), 201)


@bp.route("/licensure/licenses/<id>/ce-credits", methods=["GET"])
@require_roles(*ALL_READ)
def list_ce_credits(actor, id):
    lic = _get_license_or_404(id)
    check_applicant_ownership(actor, "license", lic)
    items = util.sorted_by_created(svc.ce_credits_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([ce_credit_view(c) for c in page], limit, offset, total)


@bp.route("/licensure/ce-credits/<creditId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_ce_credit(actor, creditId):
    c = db.ce_credits.get(creditId)
    if c is None:
        raise errors.err_not_found("CECredit not found")
    check_applicant_ownership(actor, "ce_credit", c)
    return success_object(ce_credit_view(c))


CE_CREDIT_TRANSITIONS = {
    "SUBMITTED": {"VERIFIED"},
    "VERIFIED": {"VOIDED"},
    "VOIDED": {"VERIFIED"},
}


@bp.route("/licensure/ce-credits/<creditId>/state", methods=["POST"])
@require_roles("CredentialEvaluator")
def ce_credit_state(actor, creditId):
    c = db.ce_credits.get(creditId)
    if c is None:
        raise errors.err_not_found("CECredit not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, set(CE_CREDIT_TRANSITIONS.keys()), "to_status")
    if to_status not in CE_CREDIT_TRANSITIONS[c["status"]]:
        raise errors.err_invalid_state()
    c["status"] = to_status
    util.touch(c)
    return success_object(ce_credit_view(c))


# ---------------------------------------------------------------------------
# CE audits
# ---------------------------------------------------------------------------

def ce_audit_view(a):
    return dict(a)


AUDIT_VARIANTS = {"STANDARD", "RESTORATION"}


@bp.route("/licensure/licenses/<id>/ce-audits", methods=["POST"])
@require_roles("CredentialEvaluator")
def create_ce_audit(actor, id):
    lic = _get_license_or_404(id)
    body = util.get_body()
    util.require_fields(body, ["audit_variant"])
    variant = util.require_enum(body["audit_variant"], AUDIT_VARIANTS, "audit_variant")
    # one open audit per license
    for a in svc.ce_audits_of(id):
        if a["status"] in svc.AUDIT_OPEN:
            raise errors.err_audit_already_open()
    audit = util.stamp_new({
        "id": util.new_id(),
        "license_id": id,
        "audit_variant": variant,
        "cycle_start": lic["issued_on"],
        "cycle_end": lic["expires_on"],
        "required_hours": 0,
        "verified_hours": 0,
        "status": "INITIATED",
    })
    db.ce_audits[audit["id"]] = audit
    vh, req = svc.compute_ce_audit_totals(audit)
    audit["verified_hours"] = vh
    audit["required_hours"] = req
    return success_object(ce_audit_view(audit), 201)


@bp.route("/licensure/licenses/<id>/ce-audits", methods=["GET"])
@require_roles(*ALL_READ)
def list_ce_audits(actor, id):
    lic = _get_license_or_404(id)
    check_applicant_ownership(actor, "license", lic)
    items = util.sorted_by_created(svc.ce_audits_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([ce_audit_view(a) for a in page], limit, offset, total)


@bp.route("/licensure/ce-audits/<auditId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_ce_audit(actor, auditId):
    a = db.ce_audits.get(auditId)
    if a is None:
        raise errors.err_not_found("CEAudit not found")
    check_applicant_ownership(actor, "ce_audit", a)
    return success_object(ce_audit_view(a))


CE_AUDIT_TRANSITIONS = {
    "INITIATED": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"PASSED", "FAILED"},
    "FAILED": {"REMEDIATION"},
    "REMEDIATION": {"UNDER_REVIEW"},
    "PASSED": set(),
}


@bp.route("/licensure/ce-audits/<auditId>/state", methods=["POST"])
@require_roles("CredentialEvaluator")
def ce_audit_state(actor, auditId):
    a = db.ce_audits.get(auditId)
    if a is None:
        raise errors.err_not_found("CEAudit not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, set(CE_AUDIT_TRANSITIONS.keys()), "to_status")
    if to_status not in CE_AUDIT_TRANSITIONS[a["status"]]:
        raise errors.err_invalid_state()
    if a["status"] == "UNDER_REVIEW" and to_status == "PASSED":
        if not (a.get("verified_hours") or 0) >= (a.get("required_hours") or 0):
            raise errors.err_audit_hours_insufficient()
    a["status"] = to_status
    util.touch(a)
    return success_object(ce_audit_view(a))


@bp.route("/licensure/ce-audits/<auditId>/determinations", methods=["POST"])
@require_roles("CredentialEvaluator")
def ce_audit_determination(actor, auditId):
    a = db.ce_audits.get(auditId)
    if a is None:
        raise errors.err_not_found("CEAudit not found")
    body = util.get_body()
    util.require_fields(body, ["expected_ce_audit_version"])
    expected = util.require_int(body["expected_ce_audit_version"], "expected_ce_audit_version")
    if expected != a["version"]:
        raise errors.err_stale_version()
    vh, req = svc.compute_ce_audit_totals(a)
    a["verified_hours"] = vh
    a["required_hours"] = req
    util.touch(a)
    return success_object(ce_audit_view(a), 201)


# ---------------------------------------------------------------------------
# Misconduct cases
# ---------------------------------------------------------------------------

def case_view(c):
    return dict(c)


ALLEGATION_CATEGORIES = {"BOUNDARY_VIOLATION", "FINANCIAL_MISCONDUCT", "INCOMPETENCE",
                         "CRIMINAL_CONDUCT"}
FINDINGS = {"SUBSTANTIATED", "UNSUBSTANTIATED"}


@bp.route("/licensure/licenses/<id>/misconduct-cases", methods=["POST"])
@require_roles("LegalOfficer")
def create_misconduct_case(actor, id):
    lic = _get_license_or_404(id)
    body = util.get_body()
    util.require_fields(body, ["allegation_category"])
    category = util.require_enum(body["allegation_category"], ALLEGATION_CATEGORIES,
                                 "allegation_category")
    case = util.stamp_new({
        "id": util.new_id(),
        "license_id": id,
        "allegation_category": category,
        "investigator_user_id": None,
        "finding": None,
        "status": "OPENED",
    })
    db.misconduct_cases[case["id"]] = case
    return success_object(case_view(case), 201)


@bp.route("/licensure/licenses/<id>/misconduct-cases", methods=["GET"])
@require_roles(*ALL_READ)
def list_misconduct_cases(actor, id):
    lic = _get_license_or_404(id)
    check_applicant_ownership(actor, "license", lic)
    items = util.sorted_by_created(svc.misconduct_cases_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([case_view(c) for c in page], limit, offset, total)


@bp.route("/licensure/misconduct-cases/<caseId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_misconduct_case(actor, caseId):
    case = db.misconduct_cases.get(caseId)
    if case is None:
        raise errors.err_not_found("MisconductCase not found")
    check_applicant_ownership(actor, "misconduct_case", case)
    return success_object(case_view(case))


CASE_TRANSITIONS = {
    "OPENED": {"INVESTIGATING", "DISMISSED"},
    "INVESTIGATING": {"HEARING"},
    "HEARING": {"ADJUDICATED"},
    "ADJUDICATED": {"DISMISSED"},
    "SANCTION_ISSUED": set(),
    "DISMISSED": set(),
}

CASE_ROLE_TARGETS = {
    "BackgroundInvestigator": {"INVESTIGATING"},
    "LegalOfficer": {"DISMISSED", "HEARING", "ADJUDICATED"},
}


@bp.route("/licensure/misconduct-cases/<caseId>/state", methods=["POST"])
@require_roles("LegalOfficer", "BackgroundInvestigator")
def misconduct_case_state(actor, caseId):
    case = db.misconduct_cases.get(caseId)
    if case is None:
        raise errors.err_not_found("MisconductCase not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, set(CASE_TRANSITIONS.keys()), "to_status")
    if to_status not in CASE_ROLE_TARGETS.get(actor.role, set()):
        raise errors.err_forbidden()
    current = case["status"]
    if to_status not in CASE_TRANSITIONS[current]:
        raise errors.err_invalid_state()
    if current == "OPENED" and to_status == "INVESTIGATING":
        case["investigator_user_id"] = actor.user_id
    if current == "HEARING" and to_status == "ADJUDICATED":
        if "finding" not in body or body["finding"] is None:
            raise errors.err_case_finding_required()
        finding = util.require_enum(body["finding"], FINDINGS, "finding")
        if actor.user_id == case.get("investigator_user_id"):
            raise errors.err_segregation_of_duties()
        case["finding"] = finding
    if current == "ADJUDICATED" and to_status == "DISMISSED":
        if case.get("finding") != "UNSUBSTANTIATED":
            raise errors.err_invalid_state("Only UNSUBSTANTIATED cases may be dismissed")
        for action in svc.disciplinary_actions_of_case(caseId):
            if action["status"] == "PROPOSED":
                action["status"] = "VACATED"
                util.touch(action)
    case["status"] = to_status
    util.touch(case)
    return success_object(case_view(case))


# ---------------------------------------------------------------------------
# Disciplinary actions
# ---------------------------------------------------------------------------

def action_view(a):
    return dict(a)


SANCTION_TYPES = {"REPRIMAND", "SUSPENSION", "REVOCATION", "FINE"}


@bp.route("/licensure/misconduct-cases/<caseId>/disciplinary-actions", methods=["POST"])
@require_roles("LegalOfficer")
def create_disciplinary_action(actor, caseId):
    case = db.misconduct_cases.get(caseId)
    if case is None:
        raise errors.err_not_found("MisconductCase not found")
    body = util.get_body()
    util.require_fields(body, ["sanction_type"])
    sanction_type = util.require_enum(body["sanction_type"], SANCTION_TYPES, "sanction_type")
    suspension_start = None
    suspension_end = None
    fine_cents = None
    if sanction_type == "SUSPENSION":
        util.require_fields(body, ["suspension_start", "suspension_end"])
        suspension_start = util.parse_iso(body["suspension_start"], "suspension_start")
        suspension_end = util.parse_iso(body["suspension_end"], "suspension_end")
        if suspension_end < suspension_start:
            raise errors.err_validation("suspension_end must not be earlier than suspension_start")
        # closed-interval overlap with PROPOSED/ISSUED suspensions on the license
        for a in svc.disciplinary_actions_of_license(case["license_id"]):
            if a["sanction_type"] != "SUSPENSION" or a["status"] not in ("PROPOSED", "ISSUED"):
                continue
            a_start = util.parse_iso(a["suspension_start"])
            a_end = util.parse_iso(a["suspension_end"])
            # closed semantics: touching endpoints overlap
            if suspension_start <= a_end and a_start <= suspension_end:
                raise errors.err_suspension_interval_overlap()
    if sanction_type == "FINE":
        util.require_fields(body, ["fine_cents"])
        fine_cents = util.require_int(body["fine_cents"], "fine_cents", 0)
    action = util.stamp_new({
        "id": util.new_id(),
        "case_id": caseId,
        "license_id": case["license_id"],
        "sanction_type": sanction_type,
        "suspension_start": util.to_iso(suspension_start) if suspension_start else None,
        "suspension_end": util.to_iso(suspension_end) if suspension_end else None,
        "fine_cents": fine_cents,
        "status": "PROPOSED",
    })
    db.disciplinary_actions[action["id"]] = action
    return success_object(action_view(action), 201)


@bp.route("/licensure/disciplinary-actions/<actionId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_disciplinary_action(actor, actionId):
    a = db.disciplinary_actions.get(actionId)
    if a is None:
        raise errors.err_not_found("DisciplinaryAction not found")
    check_applicant_ownership(actor, "disciplinary_action", a)
    return success_object(action_view(a))


@bp.route("/licensure/disciplinary-actions", methods=["GET"])
@require_roles(*ALL_READ)
def list_disciplinary_actions(actor):
    case_id = request.args.get("case_id")
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    items = list(db.disciplinary_actions.values())
    if actor.role == "Applicant":
        own_license_ids = {l["id"] for l in db.licenses.values()
                           if l["applicant_id"] == actor.user_id}
        items = [a for a in items if a["license_id"] in own_license_ids]
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    if license_id is not None:
        items = [a for a in items if a["license_id"] == license_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = util.sorted_by_created(items)
    page, limit, offset, total = util.paginate(items)
    return success_list([action_view(a) for a in page], limit, offset, total)


@bp.route("/licensure/disciplinary-actions/<actionId>/state", methods=["POST"])
@require_roles("LegalOfficer")
def disciplinary_action_state(actor, actionId):
    action = db.disciplinary_actions.get(actionId)
    if action is None:
        raise errors.err_not_found("DisciplinaryAction not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, {"PROPOSED", "ISSUED", "SERVED", "VACATED"}, "to_status")
    current = action["status"]
    allowed = {}
    if current == "PROPOSED":
        allowed = {"ISSUED", "VACATED"}
    if to_status not in allowed:
        raise errors.err_invalid_state()
    if to_status == "VACATED":
        action["status"] = "VACATED"
        util.touch(action)
        return success_object(action_view(action))
    # to_status == ISSUED: case must be ADJUDICATED with SUBSTANTIATED finding
    case = db.misconduct_cases.get(action["case_id"])
    if (case is None or case["status"] != "ADJUDICATED"
            or case.get("finding") != "SUBSTANTIATED"):
        raise errors.err_invalid_state(
            "Case must be ADJUDICATED with SUBSTANTIATED finding to issue")
    action["status"] = "ISSUED"
    util.touch(action)
    lic = db.licenses.get(action["license_id"])
    if action["sanction_type"] == "SUSPENSION":
        if lic is not None and lic["status"] == "ACTIVE":
            lic["status"] = "SUSPENDED"
            util.touch(lic)
    elif action["sanction_type"] == "REVOCATION":
        if lic is not None and lic["status"] in ("ACTIVE", "SUSPENDED"):
            lic["status"] = "REVOKED"
            util.touch(lic)
            svc.cascade_license_revoked(lic)
    # linked case moves to SANCTION_ISSUED
    case["status"] = "SANCTION_ISSUED"
    util.touch(case)
    return success_object(action_view(action))
