"""Survey review endpoint (interpretation improvement loop)."""
from flask import Blueprint

from errors import ApiError
from middleware import auth
from response import ok
from services import lookup, ser_survey

bp = Blueprint("surveys", __name__)


@bp.post("/surveys/<sid>/review")
def review_survey(sid):
    auth(["Curator"])
    survey = lookup("surveys", sid)
    if survey["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a SUBMITTED survey can be reviewed"
        )
    # Surveys carry no updated_at/version (PRD 2.4); only the status flips.
    survey["status"] = "REVIEWED"
    return ok(ser_survey(survey))
