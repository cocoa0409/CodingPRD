"""Test-driving system endpoints — clock advance + year tick."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import auth_required
from response import success_object
from services.calculations import vested_pct_bps
from services.clock_and_age import parse_iso, years_of_service
from services.entities import (
    recompute_vested_balance,
    serialize_vesting_event,
    stamp_create,
    stamp_update,
)
from services.validators import require_dict, require_int, require_str


bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
@auth_required("PlanAdmin")
def set_clock():
    body = require_dict(request.get_json(silent=True))
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 must be ISO 8601")
    db.set_clock(dt)
    return success_object({"clock_set_to": db.iso_ms(dt)})


@bp.post("/_system/year-tick")
@auth_required("PlanAdmin")
def year_tick():
    body = require_dict(request.get_json(silent=True))
    as_of_year = require_int(body, "as_of_year", minimum=1900, maximum=2999)

    with db.LOCK:
        # For each ENROLLED|SUSPENDED Participant whose YoS crosses a vesting
        # boundary, recompute vested_employer_balance_cents and append a
        # VestingEvent.
        for p in list(db.participants.values()):
            if p["enrollment_status"] not in {"ENROLLED", "SUSPENDED"}:
                continue
            prior_yos = p["years_of_service"]
            new_yos = years_of_service(p["hire_date"])
            plan = db.plans.get(p["plan_id"])
            schedule = plan["vesting_schedule"] if plan else "GRADED_6"
            prior_pct = vested_pct_bps(prior_yos, schedule)
            new_pct = vested_pct_bps(new_yos, schedule)
            # Update yos snapshot regardless (lazy reads also do this).
            p["years_of_service"] = new_yos
            if new_pct != prior_pct:
                # Recompute vested balance and append an audit row.
                recompute_vested_balance(p)
                stamp_update(p)
                ve = stamp_create(
                    {
                        "participant_id": p["id"],
                        "as_of_date": db.iso_ms(db.get_clock()),
                        "years_of_service_after": new_yos,
                        "vested_pct_bps_after": new_pct,
                    },
                    immutable=True,
                )
                db.vesting_events[ve["id"]] = ve

        # For each PENDING RMD with distribution_year < as_of_year -> MISSED.
        for r in db.rmd_distributions.values():
            if r["status"] == "PENDING" and r["distribution_year"] < as_of_year:
                r["status"] = "MISSED"
                stamp_update(r)
    return success_object({"year_tick_processed": as_of_year})
