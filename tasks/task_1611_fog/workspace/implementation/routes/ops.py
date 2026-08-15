"""Operations endpoints: compliance sweep and the logical clock."""
from flask import Blueprint

from db import STORE, now, set_now
from errors import ApiError, ERR_CLOCK_REGRESSION
from middleware import auth, require_roles, by_creation
from response import success
from services.calculations import CITATION_FINE
from services.posture import touch_establishment
from validation import body_json, v_dt, fmt_dt

bp = Blueprint("ops", __name__)


@bp.post("/sweeps/run")
def run_sweep():
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    current = now()
    escalated = []
    # Auto-escalate every NOTICED violation whose cure_deadline has been reached.
    for v in by_creation(list(STORE["violations"].values())):
        if v["status"] == "NOTICED" and v["cure_deadline"] <= current:
            v["status"] = "CITATION"
            v["fine_cents"] = CITATION_FINE[v["severity"]]
            v["escalated_at"] = current
            v["updated_at"] = current
            v["version"] += 1
            escalated.append(v["id"])
            est = STORE["establishments"].get(v["establishment_id"])
            if est is not None:
                touch_establishment(est, current, bump=False)
    # Recompute pumping delinquency posture for every establishment.
    for est in by_creation(list(STORE["establishments"].values())):
        touch_establishment(est, current, bump=False)
    delinquent = [
        est["id"]
        for est in by_creation(list(STORE["establishments"].values()))
        if est["compliance_status"] == "DELINQUENT"
    ]
    return success(
        {"escalated_violation_ids": escalated, "delinquent_establishment_ids": delinquent}
    )


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    body = body_json()
    target = v_dt(body, "to_iso8601")
    require_roles(role, ["ProgramAdmin"])
    current = now()
    if not target > current:
        raise ApiError(ERR_CLOCK_REGRESSION, 422, "Clock value must be strictly after the current logical clock")
    set_now(target)
    return success({"current_utc": fmt_dt(target)})
