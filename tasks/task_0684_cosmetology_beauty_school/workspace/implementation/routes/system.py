"""Administrative test-driving clock (PRD 2.9, §1.5)."""
from flask import Blueprint

import clock
import helpers
import response
from middleware import require

bp = Blueprint("system", __name__)


@bp.post("/school/_clock/set_current_utc")
@require("Registrar", "FinancialAidOfficer")
def set_clock():
    data = helpers.body()
    helpers.require_fields(data, "to_iso8601")
    dt = helpers.parse_dt(data["to_iso8601"], "to_iso8601")
    clock.set_now(dt)
    # PRD 2.9: the capability returns the resulting current_utc.
    import db
    return response.ok({"current_utc": db.iso(dt)})
