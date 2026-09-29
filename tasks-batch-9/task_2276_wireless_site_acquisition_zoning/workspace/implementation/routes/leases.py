"""Ground lease drafting, negotiation, execution and termination."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from db import db, new_record, now, serialize, set_dt
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, DATETIME, INTEGER, NUMBER, ROLE_AGENT,
                        ROLE_DIRECTOR, STRING, actor_id, authenticate, f,
                        require_conditional, validate_body)

bp = Blueprint("leases", __name__)

ESCALATION_TYPES = ["FIXED_PCT", "CPI_CAPPED", "FLAT_STEP"]
ROUND_ACTIONS = ["SUBMIT", "COUNTER", "REVISE", "ACCEPT"]


@bp.post("/leases")
def create_lease():
    authenticate([ROLE_AGENT])
    body = validate_body([
        f("candidate_id", STRING),
        f("landlord_id", STRING),
        f("negotiating_agent_user_id", STRING),
        f("base_monthly_rent_usd", NUMBER, gt=0),
        f("escalation_type", STRING, enum=ESCALATION_TYPES),
        f("escalation_pct", NUMBER, required=False, default=Decimal("0")),
        f("escalation_step_usd", NUMBER, required=False, default=Decimal("0")),
        f("cpi_cap_pct", NUMBER, required=False, default=Decimal("0")),
        f("initial_term_years", INTEGER, ge=1),
        f("renewal_option_count", INTEGER, ge=0),
        f("renewal_term_years", INTEGER, ge=0),
        f("equipment_expansion_sqft", NUMBER, ge=0),
        f("revenue_share_pct", NUMBER, required=False, default=Decimal("0")),
    ])

    candidate = db.candidates.get(body["candidate_id"])
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404)
    landlord = db.landlords.get(body["landlord_id"])
    if landlord is None:
        raise ApiError("ERR_LANDLORD_NOT_FOUND", 404)

    if landlord["id"] != candidate["landlord_id"]:
        raise ApiError("ERR_LANDLORD_MISMATCH", 409)
    if actor_id() != candidate["owning_agent_user_id"]:
        raise ApiError("ERR_NOT_CANDIDATE_OWNER", 403)
    if landlord["outreach_optout"]:
        raise ApiError("ERR_LANDLORD_OPTED_OUT", 409)

    lease = new_record({
        "candidate_id": candidate["id"],
        "landlord_id": landlord["id"],
        "negotiating_agent_user_id": body["negotiating_agent_user_id"],
        "base_monthly_rent_usd": body["base_monthly_rent_usd"],
        "escalation_type": body["escalation_type"],
        "escalation_pct": body["escalation_pct"],
        "escalation_step_usd": body["escalation_step_usd"],
        "cpi_cap_pct": body["cpi_cap_pct"],
        "initial_term_years": body["initial_term_years"],
        "renewal_option_count": body["renewal_option_count"],
        "renewal_term_years": body["renewal_term_years"],
        "equipment_expansion_sqft": body["equipment_expansion_sqft"],
        "revenue_share_pct": body["revenue_share_pct"],
        "round_count": 0,
        "last_counter_rent_usd": None,
        "rent_variance_pct": None,
        "committed_rent_provisional_usd": None,
        "committed_rent_final_usd": None,
        "execution_date": None,
        "status": "DRAFT",
    })
    set_dt(lease, "execution_date", None)
    db.leases[lease["id"]] = lease
    return created(serialize(lease))


@bp.get("/leases")
def list_leases():
    authenticate(ALL_ROLES)
    return listing("leases", ["candidate_id", "landlord_id", "status"])


@bp.get("/leases/<lease_id>")
def read_lease(lease_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("leases", lease_id)))


def _ring_of_lease(lease):
    candidate = db.candidates.get(lease["candidate_id"])
    if candidate is None:
        return None
    return db.search_rings.get(candidate["search_ring_id"])


def _variance(lease):
    ring = _ring_of_lease(lease)
    if ring is None or lease["last_counter_rent_usd"] is None:
        return None
    return calc.lease_rent_variance(lease["last_counter_rent_usd"],
                                    ring["market_benchmark_monthly_rent_usd"])


@bp.post("/leases/<lease_id>/rounds")
def record_round(lease_id):
    authenticate([ROLE_AGENT])
    body = validate_body([
        f("action", STRING, enum=ROUND_ACTIONS),
        f("counter_rent_usd", NUMBER, required=False),
    ])
    action = body["action"]
    if action in ("SUBMIT", "COUNTER", "REVISE"):
        require_conditional(body, "counter_rent_usd")

    lease = fetch("leases", lease_id)
    candidate = db.candidates.get(lease["candidate_id"])
    if candidate is not None and actor_id() != candidate["owning_agent_user_id"]:
        raise ApiError("ERR_NOT_CANDIDATE_OWNER", 403)

    status = lease["status"]
    allowed = {
        "SUBMIT": ("DRAFT",),
        "COUNTER": ("SUBMITTED", "REVISED"),
        "REVISE": ("COUNTERED",),
        "ACCEPT": ("SUBMITTED", "COUNTERED", "REVISED"),
    }[action]
    if status not in allowed:
        raise ApiError("ERR_INVALID_LEASE_STATE", 409)

    if action == "SUBMIT":
        landlord = db.landlords.get(lease["landlord_id"])
        if landlord is None or landlord["standing"] != "ACTIVE":
            raise ApiError("ERR_LANDLORD_NOT_IN_GOOD_STANDING", 409)

    if action in ("SUBMIT", "COUNTER", "REVISE"):
        if lease["round_count"] >= calc.MAX_NEGOTIATION_ROUNDS:
            raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT", 409)
        new_status = {"SUBMIT": "SUBMITTED", "COUNTER": "COUNTERED",
                      "REVISE": "REVISED"}[action]
        updates = {
            "last_counter_rent_usd": body["counter_rent_usd"],
            "round_count": lease["round_count"] + 1,
            "status": new_status,
        }
        lease["last_counter_rent_usd"] = body["counter_rent_usd"]
        updates["rent_variance_pct"] = _variance(lease)
        services.apply(lease, updates)
        return ok(serialize(lease))

    # ACCEPT
    if lease["last_counter_rent_usd"] is None:
        raise ApiError("ERR_INVALID_LEASE_STATE", 409)
    variance = lease["rent_variance_pct"]
    if variance is None:
        variance = _variance(lease)
    if variance is not None and calc.dec(variance) > calc.MAX_RENT_VARIANCE_PCT:
        raise ApiError("ERR_RENT_VARIANCE_EXCEEDED", 409)

    lease["base_monthly_rent_usd"] = lease["last_counter_rent_usd"]
    totals = calc.lease_committed_rent(lease)
    services.apply(lease, {
        "base_monthly_rent_usd": lease["last_counter_rent_usd"],
        "committed_rent_provisional_usd": totals["provisional_total_usd"],
        "status": "ACCEPTED",
    })
    return ok(serialize(lease))


@bp.post("/leases/<lease_id>/execute")
def execute_lease(lease_id):
    authenticate([ROLE_DIRECTOR])
    body = validate_body([f("execution_date", DATETIME)])
    lease = fetch("leases", lease_id)

    if actor_id() == lease["negotiating_agent_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    if lease["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_LEASE_STATE", 409)

    landlord = db.landlords.get(lease["landlord_id"])
    if landlord is None or landlord["standing"] != "ACTIVE":
        raise ApiError("ERR_LANDLORD_NOT_IN_GOOD_STANDING", 409)

    execution = body["execution_date"]
    if execution.dt > now():
        raise ApiError("ERR_DATE_IN_FUTURE", 422)

    totals = calc.lease_committed_rent(lease)
    set_dt(lease, "execution_date", execution.dt, raw=execution.raw)
    services.apply(lease, {
        "execution_date": execution.raw,
        "committed_rent_final_usd": totals["final_total_usd"],
        "status": "EXECUTED",
    })

    candidate = db.candidates.get(lease["candidate_id"])
    if candidate is not None and candidate["acquisition_status"] != "RELINQUISHED":
        services.apply(candidate, {"acquisition_status": "LEASE_EXECUTED"})
    if landlord is not None:
        services.refresh_landlord_lease_count(landlord)
    return ok(serialize(lease))


@bp.post("/leases/<lease_id>/terminate")
def terminate_lease(lease_id):
    authenticate([ROLE_DIRECTOR])
    validate_body([f("reason", STRING)])
    lease = fetch("leases", lease_id)
    if lease["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_LEASE_STATE", 409)

    services.apply(lease, {"status": "TERMINATED"})
    landlord = db.landlords.get(lease["landlord_id"])
    if landlord is not None:
        services.refresh_landlord_lease_count(landlord)
    candidate = db.candidates.get(lease["candidate_id"])
    if candidate is not None:
        services.relinquish_candidate(candidate)
    return ok(serialize(lease))


@bp.get("/leases/<lease_id>/rent-schedule")
def rent_schedule(lease_id):
    authenticate([ROLE_AGENT, ROLE_DIRECTOR])
    lease = fetch("leases", lease_id)
    totals = calc.lease_committed_rent(lease)
    return ok({
        "provisional_total_usd": totals["provisional_total_usd"],
        "final_total_usd": totals["final_total_usd"],
        "delta_usd": totals["delta_usd"],
        "priced_years": totals["priced_years"],
        "first_year_rent_usd": totals["first_year_rent_usd"],
        "last_year_rent_usd": totals["last_year_rent_usd"],
    })
