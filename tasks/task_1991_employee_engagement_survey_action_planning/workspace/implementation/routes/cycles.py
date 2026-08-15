"""Survey cycles and cycle items (PRD §3.3, §3.5)."""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, request

from db import db, stamp_new, touch, public, parse_ts
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_DUTY_SEGREGATION, ERR_DUPLICATE,
    ERR_CYCLE_ALREADY_OPEN, ERR_INSUFFICIENT_ITEMS, ERR_STALE_VERSION,
    ERR_WINDOW_VIOLATION,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body,
    require_fields, optional_fields_present, as_non_empty_string, as_enum,
    as_int, as_number,
)
from response import success_object, success_list
from services.calculations import run_eligibility_sweep
from services.domain import (
    recompute_cycle_counters, close_cycle,
    generate_snapshots, run_reminder_sweep,
)

bp = Blueprint("cycles", __name__)

CYCLE_KINDS = {"CENSUS", "PULSE"}
CYCLE_STATUSES = {"DRAFT", "CONFIGURED", "OPEN", "CLOSED", "SCORING", "REPORTED", "ARCHIVED"}


def _get_cycle_or_404(cycle_id):
    cycle = db.survey_cycles.get(cycle_id)
    if cycle is None:
        raise err(ERR_NOT_FOUND, "survey cycle not found", 404)
    return cycle


def _get_cycle_item_or_404(item_id):
    ci = db.cycle_items.get(item_id)
    if ci is None:
        raise err(ERR_NOT_FOUND, "cycle item not found", 404)
    return ci


# ---------------------------------------------------------------------------
# Cycles CRUD
# ---------------------------------------------------------------------------

@bp.post("/engagement/survey-cycles")
def create_cycle():
    user_id, role = require_roles("HRAdmin")
    body = get_json_body()
    optional_fields_present(body, {
        "label", "cycle_kind", "bank_id", "opens_at", "closes_at",
        "min_n_default", "sampling_ratio",
    })
    require_fields(body, ["label", "cycle_kind", "bank_id", "opens_at", "closes_at"])
    label = as_non_empty_string(body["label"], "label")
    cycle_kind = as_enum(body["cycle_kind"], "cycle_kind", CYCLE_KINDS)
    bank_id = as_non_empty_string(body["bank_id"], "bank_id")
    try:
        opens_at = parse_ts(body["opens_at"])
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "opens_at must be an ISO 8601 timestamp", 400)
    try:
        closes_at = parse_ts(body["closes_at"])
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "closes_at must be an ISO 8601 timestamp", 400)

    if bank_id not in db.item_banks:
        raise err(ERR_REFERENCE_NOT_FOUND, "bank_id does not exist", 404)

    min_n_default = body.get("min_n_default")
    if min_n_default is not None:
        min_n_default = as_int(min_n_default, "min_n_default")
        if min_n_default < 3 or min_n_default > 20:
            raise err(ERR_VALIDATION, "min_n_default must be between 3 and 20", 400)
    else:
        min_n_default = 5

    sampling_ratio = body.get("sampling_ratio")
    if sampling_ratio is not None:
        as_number(sampling_ratio, "sampling_ratio")
        try:
            sr = Decimal(str(sampling_ratio))
        except InvalidOperation:
            raise err(ERR_VALIDATION, "sampling_ratio must be a number", 400)
        if sr <= 0 or sr > Decimal("1.0"):
            raise err(ERR_VALIDATION, "sampling_ratio must be in (0, 1.0]", 400)
        if -sr.as_tuple().exponent > 2:
            raise err(ERR_VALIDATION, "sampling_ratio carries at most 2 decimal places", 400)
        sampling_ratio = float(sr)
    else:
        sampling_ratio = 1.0

    cycle = stamp_new({
        "label": label,
        "cycle_kind": cycle_kind,
        "bank_id": bank_id,
        "opens_at": body["opens_at"],
        "closes_at": body["closes_at"],
        "_opens_at": opens_at,
        "_closes_at": closes_at,
        "status": "DRAFT",
        "min_n_default": min_n_default,
        "sampling_ratio": sampling_ratio,
        "invited_count": 0,
        "submitted_count": 0,
        "partial_count": 0,
        "response_rate": None,
        "attrition_risk": None,
        # Record the creating HRAdmin for the segregation-of-duties check (§2.1).
        "_created_by": user_id,
    })
    db.survey_cycles[cycle["id"]] = cycle
    return success_object(public(cycle), 201)


