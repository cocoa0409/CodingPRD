"""Inspection facility endpoints (PRD 3.1)."""
from flask import Blueprint

from middleware import require_roles
from response import success_object
from services.core import new_record, serialize
from validate import body, opt_int, req_str

bp = Blueprint("facilities", __name__)


@bp.post("/api/inspection-facilities")
@require_roles(["BrokerPrincipal"])
def create_facility():
    b = body()
    rec = new_record(
        "facilities",
        {
            "name": req_str(b, "name"),
            "airport_code": req_str(b, "airport_code"),
            # Defaults to 120 (standard two-hour reset window) when omitted.
            "turnaround_buffer_minutes": opt_int(
                b, "turnaround_buffer_minutes", default=120, min_value=0
            ),
        },
    )
    return success_object(serialize("facilities", rec), 201)
