"""The test-driving logical clock endpoint."""
from flask import Blueprint, request

from authz import ROLE_COMPLIANCE_ADMIN, authorize
from core import store, success_object
from validate import as_instant, body_of, req_present

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(request, [ROLE_COMPLIANCE_ADMIN])
    body = body_of(request)
    moment = as_instant(req_present(body, "to_iso8601"), "to_iso8601")
    store.clock.set(moment)
    return success_object({})
