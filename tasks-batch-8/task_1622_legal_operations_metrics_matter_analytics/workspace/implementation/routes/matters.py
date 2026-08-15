from flask import Blueprint, request

from clock import CLOCK
from db import store, new_entity, touch
from errors import (
    ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_INVALID_AMOUNT,
    ERR_TAXONOMY_MISMATCH, ERR_ENTITY_INACTIVE, ERR_PERIOD_CLOSED,
    ERR_NO_ACTIVE_ASSIGNMENT, ERR_PERIOD_NOT_HARD_CLOSED, ERR_STALE_VERSION,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import object_response
from serializers import matter_view
from services.aggregates import matter_cost_model
from validation import Payload, require_exists, list_page

bp = Blueprint("matters", __name__, url_prefix="/legal-ops/matters")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")
MATTER_NUMBER_PATTERN = r"LGL-\d{4}-\d{5}"


@bp.post("")
@require_roles("LegalOpsAnalyst")
def create_matter(user_id, role):
    p = Payload()
    matter_number = p.req_str("matter_number", pattern=MATTER_NUMBER_PATTERN)
    title = p.req_str("title")
    pa_id = p.req_str("practice_area_id")
    mt_id = p.req_str("matter_type_id")
    fp_id = p.req_str("fiscal_period_id")
    firm_id = p.opt_str("primary_firm_id")
    counsel_id = p.req_str("lead_counsel_id")
    budget_cents = p.opt_int("budget_cents")

    # Existence (priority 3) — body FKs in declared field order.
    pa = mt = fp = firm = counsel = None
    if pa_id is not None:
        pa = require_exists(store.practice_areas, pa_id, "practice area")
    if mt_id is not None:
        mt = require_exists(store.matter_types, mt_id, "matter type")
    if fp_id is not None:
        fp = require_exists(store.fiscal_periods, fp_id, "fiscal period")
    if firm_id is not None:
        firm = require_exists(store.firms, firm_id, "firm")
    if counsel_id is not None:
        counsel = require_exists(store.counsel, counsel_id, "counsel")

    # Business rules in fixed order: taxonomy -> calendar -> activity -> uniqueness -> amount.
    if pa is not None and mt is not None and mt["practice_area_id"] != pa["id"]:
        raise ApiError(ERR_TAXONOMY_MISMATCH, 422, "Matter type does not belong to the practice area")
    if fp is not None and fp["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    if pa is not None and pa["status"] != "ACTIVE":
        raise ApiError(ERR_ENTITY_INACTIVE, 422, "Practice area is not ACTIVE")
    if matter_number is not None:
        for m in store.matters.values():
            if m["matter_number"] == matter_number:
                raise ApiError(ERR_DUPLICATE, 409, "matter_number already exists")
    if budget_cents is not None and budget_cents < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "budget_cents must be >= 0")
    p.finish()

    if budget_cents is None:
        budget_cents = mt["default_budget_cents"]
    matter = new_entity({
        "matter_number": matter_number,
        "title": title,
        "practice_area_id": pa_id,
        "matter_type_id": mt_id,
        "fiscal_period_id": fp_id,
        "primary_firm_id": firm_id,
        "lead_counsel_id": counsel_id,
        "status": "INTAKE",
        "budget_cents": budget_cents,
        "actual_spend_cents": 0,
        "accrual_outstanding_cents": 0,
        "cycle_days": None,
        "_activated_at": None,
    })
    store.matters[matter["id"]] = matter
    return object_response(matter_view(matter), 201)


@bp.get("")
@require_roles(*ALL)
def list_matters(user_id, role):
    items = list(store.matters.values())
    for param in ("status", "practice_area_id", "matter_type_id", "fiscal_period_id",
                  "primary_firm_id", "lead_counsel_id"):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m[param] == v]
    return list_page(items, matter_view)


@bp.get("/<mid>")
@require_roles(*ALL)
def get_matter(user_id, role, mid):
    return object_response(matter_view(require_exists(store.matters, mid, "matter")))


@bp.patch("/<mid>")
@require_roles("LegalOpsAnalyst")
def update_matter(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    # State: archived matters reject updates.
    if matter["status"] == "ARCHIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Cannot update an ARCHIVED matter")
    p = Payload()
    title = p.opt_str("title")
    budget_cents = p.opt_int("budget_cents")
    firm_id = p.opt_str("primary_firm_id")
    # Body FK existence.
    if firm_id is not None:
        require_exists(store.firms, firm_id, "firm")
    # Amount rule (priority 12).
    if budget_cents is not None and budget_cents < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "budget_cents must be >= 0")
    p.finish()
    if p.provided("title") or p.provided("budget_cents") or p.provided("primary_firm_id"):
        if p.provided("title"):
            matter["title"] = title
        if p.provided("budget_cents"):
            matter["budget_cents"] = budget_cents
        if p.provided("primary_firm_id"):
            matter["primary_firm_id"] = firm_id
        touch(matter)
    return object_response(matter_view(matter))


