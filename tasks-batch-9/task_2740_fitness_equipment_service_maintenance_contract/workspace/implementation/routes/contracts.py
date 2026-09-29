"""Service contracts: drafting, lifecycle, allowance, credits and quoting."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import calc, credit, domain, quoting, validate

bp = Blueprint("contracts", __name__)

TIER_PARTS_OFFERED = {
    "BRONZE": ("NONE", "WEAR_ONLY"),
    "SILVER": ("NONE", "WEAR_ONLY", "FULL"),
    "GOLD": ("NONE", "WEAR_ONLY", "FULL"),
}


@bp.post("/fleetcare/contracts")
def create_contract():
    middleware.auth(middleware.CONTRACT_ADMIN)
    body = middleware.body()
    club_id = validate.identifier(body, "club_id")
    coverage_tier = validate.enum(body, "coverage_tier", calc.COVERAGE_TIERS)
    parts_inclusion = validate.enum(body, "parts_inclusion", calc.PARTS_INCLUSIONS)
    pm_visits = validate.integer(body, "pm_visits_per_year", minimum=0)
    annual_base = validate.integer(body, "annual_base_cents", minimum=1)
    initial_allowance = validate.integer(body, "initial_parts_allowance_cents", minimum=0)
    term_start = validate.day(body, "term_start_date")
    term_end = validate.day(body, "term_end_date")
    if calc.parse_day(term_end) <= calc.parse_day(term_start):
        validate.bad("term_end_date must fall strictly after term_start_date")

    club = domain.need_club(club_id)
    if parts_inclusion not in TIER_PARTS_OFFERED[coverage_tier]:
        raise ApiError("ERR_TIER_PARTS_MISMATCH")
    if pm_visits < calc.PM_MIN_VISITS[coverage_tier]:
        raise ApiError("ERR_PM_FREQUENCY_BELOW_TIER")

    row = db.base_row()
    row.update({
        "club_id": club_id,
        "coverage_tier": coverage_tier,
        "parts_inclusion": parts_inclusion,
        "pm_visits_per_year": pm_visits,
        "annual_base_cents": annual_base,
        "initial_parts_allowance_cents": initial_allowance,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "sla_response_minutes": calc.SLA_RESPONSE_MINUTES[coverage_tier],
        "status": "DRAFT",
        "suspension_reason": None,
        "parts_allowance_total_cents": initial_allowance,
        "parts_allowance_remaining_cents": initial_allowance,
        "credit_provisional_cents": 0,
        "credit_accrued_cents": 0,
        "credit_forgone_cents": 0,
        "credit_cap_cents": calc.credit_cap_cents(annual_base),
        "pm_visits_completed_count": 0,
        "pm_visits_missed_count": 0,
        "pm_compliance_pct": calc.dec("100.00"),
        "last_reconciled_period_key": None,
    })
    row.update(domain.contract_fleet_fields(club["id"]))
    db.contracts[row["id"]] = row
    return response.created_response(row)


@bp.get("/fleetcare/contracts")
def list_contracts():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.contracts, {
        "club_id": response.arg("club_id"),
        "status": response.arg("status"),
        "coverage_tier": response.arg("coverage_tier"),
    })


@bp.get("/fleetcare/contracts/<contract_id>")
def read_contract(contract_id):
    ctx = middleware.auth(*middleware.ALL_ROLES)
    row = domain.need_contract(contract_id)
    middleware.require_club_scope(ctx, row["club_id"])
    return response.object_response(row)


@bp.post("/fleetcare/contracts/<contract_id>/activate")
def activate_contract(contract_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    contract = domain.need_contract(contract_id)
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    for other in domain.club_contracts(contract["club_id"]):
        if other["id"] == contract["id"]:
            continue
        if other["status"] in calc.LIVE_CONTRACT_STATUSES:
            raise ApiError("ERR_ACTIVE_CONTRACT_EXISTS")
    db.apply_changes(contract, {"status": "ACTIVE"})
    return response.object_response(contract)


@bp.post("/fleetcare/contracts/<contract_id>/suspend")
def suspend_contract(contract_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    contract = domain.need_contract(contract_id)
    body = middleware.body()
    reason = validate.string(body, "reason", min_len=1)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")

    db.apply_changes(contract, {"status": "SUSPENDED", "suspension_reason": reason})
    quoting.tear_down_forward_schedule(contract, "CONTRACT_SUSPENDED")
    return response.object_response(contract)


@bp.post("/fleetcare/contracts/<contract_id>/reinstate")
def reinstate_contract(contract_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    contract = domain.need_contract(contract_id)
    if contract["status"] != "SUSPENDED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    club = db.clubs.get(contract["club_id"])
    if club is not None and club["open_safety_lockout_count"] > 0:
        raise ApiError("ERR_SAFETY_LOCKOUT_OPEN")
    db.apply_changes(contract, {"status": "ACTIVE", "suspension_reason": None})
    return response.object_response(contract)


@bp.post("/fleetcare/contracts/<contract_id>/parts-allowance-adjustments")
def adjust_allowance(contract_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    contract = domain.need_contract(contract_id)
    body = middleware.body()
    amount = validate.integer(body, "amount_cents")
    validate.string(body, "memo", min_len=1)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")

    new_total = contract["parts_allowance_total_cents"] + amount
    new_remaining = contract["parts_allowance_remaining_cents"] + amount
    if new_total < 0 or new_remaining < 0:
        raise ApiError("ERR_ALLOWANCE_ADJUSTMENT_INVALID")
    contract["parts_allowance_total_cents"] = new_total
    contract["parts_allowance_remaining_cents"] = new_remaining
    db.touch(contract)
    return response.object_response(contract)


@bp.post("/fleetcare/contracts/<contract_id>/credit-reconciliations")
def reconcile_credits(contract_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    contract = domain.need_contract(contract_id)
    body = middleware.body()
    period_key = validate.period_key(body, "period_key")
    expected = validate.expected_version(body)
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if period_key == contract["last_reconciled_period_key"]:
        raise ApiError("ERR_PERIOD_ALREADY_RECONCILED")
    closed = [
        e for e in db.downtime_events.values()
        if e["contract_id"] == contract["id"]
        and e["status"] == "CLOSED"
        and e["period_key"] == period_key
    ]
    if not closed:
        raise ApiError("ERR_PERIOD_ALREADY_RECONCILED")

    summary = credit.reconcile_period(contract, period_key)
    return response.object_response(summary)


@bp.get("/fleetcare/contracts/<contract_id>/credit-summary")
def read_credit_summary(contract_id):
    ctx = middleware.auth(middleware.CONTRACT_ADMIN, middleware.CLUB_MANAGER,
                          middleware.SERVICE_COORDINATOR)
    contract = domain.need_contract(contract_id)
    middleware.require_club_scope(ctx, contract["club_id"])
    return response.object_response(credit.credit_summary(contract))


@bp.post("/fleetcare/contracts/<contract_id>/renewal-quotes")
def issue_renewal_quote(contract_id):
    middleware.auth(middleware.CONTRACT_ADMIN)
    contract = domain.need_contract(contract_id)
    body = middleware.body()
    expected = validate.expected_version(body)
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    if contract["status"] not in ("ACTIVE", "RENEWAL_QUOTED"):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if not domain.club_equipment(contract["club_id"]):
        raise ApiError("ERR_FLEET_EMPTY")

    quote = quoting.price_quote(contract)
    return response.created_response(quote)
