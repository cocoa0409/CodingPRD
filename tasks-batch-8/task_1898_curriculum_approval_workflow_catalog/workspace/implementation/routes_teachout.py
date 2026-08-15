"""Teach-out plans: create (nested under proposals), list/get, commit, complete."""

from flask import Blueprint, request

import calc
from db import STORE, new_record, pub, touch
from errors import ApiError
from helpers import body_fk, check_fields, get_json_body, list_response, path_param
from middleware import require_auth
from response import ok

bp = Blueprint("teachout", __name__)


@bp.post("/curriculum/proposals/<pid>/teach-out-plan")
def create_teach_out_plan(pid):
    uid, _ = require_auth({"FacultyProposer"})
    p = path_param("proposals", pid)
    body = get_json_body()
    check_fields(body, {
        "enrolled_cohort_count": ("int", True),
        "cohort_sizes": ("int_list", True),
        "last_enrolled_term_id": ("str", True),
    })
    last_term = body_fk("terms", body["last_enrolled_term_id"], "last_enrolled_term_id")
    count = body["enrolled_cohort_count"]
    sizes = body["cohort_sizes"]
    if len(sizes) != count:
        raise ApiError("ERR_VALIDATION", 400, "cohort_sizes length must equal enrolled_cohort_count")
    if any(s < 1 for s in sizes):
        raise ApiError("ERR_VALIDATION", 400, "every cohort size must be at least one")
    if p["proposal_type"] != "DEACTIVATION":
        raise ApiError("ERR_VALIDATION", 400, "teach-out plans serve DEACTIVATION proposals only")
    if p["declared_remaining_cohorts"] is None or count != p["declared_remaining_cohorts"]:
        raise ApiError("ERR_VALIDATION", 400, "enrolled_cohort_count must equal declared_remaining_cohorts")
    if uid != p["proposer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "only the proposal author may create its teach-out plan")
    if any(plan for plan in STORE["teach_out_plans"].values() if plan["proposal_id"] == p["id"]):
        raise ApiError("ERR_INVALID_STATE", 409, "a teach-out plan already exists for this proposal")
    rec = new_record()
    rec.update({
        "proposal_id": p["id"],
        "course_id": p["target_course_id"],
        "enrolled_cohort_count": count,
        "cohort_sizes": list(sizes),
        "last_enrolled_term_id": body["last_enrolled_term_id"],
        "provisional_completion_sequence": calc.provisional_completion_sequence(last_term, count),
        "committed_completion_sequence": None,
        "resource_cost_cents": None,
        "status": "DRAFT",
    })
    STORE["teach_out_plans"][rec["id"]] = rec
    return ok(pub(rec), 201)


_PLAN_FILTERS = ("proposal_id", "course_id", "last_enrolled_term_id", "status")


@bp.get("/curriculum/teach-out-plans")
def list_teach_out_plans():
    require_auth()
    records = list(STORE["teach_out_plans"].values())
    for f in _PLAN_FILTERS:
        v = request.args.get(f)
        if v is not None:
            records = [pl for pl in records if str(pl[f]) == v]
    return list_response(records, pub)


@bp.get("/curriculum/teach-out-plans/<plan_id>")
def get_teach_out_plan(plan_id):
    require_auth()
    return ok(pub(path_param("teach_out_plans", plan_id)), 200)


@bp.post("/curriculum/teach-out-plans/<plan_id>/commit")
def commit_teach_out_plan(plan_id):
    uid, _ = require_auth({"DepartmentChair"})
    plan = path_param("teach_out_plans", plan_id)
    check_fields(get_json_body(), {})
    proposal = STORE["proposals"].get(plan["proposal_id"])
    if proposal is None or uid != proposal["proposer_department_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "only the sponsoring department's chair may commit the plan")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not DRAFT")
    requested_term = STORE["terms"].get(proposal["requested_effective_term_id"])
    plan["committed_completion_sequence"] = calc.committed_completion_sequence(requested_term)
    plan["resource_cost_cents"] = calc.teach_out_resource_cost_cents(plan["cohort_sizes"])
    plan["status"] = "COMMITTED"
    touch(plan)
    return ok(pub(plan), 200)


@bp.post("/curriculum/teach-out-plans/<plan_id>/complete")
def complete_teach_out_plan(plan_id):
    require_auth({"Registrar"})
    plan = path_param("teach_out_plans", plan_id)
    check_fields(get_json_body(), {})
    if plan["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "plan is not IN_PROGRESS")
    course = STORE["courses"].get(plan["course_id"])
    if course is not None and course["status"] == "DEACTIVATING":
        course["status"] = "INACTIVE"
        touch(course)
        # exclude INCLUDED entries of this course in DRAFT/FROZEN editions
        affected_editions = set()
        for entry in STORE["catalog_entries"].values():
            if entry["course_id"] == course["id"] and entry["status"] == "INCLUDED":
                edition = STORE["catalog_editions"].get(entry["edition_id"])
                if edition is not None and edition["status"] in ("DRAFT", "FROZEN"):
                    entry["status"] = "EXCLUDED"
                    touch(entry)
                    affected_editions.add(edition["id"])
        for ed_id in affected_editions:
            edition = STORE["catalog_editions"][ed_id]
            edition["included_entry_count"] = sum(
                1 for e in STORE["catalog_entries"].values()
                if e["edition_id"] == ed_id and e["status"] == "INCLUDED"
            )
            touch(edition)
    plan["status"] = "COMPLETE"
    touch(plan)
    return ok(pub(plan), 200)