@bp.get("/engagement/survey-cycles")
def list_cycles():
    require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    limit, offset = parse_pagination({"status", "cycle_kind", "bank_id"})
    status = request.args.get("status")
    kind = request.args.get("cycle_kind")
    bank_id = request.args.get("bank_id")
    items = list(db.survey_cycles.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if kind is not None:
        items = [c for c in items if c["cycle_kind"] == kind]
    if bank_id is not None:
        items = [c for c in items if c["bank_id"] == bank_id]
    page, total = paginate(items, limit, offset)
    return success_list([public(c) for c in page], limit, offset, total)


@bp.get("/engagement/survey-cycles/<cycle_id>")
def get_cycle(cycle_id):
    require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    cycle = _get_cycle_or_404(cycle_id)
    return success_object(public(cycle))


# ---------------------------------------------------------------------------
# Cycle items
# ---------------------------------------------------------------------------

@bp.post("/engagement/survey-cycles/<cycle_id>/items")
def pin_cycle_item(cycle_id):
    require_roles("HRAdmin")
    cycle = _get_cycle_or_404(cycle_id)
    body = get_json_body()
    optional_fields_present(body, {"item_id", "pinned_weight", "display_order"})
    require_fields(body, ["item_id", "pinned_weight", "display_order"])
    item_id = as_non_empty_string(body["item_id"], "item_id")
    as_number(body["pinned_weight"], "pinned_weight")
    try:
        pinned_weight = Decimal(str(body["pinned_weight"]))
    except InvalidOperation:
        raise err(ERR_VALIDATION, "pinned_weight must be a number", 400)
    display_order = as_int(body["display_order"], "display_order")
    if display_order < 1:
        raise err(ERR_VALIDATION, "display_order is 1-based", 400)

    if item_id not in db.survey_items:
        raise err(ERR_REFERENCE_NOT_FOUND, "item_id does not exist", 404)

    if cycle["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  f"cannot pin items into a cycle in status {cycle['status']}", 409)

    for ci in db.cycle_items.values():
        if ci["cycle_id"] != cycle["id"]:
            continue
        if ci["display_order"] == display_order:
            raise err(ERR_DUPLICATE, "display_order must be unique within cycle", 409)
        if ci["item_id"] == item_id:
            raise err(ERR_DUPLICATE, "item_id may be pinned only once per cycle", 409)

    ci = stamp_new({
        "cycle_id": cycle["id"],
        "item_id": item_id,
        "pinned_weight": float(pinned_weight),
        "display_order": display_order,
    })
    db.cycle_items[ci["id"]] = ci
    # Pinning increments the cycle's version (§2.10).
    touch(cycle)
    return success_object(public(ci), 201)


@bp.get("/engagement/survey-cycles/<cycle_id>/items")
def list_cycle_items(cycle_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    cycle = _get_cycle_or_404(cycle_id)
    limit, offset = parse_pagination(set())
    items = [ci for ci in db.cycle_items.values() if ci["cycle_id"] == cycle["id"]]
    items.sort(key=lambda ci: ci["display_order"])
    page, total = paginate(items, limit, offset)
    return success_list([public(ci) for ci in page], limit, offset, total)


@bp.get("/engagement/cycle-items")
def list_cycle_items_global():
    require_roles("HRAdmin", "PeopleAnalyst")
    limit, offset = parse_pagination({"cycle_id", "item_id"})
    cycle_id = request.args.get("cycle_id")
    item_id = request.args.get("item_id")
    items = list(db.cycle_items.values())
    if cycle_id is not None:
        items = [ci for ci in items if ci["cycle_id"] == cycle_id]
    if item_id is not None:
        items = [ci for ci in items if ci["item_id"] == item_id]
    page, total = paginate(items, limit, offset)
    return success_list([public(ci) for ci in page], limit, offset, total)


@bp.get("/engagement/cycle-items/<item_id>")
def get_cycle_item(item_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    ci = _get_cycle_item_or_404(item_id)
    return success_object(public(ci))


# ---------------------------------------------------------------------------
# Cycle state transitions
# ---------------------------------------------------------------------------

@bp.post("/engagement/survey-cycles/<cycle_id>/configure")
def configure_cycle(cycle_id):
    require_roles("HRAdmin")
    cycle = _get_cycle_or_404(cycle_id)
    body = get_json_body()
    optional_fields_present(body, {"expected_cycle_version"})
    require_fields(body, ["expected_cycle_version"])
    expected = as_int(body["expected_cycle_version"], "expected_cycle_version")

    if cycle["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  f"cannot configure cycle in status {cycle['status']}", 409)

    items = [ci for ci in db.cycle_items.values() if ci["cycle_id"] == cycle["id"]]
    if len(items) < 3:
        raise err(ERR_INSUFFICIENT_ITEMS,
                  "configure requires at least 3 cycle items", 422)
    if not cycle["_closes_at"] > cycle["_opens_at"]:
        raise err(ERR_WINDOW_VIOLATION,
                  "closes_at must be strictly after opens_at", 422)
    bank = db.item_banks.get(cycle["bank_id"])
    if bank is None or bank["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "linked item bank is not ACTIVE", 409)

    # OCC runs last (§2.8).
    if expected != cycle["version"]:
        raise err(ERR_STALE_VERSION, "expected_cycle_version mismatch", 412)

    cycle["status"] = "CONFIGURED"
    touch(cycle)
    return success_object(public(cycle))


@bp.post("/engagement/survey-cycles/<cycle_id>/open")
def open_cycle(cycle_id):
    require_roles("HRAdmin")
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "CONFIGURED":
        raise err(ERR_INVALID_STATE,
                  f"cannot open cycle in status {cycle['status']}", 409)
    if db.clock < cycle["_opens_at"]:
        raise err(ERR_INVALID_STATE, "cycle cannot open before opens_at", 409)
    for other in db.survey_cycles.values():
        if other["id"] != cycle["id"] and other["status"] == "OPEN":
            raise err(ERR_CYCLE_ALREADY_OPEN,
                      "another survey cycle is already OPEN", 409)

    cycle["status"] = "OPEN"
    touch(cycle)
    run_eligibility_sweep(cycle)
    recompute_cycle_counters(cycle)
    return success_object(public(cycle))


@bp.post("/engagement/survey-cycles/<cycle_id>/close")
def close_cycle_endpoint(cycle_id):
    require_roles("HRAdmin")
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "OPEN":
        raise err(ERR_INVALID_STATE,
                  f"cannot close cycle in status {cycle['status']}", 409)
    # HRAdmin path is allowed at any time after open.
    close_cycle(cycle)
    return success_object(public(cycle))


@bp.post("/engagement/survey-cycles/<cycle_id>/score")
def score_cycle(cycle_id):
    user_id, role = require_roles("PeopleAnalyst")
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "CLOSED":
        raise err(ERR_INVALID_STATE,
                  f"cannot score cycle in status {cycle['status']}", 409)
    # Segregation of duties: the HRAdmin who created the cycle may not score it.
    if cycle.get("_created_by") == user_id:
        raise err(ERR_DUTY_SEGREGATION,
                  "cycle creator may not perform scoring", 403)
    cycle["status"] = "SCORING"
    touch(cycle)
    generate_snapshots(cycle)
    return success_object(public(cycle))


@bp.post("/engagement/survey-cycles/<cycle_id>/publish")
def publish_cycle(cycle_id):
    require_roles("HRAdmin")
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "SCORING":
        raise err(ERR_INVALID_STATE,
                  f"cannot publish cycle in status {cycle['status']}", 409)
    snaps = [s for s in db.report_snapshots.values() if s["cycle_id"] == cycle["id"]]
    for s in snaps:
        if s.get("generation", 0) < 1:
            raise err(ERR_INVALID_STATE, "snapshot generation below 1", 409)
    cycle["status"] = "REPORTED"
    touch(cycle)
    return success_object(public(cycle))


@bp.post("/engagement/survey-cycles/<cycle_id>/archive")
def archive_cycle(cycle_id):
    require_roles("HRAdmin")
    cycle = _get_cycle_or_404(cycle_id)
    if cycle["status"] != "REPORTED":
        raise err(ERR_INVALID_STATE,
                  f"cannot archive cycle in status {cycle['status']}", 409)
    for plan in db.action_plans.values():
        if plan["cycle_id"] == cycle["id"] and plan["status"] not in ("COMPLETED", "ABANDONED"):
            raise err(ERR_INVALID_STATE,
                      "all action plans of the cycle must be COMPLETED or ABANDONED", 409)
    cycle["status"] = "ARCHIVED"
    touch(cycle)
    return success_object(public(cycle))


@bp.post("/engagement/survey-cycles/<cycle_id>/remind")
def remind_cycle(cycle_id):
    require_roles("PeopleAnalyst")
    cycle = _get_cycle_or_404(cycle_id)
    # A sweep on a non-OPEN cycle is a state error.
    if cycle["status"] != "OPEN":
        raise err(ERR_INVALID_STATE,
                  f"reminder sweep requires an OPEN cycle (currently {cycle['status']})", 409)
    count, ids = run_reminder_sweep(cycle)
    return success_object({"reminded_count": count, "reminded_invite_ids": ids})
