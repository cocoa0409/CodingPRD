"""HandHygieneObservations and the unit hand-hygiene rate computation."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_OBSERVATION_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, round1
from services.serializers import observation_view
from util import cal_date
from validate import body, pagination_args, req_dt, req_enum, req_month

bp = Blueprint("hygiene", __name__)

OPPORTUNITY_TYPES = {
    "BEFORE_PATIENT_CONTACT",
    "AFTER_PATIENT_CONTACT",
    "ASEPTIC_TASK",
    "BODY_FLUID_RISK",
    "AFTER_SURROUNDINGS",
}
ACTIONS = {"COMPLIANT", "MISSED"}
WEIGHTS = {
    "BEFORE_PATIENT_CONTACT": Decimal("1.0"),
    "AFTER_PATIENT_CONTACT": Decimal("1.0"),
    "ASEPTIC_TASK": Decimal("2.0"),
    "BODY_FLUID_RISK": Decimal("1.5"),
    "AFTER_SURROUNDINGS": Decimal("1.0"),
}


@bp.post("/api/hand-hygiene-observations")
def create_observation():
    user_id, _ = require_roles(["UnitNurseManager"])
    b = body()
    for f in ("unit_id", "observed_at", "opportunity_type", "action"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    observed_at = req_dt(b, "observed_at")
    opportunity_type = req_enum(b, "opportunity_type", OPPORTUNITY_TYPES)
    action = req_enum(b, "action", ACTIONS)

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    obs = new_entity({
        "unit_id": unit_id,
        "observer_user_id": user_id,
        "observed_at": observed_at,
        "opportunity_type": opportunity_type,
        "action": action,
    })
    db.hand_hygiene_observations[obs["id"]] = obs
    return success_object(observation_view(obs), 201)


@bp.get("/api/hand-hygiene-observations")
def list_observations():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    unit_id = request.args.get("unit_id")
    month = request.args.get("month")

    def _match(o):
        if unit_id is not None and o["unit_id"] != unit_id:
            return False
        if month is not None:
            d = cal_date(o["observed_at"])
            if f"{d.year:04d}-{d.month:02d}" != month:
                return False
        return True

    items = [o for o in db.hand_hygiene_observations.values() if _match(o)]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([observation_view(o) for o in page], total, limit, offset)


@bp.get("/api/hand-hygiene-observations/<oid>")
def get_observation(oid):
    require_roles(ALL_ROLES)
    o = db.hand_hygiene_observations.get(oid)
    if o is None:
        raise_err(ERR_OBSERVATION_NOT_FOUND, "hand hygiene observation id does not exist")
    return success_object(observation_view(o))


# ---------------------------------------------------------------------------
# Computed rate endpoint
# ---------------------------------------------------------------------------
@bp.get("/api/units/<uid>/hand-hygiene-rate")
def hand_hygiene_rate(uid):
    require_roles(ALL_ROLES)
    unit = db.units.get(uid)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")
    month = request.args.get("month")
    if month is None:
        raise_err(ERR_INVALID_REQUEST, "month query parameter is required")
    req_month({"month": month}, "month")

    facility = db.facilities[unit["facility_id"]]
    obs = [
        o for o in db.hand_hygiene_observations.values()
        if o["unit_id"] == uid
        and f"{cal_date(o['observed_at']).year:04d}-{cal_date(o['observed_at']).month:02d}" == month
    ]
    total_count = len(obs)
    compliant = [o for o in obs if o["action"] == "COMPLIANT"]
    compliant_count = len(compliant)
    reportable = total_count >= facility["hh_min_opportunities"]

    simple_rate = None
    weighted_rate = None
    if reportable and total_count > 0:
        # Aggregate-then-round: month-level sums, rounded ONCE at 1dp half-up.
        simple_rate = round1(Decimal(100) * Decimal(compliant_count) / Decimal(total_count))
        num = sum((WEIGHTS[o["opportunity_type"]] for o in compliant), Decimal("0"))
        den = sum((WEIGHTS[o["opportunity_type"]] for o in obs), Decimal("0"))
        weighted_rate = round1(Decimal(100) * num / den) if den > 0 else None

    return success_object({
        "month": month,
        "total_count": total_count,
        "compliant_count": compliant_count,
        "simple_rate_pct": float(simple_rate) if simple_rate is not None else None,
        "weighted_rate_pct": float(weighted_rate) if weighted_rate is not None else None,
        "reportable": reportable,
    })
