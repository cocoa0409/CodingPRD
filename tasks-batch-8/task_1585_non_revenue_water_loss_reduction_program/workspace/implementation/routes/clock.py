"""POST /nrw/_clock/set_current_utc — logical clock administration."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_object
from routes import make_bp
from util import v_dt
from services import calc

bp = make_bp("clock")


@bp.route("/nrw/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = require_roles({"ProgramDirector"})
    body = get_body()
    target = v_dt(body, "to_iso8601")
    db.set_logical_now(target)

    # Re-evaluate the age lane for every AGE_BASED / HYBRID meter; IN_SERVICE
    # meters crossing the fifteen-year limit flip to FLAGGED_FOR_REPLACEMENT.
    for meter in list(db.store["customer_meters"].values()):
        if meter["replacement_policy"] not in ("AGE_BASED", "HYBRID"):
            continue
        due = calc.compute_replacement_due(meter)
        if meter["status"] == "IN_SERVICE" and calc.meter_age_trip(meter):
            before = {"status": "IN_SERVICE", "replacement_due": meter["replacement_due"]}
            meter["status"] = "FLAGGED_FOR_REPLACEMENT"
            meter["replacement_due"] = due
            db.touch(meter)
            db.append_audit("CustomerMeter", meter["id"], "FLAG_REPLACEMENT",
                            "system", "system",
                            {"before": before,
                             "after": {"status": "FLAGGED_FOR_REPLACEMENT",
                                       "replacement_due": due}})
        elif due != meter["replacement_due"]:
            meter["replacement_due"] = due
            db.touch(meter)

    return success_object({"current_utc": db.fmt_dt(db.logical_now())})
