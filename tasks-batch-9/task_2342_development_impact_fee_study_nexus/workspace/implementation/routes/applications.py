"""Development applications, assessment, credit claims, deferrals and collection."""

from decimal import Decimal
from flask import Blueprint, g

import clock
import db
import helpers
import response
import serializers
from errors import raise_error
from middleware import ANY, guard
from services import assess, calc, derive, ledger
from util import add_days

bp = Blueprint("applications", __name__)

ASSESSED_STATUSES = ("ASSESSED", "REASSESSED")


def _require_owner(application):
    if g.role == "Developer" and application.get("submitted_by_user_id") != g.user_id:
        raise_error("ERR_NOT_APPLICATION_OWNER")


# --------------------------------------------------------------------------- #
# Applications
# --------------------------------------------------------------------------- #


@bp.get("/development-applications")
@guard(*ANY)
def list_applications():
    filters = {
        "fee_program_id": helpers.arg_string("fee_program_id"),
        "pinned_fee_study_id": helpers.arg_string("pinned_fee_study_id"),
        "assessment_status": helpers.arg_enum("assessment_status", helpers.ASSESSMENT_STATUSES),
        "collection_status": helpers.arg_enum("collection_status", helpers.COLLECTION_STATUSES),
        "reassessment_required": helpers.arg_bool("reassessment_required"),
    }
    rows = [a for a in db.ordered(db.development_applications) if helpers.matches(a, filters)]
    return response.paginated(rows, serializers.development_application)


@bp.get("/development-applications/<application_id>")
@guard(*ANY)
def read_application(application_id):
    application = helpers.get_application(application_id)
    return response.object_response(serializers.development_application(application))


@bp.post("/development-applications")
@guard("Developer")
def create_application():
    body = helpers.json_body()
    body.forbid_versions()
    program_id = body.string("fee_program_id", required=True)
    permit_number = body.string("permit_number", required=True, min_len=1, max_len=40)
    land_use_category = body.enum("land_use_category", helpers.LAND_USE_CATEGORIES, required=True)
    collection_trigger = body.enum("collection_trigger", helpers.COLLECTION_TRIGGERS,
                                   default="PERMIT")
    dwelling_units = body.integer("dwelling_units", default=0, minimum=0)
    nonres_sqft = body.integer("nonres_sqft", default=0, minimum=0)
    if dwelling_units == 0 and nonres_sqft == 0:
        raise_error("ERR_INVALID_REQUEST")

    program = db.fee_programs.get(program_id)
    if program is None:
        raise_error("ERR_INVALID_REFERENCE")
    for existing in db.development_applications.values():
        if existing["fee_program_id"] == program_id and existing["permit_number"] == permit_number:
            raise_error("ERR_DUPLICATE_PERMIT_NUMBER")

    application = db.new_record(
        fee_program_id=program_id,
        permit_number=permit_number,
        land_use_category=land_use_category,
        dwelling_units=dwelling_units,
        nonres_sqft=nonres_sqft,
        collection_trigger=collection_trigger,
        submitted_by_user_id=g.user_id,
        pinned_fee_study_id=None,
        pinned_fee_study_version=None,
        assessment_status="UNASSESSED",
        collection_status="NOT_DUE",
        reassessment_required=False,
        assessed_lines=[],
        gross_assessed_cents=0,
        credit_applied_cents=0,
        admin_charge_cents=0,
        net_due_cents=0,
        paid_cents=0,
        default_penalty_cents=0,
        assessed_at=None,
        reassessed_at=None,
        co_issued_at=None,
    )
    db.development_applications[application["id"]] = application
    return response.object_response(serializers.development_application(application), 201)


@bp.post("/development-applications/<application_id>/assess")
@guard("PermitOfficer")
def assess_application(application_id):
    application = helpers.get_application(application_id)
    helpers.json_body().forbid_versions()

    study = derive.effective_study(application["fee_program_id"])
    if study is not None:
        for component in derive.components_of_study(study["id"]):
            if component["allocation_status"] != "VALID":
                raise_error("ERR_COMPONENT_ALLOCATION_STALE")
    else:
        raise_error("ERR_NO_EFFECTIVE_STUDY")

    if application["assessment_status"] != "UNASSESSED":
        if application["collection_status"] == "PAID" or application.get("co_issued_at") is not None:
            raise_error("ERR_APPLICATION_INVALID_STATE")

    if not assess.applicable_lines(study["id"], application["land_use_category"]):
        raise_error("ERR_NO_APPLICABLE_FEE_SCHEDULE")

    program = derive.program_of_application(application)
    assess.run_assessment(application, program, study)
    return response.object_response(serializers.development_application(application))