def _active_assignments(matter_id):
    return [a for a in store.assignments.values()
            if a["matter_id"] == matter_id and a["status"] == "ACTIVE"]


@bp.post("/<mid>/activate")
@require_roles("LegalOpsAnalyst")
def activate(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    if matter["status"] != "INTAKE":
        raise ApiError(ERR_INVALID_STATE, 409, "Matter is not in INTAKE")
    period = store.fiscal_periods.get(matter["fiscal_period_id"])
    if period is not None:
        if period["status"] in ("SOFT_CLOSED", "HARD_CLOSED"):
            raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is closed")
        if period["status"] == "REOPENED":
            raise ApiError(ERR_INVALID_STATE, 409, "Activation requires period status OPEN")
    pa = store.practice_areas.get(matter["practice_area_id"])
    if pa is not None and pa["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Practice area is no longer ACTIVE")
    if matter["primary_firm_id"] is not None:
        firm = store.firms.get(matter["primary_firm_id"])
        if firm is not None and firm["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "Primary firm is no longer ACTIVE")
    if not _active_assignments(mid):
        raise ApiError(ERR_NO_ACTIVE_ASSIGNMENT, 422, "Matter requires at least one ACTIVE assignment")
    matter["status"] = "ACTIVE"
    matter["_activated_at"] = CLOCK.now()
    touch(matter)
    return object_response(matter_view(matter))


@bp.post("/<mid>/hold")
@require_roles("LegalOpsAnalyst")
def hold(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    if matter["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Matter is not ACTIVE")
    matter["status"] = "ON_HOLD"
    touch(matter)
    return object_response(matter_view(matter))


@bp.post("/<mid>/resume")
@require_roles("LegalOpsAnalyst")
def resume(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    if matter["status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_STATE, 409, "Matter is not ON_HOLD")
    period = store.fiscal_periods.get(matter["fiscal_period_id"])
    if period is not None and period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PERIOD_CLOSED, 409, "Fiscal period is not OPEN or REOPENED")
    matter["status"] = "ACTIVE"
    touch(matter)
    return object_response(matter_view(matter))


@bp.post("/<mid>/close")
@require_roles("LegalOpsAnalyst")
def close(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    # State gate (priority 4) before OCC (priority 18).
    if matter["status"] not in ("ACTIVE", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Matter is not ACTIVE or REOPENED")
    for a in store.accruals.values():
        if a["matter_id"] == mid and a["status"] == "OUTSTANDING":
            raise ApiError(ERR_INVALID_STATE, 409, "Matter has OUTSTANDING accruals")
    for inv in store.invoices.values():
        if inv["matter_id"] == mid and inv["payment_status"] == "SUBMITTED":
            raise ApiError(ERR_INVALID_STATE, 409, "Matter has SUBMITTED invoices")
    p = Payload()
    expected = p.opt_int("expected_matter_version", nullable=False)
    if expected is not None and expected != matter["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_matter_version does not match current version")
    p.finish()
    # cycle_days: days from original INTAKE->ACTIVE timestamp to this close.
    if matter["_activated_at"] is not None:
        matter["cycle_days"] = (CLOCK.now() - matter["_activated_at"]).days
    matter["status"] = "CLOSED"
    touch(matter)
    for a in _active_assignments(mid):
        a["status"] = "RELEASED"
        touch(a)
    return object_response(matter_view(matter))


@bp.post("/<mid>/reopen")
@require_roles("LegalOpsManager")
def reopen(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    if matter["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Matter is not CLOSED")
    period = store.fiscal_periods.get(matter["fiscal_period_id"])
    if period is not None and period["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Fiscal period does not permit reopening matters")
    matter["status"] = "REOPENED"
    matter["cycle_days"] = None
    touch(matter)
    return object_response(matter_view(matter))


@bp.post("/<mid>/archive")
@require_roles("LegalOpsManager")
def archive(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    if matter["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Matter is not CLOSED")
    period = store.fiscal_periods.get(matter["fiscal_period_id"])
    if period is None or period["status"] != "HARD_CLOSED":
        raise ApiError(ERR_PERIOD_NOT_HARD_CLOSED, 409, "Matter archive requires fiscal period HARD_CLOSED")
    matter["status"] = "ARCHIVED"
    touch(matter)
    return object_response(matter_view(matter))


@bp.get("/<mid>/cost-model")
@require_roles(*ALL)
def cost_model(user_id, role, mid):
    matter = require_exists(store.matters, mid, "matter")
    return object_response(matter_cost_model(matter))
