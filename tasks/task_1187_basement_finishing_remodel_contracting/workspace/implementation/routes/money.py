"""Allowance lines and change orders (PRD §3.5)."""
from flask import Blueprint, request

from db import stores
from errors import fail
from response import ok
from serializers import ser_allowance_line, ser_change_order
from services import (
    ALLOWANCE_CO_STATES, CO_TERMINAL, line_remaining, price_delta,
    items_total_cents, release_draws, reserve_draws, supersede_proposed, touch,
)
from validation import (
    auth, require_role, get_body, v_str, v_int, v_arr, v_enum, v_item_object,
)
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner,
    require_homeowner_owner, new_entity, list_response,
)

bp = Blueprint("money", __name__)

KINDS = {"ADD", "CREDIT"}


# ---------------------------------------------------------------------------
# Allowance lines
# ---------------------------------------------------------------------------

@bp.post("/api/projects/<project_id>/allowance-lines")
def create_allowance_line(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    if project["status"] not in ALLOWANCE_CO_STATES:
        fail("ERR_PROJECT_STATE_FORBIDS", "Project status does not permit allowance lines")
    # Priority 25: non-negative budget.
    raw_budget = body.get("budgeted_cents")
    if isinstance(raw_budget, int) and not isinstance(raw_budget, bool) and raw_budget < 0:
        fail("ERR_INVALID_CLAIM_AMOUNT", "budgeted_cents must be non-negative")
    name = v_str(body, "name")
    budgeted = v_int(body, "budgeted_cents")
    e = new_entity({
        "project_id": project_id,
        "name": name,
        "budgeted_cents": budgeted,
        "reserved_cents": 0,
        "drawn_cents": 0,
        "selected": False,
        "actual_cents": 0,
    })
    stores["allowance_lines"][e["id"]] = e
    return ok(ser_allowance_line(e), 201)


@bp.get("/api/projects/<project_id>/allowance-lines")
def list_allowance_lines(project_id):
    auth()
    project_or_404(project_id)
    items = [l for l in stores["allowance_lines"].values() if l["project_id"] == project_id]
    return list_response(items, ser_allowance_line)


@bp.post("/api/allowance-lines/<line_id>/select")
def select_allowance_line(line_id):
    role, uid = auth()
    require_role(role, "Homeowner")
    line = get_or_404("allowance_lines", line_id, "AllowanceLine")
    project = project_or_404(line["project_id"])
    require_homeowner_owner(project, uid)
    body = get_body()
    actual = v_int(body, "actual_cents")
    line["selected"] = True
    line["actual_cents"] = actual
    touch(line)
    # Selection recomputes the project price and increments Project.version.
    touch(project)
    return ok(ser_allowance_line(line))


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------

def _scope_items_shape(items):
    for item in items:
        v_item_object(item, "scope_items")
        v_str(item, "description")
        v_int(item, "qty")
        v_int(item, "unit_cost_cents")


def _draws_shape(draws):
    for d in draws:
        v_item_object(d, "allowance_draws")
        v_str(d, "allowance_line_id")
        v_int(d, "amount_cents")


def _release_and_terminal(co, status):
    release_draws(co)
    co["status"] = status
    touch(co)
    project = project_or_404(co["project_id"])
    touch(project)
    return co


@bp.post("/api/projects/<project_id>/change-orders")
def create_change_order(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    raw_draws = body.get("allowance_draws")
    draws_list = raw_draws if isinstance(raw_draws, list) else []
    # Priority 5: allowance_draws[].allowance_line_id must resolve to a line
    # of this project.
    draw_lines = []
    for d in draws_list:
        if not isinstance(d, dict):
            continue
        lid = d.get("allowance_line_id")
        if isinstance(lid, str):
            line = stores["allowance_lines"].get(lid)
            if line is None or line["project_id"] != project_id:
                fail("ERR_REFERENCED_NOT_FOUND", "allowance_line_id does not reference an existing allowance line of this project")
            draw_lines.append((d, line))
    # Priority 6 (OCC): expected_project_version must equal Project.version.
    epv = body.get("expected_project_version")
    if isinstance(epv, int) and not isinstance(epv, bool) and epv != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION", "expected_project_version does not match current Project.version")
    # Priority 7: project state gate.
    if project["status"] not in ALLOWANCE_CO_STATES:
        fail("ERR_PROJECT_STATE_FORBIDS", "Project status does not permit change orders")
    # Priority 24: draw limits.
    kind_raw = body.get("kind")
    per_line_totals = {}
    for d, line in draw_lines:
        amt = d.get("amount_cents")
        if isinstance(amt, int) and not isinstance(amt, bool):
            per_line_totals[line["id"]] = per_line_totals.get(line["id"], 0) + amt
            if amt < 1:
                fail("ERR_ALLOWANCE_OVERDRAW", "Draw amount must be at least 1")
    for d, line in draw_lines:
        amt = d.get("amount_cents")
        if isinstance(amt, int) and not isinstance(amt, bool):
            if per_line_totals[line["id"]] > line_remaining(line):
                fail("ERR_ALLOWANCE_OVERDRAW", "Draw exceeds the line's remaining_cents")
    raw_items = body.get("scope_items")
    items_ok = isinstance(raw_items, list) and all(
        isinstance(i, dict)
        and isinstance(i.get("qty"), int) and not isinstance(i.get("qty"), bool)
        and isinstance(i.get("unit_cost_cents"), int) and not isinstance(i.get("unit_cost_cents"), bool)
        for i in raw_items
    )
    if items_ok:
        items_total = items_total_cents(raw_items)
        draws_total = sum(
            d["amount_cents"] for d, _ in draw_lines
            if isinstance(d.get("amount_cents"), int) and not isinstance(d.get("amount_cents"), bool)
        )
        if draws_total > items_total:
            fail("ERR_ALLOWANCE_OVERDRAW", "Draws total exceeds the items total")
    if kind_raw == "CREDIT" and len(draws_list) > 0:
        fail("ERR_ALLOWANCE_OVERDRAW", "CREDIT orders must carry an empty allowance_draws array")
    # Priority 25: fiscal floors on scope items.
    if isinstance(raw_items, list):
        for i in raw_items:
            if not isinstance(i, dict):
                continue
            q = i.get("qty")
            u = i.get("unit_cost_cents")
            if isinstance(q, int) and not isinstance(q, bool) and q < 1:
                fail("ERR_INVALID_CLAIM_AMOUNT", "Scope item qty must be at least 1")
            if isinstance(u, int) and not isinstance(u, bool) and u < 0:
                fail("ERR_INVALID_CLAIM_AMOUNT", "Scope item unit_cost_cents must be non-negative")
    # Priority 26: request shape.
    scope_description = v_str(body, "scope_description")
    kind = v_enum(body, "kind", KINDS)
    scope_items = v_arr(body, "scope_items")
    _scope_items_shape(scope_items)
    allowance_draws = v_arr(body, "allowance_draws")
    _draws_shape(allowance_draws)
    v_int(body, "expected_project_version")
    delta, _, _ = price_delta(kind, scope_items, allowance_draws)
    # Creation ripples: existing PROPOSED orders supersede with draws released.
    supersede_proposed(project)
    e = new_entity({
        "project_id": project_id,
        "scope_description": scope_description,
        "kind": kind,
        "scope_items": scope_items,
        "allowance_draws": allowance_draws,
        "price_delta_cents": delta,
        "status": "PROPOSED",
    })
    stores["change_orders"][e["id"]] = e
    reserve_draws(e)
    touch(project)
    return ok(ser_change_order(e), 201)


@bp.get("/api/projects/<project_id>/change-orders")
def list_change_orders(project_id):
    auth()
    project_or_404(project_id)
    items = [c for c in stores["change_orders"].values() if c["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, ser_change_order)


def _load_co_for_decision(co_id, role, uid, owner_check):
    co = get_or_404("change_orders", co_id, "ChangeOrder")
    project = project_or_404(co["project_id"])
    owner_check(project, uid)
    if co["status"] in CO_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Change order is terminal and refuses further mutation")
    if co["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED change order can be decided")
    return co, project


@bp.post("/api/change-orders/<co_id>/approve")
def approve_change_order(co_id):
    role, uid = auth()
    require_role(role, "Homeowner")
    co, project = _load_co_for_decision(co_id, role, uid, require_homeowner_owner)
    # Priority 24: each draw's line must still show remaining >= draw amount.
    for draw in co["allowance_draws"]:
        line = stores["allowance_lines"].get(draw["allowance_line_id"])
        if line is not None and line_remaining(line) < draw["amount_cents"]:
            fail("ERR_ALLOWANCE_OVERDRAW", "Draw exceeds the line's remaining_cents at approval time")
    # Convert each draw from reserved to drawn; remaining_cents unchanged.
    for draw in co["allowance_draws"]:
        line = stores["allowance_lines"].get(draw["allowance_line_id"])
        if line is not None:
            line["reserved_cents"] -= draw["amount_cents"]
            line["drawn_cents"] += draw["amount_cents"]
            touch(line)
    co["status"] = "APPROVED"
    touch(co)
    touch(project)
    return ok(ser_change_order(co))


@bp.post("/api/change-orders/<co_id>/reject")
def reject_change_order(co_id):
    role, uid = auth()
    require_role(role, "Homeowner")
    co, project = _load_co_for_decision(co_id, role, uid, require_homeowner_owner)
    body = get_body()
    v_str(body, "reason", required=False)
    _release_and_terminal(co, "REJECTED")
    return ok(ser_change_order(co))


@bp.post("/api/change-orders/<co_id>/withdraw")
def withdraw_change_order(co_id):
    role, uid = auth()
    require_role(role, "Contractor")
    co, project = _load_co_for_decision(co_id, role, uid, require_contractor_owner)
    _release_and_terminal(co, "WITHDRAWN")
    return ok(ser_change_order(co))
