"""Shared selection creation, fork resolution and compensation logic."""
from core import ApiError, base_record, db, num, parse_date, touch
from calc import composite_score
from domain import (recompute_plan, recompute_plans_touching_site,
                    recompute_site, refresh_employee_derived, stale_analyses,
                    stale_disclosures)

LIVE_SELECTION_STATUSES = ("PROPOSED", "SELECTED", "EXEMPTED", "SEPARATED")


# ---------------------------------------------------------------------------
# Creation guards (ladder rungs 22, 23, 25)
# ---------------------------------------------------------------------------
def guard_warn_window(employee, proposed_date):
    for notice in db.notices.values():
        if notice["status"] != "ISSUED" or notice["site_id"] != employee["site_id"]:
            continue
        start = parse_date(notice["window_start_date"])
        end = parse_date(notice["window_end_date"])
        if start is None or end is None:
            continue
        if notice["jurisdiction"] == "FEDERAL":
            inside = start <= proposed_date < end
        else:
            inside = start <= proposed_date <= end
        if inside:
            raise ApiError("ERR_WARN_WINDOW_COLLISION", 409)


def guard_duplicate(plan_id, employee_id):
    for selection in db.selections.values():
        if (selection["plan_id"] == plan_id
                and selection["employee_id"] == employee_id
                and selection["status"] in LIVE_SELECTION_STATUSES):
            raise ApiError("ERR_DUPLICATE_SELECTION", 409)


def guard_scores(plan, scores):
    locked = set(c["criterion_code"] for c in plan["selection_criteria"])
    supplied = set(row["criterion_code"] for row in scores)
    if locked != supplied or len(supplied) != len(scores):
        raise ApiError("ERR_CRITERION_SCORE_MISMATCH", 422)


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def create_selection(plan, employee, proposed_date, scores):
    record = base_record()
    record.update({
        "plan_id": plan["id"],
        "employee_id": employee["id"],
        "proposed_separation_date": proposed_date.isoformat(),
        "criterion_scores": [dict(row) for row in scores],
        "composite_score": num(composite_score(plan["selection_criteria"], scores)),
        "status": "PROPOSED",
        "exemption_reason": None,
        "rescind_reason": None,
        "notice_status": "NOT_DELIVERED",
        "notice_script_code": None,
        "notice_delivered_utc": None,
        "notice_days_before_separation": None,
        "short_notice_acknowledged": False,
    })
    db.selections[record["id"]] = record
    return record


# ---------------------------------------------------------------------------
# Fork resolution
# ---------------------------------------------------------------------------
def apply_select(selection):
    """PROPOSED -> SELECTED with the four-hop cascade."""
    plan = db.plans[selection["plan_id"]]
    selection["status"] = "SELECTED"
    touch(selection)

    employee = db.employees.get(selection["employee_id"])
    site = None
    if employee is not None:
        if employee["employment_status"] == "ACTIVE":
            employee["employment_status"] = "PENDING_SEPARATION"
        employee["separation_date"] = selection["proposed_separation_date"]
        refresh_employee_derived(employee)
        touch(employee)
        site = db.sites.get(employee["site_id"])

    if site is not None:
        recompute_site(site)
        recompute_plans_touching_site(site["id"])

    recompute_plan(plan)
    stale_disclosures(plan)
    stale_analyses(plan["id"])


def apply_exempt(selection, exemption_reason):
    """PROPOSED -> EXEMPTED: no downstream entity is mutated."""
    plan = db.plans[selection["plan_id"]]
    selection["status"] = "EXEMPTED"
    selection["exemption_reason"] = exemption_reason
    touch(selection)

    recompute_plan(plan)
    stale_disclosures(plan)
    stale_analyses(plan["id"])


def apply_rescind(selection, rescind_reason):
    """SELECTED -> RESCINDED with the three-hop compensation chain."""
    plan = db.plans[selection["plan_id"]]
    selection["status"] = "RESCINDED"
    selection["rescind_reason"] = rescind_reason
    touch(selection)

    employee = db.employees.get(selection["employee_id"])
    site = None
    if employee is not None:
        if employee["employment_status"] == "PENDING_SEPARATION":
            employee["employment_status"] = "ACTIVE"
        employee["separation_date"] = None
        refresh_employee_derived(employee)
        touch(employee)
        site = db.sites.get(employee["site_id"])

    if site is not None:
        recompute_site(site)
        recompute_plans_touching_site(site["id"])

    recompute_plan(plan)
    stale_disclosures(plan)
    stale_analyses(plan["id"])
