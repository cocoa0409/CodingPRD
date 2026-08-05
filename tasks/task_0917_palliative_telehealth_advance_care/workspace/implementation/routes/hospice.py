"""Hospice election, certification and benefit periods (PRD 3.10)."""

from flask import Blueprint

import calc
import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_DUPLICATE_CERTIFIER, ERR_FACE_TO_FACE_WINDOW, ERR_IDT_CADENCE_LAPSED,
    ERR_STALE_ELECTION_VERSION, ERR_VALIDATION, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, occ, pagination, paginate,
    path_row, query_filters, raw_body, state, touch, validate,
)
from store import days, ordered, store

bp = Blueprint("hospice", __name__)


@bp.post("/palliative/hospice-elections")
def create_election():
    auth([config.ROLE_PHYSICIAN, config.ROLE_DIRECTOR, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("concurrent_care_carve_out", "boolean", default=False),
    ])
    patient = fk(store.patients, data["patient_id"])
    freeze_gate(patient)
    row = store.new_row({
        "patient_id": patient["id"],
        "concurrent_care_carve_out": bool(data["concurrent_care_carve_out"]),
        "attending_certifier_user_id": None,
        "hospice_director_certifier_user_id": None,
        "certification_count": 0,
        "current_period_number": 0,
        "current_period_start": None,
        "current_period_end": None,
        "cumulative_benefit_days": 0,
        "face_to_face_at": None,
        "revocation_count": 0,
        "status": "PENDING_CERT",
    })
    store.hospice_elections[row["id"]] = row
    return created(row)


@bp.post("/palliative/hospice-elections/<eid>/certifications")
def certify_election(eid):
    ctx = auth([config.ROLE_PHYSICIAN, config.ROLE_DIRECTOR, config.ROLE_ADMIN])
    election = path_row(store.hospice_elections, eid)
    body = raw_body()
    validate(body, [field("terminal_diagnosis_code", "string", required=True)])
    freeze_gate(store.patients.get(election["patient_id"]))
    state(election["status"] == "REVOKED"
          or (election["status"] == "PENDING_CERT"
              and election["certification_count"] < config.HOSPICE_CERTIFIERS_REQUIRED))

    second = (election["status"] == "PENDING_CERT" and election["certification_count"] == 1)
    if second and ctx.user_id == election["attending_certifier_user_id"]:
        raise api_error(ERR_DUPLICATE_CERTIFIER)

    if election["status"] == "REVOKED":
        election["status"] = "PENDING_CERT"
        election["certification_count"] = 1
        election["attending_certifier_user_id"] = ctx.user_id
        election["hospice_director_certifier_user_id"] = None
    elif second:
        election["status"] = "CERTIFIED"
        election["hospice_director_certifier_user_id"] = ctx.user_id
        election["certification_count"] = config.HOSPICE_CERTIFIERS_REQUIRED
    else:
        election["attending_certifier_user_id"] = ctx.user_id
        election["certification_count"] = 1
    touch(election)
    return ok(election)


def _idt_compliant(patient_id):
    last = None
    for conf in cascades.rows_for_patient(store.conferences, patient_id):
        if conf["conference_type"] != "IDT" or conf["status"] != "ATTESTED":
            continue
        if conf["held_at"] is None:
            continue
        if last is None or conf["held_at"] > last:
            last = conf["held_at"]
    if last is None:
        return False
    return calc.idt_days_since(store.now(), last) <= config.IDT_CADENCE_MAX_DAYS


@bp.post("/palliative/hospice-elections/<eid>/periods")
def open_benefit_period(eid):
    auth([config.ROLE_DIRECTOR, config.ROLE_ADMIN])
    election = path_row(store.hospice_elections, eid)
    body = raw_body()
    data = validate(body, [
        field("expected_election_version", "integer", required=True),
        field("period_start", "datetime", required=True),
        field("face_to_face_at", "datetime"),
    ])
    patient = store.patients.get(election["patient_id"])
    freeze_gate(patient)
    state(election["status"] in ("CERTIFIED", "ELECTED"))
    occ(data["expected_election_version"], election["version"], ERR_STALE_ELECTION_VERSION)

    if not _idt_compliant(election["patient_id"]):
        raise api_error(ERR_IDT_CADENCE_LAPSED)

    new_number = election["current_period_number"] + 1
    period_start = data["period_start"]
    if new_number >= config.FACE_TO_FACE_MIN_PERIOD_NUMBER:
        if not calc.face_to_face_valid(data["face_to_face_at"], period_start):
            raise api_error(ERR_FACE_TO_FACE_WINDOW)
    if election["current_period_end"] is not None and period_start < election["current_period_end"]:
        raise api_error(ERR_VALIDATION,
                        "period_start must be at or after the outgoing current_period_end.")

    length = calc.benefit_period_length_days(new_number)
    election["current_period_number"] = new_number
    election["current_period_start"] = period_start
    election["current_period_end"] = period_start + days(length)
    election["cumulative_benefit_days"] += length
    if data["face_to_face_at"] is not None:
        election["face_to_face_at"] = data["face_to_face_at"]
    elected_now = election["status"] == "CERTIFIED"
    if elected_now:
        election["status"] = "ELECTED"
    touch(election)
    if elected_now and patient is not None:
        patient["program_status"] = "HOSPICE_ELECTED"
        touch(patient)
    return ok(election)


@bp.post("/palliative/hospice-elections/<eid>/revoke")
def revoke_election(eid):
    auth([config.ROLE_DIRECTOR, config.ROLE_ADMIN])
    election = path_row(store.hospice_elections, eid)
    body = raw_body()
    validate(body, [field("revocation_reason", "string", required=True)])
    patient = store.patients.get(election["patient_id"])
    freeze_gate(patient)
    state(election["status"] == "ELECTED")
    election["status"] = "REVOKED"
    election["revocation_count"] += 1
    touch(election)
    if patient is not None:
        patient["program_status"] = "ACTIVE"
        touch(patient)
    return ok(election)


@bp.get("/palliative/hospice-elections/<eid>")
def read_election(eid):
    auth([config.ROLE_DIRECTOR, config.ROLE_PHYSICIAN, config.ROLE_BILLING, config.ROLE_ADMIN])
    return ok(path_row(store.hospice_elections, eid))


@bp.get("/palliative/hospice-elections")
def list_elections():
    auth([config.ROLE_DIRECTOR, config.ROLE_PHYSICIAN, config.ROLE_BILLING, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(ordered(store.hospice_elections.values()),
                         query_filters(["patient_id", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