@bp.post("/development-applications/<application_id>/payments")
@guard("PermitOfficer")
def collect_payment(application_id):
    application = helpers.get_application(application_id)
    body = helpers.json_body()
    body.forbid_versions()
    amount_cents = body.integer("amount_cents", required=True)
    body.string("payment_reference")

    if application["assessment_status"] not in ASSESSED_STATUSES:
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if application["collection_status"] == "PAID":
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if (application["collection_status"] == "NOT_DUE"
            and application["collection_trigger"] != "CERTIFICATE_OF_OCCUPANCY"):
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if application["reassessment_required"]:
        raise_error("ERR_REASSESSMENT_REQUIRED")

    outstanding = application["net_due_cents"] - application["paid_cents"]
    if amount_cents != outstanding:
        raise_error("ERR_PAYMENT_AMOUNT_MISMATCH")

    program = derive.program_of_application(application)
    ledger.record_collection(application, program)
    ledger.satisfy_agreements(application)
    application["collection_status"] = "PAID"
    application["paid_cents"] = derive.paid_cents(application["id"])
    db.touch(application)

    touched = {line["facility_category_id"] for line in application.get("assessed_lines") or []}
    derive.sync_categories(touched, posture=True, force=True)
    return response.object_response(serializers.development_application(application))


@bp.post("/development-applications/<application_id>/issue-co")
@guard("PermitOfficer")
def issue_certificate_of_occupancy(application_id):
    application = helpers.get_application(application_id)
    helpers.json_body().forbid_versions()

    if application["assessment_status"] not in ASSESSED_STATUSES:
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if application.get("co_issued_at") is not None:
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if application["reassessment_required"]:
        raise_error("ERR_REASSESSMENT_REQUIRED")
    if application["collection_status"] != "PAID":
        raise_error("ERR_CO_BLOCKED_UNPAID")
    for agreement in derive.agreements_of_application(application["id"]):
        if agreement["status"] in ("REQUESTED", "EXECUTED", "DEFAULTED"):
            raise_error("ERR_CO_BLOCKED_UNPAID")

    application["co_issued_at"] = clock.now()
    db.touch(application)
    return response.object_response(serializers.development_application(application))


# --------------------------------------------------------------------------- #
# Credit claims
# --------------------------------------------------------------------------- #


@bp.get("/development-applications/<application_id>/credit-claims")
@guard(*ANY)
def list_credit_claims(application_id):
    application = helpers.get_application(application_id)
    status = helpers.arg_enum("status", helpers.CLAIM_STATUSES)
    rows = [c for c in derive.claims_of_application(application["id"])
            if status is None or c["status"] == status]
    return response.paginated(rows, serializers.credit_claim)


@bp.post("/development-applications/<application_id>/credit-claims")
@guard("Developer")
def create_credit_claim(application_id):
    application = helpers.get_application(application_id)
    body = helpers.json_body()
    body.forbid_versions()
    code = body.string("facility_category_code", required=True, pattern=helpers.CODE_PATTERN)
    credit_type = body.enum("credit_type", helpers.CREDIT_TYPES, required=True)
    valuation_method = body.enum("valuation_method", helpers.VALUATION_METHODS, required=True)
    # The strict-positivity requirement attaches to whichever amount field the
    # declared credit_type makes required; the other amount field is simply an
    # absent-or-zero contribution to the valuation.
    improvement_value = body.integer(
        "improvement_value_cents",
        required=(credit_type == "DEVELOPER_IMPROVEMENT"),
        minimum=1 if credit_type == "DEVELOPER_IMPROVEMENT" else 0,
    )
    annual_tax = body.integer(
        "annual_tax_contribution_cents",
        required=(credit_type == "EXISTING_TAX_CONTRIBUTION"),
        minimum=1 if credit_type == "EXISTING_TAX_CONTRIBUTION" else 0,
    )
    contribution_years = body.integer("contribution_years", default=0, minimum=0, maximum=50)

    _require_owner(application)

    if application.get("co_issued_at") is not None:
        raise_error("ERR_APPLICATION_INVALID_STATE")

    program = derive.program_of_application(application)
    category = derive.category_by_code(application["fee_program_id"], code)
    study = derive.effective_study(application["fee_program_id"])
    priced = False
    if category is not None and study is not None:
        for component in derive.components_of_study(study["id"]):
            if component["facility_category_id"] == category["id"]:
                priced = True
                break
    if not priced:
        raise_error("ERR_CREDIT_CATEGORY_NOT_IN_STUDY")

    claimed = calc.credit_claim_value(
        valuation_method, improvement_value, annual_tax,
        contribution_years, program["discount_rate_bp"])

    claim = db.new_record(
        development_application_id=application["id"],
        facility_category_code=code,
        credit_type=credit_type,
        valuation_method=valuation_method,
        improvement_value_cents=improvement_value,
        annual_tax_contribution_cents=annual_tax,
        contribution_years=contribution_years,
        claimed_credit_cents=claimed,
        approved_cents=0,
        status="SUBMITTED",
        decided_by_user_id=None,
        decided_at=None,
    )
    db.credit_claims[claim["id"]] = claim
    return response.object_response(serializers.credit_claim(claim), 201)


