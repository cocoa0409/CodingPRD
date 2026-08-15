"""PlacementRecord endpoints (PRD 3.2). expires_at = taken_at + 730 days."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public
from util import PLACEMENT_VALIDITY_DAYS, add_days_iso, parse_dt
from validate import get_body, req_dt, req_int, req_str, require_body_ref

bp = Blueprint("placement_records", __name__)


@bp.post("/placement-records")
def create_placement_record():
    authorized(["HsCoordinator"])
    body = get_body()
    student_id = req_str(body, "student_id")
    exam_code = req_str(body, "exam_code")
    score = req_int(body, "score", minimum=0)
    taken_raw, taken = req_dt(body, "taken_at")
    require_body_ref("students", student_id, "student_id")
    expires_raw = add_days_iso(taken_raw, PLACEMENT_VALIDITY_DAYS)
    rec = new_record(
        "placement_records",
        {
            "student_id": student_id,
            "exam_code": exam_code,
            "score": score,
            "taken_at": taken_raw,
            "expires_at": expires_raw,
        },
    )
    rec["_taken_at"] = taken
    rec["_expires_at"] = parse_dt(expires_raw)
    return success_object(public(rec), status=201)


@bp.get("/placement-records")
def list_placement_records():
    return list_response("placement_records", {"student_id": arg("student_id")})


@bp.get("/placement-records/<rid>")
def get_placement_record(rid):
    return get_one("placement_records", rid)
