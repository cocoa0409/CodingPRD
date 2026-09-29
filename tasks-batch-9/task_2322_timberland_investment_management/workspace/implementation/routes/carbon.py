"""Carbon projects, dedications and permanence obligations (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
import db
import middleware
import response
import serializers
import services
import validate
from db import store
from errors import ApiError
from routes.helpers import paginated

bp = Blueprint("carbon", __name__)

ZERO = Decimal("0.00")
OPEN_FOR_DEDICATION = ("DRAFT", "VALIDATION")
NON_TERMINAL_DEDICATIONS = ("PENDING", "ACTIVE", "REDUCED")


def _release(dedication, reason=None):
    """Move a dedication to RELEASED, returning its remaining tons to the pool."""
    dedication["status"] = "RELEASED"
    if reason is not None:
        dedication["release_reason"] = reason
    services.mark(dedication)
    stand = store.stands.get(dedication["stand_id"])
    if stand is not None:
        services.mark(stand)


@bp.post("/carbon-projects")
def create_project():
    middleware.require("CarbonDeveloper")
    body = validate.json_body()

    raw_property_id = validate.opt_str_id(body, "property_id")
    prop = None
    if raw_property_id is not None:
        prop = services.find(store.properties, raw_property_id, "ERR_PROPERTY_NOT_FOUND")

    property_id = validate.string(body, "property_id")
    registry = validate.enum(body, "registry", ("ACR", "CAR", "VERRA"))
    crediting_years = validate.integer(body, "crediting_period_years", 1, 40)
    permanence_years = validate.integer(body, "permanence_term_years", 1, 100)
    baseline = validate.number(body, "baseline_tons_per_acre", minimum=0,
                               exclusive_min=True, dp=2)
    if prop is None:
        prop = services.find(store.properties, property_id, "ERR_PROPERTY_NOT_FOUND")

    if prop["status"] not in ("OWNED", "HBU_MARKETED"):
        raise ApiError("ERR_PROPERTY_NOT_OWNED")

    rec = db.base_fields()
    rec.update({
        "property_id": prop["id"],
        "registry": registry,
        "crediting_period_years": crediting_years,
        "permanence_term_years": permanence_years,
        "baseline_tons_per_acre": baseline,
        "status": "DRAFT",
        "buffer_pool_tons": ZERO,
        "buffer_deficit_tons": ZERO,
    })
    store.carbon_projects[rec["id"]] = rec
    return response.created(serializers.carbon_project(rec))


@bp.get("/carbon-projects/<project_id>")
def get_project(project_id):
    middleware.require(*middleware.ANY_ROLE)
    project = services.find(store.carbon_projects, project_id,
                            "ERR_CARBON_PROJECT_NOT_FOUND")
    return response.ok(serializers.carbon_project(project))


@bp.get("/carbon-projects/<project_id>/dedications")
def list_project_dedications(project_id):
    middleware.require(*middleware.ANY_ROLE)
    project = services.find(store.carbon_projects, project_id,
                            "ERR_CARBON_PROJECT_NOT_FOUND")
    return paginated(services.rows(store.carbon_dedications,
                                   carbon_project_id=project["id"]),
                     serializers.carbon_dedication)


@bp.post("/carbon-projects/<project_id>/advance")
def advance_project(project_id):
    middleware.require("CarbonDeveloper")
    project = services.find(store.carbon_projects, project_id,
                            "ERR_CARBON_PROJECT_NOT_FOUND")
    body = validate.json_body()
    action = validate.enum(body, "action",
                           ("SUBMIT_VALIDATION", "REGISTER", "CURE_BUFFER", "TERMINATE"))
    cure_tons = None
    if action == "CURE_BUFFER":
        cure_tons = validate.number(body, "cure_tons", minimum=0, dp=2)

    prop = store.properties.get(project["property_id"])
    dedications = services.rows(store.carbon_dedications,
                                carbon_project_id=project["id"])
    status = project["status"]

    if action == "SUBMIT_VALIDATION":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if not any(d["status"] == "PENDING" for d in dedications):
            raise ApiError("ERR_CARBON_NO_DEDICATIONS")
        project["status"] = "VALIDATION"

    elif action == "REGISTER":
        if status != "VALIDATION":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if prop is not None and prop["certification_posture"] == "SUSPENDED":
            raise ApiError("ERR_CERTIFICATION_SUSPENDED")
        total = services.dedicated_tons_total(project["id"])
        if total <= 0:
            raise ApiError("ERR_CARBON_NO_DEDICATIONS")
        end_date = db.add_years(db.logical_date(), project["permanence_term_years"])
        for dedication in dedications:
            if dedication["status"] != "PENDING":
                continue
            dedication["status"] = "ACTIVE"
            dedication["permanence_end_date"] = end_date.isoformat()
            dedication["_permanence_end"] = end_date
            services.mark(dedication)
        project["buffer_pool_tons"] = calc.rhu(
            total * calc.CARBON_BUFFER_POOL_PCT / 100, 2)
        project["status"] = "REGISTERED"

    elif action == "CURE_BUFFER":
        if status != "REVERSAL_PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if cure_tons < calc.D(project["buffer_deficit_tons"]):
            raise ApiError("ERR_BUFFER_CURE_INSUFFICIENT")
        cost = calc.rhu(cure_tons * calc.BUFFER_CURE_COST_USD_PER_TON, 2)
        fund = services.fund_of_property(prop) if prop else None
        if fund is not None:
            services.guard_fund_cash(fund, cost)
        project["buffer_pool_tons"] = calc.rhu(
            calc.D(project["buffer_pool_tons"]) + cure_tons, 2)
        project["buffer_deficit_tons"] = ZERO
        project["status"] = "REGISTERED"
        if fund is not None:
            services.debit_fund(fund, cost, operating=True)

    else:
        if status not in ("DRAFT", "VALIDATION", "REGISTERED", "REVERSAL_PENDING"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if status == "REGISTERED":
            today = db.logical_date()
            for dedication in dedications:
                if (dedication["status"] == "ACTIVE"
                        and dedication.get("_permanence_end") is not None
                        and dedication["_permanence_end"] > today):
                    raise ApiError("ERR_CARBON_PERMANENCE_LOCK")
        for dedication in dedications:
            if dedication["status"] in NON_TERMINAL_DEDICATIONS:
                _release(dedication)
        project["status"] = "TERMINATED"

    services.mark(project)
    return response.ok(serializers.carbon_project(project))


@bp.post("/carbon-dedications")
def create_dedication():
    middleware.require("CarbonDeveloper")
    body = validate.json_body()

    raw_project_id = validate.opt_str_id(body, "carbon_project_id")
    project = None
    if raw_project_id is not None:
        project = services.find(store.carbon_projects, raw_project_id,
                                "ERR_CARBON_PROJECT_NOT_FOUND")
    raw_stand_id = validate.opt_str_id(body, "stand_id")
    stand = None
    if raw_stand_id is not None:
        stand = services.find(store.stands, raw_stand_id, "ERR_STAND_NOT_FOUND")

    project_id = validate.string(body, "carbon_project_id")
    stand_id = validate.string(body, "stand_id")
    dedicated_tons = validate.number(body, "dedicated_tons", minimum=0,
                                     exclusive_min=True, dp=2)
    expected_stand_version = validate.integer(body, "expected_stand_version")
    if project is None:
        project = services.find(store.carbon_projects, project_id,
                                "ERR_CARBON_PROJECT_NOT_FOUND")
    if stand is None:
        stand = services.find(store.stands, stand_id, "ERR_STAND_NOT_FOUND")

    if expected_stand_version != stand["version"]:
        raise ApiError("ERR_STALE_STAND_VERSION")
    if project["status"] not in OPEN_FOR_DEDICATION:
        raise ApiError("ERR_CARBON_PROJECT_NOT_OPEN_FOR_DEDICATION")
    if stand["status"] != "INVENTORIED":
        raise ApiError("ERR_STAND_NOT_INVENTORIED")
    if stand["property_id"] != project["property_id"]:
        raise ApiError("ERR_STAND_PROPERTY_MISMATCH")
    if dedicated_tons > services.available_tons(stand):
        raise ApiError("ERR_INSUFFICIENT_AVAILABLE_TONS")

    rec = db.base_fields()
    rec.update({
        "carbon_project_id": project["id"],
        "stand_id": stand["id"],
        "dedicated_tons": dedicated_tons,
        "reduced_tons": ZERO,
        "status": "PENDING",
        "permanence_end_date": None,
        "_permanence_end": None,
        "release_reason": None,
    })
    store.carbon_dedications[rec["id"]] = rec
    services.mark(stand)
    return response.created(serializers.carbon_dedication(rec))


@bp.get("/carbon-dedications/<dedication_id>")
def get_dedication(dedication_id):
    middleware.require(*middleware.ANY_ROLE)
    dedication = services.find(store.carbon_dedications, dedication_id,
                               "ERR_CARBON_DEDICATION_NOT_FOUND")
    return response.ok(serializers.carbon_dedication(dedication))


@bp.post("/carbon-dedications/<dedication_id>/release")
def release_dedication(dedication_id):
    middleware.require("CarbonDeveloper")
    dedication = services.find(store.carbon_dedications, dedication_id,
                               "ERR_CARBON_DEDICATION_NOT_FOUND")
    body = validate.json_body()
    reason = validate.string(body, "release_reason", 1, None, required=False)

    project = store.carbon_projects.get(dedication["carbon_project_id"])
    status = dedication["status"]
    if status == "PENDING":
        if project is not None and project["status"] not in OPEN_FOR_DEDICATION:
            raise ApiError("ERR_CARBON_PROJECT_NOT_OPEN_FOR_DEDICATION")
    elif status in ("ACTIVE", "REDUCED"):
        end = dedication.get("_permanence_end")
        if end is None or db.logical_date() < end:
            raise ApiError("ERR_CARBON_PERMANENCE_LOCK")
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    _release(dedication, reason)
    return response.ok(serializers.carbon_dedication(dedication))
