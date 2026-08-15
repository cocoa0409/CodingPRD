"""Work order completion submission."""

from db import now
from errors import ApiError
from helpers import (
    get_body, check_allowed_fields, get_work_order_or_404, touch, ser_work_order,
)
from middleware import authenticate, authorize
from response import success

from . import bp


@bp.post("/escrow/work-orders/<wid>/submit-completion")
def submit_completion(wid):
    uid, role = authenticate()
    authorize(role, ["Contractor"])
    wo = get_work_order_or_404(wid)
    data = get_body()
    check_allowed_fields(data, set())
    # Rung 5: only the engaged contractor declares completion.
    if uid != wo["contractor_user_id"]:
        raise ApiError("ERR_NOT_FILE_PARTY", "Only the engaged contractor may submit completion")
    # Rung 7: IN_PROGRESS -> COMPLETION_SUBMITTED only.
    if wo["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Work order is not IN_PROGRESS")
    wo["status"] = "COMPLETION_SUBMITTED"
    wo["submitted_completion_at"] = now()
    touch(wo)
    return success(ser_work_order(wo), response_type="object", status=200)
