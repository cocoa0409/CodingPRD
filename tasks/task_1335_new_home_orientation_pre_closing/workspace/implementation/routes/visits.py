"""Re-inspection visits: scheduling (half-open overlap + daily capacity) and
completion applying PASS/FAIL outcomes (PRD §3.5)."""
from flask import Blueprint, request

import db
from db import deficiency_items, homes, reps, visits
from errors import (
    err_invalid_state, err_not_found, err_referenced_entity_not_found,
    err_rep_inactive, err_schedule_in_past, err_validation, err_visit_too_early,
)
from logic import (
    DEFAULT_VISIT_DURATION_MINUTES, recompute_home, visit_capacity_check,
    visit_overlap_check,
)
from middleware import ROLE_BUYER, ROLE_MANAGER, ROLE_REP, require_roles
from response import paginate, success_list, success_object
from validation import json_body, opt_int, req_datetime_str, req_str

bp = Blueprint("visits", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)
OUTCOMES = ("PASS", "FAIL")


def _get_visit_or_404(visit_id):
    visit = visits.get(visit_id)
    if visit is None:
        raise err_not_found("Re-inspection visit %s not found." % visit_id)
    return visit


@bp.post("/api/reinspection-visits")
def create_visit():
    require_roles(ROLE_REP)
    body = json_body()
    home_id = req_str(body, "home_id")
    rep_id = req_str(body, "rep_id")
    scheduled_start = req_datetime_str(body, "scheduled_start")
    duration = opt_int(body, "duration_minutes", minimum=1)

    home = homes.get(home_id)
    rep = reps.get(rep_id)
    if home is None or rep is None:
        raise err_referenced_entity_not_found("home_id or rep_id does not resolve.")
    if duration is None:
        duration = DEFAULT_VISIT_DURATION_MINUTES
    start_dt = db.parse_dt(scheduled_start)

    if not start_dt > db.now():
        raise err_schedule_in_past()
    if not rep["active"]:
        raise err_rep_inactive()
    visit_overlap_check(rep_id, start_dt, duration)
    visit_capacity_check(rep, start_dt, duration)

    rec = db.stamp({
        "id": db.new_id(),
        "home_id": home_id,
        "rep_id": rep_id,
        "scheduled_start": scheduled_start,
        "duration_minutes": duration,
        "status": "SCHEDULED",
    })
    visits[rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.get("/api/reinspection-visits/<visit_id>")
def get_visit(visit_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_visit_or_404(visit_id)))


@bp.get("/api/reinspection-visits")
def list_visits():
    require_roles(*READ_ROLES)
    items = list(visits.values())
    for f in ("home_id", "rep_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(x) for x in page], pagination)


@bp.post("/api/reinspection-visits/<visit_id>/complete")
def complete_visit(visit_id):
    require_roles(ROLE_REP)
    body = json_body()
    results = body.get("results")
    if not isinstance(results, list):
        raise err_validation("Field 'results' is required and must be an array.")
    parsed = []
    for entry in results:
        if not isinstance(entry, dict):
            raise err_validation("Each results entry must be an object.")
        item_id = entry.get("deficiency_item_id")
        outcome = entry.get("outcome")
        if not isinstance(item_id, str) or not item_id:
            raise err_validation("Each results entry requires 'deficiency_item_id'.")
        if outcome not in OUTCOMES:
            raise err_validation("Each results entry outcome must be PASS or FAIL.")
        parsed.append((item_id, outcome))

    visit = _get_visit_or_404(visit_id)
    if visit["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED visit can be completed.")
    # Every entry must reference an item of this home in READY_FOR_REINSPECTION;
    # validate all before applying any (atomicity).
    referenced = []
    for item_id, outcome in parsed:
        item = deficiency_items.get(item_id)
        if item is None or item["home_id"] != visit["home_id"] \
                or item["status"] != "READY_FOR_REINSPECTION":
            raise err_invalid_state(
                "results must reference items of this home in READY_FOR_REINSPECTION."
            )
        referenced.append((item, outcome))
    if db.now() < db.parse_dt(visit["scheduled_start"]):
        raise err_visit_too_early()

    for item, outcome in referenced:
        item["status"] = "VERIFIED" if outcome == "PASS" else "IN_REPAIR"
        db.touch(item)
    visit["status"] = "COMPLETED"
    db.touch(visit)
    recompute_home(homes[visit["home_id"]])
    return success_object(db.public(visit))
