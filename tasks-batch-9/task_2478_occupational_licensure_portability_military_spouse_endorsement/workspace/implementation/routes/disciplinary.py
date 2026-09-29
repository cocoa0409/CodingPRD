"""National-database disciplinary records (PRD §3.3)."""
from flask import Blueprint

import clock
import db
import response
import serializers
import validators as v
from constants import ROLE_ADMIN, SEVERITIES, SOURCE_DATABASES
from errors import ERR_DISCIPLINARY_RECORD_ALREADY_RESOLVED, fail
from middleware import authenticate
from services import lookups, workflow

bp = Blueprint("disciplinary", __name__)


@bp.post("/licensure/disciplinary-records")
def create_disciplinary_record():
    authenticate([ROLE_ADMIN])
    body = v.body()
    applicant_id = v.f_string(body, "applicant_id")
    source_state = v.f_string(body, "source_state", pattern=v.TWO_LETTER_RE)
    source_database = v.f_enum(body, "source_database", SOURCE_DATABASES)
    severity = v.f_enum(body, "severity", SEVERITIES)
    action_effective_at = v.f_datetime(body, "action_effective_at")
    reported_at = v.f_datetime(body, "reported_at")

    applicant = lookups.applicant(applicant_id)

    row = db.make_row({
        "applicant_id": applicant["id"],
        "source_state": source_state,
        "source_database": source_database,
        "severity": severity,
        "action_effective_at": action_effective_at,
        "reported_at": reported_at,
        "resolved": False,
        "resolved_at": None,
    })
    db.disciplinary_records[row["id"]] = row
    workflow.recompute_applicant_discipline(applicant)
    return response.object_response(serializers.disciplinary_record(row), 201)


@bp.post("/licensure/disciplinary-records/<record_id>/resolve")
def resolve_disciplinary_record(record_id):
    authenticate([ROLE_ADMIN])
    record = lookups.disciplinary_record(record_id)
    if record["resolved"]:
        fail(ERR_DISCIPLINARY_RECORD_ALREADY_RESOLVED,
             "This disciplinary record has already been resolved.")
    record["resolved"] = True
    record["resolved_at"] = clock.now()
    db.touch(record)
    applicant = db.applicants.get(record["applicant_id"])
    if applicant is not None:
        workflow.recompute_applicant_discipline(applicant)
    return response.object_response(serializers.disciplinary_record(record))
