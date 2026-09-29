"""ActivityDefinition endpoint (PRD §3.6)."""
from flask import Blueprint

from constants import DATA_ELEMENT_CODES, ROLE_COMPLIANCE_OFFICER
from db import db
from helpers import base_row, resolve_body_fk
from middleware import authenticate, body, req_enum_list, req_string
from response import created
from serializers import activity_out

bp = Blueprint("activities", __name__)


@bp.post("/activities")
@authenticate(ROLE_COMPLIANCE_OFFICER)
def create_activity():
    data = body()
    service = resolve_body_fk("service", data, "service_id")
    activity_code = req_string(data, "activity_code")
    elements = req_enum_list(
        data, "participation_required_elements", DATA_ELEMENT_CODES, non_empty=False
    )

    activity = base_row()
    activity.update(
        {
            "service_id": service["id"],
            "activity_code": activity_code,
            "participation_required_elements": elements,
        }
    )
    db.activities[activity["id"]] = activity
    return created(activity_out(activity))
