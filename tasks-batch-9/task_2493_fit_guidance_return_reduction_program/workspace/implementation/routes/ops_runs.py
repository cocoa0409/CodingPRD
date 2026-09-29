"""The ops-run checkpoint: one hop per deployment, then a full sweep (PRD 3.9)."""

from flask import Blueprint

import clock
import constants as C
from db import db, mutating, ordered
from middleware import authenticate
from response import object_response
from services.derive import (recompute_customer, recompute_intervention,
                             recompute_item, terminate_deployment)
from services.deployments import measure_window, snapshot_baseline

bp = Blueprint("ops_runs", __name__)


@bp.post("/fit-program/ops-runs")
def run_ops_checkpoint():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)

    db.ops_run_seq += 1
    run = db.ops_run_seq
    now = clock.now()

    stats = {
        "deployments_activated": 0,
        "deployments_terminated": 0,
        "deployments_measured": 0,
        "items_swept": 0,
        "watch_flips": 0,
        "chronic_flips": 0,
        "corrections_opened": 0,
        "abuse_downgrades": 0,
    }

    # ---- deployments: at most one hop each -------------------------------
    for deployment in ordered(db.deployments.values()):
        if deployment["_hop_run"] >= run:
            continue
        status = deployment["status"]

        if status == "SCHEDULED":
            item = db.items.get(deployment["item_id"])
            if (deployment["window_start"] <= now
                    and item is not None
                    and item["listing_status"] == "LISTED"):
                with mutating(deployment):
                    deployment["status"] = "ACTIVE"
                    snapshot_baseline(deployment)
                deployment["_hop_run"] = run
                stats["deployments_activated"] += 1

        elif status == "ACTIVE":
            if deployment["window_end"] <= now:
                terminate_deployment(deployment, "WINDOW_ELAPSED")
                stats["deployments_terminated"] += 1

        elif status == "TERMINATED":
            with mutating(deployment):
                deployment["status"] = "MEASURED"
                measure_window(deployment)
            deployment["_hop_run"] = run
            intervention = db.interventions.get(deployment["intervention_id"])
            if intervention is not None:
                recompute_intervention(intervention)
            stats["deployments_measured"] += 1

    # ---- the catalog sweep ----------------------------------------------
    for item in ordered(db.items.values()):
        recompute_item(item, stats)
        stats["items_swept"] += 1

    # ---- the shopper sweep ----------------------------------------------
    for customer in ordered(db.customers.values()):
        recompute_customer(customer, stats)

    return object_response(stats)
