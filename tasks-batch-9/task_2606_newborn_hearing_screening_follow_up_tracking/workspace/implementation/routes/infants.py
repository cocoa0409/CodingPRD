"""Infant registry, discharge, contact preferences, timeliness and risk registry."""
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
from middleware import (ALL_ROLES, AUDIOLOGIST, EI_COORDINATOR, FACILITY_ADMIN,
                        FACILITY_SCREENER, NAVIGATOR, PROGRAM_ADMIN,
                        PROGRAM_AUDITOR, endpoint, identity)

bp = Blueprint("infants", __name__)


def _check_instant(infant, instant):
    if instant < infant["birth_datetime"] or instant > db.now():
        raise ApiError("ERR_TIMESTAMP_OUT_OF_RANGE")


@bp.post("/infants")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, FACILITY_SCREENER])
def create_infant():
    body = validate.body()
    birth_facility_id = validate.id_field(body, "birth_facility_id")
    birth_datetime = validate.datetime_field(body, "birth_datetime")
    birth_setting = validate.enum_field(body, "birth_setting",
                                        validate.BIRTH_SETTINGS)
    gestational_age_weeks = validate.int_field(body, "gestational_age_weeks",
                                               minimum=22, maximum=44)
    nicu_stay_days = validate.int_field(body, "nicu_stay_days", required=False,
                                        minimum=0, maximum=365, default=0)
    preferred_language = validate.enum_field(body, "preferred_language",
                                             validate.LANGUAGES, required=False,
                                             default="EN")
    interpreter_required = validate.bool_field(body, "interpreter_required",
                                               required=False, default=False)
    guardian_name = validate.string_field(body, "guardian_name", min_len=1,
                                          max_len=120)
    guardian_contact_phone = validate.string_field(body, "guardian_contact_phone",
                                                   min_len=7, max_len=20)
    guardian_consent_status = validate.enum_field(body, "guardian_consent_status",
                                                  validate.CONSENT_STATUSES,
                                                  required=False,
                                                  default="GRANTED")
    linked = resolve.fks({"birth_facility_id": birth_facility_id})
    facility = linked["birth_facility_id"]
    identity(facility_id=facility["id"])
    if facility["facility_type"] == "EI_PROGRAM":
        raise ApiError("ERR_FACILITY_TYPE_MISMATCH")
    if birth_datetime > db.now():
        raise ApiError("ERR_BIRTH_DATETIME_IN_FUTURE")

    row = db.base_row()
    row.update({
        "birth_facility_id": facility["id"],
        "birth_datetime": birth_datetime,
        "birth_setting": birth_setting,
        "gestational_age_weeks": gestational_age_weeks,
        "nicu_stay_days": nicu_stay_days,
        "preferred_language": preferred_language,
        "interpreter_required": interpreter_required,
        "guardian_name": guardian_name,
        "guardian_contact_phone": guardian_contact_phone,
        "guardian_consent_status": guardian_consent_status,
        "discharge_datetime": None,
        "discharged_unscreened": False,
        "screening_status": "NOT_SCREENED",
        "intervention_status": "NOT_APPLICABLE",
        "ltf_risk_score": 0,
        "priority_band": "LOW",
        "reengagement_count": 0,
    })
    store.infants[row["id"]] = row

    if nicu_stay_days >= 5:
        services.create_risk_entry(row, "NICU_5_PLUS_DAYS",
                                   row["birth_datetime"], "REGISTRY_AUTO")
    if birth_setting in ("OUT_OF_HOSPITAL", "HOME_BIRTH"):
        services.create_episode(row, "INITIAL_SCREEN")
    services.recompute_risk(row)
    return response.single(row, serialize.infant, 201)


@bp.post("/infants/<infant_id>/discharge")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, FACILITY_SCREENER])
def discharge_infant(infant_id):
    body = validate.body()
    discharge_datetime = validate.datetime_field(body, "discharge_datetime")
    infant = resolve.one("infant", infant_id)
    identity(facility_id=infant["birth_facility_id"])
    if infant["discharge_datetime"] is not None:
        raise ApiError("ERR_INFANT_ALREADY_DISCHARGED")
    _check_instant(infant, discharge_datetime)

    infant["discharge_datetime"] = discharge_datetime
    if infant["screening_status"] == "NOT_SCREENED":
        infant["discharged_unscreened"] = True
        if not calc.open_episodes(infant["id"]):
            services.create_episode(infant, "INITIAL_SCREEN")
    db.touch(infant)
    services.recompute_risk(infant)
    return response.single(infant, serialize.infant)


@bp.patch("/infants/<infant_id>/contact-preferences")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, NAVIGATOR])
def update_contact_preferences(infant_id):
    body = validate.body()
    preferred_language = validate.enum_field(body, "preferred_language",
                                             validate.LANGUAGES, required=False)
    interpreter_required = validate.bool_field(body, "interpreter_required",
                                               required=False)
    guardian_contact_phone = validate.string_field(body, "guardian_contact_phone",
                                                   required=False, min_len=7,
                                                   max_len=20)
    guardian_consent_status = validate.enum_field(body, "guardian_consent_status",
                                                  validate.CONSENT_STATUSES,
                                                  required=False)
    infant = resolve.one("infant", infant_id)
    identity(facility_id=infant["birth_facility_id"])
    if preferred_language is not None:
        infant["preferred_language"] = preferred_language
    if interpreter_required is not None:
        infant["interpreter_required"] = interpreter_required
    if guardian_contact_phone is not None:
        infant["guardian_contact_phone"] = guardian_contact_phone
    if guardian_consent_status is not None:
        infant["guardian_consent_status"] = guardian_consent_status
    db.touch(infant)
    services.recompute_risk(infant)
    return response.single(infant, serialize.infant)


