"""Program-wide computed metrics (PRD 3.8; calculations.program_metrics)."""
from decimal import Decimal

from flask import Blueprint

from db import db
from middleware import get_caller, check_role, COORD, LEADER
from response import success_object
from util import dec, round_half_up

bp = Blueprint("metrics", __name__)


@bp.get("/program/metrics")
def get_metrics():
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    active_agreements = sum(1 for a in db["agreements"].values() if a["status"] == "ACTIVE")
    adopted = sum((dec(s["mile_length"]) for s in db["segments"].values()
                   if s["status"] == "ADOPTED"), Decimal("0"))
    available = sum((dec(s["mile_length"]) for s in db["segments"].values()
                     if s["status"] == "AVAILABLE"), Decimal("0"))
    debris = sum((dec(r["official_weight_lbs"]) for r in db["debris_reports"].values()),
                 Decimal("0"))
    completed = sum(1 for e in db["events"].values() if e["status"] == "COMPLETED")
    open_hazards = sum(1 for h in db["hazards"].values()
                       if h["status"] in ("REPORTED", "ACKNOWLEDGED"))
    return success_object({
        "active_agreements": active_agreements,
        "adopted_miles": float(round_half_up(adopted, 2)),
        "available_miles": float(round_half_up(available, 2)),
        "total_debris_lbs": float(round_half_up(debris, 1)),
        "completed_cleanups": completed,
        "open_hazards": open_hazards,
    })
