"""Patients and their income / family-size verifications."""

from flask import Blueprint, request

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, segregation, state
from services import cascade
from services import charge
from services import fee_schedule as fs
from services import health_center as hc_svc
from validation import Field, add_days, pagination, parse_body

bp = Blueprint("patients", __name__)

MAX_VERIFICATION_RESUBMIT_ROUNDS = 3

VERIFICATION_WINDOW_DAYS = 365

PATIENT_FIELDS = [
    Field("mrn", "string", required=True),
    Field("full_name", "string", required=True),
    Field("household_size", "integer", required=True, minimum=1),
]

DOCUMENTATION_TYPES = ("TAX_RETURN", "PAY_STUBS", "W2", "SELF_DECLARATION", "REFUSED")

VERIFICATION_FIELDS = [
    Field("patient_id", "string"),
    Field("declared_annual_income_cents", "integer", required=True, minimum=0),
    Field("household_size", "integer", required=True, minimum=1),
    Field("documentation_type", "enum", required=True, enum=DOCUMENTATION_TYPES),
    Field("effective_date", "datetime", required=True),
    Field("expected_patient_version", "integer", required=True),
]

RESUBMIT_FIELDS = [
    Field("documentation_type", "enum", required=True, enum=DOCUMENTATION_TYPES),
    Field("declared_annual_income_cents", "integer", minimum=0),
    Field("household_size", "integer", minimum=1),
]


# --------------------------------------------------------------------------- #
# patients
# --------------------------------------------------------------------------- #


@bp.post("/patients")
def create_patient():
    authorize("PatientServicesRep")
    body = parse_body(PATIENT_FIELDS)

    for row in db.db.patients.values():
        if row["mrn"] == body["mrn"]:
            raise ApiError("ERR_DUPLICATE_KEY")

    row = db.base_row()
    row.update(
        {
            "mrn": body["mrn"],
            "full_name": body["full_name"],
            "household_size": body["household_size"],
        }
    )
    db.db.patients[row["id"]] = row
    return object_response(serializers.patient(row), 201)


@bp.get("/patients/<patient_id>")
def read_patient(patient_id):
    authorize(*ALL_ROLES)
    return object_response(serializers.patient(require("patients", patient_id)))


@bp.get("/patients")
def list_patients():
    authorize(*ALL_ROLES)
    limit, offset = pagination()

    wanted_status = request.args.get("sliding_fee_status")

    def predicate(row):
        if wanted_status is not None and hc_svc.sliding_fee_status(row["id"]) != wanted_status:
            return False
        return True

    return listing(
        db.all_rows("patients"),
        serializers.patient,
        limit,
        offset,
        specs=[("mrn", "mrn", "string")],
        predicate=predicate,
    )


# --------------------------------------------------------------------------- #
# income verifications
# --------------------------------------------------------------------------- #


@bp.post("/patients/<patient_id>/income-verifications")
def create_verification(patient_id):
    user_id = authorize("PatientServicesRep")
    body = parse_body(VERIFICATION_FIELDS)
    patient = require("patients", patient_id)
    owner_ref(body, "patient_id", "patients", patient_id)

    # Rung 10 — OCC on the patient.
    if body["expected_patient_version"] != patient["version"]:
        raise ApiError("ERR_STALE_PATIENT_VERSION")

    effective_date = body["effective_date"]
    row = db.base_row()
    row.update(
        {
            "patient_id": patient_id,
            "declared_annual_income_cents": body["declared_annual_income_cents"],
            "household_size": body["household_size"],
            "documentation_type": body["documentation_type"],
            "effective_date": effective_date,
            "expires_at": add_days(effective_date, VERIFICATION_WINDOW_DAYS),
            "status": "SUBMITTED",
            "resubmit_round": 0,
            "submitted_by_user_id": user_id,
            "verified_by_user_id": None,
            "insufficiency_reason": None,
            "guideline_year_used": None,
            "fpg_percent": None,
            "uds_guideline_year_used": None,
            "uds_fpg_percent": None,
            "assigned_discount_tier_id": None,
            "assigned_tier_label": None,
            "supersedes_income_verification_id": None,
        }
    )
    db.db.income_verifications[row["id"]] = row

    db.touch(patient)
    return object_response(serializers.income_verification(row), 201)


@bp.get("/income-verifications/<verification_id>")
def read_verification(verification_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.income_verification(require("income_verifications", verification_id))
    )


