"""LicenseApplication lifecycle (PRD §3.4 and §3.9)."""
from decimal import Decimal

from flask import Blueprint

import clock
import db
import response
import serializers
import validators as v
from constants import (
    ALL_ROLES, APPLICATION_STATUSES, DECISIONS, EXAM_KINDS, LEDGER_ENTRY_TYPES,
    LICENSE_TERM_DAYS, LIVE_APPLICATION_STATUSES, MAX_DEFICIENCY_CYCLES,
    PATHWAYS, PATHWAY_BAR_INDEX, REVIEWABLE_STATUSES, ROLE_ADMIN, ROLE_ANALYST,
    ROLE_APPLICANT, ROLE_DEPUTY,
)
from errors import (
    ERR_APPLICATION_NOT_REVIEWABLE, ERR_CREDENTIAL_APPLICANT_MISMATCH,
    ERR_DISCIPLINARY_BAR, ERR_DUPLICATE_ACTIVE_APPLICATION,
    ERR_EVALUATION_NOT_COMPLETE, ERR_FEE_BALANCE_OUTSTANDING,
    ERR_JURISPRUDENCE_EXAM_REQUIRED, ERR_MILITARY_STATUS_REQUIRED,
    ERR_NATIONAL_EXAM_REQUIRED, ERR_NO_QUALIFYING_CREDENTIAL,
    ERR_PAYMENT_EXCEEDS_BALANCE, ERR_REQUIREMENT_HOURS_UNSATISFIED,
    ERR_RESIDENCY_REQUIREMENT_NOT_MET, ERR_SEGREGATION_OF_DUTIES, fail,
)
from middleware import authenticate
from services import calculations, lookups, workflow

bp = Blueprint("applications", __name__)


def evaluation_of(application_id):
    for row in db.evaluations.values():
        if row["application_id"] == application_id:
            return row
    return None


def _require_reviewable(application, allowed_statuses):
    if application["status"] not in allowed_statuses:
        fail(ERR_APPLICATION_NOT_REVIEWABLE,
             "The application is in status %s, which this operation does not "
             "permit." % application["status"])


def _require_no_disciplinary_bar(application):
    applicant = db.applicants[application["applicant_id"]]
    if not applicant["good_standing_flag"]:
        fail(ERR_DISCIPLINARY_BAR, "The applicant is not in good standing.")
    if calculations.pathway_risk_index(application) >= PATHWAY_BAR_INDEX:
        fail(ERR_DISCIPLINARY_BAR,
             "The application's pathway risk index is at or above the bar.")


# ---------------------------------------------------------------------------
# create / read / list
# ---------------------------------------------------------------------------
@bp.post("/licensure/applications")
def create_application():
    user_id, role = authenticate([ROLE_APPLICANT])
    body = v.body()
    applicant_id = v.f_string(body, "applicant_id")
    profession_id = v.f_string(body, "profession_id")
    primary_credential_id = v.f_string(body, "primary_credential_id")
    pathway = v.f_enum(body, "pathway", PATHWAYS)
    expedited = v.f_bool(body, "expedited", required=False, default=False)

    applicant = lookups.applicant(applicant_id)
    profession = lookups.profession(profession_id)
    credential = lookups.credential(primary_credential_id)

    lookups.require_applicant_ownership(role, user_id, applicant["id"])

    if credential["applicant_id"] != applicant["id"]:
        fail(ERR_CREDENTIAL_APPLICANT_MISMATCH,
             "The nominated credential belongs to a different applicant.")

    for existing in db.applications.values():
        if (existing["applicant_id"] == applicant["id"]
                and existing["profession_id"] == profession["id"]
                and existing["status"] in LIVE_APPLICATION_STATUSES):
            fail(ERR_DUPLICATE_ACTIVE_APPLICATION,
                 "Another live application already exists for this applicant "
                 "and profession.")

    row = db.make_row({
        "applicant_id": applicant["id"],
        "profession_id": profession["id"],
        "primary_credential_id": credential["id"],
        "pathway": pathway,
        "expedited": expedited,
        "status": "DRAFT",
        "deficiency_cycle_count": 0,
        "submitted_at": None,
        "review_deadline_at": None,
        "decided_at": None,
        "processing_elapsed_days": 0,
        "processing_standard_met": None,
        "statutory_waiver_pct": Decimal("0.00"),
        "gross_total_cents": 0,
        "fee_balance_cents": 0,
        "requirement_hours_satisfied": Decimal("0.0"),
        "requirement_hours_remaining": profession["requirement_hours_total"],
        "national_exam_passed": False,
        "jurisprudence_exam_passed": False,
        "scope_reviewed_by_user_id": None,
        "decided_by_user_id": None,
    })
    db.applications[row["id"]] = row
    return response.object_response(serializers.application(row), 201)


