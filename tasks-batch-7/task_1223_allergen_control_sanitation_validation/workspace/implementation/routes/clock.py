from flask import Blueprint

from db import CLOCK, db, touch
from logic import recompute_training
from middleware import require_roles
from response import ok
from util import body, fmt_dt, parse_dt, req_str

bp = Blueprint("clock", __name__)


@bp.post("/qa/_clock/set_current_utc")
@require_roles("QaManager")
def set_clock():
    b = body()
    d = parse_dt(req_str(b, "to_iso8601"))
    CLOCK["current"] = d
    # Overdue sweep: OPEN findings whose due lies strictly before the new clock.
    for f in list(db["findings"].values()):
        if f["status"] == "OPEN" and parse_dt(f["corrective_action_due_utc"]) < d:
            f["status"] = "OVERDUE"
            f["_overdue_penalty"] = True
            touch(f)
            tech = db["technicians"].get(f["technician_id"])
            if tech is not None:
                recompute_training(tech)
    return ok({"current_utc": fmt_dt(d)})
