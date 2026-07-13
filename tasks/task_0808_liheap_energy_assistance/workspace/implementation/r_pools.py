"""Funding-pool endpoints (§3.1) and the logical-clock control (§2.4)."""
from store import db, stamp_new, touch, parse_dt
from common import (
    endpoint, object_response, get_body, req_int, req_enum, req_str, ApiError,
)
from calc import serialize_pool, pool_balances
from helpers import get_path

POOL_COMPONENTS = {"HEATING", "COOLING", "CRISIS"}


def register(app):
    @app.route("/liheap/funding-pools", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def create_funding_pool(role, user_id):
        body = get_body()
        season_year = req_int(body, "season_year")
        program_component = req_enum(body, "program_component", POOL_COMPONENTS)
        total_allocation_cents = req_int(body, "total_allocation_cents", gt=0)
        depletion_threshold_cents = req_int(body, "depletion_threshold_cents", minimum=0)
        pool = {
            "season_year": season_year,
            "program_component": program_component,
            "total_allocation_cents": total_allocation_cents,
            "depletion_threshold_cents": depletion_threshold_cents,
            "_closed": False,
        }
        stamp_new(pool)
        db.funding_pools[pool["id"]] = pool
        return object_response(serialize_pool(pool), 201)

    @app.route("/liheap/funding-pools/<id_>", methods=["GET"])
    @endpoint(["ProgramAdmin", "Caseworker"])
    def get_funding_pool(role, user_id, id_):
        pool = get_path(db.funding_pools, id_)
        return object_response(serialize_pool(pool), 200)

    @app.route("/liheap/funding-pools/<id_>/close", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def close_funding_pool(role, user_id, id_):
        pool = get_path(db.funding_pools, id_)
        # Generic state guard: closing an already-closed pool -> ERR_INVALID_STATE.
        if pool.get("_closed"):
            raise ApiError("ERR_INVALID_STATE", "Pool is already CLOSED")
        pool["_closed"] = True
        # Cascade: every PLEDGED pledge on this pool -> EXPIRED, releasing reserved funds.
        for pl in db.pledges.values():
            if pl["funding_pool_id"] == pool["id"] and pl["status"] == "PLEDGED":
                pl["status"] = "EXPIRED"
                touch(pl)
        touch(pool)
        return object_response(serialize_pool(pool), 200)

    @app.route("/_clock/set_current_utc", methods=["POST"])
    @endpoint(["ProgramAdmin"])
    def set_clock(role, user_id):
        body = get_body()
        raw = req_str(body, "to_iso8601")
        try:
            dt = parse_dt(raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO-8601 datetime")
        db.clock = dt
        return object_response({}, 200)
