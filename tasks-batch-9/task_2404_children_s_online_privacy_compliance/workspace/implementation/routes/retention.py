"""RetentionSchedule endpoint (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint

import calculations as calc
from constants import (
    DATA_ELEMENT_CODES,
    DISPOSAL_METHODS,
    PURPOSE_CODES,
    ROLE_COMPLIANCE_OFFICER,
)
from db import db
from errors import fail
from helpers import base_row, resolve_body_fk
from middleware import authenticate, body, req_datetime, req_enum, req_int, req_string
from response import created
from serializers import schedule_out

bp = Blueprint("retention", __name__)


@bp.post("/retention-schedules")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_schedule():
    data = body()
    service = resolve_body_fk("service", data, "service_id")

    data_element_code = req_enum(data, "data_element_code", DATA_ELEMENT_CODES)
    purpose_code = req_enum(data, "purpose_code", PURPOSE_CODES)
    retention_days = req_int(data, "retention_days")
    disposal_method = req_enum(data, "disposal_method", DISPOSAL_METHODS)
    effective_from = req_datetime(data, "effective_from")
    effective_to = req_datetime(data, "effective_to")
    defined_purpose_statement = req_string(data, "defined_purpose_statement")

    # step 16: the effective range is CLOSED at both ends, so adjacency is itself a
    # conflict — at least one clear day of handover is required.
    one_day = timedelta(days=1)
    for existing in db.retention_schedules.values():
        if (
            existing["service_id"] != service["id"]
            or existing["data_element_code"] != data_element_code
            or existing["purpose_code"] != purpose_code
        ):
            continue
        separated = (
            effective_from >= existing["effective_to"] + one_day
            or effective_to + one_day <= existing["effective_from"]
        )
        if not separated:
            fail("ERR_RETENTION_SCHEDULE_OVERLAP")

    # step 21
    if effective_to <= effective_from:
        fail("ERR_INVALID_PERIOD", "effective_to must be later than effective_from.")
    if retention_days < 1:
        fail("ERR_INVALID_PERIOD", "retention_days must be at least 1.")
    if not calc.disposal_method_permitted(data_element_code, disposal_method):
        fail("ERR_DISPOSAL_METHOD_NOT_PERMITTED")

    schedule = base_row()
    schedule.update(
        {
            "service_id": service["id"],
            "data_element_code": data_element_code,
            "purpose_code": purpose_code,
            "retention_days": retention_days,
            "disposal_method": disposal_method,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "defined_purpose_statement": defined_purpose_statement,
        }
    )
    db.retention_schedules[schedule["id"]] = schedule
    return created(schedule_out(schedule))
