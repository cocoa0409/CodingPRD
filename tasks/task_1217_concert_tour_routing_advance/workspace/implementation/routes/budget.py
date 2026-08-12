"""BudgetLine endpoints (PRD 3.7): create/list/get/patch plus flat
fetch/search. Updating a line recomputes the show's projected cost."""
from flask import Blueprint, request

from db import store, new_entity, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, get_body, v_str, v_int, v_enum,
)
from response import success_object, list_response
from services import (
    BUDGET_CATEGORIES, PROJECTION_SET,
    budget_line_json, resolve_tour, resolve_show, resolve_budget_line,
    recompute_show_projection, recompute_tour_financials,
)

bp = Blueprint("budget", __name__)

TM_ONLY = frozenset({ROLE_TOUR_MANAGER})
COMMITTED_SHOW_STATES = ("CONFIRMED", "ADVANCED", "PERFORMED", "SETTLED")


@bp.post("/tours/<tourId>/shows/<showId>/budget-lines")
def create_budget_line(tourId, showId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    b = get_body()
    category = v_enum(b, "category", BUDGET_CATEGORIES)
    description = v_str(b, "description")
    estimated_cents = v_int(b, "estimated_cents", minv=0)
    actual_cents = v_int(b, "actual_cents", required=False, minv=0)
    line = new_entity()
    line.update(
        {
            "show_id": s["id"],
            "category": category,
            "description": description,
            "estimated_cents": estimated_cents,
            "actual_cents": actual_cents,
            # is_committed is set at creation from the show's status.
            "is_committed": s["status"] in COMMITTED_SHOW_STATES,
        }
    )
    store["budget_lines"][line["id"]] = line
    if s["status"] in PROJECTION_SET and recompute_show_projection(s):
        touch(s)
    if recompute_tour_financials(t):
        touch(t)
    return success_object(budget_line_json(line), 201)


@bp.get("/tours/<tourId>/shows/<showId>/budget-lines")
def list_budget_lines(tourId, showId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    category = request.args.get("category")
    items = [l for l in store["budget_lines"].values() if l["show_id"] == s["id"]]
    if category is not None:
        items = [l for l in items if l["category"] == category]
    return list_response(items, budget_line_json)


@bp.get("/tours/<tourId>/shows/<showId>/budget-lines/<lineId>")
def get_budget_line(tourId, showId, lineId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    return success_object(budget_line_json(resolve_budget_line(s, lineId)))


@bp.patch("/tours/<tourId>/shows/<showId>/budget-lines/<lineId>")
def patch_budget_line(tourId, showId, lineId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    line = resolve_budget_line(s, lineId)
    b = get_body()
    if "estimated_cents" in b:
        line["estimated_cents"] = v_int(b, "estimated_cents", minv=0)
    if "actual_cents" in b:
        if b["actual_cents"] is None:
            line["actual_cents"] = None
        else:
            line["actual_cents"] = v_int(b, "actual_cents", minv=0)
    touch(line)
    # Updating a line recomputes the show's projected cost.
    if s["status"] in PROJECTION_SET and recompute_show_projection(s):
        touch(s)
    if recompute_tour_financials(t):
        touch(t)
    return success_object(budget_line_json(line))


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/budget-lines/<lineId>")
def flat_get_budget_line(lineId):
    authenticate(READ_ROLES)
    line = store["budget_lines"].get(lineId)
    if line is None:
        raise ApiError("ERR_NOT_FOUND", 404, "BudgetLine not found")
    return success_object(budget_line_json(line))


@bp.get("/tours/budget-lines")
def flat_search_budget_lines():
    authenticate(READ_ROLES)
    show_id = request.args.get("show_id")
    items = list(store["budget_lines"].values())
    if show_id is not None:
        items = [l for l in items if l["show_id"] == show_id]
    return list_response(items, budget_line_json)
