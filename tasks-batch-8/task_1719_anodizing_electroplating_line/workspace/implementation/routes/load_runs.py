"""Load run lifecycle endpoints: complete and abort."""
from decimal import Decimal

from flask import Blueprint

from db import store, get_clock, format_ts
from errors import ERR_LOAD_RUN_NOT_RUNNING, raise_err
from helpers import get_or_404, touch
from middleware import require_roles
from response import success_object
from serializers import load_run_view
from services import chemistry
from services.cascades import cascade_bath_exhausted

bp = Blueprint("load_runs", __name__)


@bp.route("/load-runs/<run_id>/complete", methods=["POST"])
def complete_load_run(run_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    run = get_or_404(store.load_runs, run_id)
    if run["status"] != "RUNNING":
        raise_err(ERR_LOAD_RUN_NOT_RUNNING, "complete requires load run RUNNING")

    bath = store.baths.get(run["bath_id"])
    wo = store.work_orders.get(run["work_order_id"])

    run["status"] = "COMPLETED"
    run["amp_hours_consumed"] = run["estimated_amp_hours"]
    run["ended_at"] = format_ts(get_clock())
    touch(run)

    if bath is not None:
        bath["amp_hour_reserved"] = chemistry.round2(
            Decimal(str(bath["amp_hour_reserved"])) - Decimal(str(run["estimated_amp_hours"]))
        )
        bath["amp_hour_used"] = chemistry.round2(
            Decimal(str(bath["amp_hour_used"])) + Decimal(str(run["amp_hours_consumed"]))
        )
        bath["active_load_run_id"] = None
        # Dragout depletion
        current = bath["current_concentration_g_l"]
        if current is not None:
            bath["current_concentration_g_l"] = chemistry.dragout_depletion(
                current, run["surface_area_dm2"]
            )
        touch(bath)
        # Exhaustion cascade: inclusive >=
        if bath["status"] == "ACTIVE" and Decimal(str(bath["amp_hour_used"])) >= Decimal(
            str(bath["amp_hour_capacity"])
        ):
            cascade_bath_exhausted(bath)

    if wo is not None:
        wo["completed_load_count"] += 1
        wo["status"] = "AWAITING_INSPECTION"
        touch(wo)

    return success_object(load_run_view(run))


@bp.route("/load-runs/<run_id>/abort", methods=["POST"])
def abort_load_run(run_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    run = get_or_404(store.load_runs, run_id)
    if run["status"] != "RUNNING":
        raise_err(ERR_LOAD_RUN_NOT_RUNNING, "abort requires load run RUNNING")

    bath = store.baths.get(run["bath_id"])
    wo = store.work_orders.get(run["work_order_id"])

    run["status"] = "ABORTED"
    run["ended_at"] = format_ts(get_clock())
    # amp_hours_consumed stays null
    touch(run)

    if bath is not None:
        bath["amp_hour_reserved"] = chemistry.round2(
            Decimal(str(bath["amp_hour_reserved"])) - Decimal(str(run["estimated_amp_hours"]))
        )
        bath["active_load_run_id"] = None
        touch(bath)

    if wo is not None:
        wo["status"] = "ROUTED"
        touch(wo)

    return success_object(load_run_view(run))
