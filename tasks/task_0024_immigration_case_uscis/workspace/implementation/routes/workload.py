"""Officer workload read."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth
from response import ok_object
from services.calculations import compute_officer_workload


bp = Blueprint("workload", __name__)


@bp.get("/uscis/officers/<officer_id>/workload")
def get_officer_workload(officer_id: str):
    require_auth(["FieldOfficeAdmin"])()
    # The officer_id is opaque — there's no Officer entity to look up.
    # We compute the workload regardless of whether the officer has any cases.
    data = compute_officer_workload(officer_id, db.cases, db.get_current_utc())
    return ok_object(data, 200)
