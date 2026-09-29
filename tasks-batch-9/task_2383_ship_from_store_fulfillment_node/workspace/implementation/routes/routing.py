"""Routing runs and their persisted candidate evaluations."""
from flask import Blueprint

from constants import (
    API_PREFIX, MAX_COST_INDEX_BPS, ROLE_ASSOCIATE, ROLE_CARE, ROLE_CARRIER,
    ROLE_PLANNER, RUN_INITIATORS, RUN_MODES, RUN_STATUSES,
)
from db import all_of, db
from errors import ApiError
from middleware import (
    authenticate, body, get_bool, get_enum, get_int, pagination_args, query_bool,
    query_enum, query_int, query_str,
)
from routes.common import apply_filter, fetch, finish, listing, show
from services import notifications
from services.derive import order_lines_of
from services.routing import create_run, execute_run

bp = Blueprint("routing", __name__)

ANY_ROLE = (ROLE_PLANNER, ROLE_ASSOCIATE, ROLE_CARRIER, ROLE_CARE)


@bp.route(API_PREFIX + "/orders/<order_id>/routing-runs", methods=["POST"])
def create_routing_run(order_id):
    authenticate(ROLE_PLANNER)
    payload = body()
    mode = get_enum(payload, "mode", RUN_MODES)
    expected_version = get_int(payload, "expected_order_version")
    override = get_bool(payload, "override_cost_guardrail", required=False,
                        default=False)

    order = fetch("orders", order_id)
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_NOT_ROUTABLE")
    if not any(l["open_units"] >= 1 for l in order_lines_of(order_id)):
        raise ApiError("ERR_NO_ROUTABLE_LINES")

    commit_mode = mode == "COMMIT"
    snapshot = db.snapshot() if commit_mode else None

    run = create_run(order, mode, "PLANNER", [])
    outcome = execute_run(run, order, base_generation=0)

    if commit_mode and run["projected_cost_index_bps"] > MAX_COST_INDEX_BPS:
        if not override:
            db.restore(snapshot)
            raise ApiError("ERR_COST_INDEX_GUARDRAIL")
        run["guardrail_overridden"] = True

    if commit_mode:
        if outcome["dc_fallback_units"] > 0:
            notifications.emit(order, None, "DC_FALLBACK",
                               outcome["dc_fallback_units"])
        elif outcome["empty_pool_at_first_iteration"]:
            notifications.emit(order, None, "UNROUTABLE",
                               order["unassigned_units"])

    return finish(run, 201, explicit=[order])


@bp.route(API_PREFIX + "/routing-runs", methods=["GET"])
def list_routing_runs():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("routing_runs")
    rows = apply_filter(rows, "order_id", query_str("order_id"))
    rows = apply_filter(rows, "mode", query_enum("mode", RUN_MODES))
    rows = apply_filter(rows, "status", query_enum("status", RUN_STATUSES))
    rows = apply_filter(rows, "initiated_by",
                        query_enum("initiated_by", RUN_INITIATORS))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/routing-runs/<routing_run_id>", methods=["GET"])
def read_routing_run(routing_run_id):
    authenticate(*ANY_ROLE)
    return show(fetch("routing_runs", routing_run_id))


@bp.route(API_PREFIX + "/routing-candidates", methods=["GET"])
def list_candidates():
    authenticate(*ANY_ROLE)
    limit, offset = pagination_args()
    rows = all_of("candidates")
    rows = apply_filter(rows, "routing_run_id", query_str("routing_run_id"))
    rows = apply_filter(rows, "store_id", query_str("store_id"))
    rows = apply_filter(rows, "iteration", query_int("iteration"))
    rows = apply_filter(rows, "selected", query_bool("selected"))
    rows = apply_filter(rows, "eligible", query_bool("eligible"))
    return listing(rows, limit, offset)


@bp.route(API_PREFIX + "/routing-candidates/<candidate_id>", methods=["GET"])
def read_candidate(candidate_id):
    authenticate(*ANY_ROLE)
    return show(fetch("candidates", candidate_id))
