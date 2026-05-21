"""/violations endpoints."""

from __future__ import annotations

import secrets
import string

from flask import Blueprint, g, request as flask_request

from ..auth import require_auth
from ..envelope import ok_array, ok_object
from ..errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_VIOLATION_STATE,
    ERR_NOT_FOUND,
)
from ..serializers import serialize_violation
from ..store import store
from ..timeutil import clock, iso_now
from ..util import get_pagination, paginate


violations_bp = Blueprint("violations", __name__)


_REPORT_ID_ALPHABET = string.ascii_uppercase + string.digits


def _new_report_id() -> str:
    return "FMCSA-" + "".join(secrets.choice(_REPORT_ID_ALPHABET) for _ in range(12))


@violations_bp.get("/violations")
@require_auth({"CarrierSafetyOfficer", "FMCSAAuditor"})
def list_violations():
    limit, offset = get_pagination()
    driver_id = flask_request.args.get("driver_id")
    carrier_id = flask_request.args.get("carrier_id")
    status_filter = flask_request.args.get("status")
    rule_code = flask_request.args.get("rule_code")

    items = list(store.violations.values())
    if driver_id:
        items = [v for v in items if v.get("driver_id") == driver_id]
    if carrier_id:
        items = [
            v
            for v in items
            if (
                (driver := store.drivers.get(v.get("driver_id"))) is not None
                and driver.get("carrier_id") == carrier_id
            )
        ]
    if status_filter:
        items = [v for v in items if v.get("status") == status_filter]
    if rule_code:
        items = [v for v in items if v.get("rule_code") == rule_code]
    items.sort(key=lambda v: v["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    return ok_array(
        [serialize_violation(v) for v in page],
        limit=limit,
        offset=offset,
        total_count=total,
        has_more=has_more,
    )


@violations_bp.get("/violations/<violation_id>")
@require_auth({"Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_violation(violation_id: str):
    v = store.violations.get(violation_id)
    if v is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Violation not found.")
    return ok_object(serialize_violation(v))


@violations_bp.post("/violations/<violation_id>/acknowledge")
@require_auth({"Driver"})
def acknowledge(violation_id: str):
    with store.lock:
        v = store.violations.get(violation_id)
        if v is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Violation not found.")
        if v.get("status") != "OPEN":
            raise ApiError(
                ERR_INVALID_VIOLATION_STATE, 409, "Violation must be OPEN to acknowledge.",
            )
        v["status"] = "ACKNOWLEDGED"
        store.bump(v)
    return ok_object(serialize_violation(v))


@violations_bp.post("/violations/<violation_id>/report-to-fmcsa")
@require_auth({"CarrierSafetyOfficer"})
def report_to_fmcsa(violation_id: str):
    with store.lock:
        v = store.violations.get(violation_id)
        if v is None:
            raise ApiError(ERR_NOT_FOUND, 404, "Violation not found.")
        if v.get("status") != "ACKNOWLEDGED":
            raise ApiError(
                ERR_INVALID_VIOLATION_STATE,
                409,
                "Violation must be ACKNOWLEDGED to report to FMCSA.",
            )
        v["status"] = "REPORTED"
        v["reported_to_fmcsa_at"] = iso_now(clock.now())
        v["fmcsa_report_id"] = _new_report_id()
        store.bump(v)
    return ok_object(serialize_violation(v))
