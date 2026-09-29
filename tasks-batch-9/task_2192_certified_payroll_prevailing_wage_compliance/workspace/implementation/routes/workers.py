"""Worker registration."""

from flask import Blueprint, request

import db
import serializers as s
import validators as v
from auth import ALL_ROLES, acting_staff, authenticate, require_ownership
from response import created, ok, paginated, pagination

bp = Blueprint("workers", __name__)


def get_worker(worker_id):
    return v.lookup(db.workers, worker_id, "ERR_WORKER_NOT_FOUND")


@bp.route("/workers", methods=["POST"])
def register_worker():
    actor = authenticate(["PayrollPreparer"])
    payload = v.body()
    employer = v.resolve_fk(
        payload, "employer_contractor_id", db.contractors, "ERR_CONTRACTOR_NOT_FOUND"
    )
    program = v.resolve_fk(
        payload, "apprentice_program_id", db.apprentice_programs, "ERR_PROGRAM_NOT_FOUND"
    )
    if employer is None:
        v.bad("employer_contractor_id is required.")

    staff = acting_staff(actor)
    require_ownership(staff, employer["id"])

    worker_number = v.req_string(payload, "worker_number", min_len=1)
    full_name = v.req_string(payload, "full_name", min_len=1)
    default_classification_code = v.req_string(
        payload, "default_classification_code", min_len=1, upper=True
    )
    apprentice_period = v.opt_int(payload, "apprentice_period", minimum=1, maximum=8)
    if program is not None and apprentice_period is not None:
        if apprentice_period > program["period_count"]:
            v.bad("apprentice_period may not exceed the program's period_count.")

    v.unique_or_reject(
        db.workers,
        lambda r: r["employer_contractor_id"] == employer["id"]
        and r["worker_number"] == worker_number,
        "worker_number must be unique within the employing contractor.",
    )

    row = db.base_row()
    row.update(
        {
            "employer_contractor_id": employer["id"],
            "worker_number": worker_number,
            "full_name": full_name,
            "default_classification_code": default_classification_code,
            "apprentice_program_id": program["id"] if program else None,
            "apprentice_period": apprentice_period,
            "interview_count": 0,
        }
    )
    db.workers[row["id"]] = row
    return created(s.worker(row))


@bp.route("/workers", methods=["GET"])
def list_workers():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    employer = request.args.get("employer_contractor_id")
    program = request.args.get("apprentice_program_id")
    worker_number = request.args.get("worker_number")

    def keep(row):
        if employer is not None and row["employer_contractor_id"] != employer:
            return False
        if program is not None and row["apprentice_program_id"] != program:
            return False
        if worker_number is not None and row["worker_number"] != worker_number:
            return False
        return True

    return paginated(db.ordered(db.workers, keep), s.worker, limit, offset)


@bp.route("/workers/<worker_id>", methods=["GET"])
def read_worker(worker_id):
    authenticate(ALL_ROLES)
    return ok(s.worker(get_worker(worker_id)))
