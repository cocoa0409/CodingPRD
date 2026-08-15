"""Production lifecycle: create, budget, insurance, posture transitions, wrap."""

from flask import Blueprint

from db import store
from domain import (
    get_production,
    gate_posture_setup_or_active,
    production_rollup,
    serialize_production,
    stamp_new,
    stamp_mutable,
    stop_production,
    touch,
    INSURANCE_TIER1_MAX,
    INSURANCE_TIER2_MAX,
    STOPPAGE_COOLDOWN_SECONDS,
    default_sort_key,
)
from errors import (
    err,
    ERR_STALE_VERSION,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_PRODUCTION_NOT_STOPPED,
    ERR_SERIOUS_INCIDENTS_OPEN,
    ERR_INSURANCE_NOT_FILED,
    ERR_INSURANCE_INVALID_STATE,
    ERR_SEQUENCES_NOT_TERMINAL,
    ERR_STOPPAGE_COOLDOWN,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
    v_pos_int,
    v_nonneg_int,
    v_int,
)
from response import ok, ok_list
from util import new_id, rhu, dec
from decimal import Decimal
from datetime import timedelta

bp = Blueprint("productions", __name__)

EXEC = ["ProductionExecutive"]


@bp.post("/api/productions")
def create_production():
    body = get_body()
    data = validate_payload(
        body,
        {
            "name": (v_string, True, None),
            "total_budget_cents": (v_pos_int, True, None),
        },
    )
    _, role = auth()
    require_role(role, EXEC)

    prod = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "name": data["name"],
                "total_budget_cents": data["total_budget_cents"],
                "posture": "SETUP",
                "insurance_status": "UNFILED",
                "declared_exposure_cents": None,
                "endorsement_premium_cents": None,
                "committed_pay_cents": 0,
                "stopped_at": None,
                "stop_reason": None,
            }
        )
    )
    store.productions[prod["id"]] = prod
    return ok(serialize_production(prod), 201)


@bp.get("/api/productions")
def list_productions():
    _, role = auth()
    require_role(role, ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
                        "DepartmentHead", "Performer", "EquipmentInspector"])
    limit, offset = pagination_params()
    items = sorted(store.productions.values(), key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_production(p) for p in page], total, limit, offset)


@bp.get("/api/productions/<pid>")
def get_one_production(pid):
    _, role = auth()
    require_role(role, ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
                        "DepartmentHead", "Performer", "EquipmentInspector"])
    prod = get_production(pid)
    return ok(serialize_production(prod), 200)


@bp.get("/api/productions/<pid>/summary")
def production_summary(pid):
    _, role = auth()
    require_role(role, ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
                        "DepartmentHead", "Performer", "EquipmentInspector"])
    prod = get_production(pid)
    return ok(production_rollup(prod), 200)


@bp.patch("/api/productions/<pid>/budget")
def amend_budget(pid):
    body = get_body()
    data = validate_payload(
        body,
        {
            "total_budget_cents": (v_pos_int, True, None),
            "expected_production_version": (v_int, True, None),
        },
    )
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(pid)
    if data["expected_production_version"] != prod["version"]:
        raise err(ERR_STALE_VERSION, "expected_production_version does not match the "
                                     "production's current version", 412)
    gate_posture_setup_or_active(prod)
    prod["total_budget_cents"] = data["total_budget_cents"]
    touch(prod)
    return ok(serialize_production(prod), 200)


@bp.post("/api/productions/<pid>/file-insurance")
def file_insurance(pid):
    body = get_body()
    data = validate_payload(
        body,
        {"declared_exposure_cents": (v_nonneg_int, True, None)},
    )
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(pid)
    gate_posture_setup_or_active(prod)
    if prod["insurance_status"] != "UNFILED":
        raise err(ERR_INSURANCE_INVALID_STATE,
                  "file-insurance requires insurance_status UNFILED", 409)

    exposure = data["declared_exposure_cents"]
    if exposure <= INSURANCE_TIER1_MAX:
        rate = Decimal("0.02")
    elif exposure <= INSURANCE_TIER2_MAX:
        rate = Decimal("0.03")
    else:
        rate = Decimal("0.04")
    prod["declared_exposure_cents"] = exposure
    prod["endorsement_premium_cents"] = rhu(dec(exposure) * rate)
    prod["insurance_status"] = "FILED"
    touch(prod)
    return ok(serialize_production(prod), 200)


