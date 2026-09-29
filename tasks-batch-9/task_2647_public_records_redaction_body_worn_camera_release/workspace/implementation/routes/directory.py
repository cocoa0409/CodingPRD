"""Staff and requester registration (PRD 3.1)."""
from flask import Blueprint

import calc
import validate
from core import must_get, read_endpoint, write_endpoint
from db import store
from middleware import (
    ROLE_LEGAL_COUNSEL,
    ROLE_QUALITY_REVIEWER,
    ROLE_RECORDS_CLERK,
    ROLE_RECORDS_SUPERVISOR,
    ROLE_REDACTION_TECHNICIAN,
)

bp = Blueprint("directory", __name__)


@bp.route("/records/staff", methods=["POST"])
@write_endpoint([ROLE_RECORDS_SUPERVISOR], code=201)
def create_staff(ctx):
    data = validate.body()
    full_name = validate.req_str(data, "full_name")
    role_type = validate.req_enum(data, "role_type", calc.STAFF_ROLE_TYPES)
    level = validate.opt_int(data, "redaction_certification_level", default=0,
                             minimum=0, maximum=3)
    return store.insert("staff", {
        "full_name": full_name,
        "role_type": role_type,
        "redaction_certification_level": level,
        "open_qa_assignment_count": 0,
    })


@bp.route("/records/requesters", methods=["POST"])
@write_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR], code=201)
def create_requester(ctx):
    data = validate.body()
    full_name = validate.req_str(data, "full_name")
    email = validate.req_str(data, "email")
    requester_type = validate.req_enum(data, "requester_type", calc.REQUESTER_TYPES)
    indigency = validate.opt_bool(data, "indigency_certified", default=False)
    # Frozen once at registration and never recomputed.
    if indigency:
        waiver_pct = 1.00
    elif requester_type == "MEDIA":
        waiver_pct = 0.25
    else:
        waiver_pct = 0.00
    return store.insert("requesters", {
        "full_name": full_name,
        "email": email,
        "requester_type": requester_type,
        "indigency_certified": indigency,
        "fee_waiver_pct": waiver_pct,
        "open_request_count": 0,
    })


@bp.route("/records/staff/<staff_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR,
                ROLE_REDACTION_TECHNICIAN, ROLE_QUALITY_REVIEWER,
                ROLE_LEGAL_COUNSEL])
def get_staff(ctx, staff_id):
    return must_get("staff", staff_id, "ERR_STAFF_NOT_FOUND")


@bp.route("/records/requesters/<requester_id>", methods=["GET"])
@read_endpoint([ROLE_RECORDS_CLERK, ROLE_RECORDS_SUPERVISOR, ROLE_LEGAL_COUNSEL])
def get_requester(ctx, requester_id):
    return must_get("requesters", requester_id, "ERR_REQUESTER_NOT_FOUND")
