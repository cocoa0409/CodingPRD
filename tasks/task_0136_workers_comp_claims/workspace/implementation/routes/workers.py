"""Worker endpoints (PRD §3.1). Computes AWW at creation."""
from __future__ import annotations

from flask import Blueprint, g

import db
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_str, require_int
from services import calculations as calc
from routes._common import get_employer, get_worker, assert_employer_owns_employer

bp = Blueprint("workers", __name__)


@bp.post("/workers")
def create_worker():
    require_auth(["PlatformAdmin", "Employer"])()
    body = get_json_body()

    employer_id = require_str(body, "employer_id")
    emp = get_employer(employer_id)
    # An Employer may only register workers under itself.
    assert_employer_owns_employer(employer_id)

    full_name = require_str(body, "full_name")
    gross_wages_cents = require_int(body, "gross_wages_cents", minimum=0)
    weeks_worked = require_int(body, "weeks_worked", minimum=1, maximum=52)

    aww = calc.average_weekly_wage(gross_wages_cents, weeks_worked)
    worker = {
        "employer_id": employer_id,
        "full_name": full_name,
        "gross_wages_cents": gross_wages_cents,
        "weeks_worked": weeks_worked,
        "average_weekly_wage_cents": aww,
    }
    db.stamp_common(worker)
    db.workers[worker["id"]] = worker
    return ok_object(worker, 201)


@bp.get("/workers/<rid>")
def get_worker_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer", "Employer"])()
    worker = get_worker(rid)
    assert_employer_owns_employer(worker["employer_id"])
    return ok_object(worker, 200)
