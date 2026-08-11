"""StandbyClaim endpoints (PRD 3.8): deductible + reason multiplier payable
computation, shutdown-hours aggregate honesty check, adjudication."""
import uuid
from decimal import Decimal

from flask import Blueprint, g

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CLAIM_PERIOD_OUTSIDE_WINDOW,
    ERR_CLAIM_NOT_PAYABLE,
    ERR_STANDBY_HOURS_EXCEED_SHUTDOWN,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import (
    serialize_claim,
    STANDBY_DEDUCTIBLE_HOURS,
    STANDBY_MULTIPLIER,
)
from util import (
    as_enum,
    as_num,
    as_str,
    check,
    get_body,
    new_entity,
    parse_dt,
    req_present,
    r0,
    touch,
)

bp = Blueprint("claims", __name__)


@bp.post("/standby-claims")
@require_roles("ContractorOps")
def create_claim():
    body = get_body()
    # Existence (class 3): project_id then plant_id.
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    plant_id = body.get("plant_id")
    if plant_id is not None and plant_id not in store.plants:
        raise ApiError(ERR_NOT_FOUND, "DredgePlant not found", 404)
    project_id = as_str(req_present(body, "project_id"), "project_id")
    plant_id = as_str(req_present(body, "plant_id"), "plant_id")
    period_start = parse_dt(req_present(body, "period_start_utc"), "period_start_utc")
    period_end = parse_dt(req_present(body, "period_end_utc"), "period_end_utc")
    check(period_end > period_start, "period_end_utc must be > period_start_utc")
    claimed = as_num(req_present(body, "claimed_hours"), "claimed_hours")
    check(claimed > 0, "claimed_hours must be > 0")
    reason = as_enum(
        req_present(body, "reason"),
        "reason",
        ["WEATHER", "SPECIES_SHUTDOWN", "OWNER_DIRECTED", "EQUIPMENT_BREAKDOWN"],
    )
    # Aggregate honesty check (class 10): claimed hours must not exceed the
    # plant's total shutdown_accumulated_hours on this project.
    accumulated = sum(
        (
            e["shutdown_accumulated_hours"]
            for e in store.events.values()
            if e["_project_id"] == project_id and e["plant_id"] == plant_id
        ),
        Decimal("0"),
    )
    if claimed > accumulated:
        raise ApiError(
            ERR_STANDBY_HOURS_EXCEED_SHUTDOWN,
            "claimed_hours exceeds the plant's accumulated shutdown hours on the project",
            422,
        )
    # Payable computation at creation (frozen at approval).
    multiplier = STANDBY_MULTIPLIER[reason]
    if multiplier == 0:
        payable_hours = Decimal("0")
    else:
        payable_hours = max(Decimal("0"), claimed - STANDBY_DEDUCTIBLE_HOURS)
    project = store.projects[project_id]
    payable_amount = r0(
        payable_hours * Decimal(project["standby_rate_cents_per_hour"]) * multiplier
    )
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "plant_id": plant_id,
            "period_start_utc": period_start,
            "period_end_utc": period_end,
            "claimed_hours": claimed,
            "reason": reason,
            "payable_hours": payable_hours,
            "payable_amount_cents": payable_amount,
            "claimed_by_user_id": g.user_id,
            "status": "SUBMITTED",
        }
    )
    store.claims[rec["id"]] = rec
    return ok(serialize_claim(rec), 201)


def _get_claim(cid):
    claim = store.claims.get(cid)
    if claim is None:
        raise ApiError(ERR_NOT_FOUND, "StandbyClaim not found", 404)
    return claim


@bp.get("/standby-claims/<cid>")
@require_roles(*ALL_ROLES)
def get_claim(cid):
    return ok(serialize_claim(_get_claim(cid)))


@bp.get("/standby-claims")
@require_roles(*ALL_ROLES)
def list_claims():
    return list_response(
        store.claims, serialize_claim, ["project_id", "plant_id", "status"]
    )


@bp.post("/standby-claims/<cid>/approve")
@require_roles("OwnerEngineer")
def approve_claim(cid):
    claim = _get_claim(cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED claim can be approved", 409)
    # Segregation of duties (class 8).
    if g.user_id == claim["claimed_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "The claimant cannot approve the claim", 403
        )
    # Temporal (class 9): the claim period must overlap at least one ISSUED
    # permit's closed window (share at least one instant).
    ps, pe = claim["period_start_utc"], claim["period_end_utc"]
    if not any(
        p["project_id"] == claim["project_id"]
        and p["status"] == "ISSUED"
        and ps <= p["window_end_utc"]
        and p["window_start_utc"] <= pe
        for p in store.permits.values()
    ):
        raise ApiError(
            ERR_CLAIM_PERIOD_OUTSIDE_WINDOW,
            "Claim period does not overlap any ISSUED permit window",
            409,
        )
    # Fiscal (class 12): EQUIPMENT_BREAKDOWN is never payable.
    if claim["reason"] == "EQUIPMENT_BREAKDOWN":
        raise ApiError(
            ERR_CLAIM_NOT_PAYABLE, "EQUIPMENT_BREAKDOWN claims are not payable", 422
        )
    claim["status"] = "APPROVED"  # payable fields stay frozen as computed
    touch(claim)
    return ok(serialize_claim(claim))


@bp.post("/standby-claims/<cid>/deny")
@require_roles("OwnerEngineer")
def deny_claim(cid):
    claim = _get_claim(cid)
    if claim["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED claim can be denied", 409)
    if g.user_id == claim["claimed_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, "The claimant cannot deny the claim", 403
        )
    claim["status"] = "DENIED"
    touch(claim)
    return ok(serialize_claim(claim))
