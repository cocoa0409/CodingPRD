"""The /_ namespace: the logical clock setter and the compliance sweep."""

from flask import Blueprint

import db
from middleware import authorize
from response import object_response
from services import sweep
from validation import Field, iso, parse_body

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize("PlatformAdmin")
    body = parse_body([Field("current_utc", "datetime", required=True)])
    db.set_clock(body["current_utc"])
    return object_response({"current_utc": iso(db.now())})


@bp.post("/_ops/compliance-sweep")
def compliance_sweep():
    authorize("PlatformAdmin")
    parse_body([])
    return object_response(sweep.run())
