"""Liability protections, the inquiry dimension and continuing obligations."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import actor_id, endpoint
from routes.common import apply_filter, fetch, require_owner
from services import calc, derive
from services.constants import (
    AAI_LOOKBACK_DAYS,
    AT_RISK_GRACE_DAYS,
    OBLIGATION_CATEGORIES,
    OBLIGATION_STATUS,
)
from services.serialize import dump_obligation, dump_protection

bp = Blueprint("protections", __name__)

READ_ROLES = ["Redeveloper", "EnvironmentalConsultant", "StateAgencyReviewer",
              "Insurer", "Lender"]
OBLIGATION_READ_ROLES = ["Redeveloper", "EnvironmentalConsultant",
                         "StateAgencyReviewer", "Lender"]


def _reference_date(site):
    if site["acquisition_status"] == "ACQUIRED" and site.get("acquisition_date"):
        return db.parse_date(site["acquisition_date"])
    return db.parse_date(site["planned_acquisition_date"])


@bp.post("/liability-protections")
@endpoint(["Redeveloper"])
def create_protection():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    site = fetch("sites", site_id)
    require_owner(site)
    if derive.protection_for_site(site["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_LIABILITY_PROTECTION",
                       "Parcel %s already has a liability protection record."
                       % site["id"])
    derive.assert_not_frozen(site)
    row = db.insert("liability_protections", {
        "site_id": site["id"],
        "inquiry_state": "AAI_PENDING",
        "obligation_state": "OBLIGATIONS_NONE",
        "bfpp_status": "NOT_ESTABLISHED",
        "aai_phase_id": None,
        "aai_report_date": None,
        "aai_expires_on": None,
        "obligations_total_weight": 0,
        "current_weight": 0,
        "satisfied_weight": 0,
        "at_risk_weight": 0,
        "lapsed_weight": 0,
        "compliance_pct": float(calc.D("1.0")),
    })
    return response.created(dump_protection(row))


@bp.get("/liability-protections/<protection_id>")
@endpoint(READ_ROLES)
def get_protection(protection_id):
    return response.object_response(
        dump_protection(fetch("liability_protections", protection_id)))


@bp.post("/liability-protections/<protection_id>/inquiry-completion")
@endpoint(["EnvironmentalConsultant"])
def inquiry_completion(protection_id):
    body = V.json_body()
    aai_phase_id = V.id_field(body, "aai_phase_id", True)

    protection = fetch("liability_protections", protection_id)
    phase = fetch("assessment_phases", aai_phase_id)
    site = db.get("sites", protection["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if protection["inquiry_state"] == "AAI_DEFICIENT":
        raise ApiError("ERR_INQUIRY_DEFICIENT",
                       "The inquiry record is deficient and cannot be cured.")
    if protection["inquiry_state"] not in ("AAI_PENDING", "AAI_STALE"):
        raise ApiError("ERR_INQUIRY_DEFICIENT",
                       "The inquiry dimension is already complete.")
    if (phase["site_id"] != protection["site_id"]
            or phase["phase_type"] != "PHASE_I"
            or phase["status"] != "APPROVED"):
        raise ApiError("ERR_PHASE_I_NOT_APPROVED",
                       "The nominated phase must be an APPROVED PHASE_I on this "
                       "parcel.")
    report_date = db.parse_date(phase["aai_report_date"]) \
        if phase.get("aai_report_date") else None
    if report_date is None:
        raise ApiError("ERR_PHASE_I_NOT_APPROVED",
                       "The nominated phase carries no aai_report_date.")
    reference = _reference_date(site) if site is not None else report_date
    if report_date > reference:
        raise ApiError("ERR_AAI_AFTER_ACQUISITION",
                       "The inquiry report post-dates the acquisition reference "
                       "date.")
    if db.days_between(reference, report_date) > AAI_LOOKBACK_DAYS:
        raise ApiError("ERR_AAI_REPORT_STALE",
                       "The inquiry report is older than %d days."
                       % AAI_LOOKBACK_DAYS)

    protection["inquiry_state"] = "AAI_COMPLETE"
    protection["aai_phase_id"] = phase["id"]
    protection["aai_report_date"] = report_date.isoformat()
    protection["aai_expires_on"] = derive.aai_expiry(report_date).isoformat()
    derive.recompute_protection(protection, site)
    db.touch(protection)
    return response.object_response(dump_protection(protection))


# --------------------------------------------------------- continuing duties


@bp.post("/liability-protections/<protection_id>/continuing-obligations")
@endpoint(["StateAgencyReviewer"])
def impose_obligation(protection_id):
    body = V.json_body()
    category = V.enum_field(body, "obligation_category", OBLIGATION_CATEGORIES, True)
    description = V.string_field(body, "description", True, 1, 400)
    due_date = V.date_field(body, "due_date", True)
    recurrence_days = V.int_field(body, "recurrence_days", True, minimum=30)

    protection = fetch("liability_protections", protection_id)
    site = db.get("sites", protection["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)

    row = db.insert("continuing_obligations", {
        "liability_protection_id": protection["id"],
        "obligation_category": category,
        "description": description,
        "due_date": due_date.isoformat(),
        "recurrence_days": recurrence_days,
        "imposed_by_user_id": actor_id(),
        "status": "CURRENT",
        "certified_at": None,
        "certification_count": 0,
        "prior_due_date": None,
    })
    derive.recompute_protection(protection, site)
    db.touch(protection)
    return response.created(dump_obligation(row))


@bp.get("/liability-protections/<protection_id>/continuing-obligations")
@endpoint(OBLIGATION_READ_ROLES)
def list_obligations(protection_id):
    protection = fetch("liability_protections", protection_id)
    rows = derive.obligations_of(protection["id"])
    rows = apply_filter(rows, "status", V.query_enum("status", OBLIGATION_STATUS))
    rows = apply_filter(rows, "obligation_category",
                        V.query_enum("obligation_category", OBLIGATION_CATEGORIES))
    return response.list_response(rows, dump_obligation)


@bp.get("/continuing-obligations/<obligation_id>")
@endpoint(OBLIGATION_READ_ROLES)
def get_obligation(obligation_id):
    return response.object_response(
        dump_obligation(fetch("continuing_obligations", obligation_id)))


def _protection_and_site(obligation):
    protection = db.get("liability_protections",
                        obligation["liability_protection_id"])
    site = db.get("sites", protection["site_id"]) if protection else None
    return protection, site


@bp.post("/continuing-obligations/<obligation_id>/certify")
@endpoint(["Redeveloper"])
def certify_obligation(obligation_id):
    obligation = fetch("continuing_obligations", obligation_id)
    protection, site = _protection_and_site(obligation)
    if site is not None:
        require_owner(site)
        derive.assert_not_frozen(site)
    if obligation["status"] not in ("CURRENT", "AT_RISK"):
        raise ApiError("ERR_INVALID_OBLIGATION_STATE",
                       "Only a CURRENT or AT_RISK duty may be certified.")
    due = db.parse_date(obligation["due_date"])
    if db.today() > due:
        raise ApiError("ERR_CERTIFICATION_WINDOW_CLOSED",
                       "The certification period closed on %s." % due.isoformat())

    obligation["prior_due_date"] = obligation["due_date"]
    obligation["due_date"] = db.add_days(
        due, int(obligation["recurrence_days"])).isoformat()
    obligation["certified_at"] = db.now_ts()
    obligation["certification_count"] = int(obligation["certification_count"]) + 1
    obligation["status"] = "SATISFIED"
    db.touch(obligation)
    if protection is not None:
        derive.recompute_protection(protection, site)
        db.touch(protection)
    return response.object_response(dump_obligation(obligation))


@bp.post("/continuing-obligations/<obligation_id>/void-certification")
@endpoint(["StateAgencyReviewer"])
def void_certification(obligation_id):
    body = V.json_body()
    V.string_field(body, "void_reason", True, 1, 400)

    obligation = fetch("continuing_obligations", obligation_id)
    protection, site = _protection_and_site(obligation)
    if actor_id() == obligation["imposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The reviewer who imposed the duty may not void its "
                       "certification.")
    if int(obligation["certification_count"]) < 1:
        raise ApiError("ERR_INVALID_OBLIGATION_STATE",
                       "The duty carries no accepted certification to void.")

    prior = obligation.get("prior_due_date")
    if prior is not None:
        obligation["due_date"] = prior
    obligation["prior_due_date"] = None
    obligation["certified_at"] = None
    obligation["certification_count"] = int(obligation["certification_count"]) - 1

    restored = db.parse_date(obligation["due_date"])
    remaining = (restored - db.today()).days
    obligation["status"] = "CURRENT" if remaining > AT_RISK_GRACE_DAYS else "AT_RISK"
    db.touch(obligation)
    if protection is not None:
        derive.recompute_protection(protection, site)
        db.touch(protection)
    return response.object_response(dump_obligation(obligation))