@bp.post("/api/productions/<pid>/acknowledge-insurance")
def acknowledge_insurance(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(pid)
    gate_posture_setup_or_active(prod)
    if prod["insurance_status"] != "FILED":
        raise err(ERR_INSURANCE_INVALID_STATE,
                  "acknowledge-insurance requires insurance_status FILED", 409)
    prod["insurance_status"] = "ACKNOWLEDGED"
    touch(prod)
    return ok(serialize_production(prod), 200)


@bp.post("/api/productions/<pid>/activate")
def activate_production(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(pid)
    if prod["posture"] != "SETUP":
        raise err(ERR_PRODUCTION_NOT_ACTIVE,
                  "activate requires posture SETUP", 409)
    if prod["insurance_status"] not in ("FILED", "ACKNOWLEDGED"):
        raise err(ERR_INSURANCE_NOT_FILED,
                  "activate requires insurance FILED or ACKNOWLEDGED", 409)
    prod["posture"] = "ACTIVE"
    touch(prod)
    return ok(serialize_production(prod), 200)


@bp.post("/api/productions/<pid>/stop")
def stop_production_endpoint(pid):
    body = get_body()
    data = validate_payload(body, {"reason": (v_nonempty_string, True, None)})
    _, role = auth()
    require_role(role, ["SafetyOfficer", "ProductionExecutive"])
    prod = get_production(pid)
    if prod["posture"] != "ACTIVE":
        raise err(ERR_PRODUCTION_NOT_ACTIVE, "stop requires posture ACTIVE", 409)
    stop_production(prod, data["reason"])
    return ok(serialize_production(prod), 200)


@bp.post("/api/productions/<pid>/lift-stoppage")
def lift_stoppage(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(pid)
    if prod["posture"] != "STOPPED":
        raise err(ERR_PRODUCTION_NOT_STOPPED, "lift-stoppage requires posture STOPPED", 409)
    open_serious = any(
        i["production_id"] == prod["id"]
        and i["severity"] in ("SERIOUS", "CRITICAL")
        and i["status"] in ("REPORTED", "UNDER_INVESTIGATION")
        for i in store.incidents.values()
    )
    if open_serious:
        raise err(ERR_SERIOUS_INCIDENTS_OPEN,
                  "Open SERIOUS or CRITICAL incidents block lifting the stoppage", 409)
    if store.now() < prod["stopped_at"] + timedelta(seconds=STOPPAGE_COOLDOWN_SECONDS):
        raise err(ERR_STOPPAGE_COOLDOWN,
                  "The 86400-second stoppage cooldown has not elapsed", 409)
    prod["posture"] = "ACTIVE"
    touch(prod)
    return ok(serialize_production(prod), 200)


@bp.post("/api/productions/<pid>/wrap")
def wrap_production(pid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, EXEC)
    prod = get_production(pid)
    if prod["posture"] != "ACTIVE":
        raise err(ERR_PRODUCTION_NOT_ACTIVE, "wrap requires posture ACTIVE", 409)
    non_terminal = any(
        s["production_id"] == prod["id"] and s["status"] not in ("REVIEWED", "CANCELLED")
        for s in store.sequences.values()
    )
    if non_terminal:
        raise err(ERR_SEQUENCES_NOT_TERMINAL,
                  "Every sequence must be REVIEWED or CANCELLED before wrap", 409)
    prod["posture"] = "WRAPPED"
    touch(prod)
    return ok(serialize_production(prod), 200)
