"""DeviceStipend endpoints (PRD section 3.4)."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_ACTIVE_STIPEND,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, pagination_params, paginate, apply_filters,
    require_fk, exist_body_fks,
)

bp = make_blueprint("stipends")

STIPEND_TYPES = ["DEVICE", "INTERNET"]
STIPEND_READ_ROLES = ["PlatformAdmin", "FinanceOfficer", "EnrollmentOfficer"]
ACTIVE_ISSUE_STATUSES = ("REQUESTED", "ISSUED", "RETURN_REQUESTED")


@bp.post("/stipends")
def create_stipend():
    authenticate(["FinanceOfficer"])
    body = body_json()
    exist_body_fks(body, {"student_id": ("students", "student")})
    check_shape(body, {
        "student_id": {"type": "string", "required": True},
        "stipend_type": {"type": "enum", "required": True, "values": STIPEND_TYPES},
        "amount_cents": {"type": "integer", "required": True, "min": 0},
    })
    stipend = db.new_entity("stipends", {
        "student_id": body["student_id"],
        "stipend_type": body["stipend_type"],
        "amount_cents": body["amount_cents"],
        "issue_status": "REQUESTED",
        "issued_at": None,
        "return_due_date": None,
        "clawback_cents": 0,
    })
    return success_obj(db.public(stipend), 201)


@bp.get("/stipends/<sid>")
def get_stipend(sid):
    authenticate(STIPEND_READ_ROLES)
    stipend = require_fk("stipends", sid, "stipend")
    return success_obj(db.public(stipend), 200)


@bp.get("/students/<sid>/stipends")
def list_student_stipends(sid):
    authenticate(STIPEND_READ_ROLES)
    student = require_fk("students", sid, "student")
    limit, offset = pagination_params()
    items = [s for s in db.all_of("stipends") if s["student_id"] == student["id"]]
    items = apply_filters(items, ["issue_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(s) for s in page], limit, offset, total, has_more)


@bp.post("/stipends/<sid>/issue")
def issue_stipend(sid):
    authenticate(["FinanceOfficer"])
    stipend = require_fk("stipends", sid, "stipend")
    # State admissibility (priority 5): stipend REQUESTED, student ENROLLED.
    if stipend["issue_status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a REQUESTED stipend can be issued")
    student = db.get("students", stipend["student_id"])
    if student is None or student["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "stipend issuance requires an ENROLLED student")
    # Uniqueness (priority 13): no other live stipend of the same type.
    for other in db.all_of("stipends"):
        if (other["id"] != stipend["id"]
                and other["student_id"] == stipend["student_id"]
                and other["stipend_type"] == stipend["stipend_type"]
                and other["issue_status"] in ACTIVE_ISSUE_STATUSES):
            raise ApiError(ERR_DUPLICATE_ACTIVE_STIPEND, 422,
                           "another active stipend of this type exists for the student")
    stipend["issue_status"] = "ISSUED"
    stipend["issued_at"] = db.fmt_ts(db.now())
    db.touch(stipend)
    return success_obj(db.public(stipend), 200)


@bp.post("/stipends/<sid>/mark-returned")
def mark_stipend_returned(sid):
    authenticate(["FinanceOfficer"])
    stipend = require_fk("stipends", sid, "stipend")
    if stipend["issue_status"] != "RETURN_REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a RETURN_REQUESTED stipend can be marked returned")
    stipend["issue_status"] = "RETURNED"
    stipend["clawback_cents"] = 0
    db.touch(stipend)
    return success_obj(db.public(stipend), 200)
