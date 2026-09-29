"""The test-driving logical clock (PRD 2.4)."""
from flask import Blueprint

import response
import store
import validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    validate.auth("PlantOperator", "FeedstockTrader", "QualityAnalyst",
                  "ComplianceOfficer", "IndependentVerifier")
    data = validate.body()
    moment = validate.get_dt(data, "to_iso8601")
    store.set_now(moment)
    return response.raw({"current_utc": store.iso(store.now())})
