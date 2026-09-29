"""Diagnostic evaluations and early intervention referrals."""
from flask import Blueprint, request

import calc
import db
import resolve
import response
import serialize
import services
import validate
from db import store
from errors import ApiError
from middleware import (AUDIOLOGIST, EI_COORDINATOR, FACILITY_ADMIN, NAVIGATOR,
                        PROGRAM_ADMIN, PROGRAM_AUDITOR, endpoint, identity,
                        role, user_id)

bp = Blueprint("diagnostics", __name__)

READ_ROLES = [PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN, AUDIOLOGIST,
              NAVIGATOR, EI_COORDINATOR]
THRESHOLD_CUTOFF = 25


# --- diagnostic evaluations -------------------------------------------------
@bp.post("/diagnostic-evaluations")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, AUDIOLOGIST])
def create_evaluation():
    body = validate.body()
    infant_id = validate.id_field(body, "infant_id")
    episode_id = validate.id_field(body, "episode_id")
    facility_id = validate.id_field(body, "facility_id")
    performed_by_provider_id = validate.id_field(body, "performed_by_provider_id")
    evaluation_datetime = validate.datetime_field(body, "evaluation_datetime")
    method = validate.enum_field(body, "method", validate.EVALUATION_METHODS)
    linked = resolve.fks({
        "facility_id": facility_id,
        "performed_by_provider_id": performed_by_provider_id,
        "infant_id": infant_id,
        "episode_id": episode_id,
    })
    facility = linked["facility_id"]
    provider = linked["performed_by_provider_id"]
    infant = linked["infant_id"]
    episode = linked["episode_id"]
    identity(facility_id=facility["id"])
    if provider["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if provider["provider_type"] != "AUDIOLOGIST":
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH")
    if episode["infant_id"] != infant["id"]:
        raise ApiError("ERR_LINKAGE_MISMATCH")
    if (evaluation_datetime < infant["birth_datetime"]
            or evaluation_datetime > db.now()):
        raise ApiError("ERR_TIMESTAMP_OUT_OF_RANGE")
    row = db.base_row()
    row.update({
        "infant_id": infant["id"],
        "episode_id": episode["id"],
        "facility_id": facility["id"],
        "performed_by_provider_id": provider["id"],
        "attested_by_provider_id": None,
        "evaluation_datetime": evaluation_datetime,
        "method": method,
        "left_ear_threshold_db": None,
        "right_ear_threshold_db": None,
        "outcome": None,
        "status": "DRAFT",
        "finalized_at": None,
        "age_days_at_finalize": None,
        "timeliness_status": "PENDING",
        "timeliness_status_chronological_basis": "PENDING",
        "attestation_note": None,
    })
    store.evaluations[row["id"]] = row
    return response.single(row, serialize.evaluation, 201)


def _outcome_matches(outcome, left, right):
    above = (1 if left > THRESHOLD_CUTOFF else 0) + (1 if right > THRESHOLD_CUTOFF else 0)
    if outcome == "NO_LOSS":
        return above == 0
    if outcome == "UNILATERAL_LOSS":
        return above == 1
    return above == 2


@bp.post("/diagnostic-evaluations/<evaluation_id>/submit")
@endpoint([AUDIOLOGIST])
def submit_evaluation(evaluation_id):
    body = validate.body()
    left = validate.int_field(body, "left_ear_threshold_db", minimum=0, maximum=120)
    right = validate.int_field(body, "right_ear_threshold_db", minimum=0, maximum=120)
    outcome = validate.enum_field(body, "outcome", validate.EVALUATION_OUTCOMES)
    evaluation = resolve.one("evaluation", evaluation_id)
    identity()
    infant = store.infants.get(evaluation["infant_id"])
    if evaluation["status"] != "DRAFT":
        raise ApiError("ERR_EVALUATION_INVALID_STATE")
    if infant is not None and infant["guardian_consent_status"] == "REFUSED":
        raise ApiError("ERR_GUARDIAN_CONSENT_REFUSED")
    if not _outcome_matches(outcome, left, right):
        raise ApiError("ERR_OUTCOME_THRESHOLD_MISMATCH")
    performer = store.providers.get(evaluation["performed_by_provider_id"])
    if performer is not None and performer["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if infant is not None and infant["screening_status"] not in (
            "REFERRED", "DIAGNOSTIC_IN_PROGRESS"):
        raise ApiError("ERR_INFANT_NOT_REFERRED")
    evaluation["left_ear_threshold_db"] = left
    evaluation["right_ear_threshold_db"] = right
    evaluation["outcome"] = outcome
    evaluation["status"] = "PENDING_ATTESTATION"
    db.touch(evaluation)
    return response.single(evaluation, serialize.evaluation)


@bp.post("/diagnostic-evaluations/<evaluation_id>/attest")
@endpoint([AUDIOLOGIST])
def attest_evaluation(evaluation_id):
    body = validate.body()
    decision = validate.enum_field(body, "decision", validate.ATTEST_DECISIONS)
    note = validate.string_field(body, "note", required=False)
    evaluation = resolve.one("evaluation", evaluation_id)
    attester = identity()
    if evaluation["status"] != "PENDING_ATTESTATION":
        raise ApiError("ERR_EVALUATION_INVALID_STATE")
    if user_id() == evaluation["performed_by_provider_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if attester is not None and attester["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_CREDENTIALED")
    if decision == "ACCEPT":
        evaluation["attested_by_provider_id"] = user_id()
        evaluation["attestation_note"] = note
        evaluation["status"] = "ATTESTED"
    else:
        evaluation["left_ear_threshold_db"] = None
        evaluation["right_ear_threshold_db"] = None
        evaluation["outcome"] = None
        evaluation["attestation_note"] = note
        evaluation["status"] = "DRAFT"
    db.touch(evaluation)
    return response.single(evaluation, serialize.evaluation)


@bp.post("/diagnostic-evaluations/<evaluation_id>/finalize")
@endpoint([AUDIOLOGIST])
def finalize_evaluation(evaluation_id):
    validate.body()
    evaluation = resolve.one("evaluation", evaluation_id)
    identity()
    if evaluation["status"] != "ATTESTED":
        raise ApiError("ERR_EVALUATION_INVALID_STATE")
    facility = store.facilities.get(evaluation["facility_id"])
    if facility is not None and calc.facility_posture(facility) == "SUSPENDED":
        raise ApiError("ERR_FACILITY_SUSPENDED")

    infant = store.infants.get(evaluation["infant_id"])
    episode = store.episodes.get(evaluation["episode_id"])
    finalized_at = db.now()
    parts = calc.age_parts(infant, finalized_at)
    evaluation["finalized_at"] = finalized_at
    evaluation["age_days_at_finalize"] = parts["chronological_age_days"]
    evaluation["timeliness_status"] = calc.timeliness(
        parts["effective_age_days"], calc.DIAGNOSTIC_BENCHMARK_DAYS, True)
    evaluation["timeliness_status_chronological_basis"] = calc.timeliness(
        parts["chronological_age_days"], calc.DIAGNOSTIC_BENCHMARK_DAYS, True)

    loss = evaluation["outcome"] in ("UNILATERAL_LOSS", "BILATERAL_LOSS")
    evaluation["status"] = "FINALIZED_LOSS" if loss else "FINALIZED_NO_LOSS"
    db.touch(evaluation)

    if episode is not None:
        services.close_episode(
            episode,
            "RESOLVED_DIAGNOSED" if loss else "RESOLVED_NO_LOSS",
            "DIAGNOSIS_CONFIRMED" if loss else "DIAGNOSIS_NO_LOSS",
            infant=infant, instant=finalized_at, write_timeliness=True)
    if loss:
        infant["screening_status"] = "DIAGNOSED_LOSS"
        db.touch(infant)
        services.mint_referral(infant, evaluation["id"])
        infant["intervention_status"] = "REFERRED"
        services.mint_cascade_task(infant, "EI_LINKAGE", episode_id=None)
    else:
        infant["screening_status"] = "DIAGNOSED_NO_LOSS"
        db.touch(infant)
    services.recompute_risk(infant)
    return response.single(evaluation, serialize.evaluation)


@bp.get("/diagnostic-evaluations/<evaluation_id>")
@endpoint(READ_ROLES)
def get_evaluation(evaluation_id):
    row = resolve.one("evaluation", evaluation_id)
    identity()
    return response.single(row, serialize.evaluation)


@bp.get("/diagnostic-evaluations")
@endpoint(READ_ROLES)
def list_evaluations():
    limit, offset = response.pagination()
    identity()
    rows = list(store.evaluations.values())
    for field in ("infant_id", "episode_id", "facility_id",
                  "performed_by_provider_id", "attested_by_provider_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.evaluation, limit, offset)


# --- early intervention referrals -------------------------------------------
@bp.post("/ei-referrals/<referral_id>/assign-program")
@endpoint([PROGRAM_ADMIN])
def assign_program(referral_id):
    body = validate.body()
    ei_program_facility_id = validate.id_field(body, "ei_program_facility_id")
    referral = resolve.one("referral", referral_id)
    linked = resolve.fks({"ei_program_facility_id": ei_program_facility_id})
    program = linked["ei_program_facility_id"]
    # Priority 13: assign-program is available only while the program slot is null.
    if referral["ei_program_facility_id"] is not None:
        raise ApiError("ERR_REFERRAL_INVALID_STATE")
    if program["facility_type"] != "EI_PROGRAM":
        raise ApiError("ERR_FACILITY_TYPE_MISMATCH")
    referral["ei_program_facility_id"] = program["id"]
    db.touch(referral)
    return response.single(referral, serialize.referral)


@bp.post("/ei-referrals/<referral_id>/decision")
@endpoint([EI_COORDINATOR, NAVIGATOR])
def referral_decision(referral_id):
    body = validate.body()
    decision = validate.enum_field(body, "decision", validate.REFERRAL_DECISIONS)
    reason = validate.string_field(body, "reason", required=False)
    if role() == NAVIGATOR and decision != "FAMILY_DECLINED":
        raise ApiError("ERR_FORBIDDEN_ROLE")
    referral = resolve.one("referral", referral_id)
    identity(facility_id=referral["ei_program_facility_id"])
    infant = store.infants.get(referral["infant_id"])

    if decision == "ACCEPT":
        if referral["status"] != "PENDING" or referral["ei_program_facility_id"] is None:
            raise ApiError("ERR_REFERRAL_INVALID_STATE")
        referral["status"] = "ACCEPTED"
        referral["accepted_at"] = db.now()
        if reason is not None:
            referral["resolution_reason"] = reason
        db.touch(referral)
    elif decision == "REJECT":
        if referral["status"] != "PENDING":
            raise ApiError("ERR_REFERRAL_INVALID_STATE")
        rejecting = referral["ei_program_facility_id"]
        referral["status"] = "REJECTED_BY_PROGRAM"
        referral["resolution_reason"] = reason
        db.touch(referral)
        infant["intervention_status"] = "REFERRAL_DUE"
        db.touch(infant)
        excluded = set()
        for other in store.referrals.values():
            if (other["diagnostic_evaluation_id"] == referral["diagnostic_evaluation_id"]
                    and other["status"] == "REJECTED_BY_PROGRAM"
                    and other["ei_program_facility_id"]):
                excluded.add(other["ei_program_facility_id"])
        if rejecting:
            excluded.add(rejecting)
        services.mint_referral(infant, referral["diagnostic_evaluation_id"],
                               excluded=excluded)
        infant["intervention_status"] = "REFERRED"
    else:
        if referral["status"] not in ("PENDING", "ACCEPTED"):
            raise ApiError("ERR_REFERRAL_INVALID_STATE")
        referral["status"] = "DECLINED_BY_FAMILY"
        referral["resolution_reason"] = reason
        db.touch(referral)
        infant["intervention_status"] = "DECLINED"
        db.touch(infant)
        for task in db.sort_rows(calc.infant_tasks(infant["id"])):
            if (task["task_type"] == "EI_LINKAGE"
                    and task["status"] in ("UNASSIGNED", "OPEN")):
                task["status"] = "CANCELLED"
                db.touch(task)
        services.recompute_risk(infant)
    return response.single(referral, serialize.referral)


@bp.post("/ei-referrals/<referral_id>/enroll")
@endpoint([EI_COORDINATOR])
def enroll_referral(referral_id):
    body = validate.body()
    ifsp_date = validate.datetime_field(body, "ifsp_date")
    referral = resolve.one("referral", referral_id)
    identity(facility_id=referral["ei_program_facility_id"])
    if referral["status"] != "ACCEPTED":
        raise ApiError("ERR_REFERRAL_INVALID_STATE")
    evaluation = store.evaluations.get(referral["diagnostic_evaluation_id"])
    if evaluation is None or evaluation["status"] != "FINALIZED_LOSS":
        raise ApiError("ERR_EVALUATION_INVALID_STATE")
    if ifsp_date < referral["referred_at"] or ifsp_date > db.now():
        raise ApiError("ERR_TIMESTAMP_OUT_OF_RANGE")
    infant = store.infants.get(referral["infant_id"])
    age = calc.effective_age(infant, ifsp_date)
    referral["status"] = "ENROLLED"
    referral["ifsp_date"] = ifsp_date
    referral["enrollment_age_days"] = age
    referral["ei_timeliness_status"] = calc.timeliness(
        age, calc.EI_BENCHMARK_DAYS, True)
    db.touch(referral)
    infant["intervention_status"] = "ENROLLED"
    db.touch(infant)
    for task in db.sort_rows(calc.infant_tasks(infant["id"])):
        if task["task_type"] == "EI_LINKAGE" and task["status"] == "OPEN":
            task["status"] = "COMPLETED"
            task["outcome"] = "LINKED"
            db.touch(task)
    services.recompute_risk(infant)
    return response.single(referral, serialize.referral)


@bp.get("/ei-referrals/<referral_id>")
@endpoint(READ_ROLES)
def get_referral(referral_id):
    row = resolve.one("referral", referral_id)
    identity()
    return response.single(row, serialize.referral)


@bp.get("/ei-referrals")
@endpoint(READ_ROLES)
def list_referrals():
    limit, offset = response.pagination()
    identity()
    rows = list(store.referrals.values())
    for field in ("infant_id", "diagnostic_evaluation_id", "ei_program_facility_id",
                  "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.referral, limit, offset)
