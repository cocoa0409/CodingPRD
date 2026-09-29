"""Funding instruments: membership packages and team contracts (PRD 3.6)."""

from flask import Blueprint

import response
import serializers
from db import (create, now, now_iso, ordered, parse_date, parse_instant, store,
                today, touch)
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum, query_str,
                        resolve_acting_staff, slice_page, v_date, v_enum,
                        v_int, v_string)
from routes.common import (get_athlete, get_membership_package,
                           get_team_contract, require_state)
from services import calc, domain

bp = Blueprint("funding", __name__)

PACKAGE_STATUSES = ("ACTIVE", "FROZEN", "DEPLETED", "EXPIRED")
PACKAGE_TERMINAL = ("EXPIRED",)
ORGANIZATION_TYPES = ("SCHOOL", "CLUB")
CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")


# -------------------------------------------------------- membership packages ----
@bp.post("/membership-packages")
def sell_package():
    guard("FrontDesk")
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))
    sessions_purchased = v_int(body, "sessions_purchased", minimum=1, maximum=100)
    price_cents = v_int(body, "price_cents", minimum=0)
    expires_on = v_date(body, "expires_on")
    if expires_on < today():
        raise ApiError(
            "ERR_INVALID_REQUEST", "expires_on may not fall earlier than the current logical date"
        )
    if athlete["membership_status"] == "SUSPENDED":
        raise ApiError("ERR_ATHLETE_SUSPENDED", "A suspended athlete may not be sold a package")

    record = create(
        store.membership_packages,
        {
            "athlete_id": athlete["id"],
            "sessions_purchased": sessions_purchased,
            "price_cents": price_cents,
            "expires_on": expires_on.isoformat(),
            "frozen_days_total": 0,
            "frozen_at": None,
            "effective_expires_on": expires_on.isoformat(),
            "sessions_remaining": sessions_purchased,
            "sessions_reserved": 0,
            "sessions_consumed": 0,
            "sessions_forfeited": 0,
            "status": "ACTIVE",
        },
    )
    return response.created(serializers.membership_package(record))


@bp.get("/membership-packages/<membership_package_id>")
def read_package(membership_package_id):
    ctx = guard("PerformanceDirector", "FrontDesk", "Athlete", "Guardian")
    package = get_membership_package(membership_package_id)
    resolve_acting_staff(ctx)
    athlete = store.athletes.get(package["athlete_id"])
    if athlete is not None:
        domain.enforce_athlete_scope(ctx, athlete)
    return response.ok(serializers.membership_package(package))


@bp.get("/membership-packages")
def list_packages():
    ctx = guard("PerformanceDirector", "FrontDesk")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    status = query_enum("status", PACKAGE_STATUSES)

    rows = ordered(store.membership_packages)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list(
        [serializers.membership_package(r) for r in page], limit, offset, total
    )


@bp.post("/membership-packages/<membership_package_id>/freeze")
def freeze_package(membership_package_id):
    guard("FrontDesk")
    package = get_membership_package(membership_package_id)
    body_json()
    require_state(package, "status", ("ACTIVE",), PACKAGE_TERMINAL, "MembershipPackage")

    package["status"] = "FROZEN"
    package["frozen_at"] = now_iso()
    touch(package)
    return response.ok(serializers.membership_package(package))


@bp.post("/membership-packages/<membership_package_id>/unfreeze")
def unfreeze_package(membership_package_id):
    guard("FrontDesk")
    package = get_membership_package(membership_package_id)
    body_json()
    require_state(package, "status", ("FROZEN",), PACKAGE_TERMINAL, "MembershipPackage")

    frozen_at = parse_instant(package["frozen_at"])
    elapsed = 0
    if frozen_at is not None:
        seconds = int((now() - frozen_at).total_seconds())
        if seconds < 0:
            seconds = 0
        elapsed = calc.ceil_div(seconds, 86400)
    package["frozen_days_total"] += elapsed
    package["frozen_at"] = None
    package["status"] = "ACTIVE"
    domain.recompute_package_expiry(package)
    touch(package)
    return response.ok(serializers.membership_package(package))


# ------------------------------------------------------------- team contracts ----
@bp.post("/team-contracts")
def create_contract():
    guard("PerformanceDirector")
    body = body_json()
    organization_name = v_string(body, "organization_name", min_len=1, max_len=160)
    organization_type = v_enum(body, "organization_type", ORGANIZATION_TYPES)
    contracted_sessions = v_int(body, "contracted_sessions", minimum=1, maximum=500)
    base_rate_cents = v_int(body, "base_rate_cents", minimum=0)
    offsite_allowance = v_int(body, "offsite_allowance", required=False, minimum=0, default=0)
    term_start = v_date(body, "term_start")
    term_end = v_date(body, "term_end")
    if term_end < term_start:
        raise ApiError("ERR_INVALID_REQUEST", "term_end may not fall earlier than term_start")

    record = create(
        store.team_contracts,
        {
            "organization_name": organization_name,
            "organization_type": organization_type,
            "contracted_sessions": contracted_sessions,
            "base_rate_cents": base_rate_cents,
            "offsite_allowance": offsite_allowance,
            "term_start": term_start.isoformat(),
            "term_end": term_end.isoformat(),
            "sessions_available": contracted_sessions,
            "sessions_reserved": 0,
            "sessions_delivered": 0,
            "offsite_sessions_used": 0,
            "billed_amount_cents": 0,
            "status": "DRAFT",
        },
    )
    return response.created(serializers.team_contract(record))


@bp.get("/team-contracts/<team_contract_id>")
def read_contract(team_contract_id):
    ctx = guard("PerformanceDirector", "FrontDesk")
    contract = get_team_contract(team_contract_id)
    resolve_acting_staff(ctx)
    return response.ok(serializers.team_contract(contract))


@bp.get("/team-contracts")
def list_contracts():
    ctx = guard("PerformanceDirector", "FrontDesk")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    organization_type = query_enum("organization_type", ORGANIZATION_TYPES)
    status = query_enum("status", CONTRACT_STATUSES)

    rows = ordered(store.team_contracts)
    if organization_type:
        rows = [r for r in rows if r["organization_type"] == organization_type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.team_contract(r) for r in page], limit, offset, total)


@bp.post("/team-contracts/<team_contract_id>/activate")
def activate_contract(team_contract_id):
    guard("PerformanceDirector")
    contract = get_team_contract(team_contract_id)
    body_json()
    require_state(contract, "status", ("DRAFT",), (), "TeamContract")
    if parse_date(contract["term_end"]) <= today():
        raise ApiError(
            "ERR_INVALID_STATE",
            "A contract whose term_end is not later than the current logical date cannot be activated",
        )

    contract["status"] = "ACTIVE"
    contract["sessions_available"] = contract["contracted_sessions"]
    touch(contract)
    return response.ok(serializers.team_contract(contract))


@bp.post("/team-contracts/<team_contract_id>/athletes")
def link_athlete(team_contract_id):
    guard("PerformanceDirector", "FrontDesk")
    contract = get_team_contract(team_contract_id)
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))

    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "The team contract is not ACTIVE")

    athlete["team_contract_id"] = contract["id"]
    touch(athlete)
    return response.ok(serializers.athlete(athlete))