@bp.post("/credit-claims/<claim_id>/decide")
@guard("NexusAnalyst")
def decide_credit_claim(claim_id):
    claim = helpers.get_claim(claim_id)
    body = helpers.json_body()
    body.forbid_versions("expected_development_application_version")
    decision = body.enum("decision", helpers.CLAIM_DECISIONS, required=True)
    expected = body.integer("expected_development_application_version", required=True)
    approved_cents = None
    if decision == "APPROVE_PARTIAL":
        approved_cents = body.integer("approved_cents", required=True)
        if approved_cents <= 0 or approved_cents >= claim["claimed_credit_cents"]:
            raise_error("ERR_INVALID_REQUEST")

    application = db.development_applications.get(claim["development_application_id"])
    if application is None:
        raise_error("ERR_DEVELOPMENT_APPLICATION_NOT_FOUND")
    if expected != application["version"]:
        raise_error("ERR_STALE_APPLICATION_VERSION")
    if application["assessment_status"] not in ASSESSED_STATUSES:
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if application.get("co_issued_at") is not None:
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if claim["status"] != "SUBMITTED":
        raise_error("ERR_CLAIM_INVALID_STATE")

    claim["decided_by_user_id"] = g.user_id
    claim["decided_at"] = clock.now()
    if decision == "APPROVE_FULL":
        claim["status"] = "APPROVED_FULL"
        claim["approved_cents"] = claim["claimed_credit_cents"]
    elif decision == "APPROVE_PARTIAL":
        claim["status"] = "APPROVED_PARTIAL"
        claim["approved_cents"] = approved_cents
    else:
        claim["status"] = "DENIED"
        claim["approved_cents"] = 0
    db.touch(claim)

    if decision in ("APPROVE_FULL", "APPROVE_PARTIAL"):
        program = derive.program_of_application(application)
        assess.system_reassessment(application, program)
    return response.object_response(serializers.credit_claim(claim))


# --------------------------------------------------------------------------- #
# Deferral agreements
# --------------------------------------------------------------------------- #


@bp.get("/development-applications/<application_id>/deferral-agreements")
@guard(*ANY)
def list_deferral_agreements(application_id):
    application = helpers.get_application(application_id)
    status = helpers.arg_enum("status", helpers.AGREEMENT_STATUSES)
    rows = [a for a in derive.agreements_of_application(application["id"])
            if status is None or a["status"] == status]
    return response.paginated(rows, serializers.deferral_agreement)


@bp.post("/development-applications/<application_id>/deferral-agreements")
@guard("Developer")
def create_deferral_agreement(application_id):
    application = helpers.get_application(application_id)
    body = helpers.json_body()
    body.forbid_versions()
    security_type = body.enum("requested_security_type", helpers.SECURITY_TYPES, required=True)
    security_amount = body.integer("security_amount_cents", required=True, minimum=1)
    requested_due_at = body.timestamp("requested_due_at", required=True)

    _require_owner(application)

    if (application["assessment_status"] not in ASSESSED_STATUSES
            or application.get("co_issued_at") is not None
            or application["collection_trigger"] != "PERMIT"
            or application["collection_status"] != "DUE"):
        raise_error("ERR_APPLICATION_INVALID_STATE")
    if requested_due_at <= clock.now():
        raise_error("ERR_DEFERRAL_DUE_DATE_INVALID")

    agreement = db.new_record(
        development_application_id=application["id"],
        requested_security_type=security_type,
        security_amount_cents=security_amount,
        requested_due_at=requested_due_at,
        due_at=None,
        status="REQUESTED",
        decided_by_user_id=None,
        decided_at=None,
        executed_at=None,
        satisfied_at=None,
        defaulted_at=None,
    )
    db.deferral_agreements[agreement["id"]] = agreement
    return response.object_response(serializers.deferral_agreement(agreement), 201)


@bp.post("/deferral-agreements/<agreement_id>/decide")
@guard("PermitOfficer")
def decide_deferral_agreement(agreement_id):
    agreement = helpers.get_agreement(agreement_id)
    body = helpers.json_body()
    body.forbid_versions()
    decision = body.enum("decision", helpers.AGREEMENT_DECISIONS, required=True)

    application = db.development_applications.get(agreement["development_application_id"])
    if (agreement["status"] != "REQUESTED"
            or application is None
            or application["collection_trigger"] != "PERMIT"
            or application["collection_status"] != "DUE"):
        raise_error("ERR_DEFERRAL_INVALID_STATE")

    if decision == "DENY":
        agreement["status"] = "DENIED"
        agreement["decided_by_user_id"] = g.user_id
        agreement["decided_at"] = clock.now()
        db.touch(agreement)
        return response.object_response(serializers.deferral_agreement(agreement))

    if agreement["security_amount_cents"] < application["net_due_cents"]:
        raise_error("ERR_INSUFFICIENT_SECURITY")

    program = derive.program_of_application(application)
    moment = clock.now()
    ceiling = add_days(moment, program["max_deferral_days"])
    requested = agreement["requested_due_at"]
    agreement["status"] = "EXECUTED"
    agreement["decided_by_user_id"] = g.user_id
    agreement["decided_at"] = moment
    agreement["executed_at"] = moment
    agreement["due_at"] = requested if requested < ceiling else ceiling
    db.touch(agreement)

    application["collection_status"] = "DEFERRED"
    db.touch(application)
    touched = {line["facility_category_id"] for line in application.get("assessed_lines") or []}
    derive.sync_categories(touched, force=True)
    return response.object_response(serializers.deferral_agreement(agreement))