@bp.get("/licensure/applications/<application_id>")
def read_application(application_id):
    user_id, role = authenticate(ALL_ROLES)
    application = lookups.application(application_id)
    lookups.require_applicant_ownership(role, user_id, application["applicant_id"])
    return response.object_response(serializers.application(application))


@bp.get("/licensure/applications")
def list_applications():
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    applicant_id = response.query_string("applicant_id")
    profession_id = response.query_string("profession_id")
    primary_credential_id = response.query_string("primary_credential_id")
    status = response.query_enum("status", APPLICATION_STATUSES)

    rows = []
    for row in db.applications.values():
        if applicant_id is not None and row["applicant_id"] != applicant_id:
            continue
        if profession_id is not None and row["profession_id"] != profession_id:
            continue
        if (primary_credential_id is not None
                and row["primary_credential_id"] != primary_credential_id):
            continue
        if status is not None and row["status"] != status:
            continue
        if role == ROLE_APPLICANT and row["applicant_id"] != user_id:
            continue
        rows.append(row)
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.application)


# ---------------------------------------------------------------------------
# DRAFT -> SUBMITTED
# ---------------------------------------------------------------------------
@bp.post("/licensure/applications/<application_id>/submit")
def submit_application(application_id):
    user_id, role = authenticate([ROLE_APPLICANT])
    application = lookups.application(application_id)
    lookups.require_applicant_ownership(role, user_id, application["applicant_id"])
    _require_reviewable(application, ("DRAFT",))

    applicant = db.applicants[application["applicant_id"]]
    profession = db.professions[application["profession_id"]]

    _require_no_disciplinary_bar(application)

    if (application["pathway"] == "MILITARY_SPOUSE_EXPEDITED"
            and applicant["military_status"] != "MILITARY_SPOUSE"):
        fail(ERR_MILITARY_STATUS_REQUIRED,
             "The military-spouse expedited pathway requires MILITARY_SPOUSE "
             "status.")

    if (application["pathway"] == "UNIVERSAL_RECOGNITION"
            and applicant["residency_months"]
            < profession["universal_recognition_min_residency_months"]):
        fail(ERR_RESIDENCY_REQUIREMENT_NOT_MET,
             "The universal-recognition pathway requires more in-state "
             "residency months.")

    qualifying = {c["id"] for c in db.credentials.values()
                  if c["applicant_id"] == applicant["id"]
                  and c["status"] == "ACTIVE"
                  and c["verified_good_standing"]}
    if not qualifying or application["primary_credential_id"] not in qualifying:
        fail(ERR_NO_QUALIFYING_CREDENTIAL,
             "The applicant holds no qualifying credential, or the nominated "
             "primary credential is not a member of the qualifying set.")

    now = clock.now()
    application["submitted_at"] = now
    application["status"] = "SUBMITTED"
    application["review_deadline_at"] = calculations.review_deadline(
        application, profession, now)

    fee = calculations.net_fee_due(application, applicant, profession)
    application["statutory_waiver_pct"] = fee["statutory_waiver_pct"]
    application["gross_total_cents"] = fee["gross_total_cents"]
    workflow.append_ledger(application, "ASSESSMENT", fee["gross_total_cents"])
    workflow.append_ledger(application, "WAIVER_CREDIT",
                           -fee["waiver_credit_cents"])
    workflow.recompute_balance(application)
    application["requirement_hours_remaining"] = (
        profession["requirement_hours_total"]
        - application["requirement_hours_satisfied"])
    db.touch(application)
    return response.object_response(serializers.application(application))


