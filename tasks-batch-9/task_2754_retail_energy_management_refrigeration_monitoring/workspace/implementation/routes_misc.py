"""Portfolio benchmarking report and the logical clock (PRD 3.10, 2.5)."""

from flask import Blueprint

import calc
import cascade
import derive
import envelope
import validate as v
from common import CLIMATE_ZONES, STORE_FORMATS
from db import db
from security import (ENERGY_ANALYST, ENERGY_MANAGER, PLATFORM_ADMIN, roles)
from util import fmt_iso, q

bp = Blueprint("misc", __name__)


@bp.route("/benchmark-report", methods=["GET"])
@roles(PLATFORM_ADMIN, ENERGY_MANAGER, ENERGY_ANALYST)
def benchmark_report():
    climate_zone = v.query_enum("climate_zone", CLIMATE_ZONES, required=True)
    store_format = v.query_enum("store_format", STORE_FORMATS, required=True)
    outliers_only = v.query_bool("outliers_only")
    eui_map = calc.all_store_euis()
    # Every store of the requested climate zone and format is reported, because
    # "A store with a null intensity has a null percentile and a false flag".
    scope = [s for s in derive._by_created(list(db.stores.values()))
             if s["climate_zone"] == climate_zone
             and s["store_format"] == store_format]
    # The peer group itself holds only the members with a non-null intensity:
    # "a store with a null intensity is in nobody's peer group, not even its own
    # group's count".
    group = [s for s in scope if eui_map.get(s["id"]) is not None]
    ordered = sorted([(eui_map[s["id"]], s["created_at"], s["_seq"]) for s in group],
                     key=lambda t: (t[0], t[1], t[2]))
    group_median = calc._median(ordered)
    rows = []
    outlier_count = 0
    for store in scope:
        figures = calc.benchmark_for_store(store, eui_map)
        if figures["benchmark_outlier_flag"]:
            outlier_count += 1
        if outliers_only and not figures["benchmark_outlier_flag"]:
            continue
        rows.append({
            "store_id": store["id"],
            "code": store["code"],
            "eui_kbtu_per_sqft": q(figures["eui_kbtu_per_sqft"], 2),
            "benchmark_percentile": q(figures["benchmark_percentile"], 1),
            "benchmark_outlier_flag": figures["benchmark_outlier_flag"],
            "peer_median_eui": q(figures["peer_median_eui"], 2),
            "outlier_threshold_eui": q(figures["outlier_threshold_eui"], 2),
        })
    return envelope.ok({
        "climate_zone": climate_zone,
        "store_format": store_format,
        "peer_group_count": len(group),
        "peer_group_median_eui": q(group_median, 2),
        "outlier_count": outlier_count,
        "stores": rows,
    })


@bp.route("/_clock/set_current_utc", methods=["POST"])
@roles(PLATFORM_ADMIN)
def set_clock():
    body = v.body()
    current_utc = v.get_dt(body, "current_utc")
    db.clock = current_utc

    affected = []

    def mark(store):
        if store is not None and store["id"] not in [s["id"] for s in affected]:
            affected.append(store)

    dr_events_completed = 0
    for event in derive._by_created(list(db.dr_events.values())):
        if (event["event_state"] == "ACTIVE"
                and event["curtailment_end_iso"] <= db.clock):
            event["event_state"] = "COMPLETED"
            cascade.touch(event)
            dr_events_completed += 1
            mark(derive.store_of_account(derive.account_of_event(event)))

    overrides_activated = 0
    for override in derive._by_created(list(db.overrides.values())):
        if (override["state"] == "SCHEDULED"
                and override["start_iso"] <= db.clock < override["end_iso"]):
            override["state"] = "ACTIVE"
            cascade.touch(override)
            overrides_activated += 1
            mark(db.stores.get(override["store_id"]))

    overrides_expired = 0
    for override in derive._by_created(list(db.overrides.values())):
        if (override["state"] in ("SCHEDULED", "ACTIVE")
                and override["end_iso"] <= db.clock):
            override["state"] = "EXPIRED"
            cascade.touch(override)
            overrides_expired += 1
            mark(db.stores.get(override["store_id"]))

    for store in affected:
        cascade.recompute_posture(store)

    return envelope.ok({
        "current_utc": fmt_iso(db.clock),
        "dr_events_completed": dr_events_completed,
        "overrides_activated": overrides_activated,
        "overrides_expired": overrides_expired,
        "stores_posture_recomputed": len(affected),
    })
