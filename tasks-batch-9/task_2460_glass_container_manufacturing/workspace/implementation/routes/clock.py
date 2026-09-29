from flask import Blueprint

from envelope import success
from store import db
from validation import Ts, authorize, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    """PRD 2.4: administrative capability mounted outside the /glass-plant tree."""
    authorize("PlantManager")
    data = validate_body([Ts("current_utc")])
    db.clock = data["current_utc"]
    return success({}, 200)
