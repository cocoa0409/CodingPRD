"""Providers (PRD 3.1)."""
from flask import Blueprint

import db
import helpers
import response
from middleware import require

bp = Blueprint("providers", __name__)

ALL_ROLES = ("PracticeAdmin", "FrontDesk", "Provider", "BillingSpecialist", "PathLab")


@bp.post("/providers")
@require("PracticeAdmin")
def create_provider():
    data = helpers.body()
    full_name = helpers.require_str(data, "full_name")
    npi = helpers.require_str(data, "npi")
    row = {
        "full_name": full_name,
        "npi": npi,
        "can_perform_mohs": helpers.opt_bool(data, "can_perform_mohs", False),
        "active": helpers.opt_bool(data, "active", True),
    }
    db.stamp_new(row)
    db.providers[row["id"]] = row
    return response.created(row)


@bp.get("/providers/<pid>")
@require(*ALL_ROLES)
def get_provider(pid):
    row = helpers.get_or_404(db.providers, pid, "provider")
    return response.ok(row)


@bp.get("/providers")
@require(*ALL_ROLES)
def list_providers():
    page, limit, offset, total = helpers.paginate(list(db.providers.values()))
    return response.listing(page, limit, offset, total)
