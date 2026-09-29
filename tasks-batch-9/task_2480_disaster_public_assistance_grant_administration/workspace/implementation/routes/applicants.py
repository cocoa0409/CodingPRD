"""Applicant endpoints: registration, eligibility determination, reporting sweep."""
from flask import Blueprint

from db import db, dt_of, new_row, now, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate
from routes.common import PREFIX, render_list, require, respond
from services.calc import risk_score_screening, risk_tier
from services.constants import APPLICANT_TYPES, PNP_SERVICE_TYPES
from services.ledger import (
    cascade_applicant,
    facilities_of_applicant,
    policies_of_facility,
    refresh_risk_tier,
    reports_of_applicant,
    rescore_monitoring,
)
from validate import body, present, v_bool, v_enum, v_id, v_int, v_str

bp = Blueprint("applicants", __name__)


@bp.route(PREFIX + "/applicants", methods=["POST"])
def create_applicant():
    authenticate(("PlatformAdmin",))
    payload = body()

    disaster_id = v_id(payload, "disaster_id")
    name = v_str(payload, "name")
    applicant_type = v_enum(payload, "applicant_type", APPLICANT_TYPES)
    population_served = v_int(payload, "population_served", minimum=0)
    pnp_service_type = v_enum(payload, "pnp_service_type", PNP_SERVICE_TYPES,
                              required=False, default=None)
    sba = v_bool(payload, "pnp_sba_referral_completed", required=False, default=False)
    tax_exempt = v_bool(payload, "tax_exempt_letter_on_file", required=False, default=False)

    require("disasters", disaster_id)

    row = new_row("applicants", {
        "disaster_id": disaster_id,
        "name": name,
        "applicant_type": applicant_type,
        "pnp_service_type": pnp_service_type,
        "pnp_sba_referral_completed": sba,
        "tax_exempt_letter_on_file": tax_exempt,
        "population_served": population_served,
        "eligibility_status": "PENDING",
        "eligibility_rationale": None,
        "monitoring_status": "STANDARD",
        "drawdown_status": "ACTIVE",
        "audit_requirement": "NONE",
        "risk_score_screening": 0,
        "risk_score_monitoring": None,
        "monitoring_scored_at": None,
        "risk_tier": "LOW",
        "total_obligated_cents": 0,
        "total_drawn_cents": 0,
        "total_refunded_cents": 0,
        "cash_on_hand_cents": 0,
        "available_drawdown_cents": 0,
        "pending_deobligation_cents": 0,
        "delinquent_report_count": 0,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/applicants", methods=["GET"])
def list_applicants():
    authenticate(ALL_ROLES)
    return render_list("applicants", {
        "disaster_id": "disaster_id",
        "eligibility_status": "eligibility_status",
        "monitoring_status": "monitoring_status",
        "drawdown_status": "drawdown_status",
    })


@bp.route(PREFIX + "/applicants/<applicant_id>", methods=["GET"])
def get_applicant(applicant_id):
    authenticate(ALL_ROLES)
    row = require("applicants", applicant_id)
    return respond(row)


@bp.route(PREFIX + "/applicants/<applicant_id>/eligibility-determination",
          methods=["POST"])
def eligibility_determination(applicant_id):
    authenticate(("ProgramSpecialist",))
    applicant = require("applicants", applicant_id)
    payload = body()
    decision = v_enum(payload, "decision", ("ELIGIBLE", "INELIGIBLE"))
    rationale = v_str(payload, "rationale", non_empty=False)

    if applicant["eligibility_status"] != "PENDING":
        fail("ERR_APPLICANT_INVALID_STATE",
             "eligibility has already been determined")

    if decision == "ELIGIBLE" \
            and applicant["applicant_type"] == "PRIVATE_NONPROFIT" \
            and applicant["pnp_service_type"] == "ESSENTIAL_NON_CRITICAL" \
            and applicant["pnp_sba_referral_completed"] is False:
        fail("ERR_PNP_SBA_REFERRAL_REQUIRED",
             "an SBA disaster-loan referral must be completed first")

    setf(applicant, "eligibility_status", decision)
    setf(applicant, "eligibility_rationale", rationale)

    facilities = facilities_of_applicant(applicant["id"])
    uninsured_flood = False
    for facility in facilities:
        if facility["flood_zone"] is not True:
            continue
        has_flood_policy = any(p["policy_type"] == "FLOOD"
                               for p in policies_of_facility(facility["id"]))
        if not has_flood_policy:
            uninsured_flood = True
            break
    score = risk_score_screening(applicant, len(facilities), uninsured_flood)
    setf(applicant, "risk_score_screening", float(score))
    refresh_risk_tier(applicant)
    touch(applicant)
    return respond(applicant)


@bp.route(PREFIX + "/applicants/<applicant_id>/reporting-sweep", methods=["POST"])
def reporting_sweep(applicant_id):
    authenticate(("PlatformAdmin",))
    applicant = require("applicants", applicant_id)

    clock = now()
    for report in reports_of_applicant(applicant["id"]):
        if report["status"] != "DUE":
            continue
        due = dt_of(report, "due_at")
        if due is not None and clock > due:
            setf(report, "status", "DELINQUENT")
            touch(report)

    cascade_applicant(applicant)
    rescore_monitoring(applicant)
    cascade_applicant(applicant)
    touch(applicant)
    return respond(applicant)