# ---------------------------------------------------------------------------
# payments and the ledger
# ---------------------------------------------------------------------------
@bp.post("/licensure/applications/<application_id>/payments")
def create_payment(application_id):
    user_id, role = authenticate([ROLE_APPLICANT])
    body = v.body()
    amount_cents = v.f_int(body, "amount_cents", minimum=1)

    application = lookups.application(application_id)
    lookups.require_applicant_ownership(role, user_id, application["applicant_id"])

    if amount_cents > application["fee_balance_cents"]:
        fail(ERR_PAYMENT_EXCEEDS_BALANCE,
             "The payment exceeds the application's outstanding balance.")

    entry = workflow.append_ledger(application, "PAYMENT", -amount_cents)
    workflow.recompute_balance(application)
    db.touch(application)
    return response.object_response(serializers.ledger_entry(entry), 201)


@bp.get("/licensure/applications/<application_id>/fee-ledger-entries")
def list_ledger_entries(application_id):
    user_id, role = authenticate(ALL_ROLES)
    limit, offset = response.pagination()
    entry_type = response.query_enum("entry_type", LEDGER_ENTRY_TYPES)
    application = lookups.application(application_id)
    lookups.require_applicant_ownership(role, user_id, application["applicant_id"])
    rows = [e for e in db.ledger_entries.values()
            if e["application_id"] == application["id"]
            and (entry_type is None or e["entry_type"] == entry_type)]
    return response.paginate(db.ordered(rows), limit, offset,
                             serializers.ledger_entry)


# ---------------------------------------------------------------------------
# exam results
# ---------------------------------------------------------------------------
@bp.post("/licensure/applications/<application_id>/exam-results")
def record_exam_result(application_id):
    authenticate([ROLE_ADMIN])
    body = v.body()
    exam_kind = v.f_enum(body, "exam_kind", EXAM_KINDS)
    passed = v.f_bool(body, "passed")
    v.f_number(body, "score", required=False, default=None, places=2)

    application = lookups.application(application_id)
    _require_reviewable(application, REVIEWABLE_STATUSES)

    if exam_kind == "NATIONAL":
        application["national_exam_passed"] = passed
    else:
        application["jurisprudence_exam_passed"] = passed
    db.touch(application)
    return response.object_response(serializers.application(application))


# ---------------------------------------------------------------------------
# deficiency cycles
# ---------------------------------------------------------------------------
@bp.post("/licensure/applications/<application_id>/deficiency")
def record_deficiency(application_id):
    user_id, role = authenticate([ROLE_ANALYST])
    body = v.body()
    v.f_string(body, "reason_code")

    application = lookups.application(application_id)
    _require_reviewable(application, ("UNDER_REVIEW",))

    application["deficiency_cycle_count"] = application["deficiency_cycle_count"] + 1
    if application["deficiency_cycle_count"] <= MAX_DEFICIENCY_CYCLES:
        application["status"] = "DEFICIENT"
        db.touch(application)
    else:
        _deny(application, user_id)
    return response.object_response(serializers.application(application))


@bp.post("/licensure/applications/<application_id>/cure")
def cure_application(application_id):
    user_id, role = authenticate([ROLE_APPLICANT])
    application = lookups.application(application_id)
    lookups.require_applicant_ownership(role, user_id, application["applicant_id"])
    _require_reviewable(application, ("DEFICIENT",))
    application["status"] = "UNDER_REVIEW"
    db.touch(application)
    return response.object_response(serializers.application(application))


