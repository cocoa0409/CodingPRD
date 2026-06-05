"""PlanOfCare routes (scaffold §1.5 — Plans of Care; PRD §3.2 / §3.6)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RECERT_WINDOW_EXCEEDED,
    ERR_STALE_PLAN_VERSION,
    ERR_THERAPIST_LICENSE_INVALID,
    ERR_VA_REFERRAL_REQUIRED,
)
from middleware import current_role, current_user_id, get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.cascades import cascade_poc_activate, cascade_poc_discharge
from services.validation import (
    lookup_or_404,
    require_date,
    require_fields,
    require_icd10,
    require_int,
    require_string,
)


bp = Blueprint("plans_of_care", __name__)


PLAN_STATUSES = {"DRAFT", "ACTIVE", "RECERT_DUE", "DISCHARGED", "EXPIRED"}


def _check_therapist_license(therapist: dict, patient: dict) -> None:
    """PRD §3.10 demo licensing policy (priority 420).

    VA_TRICARE accepts any license_state; every other insurance_type requires CA.
    """
    if patient["insurance_type"] == "VA_TRICARE":
        return
    if therapist["license_state"] != "CA":
        raise APIError(
            ERR_THERAPIST_LICENSE_INVALID,
            422,
            f"Therapist.license_state={therapist['license_state']} not valid "
            f"for patient.insurance_type={patient['insurance_type']}",
        )


@bp.post("/rehab/plans-of-care")
def create_plan_of_care():
    require_auth(["Therapist", "CaseManager"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "patient_id",
            "primary_therapist_id",
            "diagnosis_icd10",
            "certified_start_date",
            "certified_end_date",
        ],
    )
    patient_id = require_string(body["patient_id"], "patient_id")
    therapist_id = require_string(body["primary_therapist_id"], "primary_therapist_id")
    icd10 = require_icd10(body["diagnosis_icd10"], "diagnosis_icd10")
    start = require_date(body["certified_start_date"], "certified_start_date")
    end = require_date(body["certified_end_date"], "certified_end_date")
    veteran_referral_id = body.get("veteran_referral_id")
    if veteran_referral_id is not None and not isinstance(veteran_referral_id, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "veteran_referral_id must be a string")

    # FK existence (priority 210)
    patient = lookup_or_404(db.patients, patient_id, "Patient")
    therapist = lookup_or_404(db.therapists, therapist_id, "Therapist")
    if veteran_referral_id:
        lookup_or_404(db.veteran_referrals, veteran_referral_id, "VeteranReferral")

    # Window sanity: end >= start AND end - start <= 90 days.
    if end < start:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "certified_end_date must be on or after certified_start_date",
        )
    if (end - start).days > 90:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "certification window must be at most 90 days",
        )

    # veteran_referral_id presence rules (PRD §3.2): required for VA_TRICARE,
    # forbidden otherwise. This is an input-shape validity check, surfaced as
    # ERR_INVALID_REQUEST (priority 900) rather than VA_REFERRAL_REQUIRED — the
    # safety rule (priority 400) fires only at the activate boundary.
    if patient["insurance_type"] == "VA_TRICARE" and not veteran_referral_id:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "veteran_referral_id required for VA_TRICARE patients",
        )
    if patient["insurance_type"] != "VA_TRICARE" and veteran_referral_id:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "veteran_referral_id must be omitted for non-VA_TRICARE patients",
        )

    # PRD §3.10: licensing demo policy applies on POC create.
    _check_therapist_license(therapist, patient)

    with db.mutation_lock:
        poc = {
            "patient_id": patient_id,
            "primary_therapist_id": therapist_id,
            "initial_evaluation_id": None,
            "veteran_referral_id": veteran_referral_id,
            "diagnosis_icd10": icd10,
            "certified_start_date": start.isoformat(),
            "certified_end_date": end.isoformat(),
            "status": "DRAFT",
            "capped_dollar_limit_cents": None,
            "cumulative_billed_cents": 0,
            "capped_status": "UNDER_CAP",
        }
        db.stamp_common(poc)
        db.plans_of_care[poc["id"]] = poc
        return ok_object(poc, 201)


@bp.get("/rehab/plans-of-care/<pid>")
def get_plan_of_care(pid: str):
    require_auth(
        ["PlatformAdmin", "CaseManager", "Therapist", "BillingClerk", "VAReferralCoordinator"]
    )()
    poc = lookup_or_404(db.plans_of_care, pid, "PlanOfCare")
    return ok_object(poc, 200)


@bp.get("/rehab/plans-of-care")
def list_plans_of_care():
    require_auth(
        ["PlatformAdmin", "CaseManager", "Therapist", "BillingClerk", "VAReferralCoordinator"]
    )()
    limit, offset = paginate_params(request.args)
    items = list(db.plans_of_care.values())
    for key in ("patient_id", "primary_therapist_id", "veteran_referral_id",
                "initial_evaluation_id", "status"):
        if key in request.args:
            val = request.args.get(key)
            items = [p for p in items if p.get(key) == val]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/rehab/plans-of-care/<pid>/activate")
def activate_plan_of_care(pid: str):
    require_auth(["Therapist"])()
    poc = lookup_or_404(db.plans_of_care, pid, "PlanOfCare")

    # State precondition (priority 300): DRAFT only.
    if poc["status"] != "DRAFT":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"PlanOfCare must be DRAFT to activate; current={poc['status']}",
        )
    # An INITIAL Evaluation must exist on this POC.
    has_initial = any(
        e["plan_of_care_id"] == pid and e["evaluation_kind"] == "INITIAL"
        for e in db.evaluations.values()
    )
    if not has_initial:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "Activation requires an INITIAL Evaluation on the PlanOfCare",
        )

    # VA-safety preconditions (priority 400)
    patient = db.patients[poc["patient_id"]]
    if patient["insurance_type"] == "VA_TRICARE":
        referral_id = poc.get("veteran_referral_id")
        if not referral_id:
            raise APIError(
                ERR_VA_REFERRAL_REQUIRED,
                422,
                "VA_TRICARE PlanOfCare requires a linked VeteranReferral",
            )
        referral = db.veteran_referrals.get(referral_id)
        if referral is None or referral["status"] != "ISSUED":
            raise APIError(
                ERR_VA_REFERRAL_REQUIRED,
                422,
                "VeteranReferral must be in ISSUED status at activation",
            )
        # certified_end_date <= referral.expires_on
        ce = db.parse_iso_date(poc["certified_end_date"])
        exp = db.parse_iso_date(referral["expires_on"])
        if ce is not None and exp is not None and ce > exp:
            raise APIError(
                ERR_VA_REFERRAL_REQUIRED,
                422,
                "certified_end_date must be on or before VeteranReferral.expires_on",
            )

    with db.mutation_lock:
        cascade_poc_activate(poc)
        return ok_object(poc, 200)


@bp.post("/rehab/plans-of-care/<pid>/recertify")
def recertify_plan_of_care(pid: str):
    require_auth(["Therapist"])()
    poc = lookup_or_404(db.plans_of_care, pid, "PlanOfCare")

    body = get_json_body()
    require_fields(
        body, ["expected_plan_of_care_version", "certified_start_date", "certified_end_date"]
    )
    expected_version = require_int(
        body["expected_plan_of_care_version"], "expected_plan_of_care_version", min_value=0
    )
    new_start = require_date(body["certified_start_date"], "certified_start_date")
    new_end = require_date(body["certified_end_date"], "certified_end_date")

    # State precondition (priority 300): RECERT_DUE only.
    if poc["status"] != "RECERT_DUE":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"PlanOfCare must be RECERT_DUE to recertify; current={poc['status']}",
        )

    # OCC (priority 305)
    if expected_version != poc["version"]:
        raise APIError(
            ERR_STALE_PLAN_VERSION,
            412,
            "expected_plan_of_care_version does not match current PlanOfCare.version",
        )

    # RE_EVALUATION must exist with performed_on in [old start, old end]
    old_start = db.parse_iso_date(poc["certified_start_date"])
    old_end = db.parse_iso_date(poc["certified_end_date"])
    has_reeval = False
    for e in db.evaluations.values():
        if e["plan_of_care_id"] != pid:
            continue
        if e["evaluation_kind"] != "RE_EVALUATION":
            continue
        perf = db.parse_iso_date(e["performed_on"])
        if perf is not None and old_start is not None and old_end is not None:
            if old_start <= perf <= old_end:
                has_reeval = True
                break
    if not has_reeval:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "A RE_EVALUATION within the current certification window is required to recertify",
        )

    # Business: new_end <= old_end + 90 days (priority 455)
    if old_end is not None:
        if (new_end - old_end).days > 90:
            raise APIError(
                ERR_RECERT_WINDOW_EXCEEDED,
                422,
                "recertify certified_end_date exceeds old certified_end_date + 90 days",
            )

    if new_end < new_start:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "certified_end_date must be on or after certified_start_date",
        )

    with db.mutation_lock:
        poc["status"] = "ACTIVE"
        poc["certified_start_date"] = new_start.isoformat()
        poc["certified_end_date"] = new_end.isoformat()
        db.bump(poc)
        return ok_object(poc, 200)


@bp.post("/rehab/plans-of-care/<pid>/discharge")
def discharge_plan_of_care(pid: str):
    require_auth(["Therapist"])()
    poc = lookup_or_404(db.plans_of_care, pid, "PlanOfCare")

    # State precondition (priority 300): only ACTIVE per scaffold §1.2.
    if poc["status"] != "ACTIVE":
        raise APIError(
            ERR_INVALID_STATE,
            409,
            f"PlanOfCare must be ACTIVE to discharge; current={poc['status']}",
        )

    # A DischargeAssessment must exist for this POC.
    has_assessment = any(
        d["plan_of_care_id"] == pid for d in db.discharge_assessments.values()
    )
    if not has_assessment:
        raise APIError(
            ERR_INVALID_STATE,
            409,
            "Discharging a PlanOfCare requires a DischargeAssessment on file",
        )

    with db.mutation_lock:
        cascade_poc_discharge(poc)
        return ok_object(poc, 200)
