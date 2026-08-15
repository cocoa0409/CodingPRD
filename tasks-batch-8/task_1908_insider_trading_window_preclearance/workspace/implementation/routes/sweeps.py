"""Compliance sweep endpoint."""
from flask import Blueprint

from middleware import require_roles
from response import success
from services.sweep import run_sweep

bp = Blueprint("sweeps", __name__)


@bp.post("/compliance-sweeps")
def sweep():
    require_roles("ComplianceOfficer")
    counts = run_sweep()
    return success(counts)
