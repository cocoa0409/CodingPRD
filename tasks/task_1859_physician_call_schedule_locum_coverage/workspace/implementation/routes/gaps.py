"""Coverage gaps — read-only; created by cascades (PRD §3.5)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, paginate

bp = Blueprint("gaps", __name__)

ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_gap_or_404(gap_id):
    gap = store.gaps.get(gap_id)
    if gap is None:
        raise ApiError("ERR_GAP_NOT_FOUND", 404, "CoverageGap id does not exist")
    return gap


@bp.route("/api/coverage-gaps", methods=["GET"])
def list_gaps():
    require_roles(ALL)
    rows = list(store.gaps.values())
    rows = paginate.filter(rows, "program_id")
    rows = paginate.filter(rows, "slot_id")
    rows = paginate.filter(rows, "status")
    rows = paginate.filter(rows, "reason")
    rows = paginate.filter(rows, "resolved_by_assignment_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/coverage-gaps/<gap_id>", methods=["GET"])
def get_gap(gap_id):
    require_roles(ALL)
    return ok(get_gap_or_404(gap_id))
