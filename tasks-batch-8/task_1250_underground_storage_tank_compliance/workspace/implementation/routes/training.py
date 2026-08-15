"""TrainingRecord issuance and reads (PRD 3.7). Immutable ledger."""
from flask import Blueprint

from authz import READ_ROLES, TECHNICIAN, require_roles
from calc import VALIDITY_MONTHS
from db import store
from errors import (
    class_mismatch, instructor_not_trainer, invalid_request,
    technician_not_found, training_record_not_found,
)
from respond import success
from routes.operators import get_operator_or_404
from serialize import ser_training_record
from store_ops import (
    check_closed, get_or_404, json_body, new_id, paginate, qparam, req_enum,
    req_instant, req_str, sorted_by_creation,
)
from timeutil import add_months

bp = Blueprint("training_records", __name__)

COURSE_CLASSES = ["A", "B", "C"]


@bp.route("/training-records", methods=["POST"])
def create_training_record():
    uid, _ = require_roles([TECHNICIAN])
    data = json_body()
    check_closed(data, {"operator_id", "course_class", "completed_at"})
    operator_id = req_str(data, "operator_id")
    course_class = req_enum(data, "course_class", COURSE_CLASSES)
    completed_at = req_instant(data, "completed_at")

    op = get_operator_or_404(operator_id)
    # The acting instructor is the Technician identified by X-User-ID.
    instructor = store.technicians.get(uid)
    if instructor is None:
        raise technician_not_found("X-User-ID does not reference a Technician")
    # Priority 8: trainer flag, then class match.
    if not instructor["trainer"]:
        raise instructor_not_trainer()
    if course_class != op["operator_class"]:
        raise class_mismatch()
    if completed_at > store.clock:
        raise invalid_request("completed_at must not be after the current clock")

    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "operator_id": operator_id,
        "instructor_technician_id": uid,
        "course_class": course_class,
        "completed_at": completed_at,
        "expires_at": add_months(completed_at, VALIDITY_MONTHS[course_class]),
        "created_at": store.clock,
    }
    store.training_records[t["id"]] = t
    return success(ser_training_record(t), status=201)


@bp.route("/training-records", methods=["GET"])
def list_training_records():
    require_roles(READ_ROLES)
    items = store.training_records.values()
    for f in ("operator_id", "instructor_technician_id", "course_class"):
        v = qparam(f)
        if v is not None:
            items = [t for t in items if t[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_training_record(t) for t in page], response_type="array",
                   pagination=pagination)


@bp.route("/training-records/<rec_id>", methods=["GET"])
def get_training_record(rec_id):
    require_roles(READ_ROLES)
    return success(ser_training_record(get_or_404(store.training_records, rec_id,
                                                  training_record_not_found)))
