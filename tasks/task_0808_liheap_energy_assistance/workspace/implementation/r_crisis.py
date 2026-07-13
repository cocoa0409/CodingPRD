"""Energy crisis benefit endpoints and the 48-hour deadline (§3.8)."""
from flask import request

from store import db, stamp_new, touch, public, add_hours, format_dt
from common import (
    endpoint, object_response, get_body, req_str, req_enum, ApiError,
)
from calc import CRISIS_RATE_CENTS, CRISIS_DEADLINE_HOURS, pool_balances
from helpers import get_path, get_ref, list_collection
from pledge_ops import create_pledge

CRISIS_TYPES = {"NO_HEAT", "DISCONNECTION_NOTICE", "OUT_OF_FUEL"}


def _window_overlaps_open_crisis(household_id, start_dt, end_dt):
    """Half-open [reported_at, resolve_by) overlap against this household's OPEN crises.

    Adjacency at a resolve_by boundary is allowed; any true overlap is not.
    """
    for cb in db.crisis_benefits.values():
        if cb["household_id"] != household_id or cb["status"] != "OPEN":
            continue
        if start_dt < cb["_resolve_by_dt"] and cb["_reported_at_dt"] < end_dt:
            return True
    return False


def register(app):
    @app.route("/liheap/crisis-benefits", methods=["POST"])
    @endpoint(["Caseworker"])
    def create_crisis_benefit(role, user_id):
        body = get_body()
        household_id = req_str(body, "household_id")
        utility_account_id = req_str(body, "utility_account_id")
        funding_pool_id = req_str(body, "funding_pool_id")
        crisis_type = req_enum(body, "crisis_type", CRISIS_TYPES)

        # Body FKs resolve first (422), then the component check (422).
        household = get_ref(db.households, household_id)
        get_ref(db.utility_accounts, utility_account_id)
        pool = get_ref(db.funding_pools, funding_pool_id)
        if pool["program_component"] != "CRISIS":
            raise ApiError("ERR_POOL_COMPONENT_MISMATCH", "Funding pool is not a CRISIS pool")

        reported_at = db.now()
        resolve_by = add_hours(reported_at, CRISIS_DEADLINE_HOURS)
        if _window_overlaps_open_crisis(household["id"], reported_at, resolve_by):
            raise ApiError("ERR_CRISIS_WINDOW_OVERLAP",
                           "Crisis window overlaps an existing OPEN crisis for this household")

        crisis = {
            "household_id": household_id,
            "utility_account_id": utility_account_id,
            "funding_pool_id": funding_pool_id,
            "crisis_type": crisis_type,
            "reported_at": format_dt(reported_at),
            "resolve_by": format_dt(resolve_by),
            "estimated_benefit_cents": CRISIS_RATE_CENTS[crisis_type],
            "resolved_benefit_cents": None,
            "status": "OPEN",
            "_reported_at_dt": reported_at,
            "_resolve_by_dt": resolve_by,
        }
        stamp_new(crisis)
        db.crisis_benefits[crisis["id"]] = crisis
        return object_response(public(crisis), 201)

    @app.route("/liheap/crisis-benefits/<id_>", methods=["GET"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def get_crisis_benefit(role, user_id, id_):
        crisis = get_path(db.crisis_benefits, id_)
        return object_response(public(crisis), 200)

    @app.route("/liheap/crisis-benefits", methods=["GET"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def list_crisis_benefits(role, user_id):
        filters = {
            "household_id": request.args.get("household_id"),
            "utility_account_id": request.args.get("utility_account_id"),
            "funding_pool_id": request.args.get("funding_pool_id"),
            "status": request.args.get("status"),
        }
        return list_collection(db.crisis_benefits, "crisis_benefits", filters)

    @app.route("/liheap/crisis-benefits/<id_>/resolve", methods=["POST"])
    @endpoint(["Caseworker"])
    def resolve_crisis_benefit(role, user_id, id_):
        crisis = get_path(db.crisis_benefits, id_)
        if crisis["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Crisis benefit is not OPEN")
        # Strictly before the deadline; at or after resolve_by is too late.
        if db.now() >= crisis["_resolve_by_dt"]:
            raise ApiError("ERR_CRISIS_DEADLINE_PASSED", "Crisis deadline has passed")

        pool = db.funding_pools[crisis["funding_pool_id"]]
        account = db.utility_accounts[crisis["utility_account_id"]]
        reserved, disbursed, available, status = pool_balances(pool)
        if status in ("CLOSED", "DEPLETED"):
            raise ApiError("ERR_POOL_DEPLETED", "Funding pool is CLOSED or DEPLETED")

        owed = account["current_balance_cents"] + account["arrearage_cents"]
        resolved = min(crisis["estimated_benefit_cents"], available, owed)

        # Expedited crisis pledge: no application, no coverage window, no OCC guard.
        create_pledge(pool, {
            "application_id": None,
            "vendor_id": account["vendor_id"],
            "funding_pool_id": pool["id"],
            "utility_account_id": account["id"],
            "pledge_type": "CRISIS",
            "pledged_amount_cents": resolved,
            "benefit_period_start": None,
            "benefit_period_end": None,
            "expected_pool_version": None,
        })

        crisis["resolved_benefit_cents"] = resolved
        crisis["status"] = "RESOLVED"
        touch(crisis)
        return object_response(public(crisis), 200)

    @app.route("/liheap/crisis-benefits/<id_>/breach", methods=["POST"])
    @endpoint(["Caseworker", "ProgramAdmin"])
    def breach_crisis_benefit(role, user_id, id_):
        crisis = get_path(db.crisis_benefits, id_)
        if crisis["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Crisis benefit is not OPEN")
        if db.now() < crisis["_resolve_by_dt"]:
            raise ApiError("ERR_CRISIS_NOT_DUE", "Crisis deadline has not passed")
        crisis["status"] = "BREACHED"
        touch(crisis)
        return object_response(public(crisis), 200)
