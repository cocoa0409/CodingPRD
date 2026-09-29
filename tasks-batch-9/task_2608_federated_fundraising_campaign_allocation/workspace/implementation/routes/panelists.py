"""Volunteer panelist registry (PRD 3.7)."""

from flask import Blueprint

from auth import ALL_ROLES, authenticate, get_panelist
from envelope import created, filter_bool, ok, paginate
from store import base_entity, db, sort_created_asc
from validators import bad, body, get_enum, get_str

from services import aggregates

bp = Blueprint("panelists", __name__)

EXPERTISE_AREAS = (
    "BASIC_NEEDS",
    "EDUCATION",
    "HEALTH",
    "FINANCIAL_STABILITY",
    "FINANCE",
)


@bp.get("/panelists/<panelist_id>")
def read_panelist(panelist_id):
    authenticate(ALL_ROLES)
    return ok(get_panelist(panelist_id))


@bp.get("/panelists/<panelist_id>/scores")
def list_panelist_scores(panelist_id):
    authenticate(ALL_ROLES)
    get_panelist(panelist_id)
    rows = [s for s in db.scores.values() if s["panelist_id"] == panelist_id]
    eligible = filter_bool("eligible")
    if eligible is not None:
        rows = [s for s in rows if s["eligible"] == eligible]
    return paginate(sort_created_asc(rows))


@bp.get("/panelists/<panelist_id>/panel-assignments")
def list_panelist_assignments(panelist_id):
    authenticate(ALL_ROLES)
    get_panelist(panelist_id)
    rows = [a for a in db.assignments.values() if a["panelist_id"] == panelist_id]
    conflict = filter_bool("conflict_declared")
    if conflict is not None:
        rows = [a for a in rows if a["conflict_declared"] == conflict]
    return paginate(sort_created_asc(rows))


@bp.post("/panelists")
def create_panelist():
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    data = body()
    full_name = get_str(data, "full_name", min_len=1, max_len=120)
    email = get_str(data, "email", min_len=1)
    if "@" not in email:
        bad("Field 'email' must contain '@'.")
    expertise_area = get_enum(data, "expertise_area", EXPERTISE_AREAS)
    for other in db.panelists.values():
        if other["email"] == email:
            bad("Field 'email' must be globally unique.")

    row = base_entity()
    row.update({
        "full_name": full_name,
        "email": email,
        "expertise_area": expertise_area,
        "submitted_score_count": 0,
        "site_visit_count": 0,
    })
    db.panelists[row["id"]] = row
    return created(row)
