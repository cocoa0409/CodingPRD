"""Adverse events: report and acknowledge."""

from datetime import timedelta

from flask import Blueprint

from db import store, new_id, now_iso, logical_now
from errors import (
    ApiError,
    ERR_ENROLLMENT_DISCONTINUED,
    ERR_AE_REPORT_WINDOW_MISSED,
    ERR_ALREADY_TERMINAL,
)
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, req_datetime, req_enum, req_string,
    get_enrollment_or_404, get_ae_or_404,
    pagination_params, paginate, touch,
)
from services.calc import serialize_ae, aes_for_enrollment, AE_REPORT_WINDOW_HOURS

bp = Blueprint("adverse_events", __name__)


def _fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.post("/hub/enrollments/<eid>/adverse-events")
def create_ae(eid):
    user_id, _ = require_roles("CaseManager", "NurseEducator")
    e = get_enrollment_or_404(eid)
    data = body()
    awareness_at = req_datetime(data, "awareness_at")
    seriousness = req_enum(data, "seriousness", ("SERIOUS", "NON_SERIOUS"))
    description = req_string(data, "description")

    # Body schema (priority 3.5): awareness_at must not lie in the future.
    now = logical_now()
    from errors import ERR_VALIDATION
    if awareness_at > now:
        raise ApiError(ERR_VALIDATION,
                       "awareness_at must not lie in the future.", 400)

    # State validity.
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)

    # Compliance gate: report within AE_REPORT_WINDOW_HOURS of awareness.
    if now - awareness_at > timedelta(hours=AE_REPORT_WINDOW_HOURS):
        raise ApiError(ERR_AE_REPORT_WINDOW_MISSED,
                       "Adverse event reported more than 24 hours after "
                       "awareness.", 422)

    ts = now_iso()
    ae = {
        "id": new_id(),
        "enrollment_id": eid,
        "awareness_at": _fmt_dt(awareness_at),
        "seriousness": seriousness,
        "description": description,
        "reported_by_user_id": user_id,
        "status": "REPORTED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.adverse_events[ae["id"]] = ae
    return success_object(serialize_ae(ae), 201)


@bp.get("/hub/enrollments/<eid>/adverse-events")
def list_aes(eid):
    get_auth()
    get_enrollment_or_404(eid)
    limit, offset = pagination_params()
    page, total = paginate(aes_for_enrollment(eid), limit, offset)
    return success_array([serialize_ae(a) for a in page],
                         limit, offset, total, 200)


@bp.post("/hub/adverse-events/<aid>/acknowledge")
def acknowledge_ae(aid):
    require_roles("ManufacturerMonitor")
    ae = get_ae_or_404(aid)
    if ae["status"] == "ACKNOWLEDGED":
        raise ApiError(ERR_ALREADY_TERMINAL,
                       "Adverse event is already acknowledged.", 409)
    ae["status"] = "ACKNOWLEDGED"
    touch(ae)
    return success_object(serialize_ae(ae), 200)
