"""Inflation monitoring epochs and the logical clock (PRD 3.9 / 2.4)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate
from response import list_response, object_response, touch
from services import calc, cascades

bp = Blueprint("monitoring", __name__)

READ_ROLES = (
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_COMPLIANCE_OFFICER,
)


@bp.post("/monitoring-runs")
def create_monitoring_run():
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    payload = v.body()
    season = resolve.body_fk(payload, "season_id", db.db.seasons, "ERR_SEASON_NOT_FOUND")
    v.req_string(payload, "season_id")
    epoch_no = v.req_int(payload, "epoch_no", minimum=1)
    window_start = v.req_datetime(payload, "window_start")
    window_end = v.req_datetime(payload, "window_end")
    if window_end <= window_start:
        v.bad("window_end", "must be strictly after window_start")

    siblings = [r for r in db.db.monitoring_runs.values() if r["season_id"] == season["id"]]
    highest = max([r["epoch_no"] for r in siblings], default=0)
    if epoch_no != highest + 1:
        fail(
            "ERR_MONITORING_EPOCH_SEQUENCE",
            "epoch_no must be exactly one greater than the season's highest epoch_no.",
        )
    for sibling in siblings:
        if sibling["status"] == "OPEN":
            fail("ERR_MONITORING_EPOCH_SEQUENCE", "Another run of this season is still OPEN.")

    run = db.insert(
        db.db.monitoring_runs,
        {
            "season_id": season["id"],
            "epoch_no": epoch_no,
            "window_start": window_start,
            "window_end": window_end,
            "gross_faucet_minor": 0,
            "gross_sink_minor": 0,
            "sink_faucet_ratio_bp": None,
            "resulting_health": None,
            "suspended_offer_count": 0,
            "denied_purchase_count": 0,
            "status": "OPEN",
            "computed_at": None,
            "certified_by_user_id": None,
        },
    )
    return object_response(serialize(run), 201)


@bp.get("/monitoring-runs/<run_id>")
def read_monitoring_run(run_id):
    authenticate(*READ_ROLES)
    run = resolve.monitoring_run(run_id)
    return object_response(serialize(run))


@bp.get("/monitoring-runs")
def list_monitoring_runs():
    authenticate(*READ_ROLES)
    season_id = request.args.get("season_id")
    status = v.query_enum("status", config.MONITORING_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.db.monitoring_runs.values())
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    records = [serialize(r) for r in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/monitoring-runs/<run_id>/compute")
def compute_monitoring_run(run_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    run = resolve.monitoring_run(run_id)
    season = db.db.seasons.get(run["season_id"])

    if run["status"] != "OPEN":
        fail("ERR_MONITORING_RUN_INVALID_STATE", "Only an OPEN run can be computed.")
    if season is None or season["status"] not in ("LIVE", "CONCLUDED"):
        fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE or CONCLUDED to compute a run.")

    faucet, sink = calc.epoch_totals(season["id"], run["window_start"], run["window_end"])
    ratio = calc.ratio_bp(sink, faucet)
    run["gross_faucet_minor"] = faucet
    run["gross_sink_minor"] = sink
    run["sink_faucet_ratio_bp"] = ratio
    run["resulting_health"] = calc.health_band(ratio)
    run["computed_at"] = db.now()
    run["status"] = "COMPUTED"

    # Level 1 -- season posture.
    season["economy_health"] = run["resulting_health"]
    calc.recompute_cadence(season)
    touch(season)

    # Levels 2 to 4 -- LOOT_BOX suspension and the denial fan-out.
    suspended = 0
    denied = 0
    if season["economy_health"] == "INFLATED":
        offers = ordered(
            [
                o
                for o in db.db.offers.values()
                if o["season_id"] == season["id"]
                and o["offer_type"] == "LOOT_BOX"
                and o["availability_status"] == "LIVE"
            ]
        )
        for offer in offers:
            cascades.suspend_offer(offer)
            suspended += 1
            for purchase in cascades.pending_purchases_of_offer(offer):
                cascades.deny_purchase(purchase, cascades.DENY_MONITORING)
                denied += 1
    run["suspended_offer_count"] = suspended
    run["denied_purchase_count"] = denied
    touch(run)

    # Independent of the inflation branch: revisit every player of the season.
    players = ordered([p for p in db.db.players.values() if p["active_season_id"] == season["id"]])
    for player in players:
        calc.refresh_realized_pacing(player)
        cascades.reevaluate_spend_state(player, "MONITORING")
    return object_response(serialize(run))


@bp.post("/monitoring-runs/<run_id>/decision")
def decide_monitoring_run(run_id):
    user_id, _role = authenticate(config.ROLE_LIVEOPS_COMMANDER)
    run = resolve.monitoring_run(run_id)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("CERTIFY", "VOID"))

    if run["status"] != "COMPUTED":
        fail("ERR_MONITORING_RUN_INVALID_STATE", "Only a COMPUTED run can be certified or voided.")

    if decision == "CERTIFY":
        run["status"] = "CERTIFIED"
    else:
        run["status"] = "VOIDED"
        season = db.db.seasons.get(run["season_id"])
        if season is not None:
            certified = [
                r
                for r in db.db.monitoring_runs.values()
                if r["season_id"] == season["id"] and r["status"] == "CERTIFIED"
            ]
            if certified:
                latest = max(certified, key=lambda r: r["epoch_no"])
                season["economy_health"] = latest["resulting_health"]
            else:
                season["economy_health"] = "HEALTHY"
            touch(season)
    run["certified_by_user_id"] = user_id
    touch(run)
    return object_response(serialize(run))


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    payload = v.body()
    instant = v.req_datetime(payload, "to_iso8601")
    db.set_clock(instant)
    return object_response({"current_utc": db.iso(instant)})