@bp.get("/income-verifications")
def list_verifications():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    return listing(
        db.all_rows("income_verifications"),
        serializers.income_verification,
        limit,
        offset,
        specs=[
            ("patient_id", "patient_id", "string"),
            ("assigned_discount_tier_id", "assigned_discount_tier_id", "string"),
            (
                "supersedes_income_verification_id",
                "supersedes_income_verification_id",
                "string",
            ),
            ("status", "status", "string"),
        ],
    )


@bp.post("/income-verifications/<verification_id>/verify")
def verify_verification(verification_id):
    user_id = authorize("EligibilityVerifier")
    body = parse_body(
        [
            Field("decision", "enum", required=True, enum=("VERIFY", "MARK_INSUFFICIENT")),
            Field("insufficiency_reason", "string", nullable=True),
        ]
    )
    verification = require("income_verifications", verification_id)

    state(verification, "status", ("SUBMITTED",))
    segregation(user_id, verification["submitted_by_user_id"])

    if body["decision"] == "MARK_INSUFFICIENT":
        verification["status"] = "INSUFFICIENT_DOCUMENTATION"
        verification["insufficiency_reason"] = body.get("insufficiency_reason")
        verification["verified_by_user_id"] = user_id
        db.touch(verification)
        return object_response(serializers.income_verification(verification))

    # Rung 16 — a refusal to document can never be VERIFIED.
    if verification["documentation_type"] == "REFUSED":
        raise ApiError("ERR_DOCUMENTATION_REFUSED")

    effective_date = verification["effective_date"]

    # Rung 36 — the schedule-year variant needs an adopted schedule.
    schedule = fs.select_schedule_for_patient(verification["patient_id"], effective_date)
    if schedule is None:
        raise ApiError("ERR_NO_EFFECTIVE_FEE_SCHEDULE")

    # Rung 37 — both guideline years must be published.
    schedule_year = schedule["fpg_year"]
    intake_year = effective_date.year
    schedule_guideline = fs.guideline_for_year(schedule_year)
    intake_guideline = fs.guideline_for_year(intake_year)
    if schedule_guideline is None or intake_guideline is None:
        raise ApiError("ERR_POVERTY_GUIDELINE_MISSING")

    household = verification["household_size"]
    income = verification["declared_annual_income_cents"]

    verification["status"] = "VERIFIED"
    verification["verified_by_user_id"] = user_id
    verification["guideline_year_used"] = schedule_year
    verification["fpg_percent"] = charge.fpg_percent(income, household, schedule_guideline)
    verification["uds_guideline_year_used"] = intake_year
    verification["uds_fpg_percent"] = charge.fpg_percent(income, household, intake_guideline)

    tier = fs.select_tier(schedule["id"], verification["fpg_percent"])
    verification["assigned_discount_tier_id"] = tier["id"] if tier else None
    verification["assigned_tier_label"] = tier["tier_label"] if tier else None
    db.touch(verification)

    # Hops 1, 2 and 4 of the depth-5 cascade.
    affected = cascade.verify_cascade(verification)

    # Hop 3 — the patient ledger is derived, so the version increment records it.
    patient = db.db.patients.get(verification["patient_id"])
    if patient is not None:
        db.touch(patient)

    # Hop 5 — the grantees of the recomputed encounters.
    grantee_ids = []
    for enc in affected:
        hc = hc_svc.health_center_of_encounter(enc)
        if hc is not None and hc["id"] not in grantee_ids:
            grantee_ids.append(hc["id"])
    for hc_id in grantee_ids:
        hc_svc.bump(db.db.health_centers[hc_id])

    return object_response(serializers.income_verification(verification))


@bp.post("/income-verifications/<verification_id>/resubmit")
def resubmit_verification(verification_id):
    user_id = authorize("PatientServicesRep")
    body = parse_body(RESUBMIT_FIELDS)
    verification = require("income_verifications", verification_id)

    state(verification, "status", ("INSUFFICIENT_DOCUMENTATION",))
    if verification["resubmit_round"] >= MAX_VERIFICATION_RESUBMIT_ROUNDS:
        raise ApiError("ERR_LOOP_LIMIT_EXCEEDED")

    verification["resubmit_round"] += 1
    verification["documentation_type"] = body["documentation_type"]
    if "declared_annual_income_cents" in body:
        verification["declared_annual_income_cents"] = body["declared_annual_income_cents"]
    if "household_size" in body:
        verification["household_size"] = body["household_size"]
    verification["status"] = "SUBMITTED"
    verification["insufficiency_reason"] = None
    verification["verified_by_user_id"] = None
    verification["submitted_by_user_id"] = user_id
    db.touch(verification)
    return object_response(serializers.income_verification(verification))