@bp.get("/infants/<infant_id>")
@endpoint(ALL_ROLES)
def get_infant(infant_id):
    infant = resolve.one("infant", infant_id)
    identity()
    return response.single(infant, serialize.infant)


@bp.get("/infants")
@endpoint(ALL_ROLES)
def list_infants():
    limit, offset = response.pagination()
    identity()
    rows = list(store.infants.values())
    for field in ("birth_facility_id", "screening_status", "intervention_status",
                  "priority_band", "birth_setting"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return response.listing(db.sort_rows(rows), serialize.infant, limit, offset)


@bp.get("/infants/<infant_id>/timeliness")
@endpoint([PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN, AUDIOLOGIST, NAVIGATOR,
           EI_COORDINATOR])
def infant_timeliness(infant_id):
    infant = resolve.one("infant", infant_id)
    identity()
    parts = calc.age_parts(infant, db.now())

    # PRD 2.6: "The reference instant is the logical clock for a live read, and the
    # milestone's own instant for a stored status."  The panel is a live read, so a
    # milestone that has not yet been completed is classified per 2.7 at the logical
    # clock; a completed milestone keeps the status stored at its own instant.
    screening_episodes = [e for e in calc.infant_episodes(infant["id"])
                          if e["episode_type"] in ("INITIAL_SCREEN", "RESCREEN")]
    screening_episode = db.latest(screening_episodes)
    if (screening_episode is not None
            and screening_episode["status"] not in calc.OPEN_EPISODE_STATUSES):
        screening_status = screening_episode["timeliness_status"]
    else:
        screening_status = calc.timeliness(parts["effective_age_days"],
                                          calc.SCREENING_BENCHMARK_DAYS, False)

    evaluations = [e for e in store.evaluations.values()
                   if e["infant_id"] == infant["id"]]
    evaluation = db.latest(evaluations)
    finalized = evaluation is not None and evaluation["status"] in (
        "FINALIZED_LOSS", "FINALIZED_NO_LOSS")
    if finalized:
        diagnostic_status = evaluation["timeliness_status"]
        diagnostic_chronological = evaluation["timeliness_status_chronological_basis"]
    else:
        diagnostic_status = calc.timeliness(parts["effective_age_days"],
                                            calc.DIAGNOSTIC_BENCHMARK_DAYS, False)
        diagnostic_chronological = calc.timeliness(
            parts["chronological_age_days"], calc.DIAGNOSTIC_BENCHMARK_DAYS, False)

    referrals = [r for r in store.referrals.values()
                 if r["infant_id"] == infant["id"]]
    referral = db.latest(referrals)
    if referral is not None and referral["status"] == "ENROLLED":
        ei_status = referral["ei_timeliness_status"]
    else:
        ei_status = calc.timeliness(parts["effective_age_days"],
                                    calc.EI_BENCHMARK_DAYS, False)

    data = {
        "infant_id": infant["id"],
        "chronological_age_days": parts["chronological_age_days"],
        "corrected_age_days": parts["corrected_age_days"],
        "effective_age_days": parts["effective_age_days"],
        "prematurity_offset_days": parts["prematurity_offset_days"],
        "benchmark_age_basis": parts["benchmark_age_basis"],
        "screening_timeliness_status": screening_status,
        "diagnostic_timeliness_status": diagnostic_status,
        "diagnostic_timeliness_status_chronological_basis": diagnostic_chronological,
        "ei_timeliness_status": ei_status,
        "ltf_risk_score": infant["ltf_risk_score"],
        "priority_band": infant["priority_band"],
    }
    return response.payload(data)


@bp.get("/infants/<infant_id>/risk-factor-entries")
@endpoint([PROGRAM_ADMIN, PROGRAM_AUDITOR, FACILITY_ADMIN, AUDIOLOGIST, NAVIGATOR])
def list_infant_risk_entries(infant_id):
    limit, offset = response.pagination()
    infant = resolve.one("infant", infant_id)
    identity()
    rows = calc.infant_risk_entries(infant["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return response.listing(db.sort_rows(rows), serialize.risk_entry, limit, offset)


@bp.post("/risk-factor-entries")
@endpoint([PROGRAM_ADMIN, FACILITY_ADMIN, FACILITY_SCREENER, AUDIOLOGIST])
def create_risk_factor_entry():
    body = validate.body()
    infant_id = validate.id_field(body, "infant_id")
    code = validate.enum_field(body, "risk_factor_code",
                               validate.RISK_FACTOR_CODES)
    identified_at = validate.datetime_field(body, "identified_at")
    source = validate.enum_field(body, "source", validate.RISK_SOURCES,
                                 required=False, default="BIRTH_FACILITY")
    linked = resolve.fks({"infant_id": infant_id})
    infant = linked["infant_id"]
    identity(facility_id=infant["birth_facility_id"])
    _check_instant(infant, identified_at)
    row = services.create_risk_entry(infant, code, identified_at, source)
    services.recompute_risk(infant)
    return response.single(row, serialize.risk_entry, 201)
