"""Measurement epoch + snapshots (PRD 3.10): per-carrier monthly cycle."""
from flask import Blueprint, request

from db import db, next_seq
from errors import raise_error, ERR_CYCLE_ALREADY_RUN_TODAY
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import (
    touch, sweep_quoted_premiums, recompute_posture, recompute_driver_risk,
    recompute_inspection_total,
)
from validate import get_body, req_str, require_ref
from util import new_id, parse_datetime, fmt_datetime, CLOCK

bp = Blueprint("cycles", __name__)


def _snapshot_public(rec):
    # Snapshots are immutable epoch artifacts: id + created_at only (PRD 2.4).
    return public(rec)


@bp.post("/safety/measurement-cycles")
def run_cycle():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    carrier_id = req_str(body, "carrier_id")
    carrier = require_ref("carriers", carrier_id, "carrier_id")
    as_of = CLOCK.now()
    cycle_date = as_of.date().isoformat()
    # Stage 9: one cycle per carrier per UTC date
    if carrier["last_cycle_date"] == cycle_date:
        raise_error(ERR_CYCLE_ALREADY_RUN_TODAY,
                    "a measurement cycle already ran for this carrier today")
    posture_before = carrier["posture"]

    # 1. Refresh every violation's time weight and weighted points (carrier scope)
    for v in db["inspection_violations"].values():
        insp = db["roadside_inspections"].get(v["inspection_id"])
        if not insp or insp["carrier_id"] != carrier_id:
            continue
        w = calc.time_weight(parse_datetime(v["occurred_at"]), as_of)
        wp = v["severity_weight"] * w
        if w != v["time_weight_multiplier"] or wp != v["weighted_points"]:
            v["time_weight_multiplier"] = w
            v["weighted_points"] = wp
            touch(v)

    # 2. Reconcile inspection totals against refreshed weights
    for insp in db["roadside_inspections"].values():
        if insp["carrier_id"] == carrier_id:
            recompute_inspection_total(insp)

    # 3. Recompute each driver risk score/tier (blanket QUOTED sweep happens below)
    for d in db["drivers"].values():
        if d["carrier_id"] == carrier_id:
            recompute_driver_risk(d, sweep=False)

    # 4. Emit one snapshot per category (official + provisional variants)
    snapshots_created = 0
    categories = sorted(db["violation_categories"].values(), key=lambda c: c["_seq"])
    for cat in categories:
        official_measure = calc.measure_from_points(
            calc.category_points(carrier_id, cat, "official"), carrier["fleet_size"])
        provisional_measure = calc.measure_from_points(
            calc.category_points(carrier_id, cat, "provisional"), carrier["fleet_size"])
        official_pct = calc.percentile_from_measure(official_measure, cat["benchmark_measure"])
        provisional_pct = calc.percentile_from_measure(provisional_measure, cat["benchmark_measure"])
        snap = {
            "id": new_id(),
            "created_at": CLOCK.now_ts(),
            "_seq": next_seq(),
            "carrier_id": carrier_id,
            "category_id": cat["id"],
            "cycle_date": cycle_date,
            "as_of": fmt_datetime(as_of),
            "official_measure": float(official_measure),
            "provisional_measure": float(provisional_measure),
            "official_percentile": official_pct,
            "provisional_percentile": provisional_pct,
            "alerted_official": official_pct >= cat["intervention_threshold"],
            "alerted_provisional": provisional_pct >= cat["intervention_threshold"],
        }
        db["measurement_snapshots"][snap["id"]] = snap
        snapshots_created += 1

    # 5. Coaching sweep: ASSIGNED|IN_PROGRESS with due_date passed -> OVERDUE
    driver_ids = {d["id"] for d in db["drivers"].values() if d["carrier_id"] == carrier_id}
    overdue_marked = 0
    for c in db["coaching_assignments"].values():
        if (c["driver_id"] in driver_ids and c["status"] in ("ASSIGNED", "IN_PROGRESS")
                and parse_datetime(c["due_date"]) < as_of):
            c["status"] = "OVERDUE"
            touch(c)
            overdue_marked += 1

    # 6. Document sweep: RETAINED with retention reached -> PURGE_ELIGIBLE
    docs_marked = 0
    for doc in db["document_records"].values():
        if (doc["carrier_id"] == carrier_id and doc["status"] == "RETAINED"
                and parse_datetime(doc["retention_until"]) <= as_of):
            doc["status"] = "PURGE_ELIGIBLE"
            touch(doc)
            docs_marked += 1

    # 7. Posture from the fresh snapshots; stamp cycle date; single version bump
    carrier["last_cycle_date"] = cycle_date
    posture_after = recompute_posture(carrier)
    touch(carrier)

    # 8. Sweep the carrier's QUOTED premium models to STALE
    premiums_marked = sweep_quoted_premiums(carrier_id)

    return success_object({
        "cycle_date": cycle_date,
        "carrier_id": carrier_id,
        "snapshots_created": snapshots_created,
        "overdue_coaching_marked": overdue_marked,
        "documents_marked_purge_eligible": docs_marked,
        "premiums_marked_stale": premiums_marked,
        "posture_before": posture_before,
        "posture_after": posture_after,
    }, status=201)


@bp.get("/safety/measurement-snapshots")
def list_snapshots():
    return list_response("measurement_snapshots", filters={
        "carrier_id": request.args.get("carrier_id"),
        "category_id": request.args.get("category_id"),
        "cycle_date": request.args.get("cycle_date"),
    }, serializer=_snapshot_public)


@bp.get("/safety/measurement-snapshots/<rid>")
def get_snapshot(rid):
    return get_one("measurement_snapshots", rid, serializer=_snapshot_public)
