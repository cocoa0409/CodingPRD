"""Capital projects, the reinvestment run and the logical-clock test hook."""

from flask import Blueprint

import auth
import clock
import engine
import guards
import response
import serializers
import store
import validators as v
from auth import CLUB_ADMIN, PARK_MANAGER
from errors import fail

bp = Blueprint("capital", __name__)

CATEGORIES = ("SAFETY", "UTILITY", "AMENITY", "EXPANSION")
SAFE_WHILE_NON_COMPLIANT = ("SAFETY", "UTILITY")


@bp.post("/capital-projects")
def propose_project():
    actor = auth.authorize(PARK_MANAGER, CLUB_ADMIN)
    data = v.body()
    raw_park = v.raw_id(data, "park_id")
    auth.require_park_manager(actor, raw_park if raw_park else None)
    guards.maybe("parks", raw_park)
    park_id = v.req_id(data, "park_id")
    title = v.req_str(data, "title")
    category = v.req_enum(data, "category", CATEGORIES)
    requested_cost = v.req_int(data, "requested_cost_cents", minimum=0)
    fiscal_year = v.req_int(data, "fiscal_year", minimum=0)

    park = guards.fetch("parks", park_id)
    row = store.base_row()
    row.update({
        "park_id": park_id,
        "title": title,
        "category": category,
        "requested_cost_cents": requested_cost,
        "fiscal_year": fiscal_year,
        "status": "PROPOSED",
        "priority_score": 0,
        "funded_amount_cents": 0,
        "requested_by_user_id": actor.user_id,
        "decided_by_user_id": None,
    })
    row["priority_score"] = engine.project_priority(row, park)
    store.insert("capital_projects", row)
    return response.created(serializers.capital_project(row))


@bp.get("/capital-projects/<project_id>")
def read_project(project_id):
    auth.authorize(CLUB_ADMIN, PARK_MANAGER)
    row = guards.fetch("capital_projects", project_id)
    return response.ok(serializers.capital_project(row))


@bp.post("/capital-projects/<project_id>/decision")
def decide_project(project_id):
    actor = auth.authorize(CLUB_ADMIN)
    project = guards.fetch("capital_projects", project_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("APPROVE", "REJECT"))
    expected_version = v.req_int(data, "expected_park_version", minimum=0)
    note = v.opt_str(data, "decision_note")
    park = guards.fetch("parks", project["park_id"])
    if expected_version != park.get("version"):
        fail("ERR_STALE_PARK_VERSION",
             "expected_park_version does not match the park version")
    if project["status"] != "PROPOSED":
        fail("ERR_INVALID_REQUEST", "only a PROPOSED project may be decided")
    if actor.user_id == project.get("requested_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the approver may not be the proposer of the project")
    if (decision == "APPROVE"
            and park["amenity_compliance_status"] == "NON_COMPLIANT"
            and project["category"] not in SAFE_WHILE_NON_COMPLIANT):
        fail("ERR_INVALID_REQUEST",
             "a NON_COMPLIANT park may only fund SAFETY or UTILITY work")

    project["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    project["decided_by_user_id"] = actor.user_id
    if note is not None:
        project["_decision_note"] = note
    project["priority_score"] = engine.project_priority(project, park)
    store.touch(project)
    store.touch(park)
    return response.ok(serializers.capital_project(project))


@bp.post("/ops/reinvestment-runs")
def reinvestment_run():
    auth.authorize(CLUB_ADMIN)
    data = v.body()
    fiscal_year = v.req_int(data, "fiscal_year", minimum=0)
    budget = v.req_int(data, "budget_cents", minimum=0)

    candidates = []
    for project in store.ordered(store.all_rows("capital_projects")):
        if project["status"] not in ("APPROVED", "DEFERRED"):
            continue
        if project["fiscal_year"] != fiscal_year:
            continue
        park = store.get("parks", project["park_id"])
        if park is None:
            continue
        if park["park_status"] not in ("OPEN", "SEASONAL_CLOSED", "MAINTENANCE_HOLD"):
            continue
        score = engine.project_priority(project, park)
        if project.get("priority_score") != score:
            project["priority_score"] = score
            store.touch(project)
        candidates.append((project, park))

    candidates.sort(key=lambda pair: (-pair[0]["priority_score"],
                                      pair[0].get("created_at") or "",
                                      pair[0].get("_seq") or 0))

    remaining = budget
    funded = 0
    deferred = 0
    funded_parks = []
    for project, park in candidates:
        if project["requested_cost_cents"] <= remaining:
            project["status"] = "FUNDED"
            project["funded_amount_cents"] = project["requested_cost_cents"]
            remaining -= project["requested_cost_cents"]
            funded += 1
            if park["id"] not in funded_parks:
                funded_parks.append(park["id"])
        else:
            project["status"] = "DEFERRED"
            project["funded_amount_cents"] = 0
            deferred += 1
        store.touch(project)

    for park_id in funded_parks:
        park = store.get("parks", park_id)
        if park is None:
            continue
        engine.recompute_funded_capital(park, fiscal_year)
        store.touch(park)

    return response.ok({
        "fiscal_year": fiscal_year,
        "budget_cents": budget,
        "allocated_cents": budget - remaining,
        "unallocated_cents": remaining,
        "funded_project_count": funded,
        "deferred_project_count": deferred,
    })


# ---------------------------------------------------------------------------
# logical clock test hook (exempt from ladder rung 1)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authorize_clock()
    data = v.body()
    if not v.present(data, "current_utc"):
        fail("ERR_INVALID_REQUEST", "current_utc is required")
    instant = clock.parse_instant(data.get("current_utc"))
    clock.set_now(instant)
    return response.ok({"current_utc": clock.fmt_instant(instant)})
