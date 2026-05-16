"""EnrollmentPeriod creation and listing under a beneficiary."""
from flask import Blueprint, g, request

from auth import require_roles
from errors import err
from response import ok_array, ok_object
from serializers import serialize_enrollment_period
from store import store
from utils import (
    iso_string,
    paginate,
    parse_iso_datetime,
    parse_pagination,
    require_enum,
    require_field,
    stamp_create,
)

bp = Blueprint("enrollment_periods", __name__)

# IEP is auto-created by intake — admins may only open these explicit period_types.
ADMIN_PERIOD_TYPES = {"AEP", "GEP", "SEP_MOVE", "SEP_LOSS_OF_COVERAGE", "MEDIGAP_GI"}
ALL_PERIOD_TYPES = {"IEP", "AEP", "GEP", "SEP_MOVE", "SEP_LOSS_OF_COVERAGE", "MEDIGAP_GI"}


@bp.route("/beneficiaries/<bid>/enrollment-periods", methods=["POST"])
@require_roles("PlanAdmin")
def create_period(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if b["lifecycle_status"] == "DECEASED":
        raise err("ERR_BENEFICIARY_DECEASED", "Beneficiary is deceased")
    body = request.get_json(silent=True) or {}
    period_type = require_enum(require_field(body, "period_type"), field="period_type", allowed=ADMIN_PERIOD_TYPES)
    window_start = parse_iso_datetime(require_field(body, "window_start"), field="window_start")
    window_end = parse_iso_datetime(require_field(body, "window_end"), field="window_end")
    if window_end < window_start:
        raise err("ERR_VALIDATION", "window_end must be >= window_start")

    now = store.clock
    if now < window_start:
        status = "SCHEDULED"
    elif window_start <= now <= window_end:
        status = "OPEN"
    else:
        status = "CLOSED"

    now_iso = store.now_iso()
    pid = store.new_id()
    period = {
        "id": pid,
        "beneficiary_id": bid,
        "period_type": period_type,
        "status": status,
        "consumed_by_enrollment_id": None,
        "_window_start_dt": window_start,
        "_window_end_dt": window_end,
    }
    stamp_create(period, store_now_iso=now_iso)
    store.enrollment_periods[pid] = period
    return ok_object(serialize_enrollment_period(period), status=201)


@bp.route("/beneficiaries/<bid>/enrollment-periods", methods=["GET"])
@require_roles("PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor")
def list_periods(bid):
    b = store.beneficiaries.get(bid)
    if not b:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    if g.role == "Beneficiary" and g.user_id != bid:
        raise err("ERR_FORBIDDEN", "Beneficiaries may only read their own periods")
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("status")
    type_filter = request.args.get("period_type")

    items = [p for p in store.enrollment_periods.values() if p["beneficiary_id"] == bid]
    items.sort(key=lambda p: p["created_at"])
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    if type_filter:
        items = [p for p in items if p["period_type"] == type_filter]

    page, pagination = paginate(items, limit, offset)
    return ok_array([serialize_enrollment_period(p) for p in page], pagination)