# ---------------------------------------------------------------------------
# board decision
# ---------------------------------------------------------------------------
def _deny(application, user_id):
    now = clock.now()
    application["status"] = "DENIED"
    application["decided_at"] = now
    application["decided_by_user_id"] = user_id
    elapsed, standard_met = calculations.processing_time_metrics(application)
    application["processing_elapsed_days"] = elapsed
    application["processing_standard_met"] = standard_met
    db.touch(application)
    workflow.leave_reviewable_cascade(application, "APPLICATION_DENIED")


def _approve(application, user_id):
    now = clock.now()
    profession = db.professions[application["profession_id"]]
    application["status"] = "APPROVED"
    application["decided_at"] = now
    application["decided_by_user_id"] = user_id
    elapsed, standard_met = calculations.processing_time_metrics(application)
    application["processing_elapsed_days"] = elapsed
    application["processing_standard_met"] = standard_met

    # CASCADE LINK 1 — mint the licence.
    sequence = db.next_license_sequence()
    license_row = db.make_row({
        "application_id": application["id"],
        "profession_id": profession["id"],
        "converted_from_permit_id": None,
        "license_number": "%s-%06d" % (profession["profession_code"], sequence),
        "status": "ACTIVE",
        "issued_at": now,
        "expires_at": clock.add_days(now, LICENSE_TERM_DAYS),
    })
    db.licenses[license_row["id"]] = license_row

    # fan-out of link 1 — assignments complete.
    workflow.complete_assignments(application["id"])

    # CASCADE LINKS 2 and 3 — convert the bridging permit and credit the unused
    # days.  The application's version increments once for the approval as a
    # whole, so convert_permit does not touch it.
    for permit in workflow.active_permits(application["id"]):
        workflow.convert_permit(permit, license_row)

    db.touch(application)


@bp.post("/licensure/applications/<application_id>/decision")
def decide_application(application_id):
    user_id, role = authenticate([ROLE_DEPUTY])
    body = v.body()
    decision = v.f_enum(body, "decision", DECISIONS)
    v.f_string(body, "memo", required=False, default=None)

    application = lookups.application(application_id)
    _require_reviewable(application, ("UNDER_REVIEW",))

    if decision == "APPROVE":
        _require_no_disciplinary_bar(application)

    if user_id == application["scope_reviewed_by_user_id"]:
        fail(ERR_SEGREGATION_OF_DUTIES,
             "The officer who recorded the scope review may not decide the "
             "application.")

    if decision == "DENY":
        _deny(application, user_id)
        return response.object_response(serializers.application(application))

    profession = db.professions[application["profession_id"]]
    applicant = db.applicants[application["applicant_id"]]

    evaluation = evaluation_of(application["id"])
    if evaluation is None or evaluation["overall_status"] != "COMPLETE":
        fail(ERR_EVALUATION_NOT_COMPLETE,
             "The application's credential evaluation is missing or still in "
             "progress.")

    if application["requirement_hours_remaining"] != Decimal("0.0"):
        fail(ERR_REQUIREMENT_HOURS_UNSATISFIED,
             "The application still has outstanding requirement hours.")

    if not (evaluation["exam_waiver_granted"]
            or application["national_exam_passed"]):
        fail(ERR_NATIONAL_EXAM_REQUIRED,
             "The national examination has neither been waived nor passed.")

    if profession["jurisprudence_exam_required"]:
        compact = calculations.unexpired_compact(profession["id"],
                                                 applicant["state_code"])
        waived = compact is not None and compact["jurisprudence_waiver_allowed"]
        if not (application["jurisprudence_exam_passed"] or waived):
            fail(ERR_JURISPRUDENCE_EXAM_REQUIRED,
                 "The jurisprudence examination has neither been passed nor "
                 "waived by an unexpired compact.")

    if application["fee_balance_cents"] > 0:
        fail(ERR_FEE_BALANCE_OUTSTANDING,
             "The application still owes fees.")

    _approve(application, user_id)
    return response.object_response(serializers.application(application))
