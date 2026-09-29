"""Preadmission screening lifecycle (PRD §3.2)."""

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import by_seq, require, stamp_new, touch
from util import Body, iso, serialize

bp = Blueprint("screenings", __name__)

SCREENING_STATUSES = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "PHYSICIAN_CONCURRED",
                      "ON_HOLD", "EXPIRED")
DOCUMENTATION_FLAGS = ("intensive_therapy_documented", "expected_functional_improvement_documented",
                       "prior_functional_level_documented", "medical_supervision_documented")


@bp.post("/screenings")
def create_screening():
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))

    patient_id = body.id_field("patient_id")
    conducted_by = body.id_field("conducted_by_clinician_id")
    expected_admission_at = body.dt_field("expected_admission_at")
    flags = {name: body.bool_field(name) for name in DOCUMENTATION_FLAGS}

    # ladder rank 10 — body identifier existence
    patient = require(store.patients, patient_id)
    screener = require(store.clinicians, conducted_by)

    # ladder rank 13 — facility boundary
    if screener["facility_id"] != patient["facility_id"]:
        raise ApiError("ERR_CROSS_FACILITY_MISMATCH")

    # ladder rank 25 — screener credential
    if screener["credential"] not in ("NURSE", "REHAB_PHYSICIAN"):
        raise ApiError("ERR_SCREENER_CREDENTIAL_INVALID")

    screening = stamp_new({
        "patient_id": patient_id,
        "conducted_by_clinician_id": conducted_by,
        "reviewed_by_clinician_id": None,
        "conducted_at": iso(store.clock),
        "expected_admission_at": iso(expected_admission_at),
        "intensive_therapy_documented": flags["intensive_therapy_documented"],
        "expected_functional_improvement_documented": flags["expected_functional_improvement_documented"],
        "prior_functional_level_documented": flags["prior_functional_level_documented"],
        "medical_supervision_documented": flags["medical_supervision_documented"],
        "reviewed_at": None,
        "reviewer_note": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    store.screenings[screening["id"]] = screening
    return envelope(serialize(screening), 201)


@bp.get("/screenings/<screening_id>")
def get_screening(screening_id):
    authenticate(ALL_ROLES)
    screening = require(store.screenings, screening_id)
    return envelope(serialize(screening), 200)


@bp.get("/screenings")
def list_screenings():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "patient_id": str_arg("patient_id"),
        "conducted_by_clinician_id": str_arg("conducted_by_clinician_id"),
        "reviewed_by_clinician_id": str_arg("reviewed_by_clinician_id"),
        "status": enum_arg("status", SCREENING_STATUSES),
    }
    items = [s for s in by_seq(list(store.screenings.values())) if matches(s, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(s) for s in page], 200, pagination)


@bp.patch("/screenings/<screening_id>")
def revise_screening(screening_id):
    authenticate(("NurseCaseManager",))
    body = Body(request.get_json(silent=True))

    expected_admission_at = body.dt_field("expected_admission_at", required=False)
    updates = {}
    for name in DOCUMENTATION_FLAGS:
        if body.present(name):
            updates[name] = body.bool_field(name)

    screening = require(store.screenings, screening_id)

    # ladder rank 16 — PATCH is declared from DRAFT (field edit) and from
    # CHANGES_REQUESTED (returns to DRAFT).
    if screening["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")

    if expected_admission_at is not None:
        screening["expected_admission_at"] = iso(expected_admission_at)
    screening.update(updates)

    if screening["status"] == "CHANGES_REQUESTED":
        screening["status"] = "DRAFT"
        screening["revision_count"] = screening["revision_count"] + 1
        screening["reviewed_by_clinician_id"] = None
        screening["reviewed_at"] = None

    touch(screening)
    return envelope(serialize(screening), 200)


@bp.post("/screenings/<screening_id>/submit")
def submit_screening(screening_id):
    authenticate(("NurseCaseManager",))
    screening = require(store.screenings, screening_id)

    # ladder rank 16 — declared transition DRAFT -> SUBMITTED
    if screening["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    # ladder rank 24 — documentation completeness
    if not all(screening[name] for name in DOCUMENTATION_FLAGS):
        raise ApiError("ERR_SCREENING_DOCUMENTATION_INCOMPLETE")

    # the named screener must still be ACTIVE (PRD §3.2)
    screener = store.clinicians.get(screening["conducted_by_clinician_id"])
    if screener is None or screener["status"] != "ACTIVE":
        raise ApiError("ERR_ACTING_CLINICIAN_INACTIVE")

    screening["status"] = "SUBMITTED"
    touch(screening)
    return envelope(serialize(screening), 200)


@bp.post("/screenings/<screening_id>/review")
def review_screening(screening_id):
    user_id, _ = authenticate(("RehabPhysician",))
    body = Body(request.get_json(silent=True))

    decision = body.enum_field("decision", ("CONCUR", "REQUEST_CHANGES"))
    reviewer_note = body.str_field("reviewer_note", required=False, min_len=0)

    screening = require(store.screenings, screening_id)

    # ladder rank 14 — segregation of duties
    if user_id == screening["conducted_by_clinician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # ladder rank 16 — both review branches are declared only from SUBMITTED
    if screening["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")

    screening["reviewed_by_clinician_id"] = user_id
    screening["reviewed_at"] = iso(store.clock)
    if decision == "CONCUR":
        screening["status"] = "PHYSICIAN_CONCURRED"
    else:
        screening["status"] = "CHANGES_REQUESTED"
        screening["reviewer_note"] = reviewer_note
    touch(screening)
    return envelope(serialize(screening), 200)
