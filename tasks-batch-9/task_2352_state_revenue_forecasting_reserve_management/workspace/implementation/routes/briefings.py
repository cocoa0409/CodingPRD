"""Rating-agency briefings: the publish / stale / republish cycle."""

from datetime import timedelta

from flask import Blueprint

from db import db, make_record, now_dt, now_iso, ordered, touch
from errors import fail
from middleware import authorize, body, req_bool, req_str, validation
from response import object_response
from routes.helpers import briefing_or_404, cycle_or_404, fund_or_404, listing
from services import calc
from util import parse_dt

bp = Blueprint("briefings", __name__)

ROLES = ("ForecastDirector", "ReserveTreasurer", "RatingAnalyst")
NARRATIVE_MIN = 20


@bp.get("/rating-briefings")
@authorize(*ROLES)
def list_briefings():
    return listing(
        ordered(db.briefings),
        {
            "fund_id": ("fund_id", str),
            "cycle_id": ("cycle_id", str),
            "status": ("status", str),
            "stale_reason": ("stale_reason", str),
        },
    )


@bp.get("/rating-briefings/<briefing_id>")
@authorize(*ROLES)
def get_briefing(briefing_id):
    return object_response(briefing_or_404(briefing_id))


@bp.post("/rating-briefings")
@authorize("ForecastDirector", "RatingAnalyst")
def create_briefing():
    data = body()

    fund = None
    cycle = None
    if data.get("fund_id") is not None:
        if not isinstance(data["fund_id"], str):
            validation("fund_id must be a string")
        fund = fund_or_404(data["fund_id"])
    if data.get("cycle_id") is not None:
        if not isinstance(data["cycle_id"], str):
            validation("cycle_id must be a string")
        cycle = cycle_or_404(data["cycle_id"])
    if fund is None:
        validation("fund_id is required")
    if cycle is None:
        validation("cycle_id is required")
    narrative = req_str(data, "narrative", min_len=NARRATIVE_MIN)

    rec = make_record(
        {
            "fund_id": fund["id"],
            "cycle_id": cycle["id"],
            "narrative": narrative,
            "snapshot_fund_version": fund["version"],
            "snapshot_adequacy_band": fund["adequacy_band"],
            "snapshot_coverage_ratio_bps": fund["coverage_ratio_bps"],
            "status": "DRAFT",
            "published_at": None,
            "stale_reason": None,
            "retracted_at": None,
        }
    )
    db.briefings[rec["id"]] = rec
    return object_response(rec, 201)


@bp.patch("/rating-briefings/<briefing_id>")
@authorize("ForecastDirector", "RatingAnalyst")
def patch_briefing(briefing_id):
    briefing = briefing_or_404(briefing_id)
    data = body()
    narrative = req_str(data, "narrative", min_len=NARRATIVE_MIN)
    if briefing["status"] == "RETRACTED":
        fail("ERR_BRIEFING_TERMINAL", "a RETRACTED briefing is immutable")
    briefing["narrative"] = narrative
    touch(briefing)
    return object_response(briefing)


@bp.post("/rating-briefings/<briefing_id>/publish")
@authorize("ForecastDirector")
def publish_briefing(briefing_id):
    briefing = briefing_or_404(briefing_id)
    data = body()
    refresh = req_bool(data, "refresh_snapshot", default=False)

    if briefing["status"] not in ("DRAFT", "STALE"):
        fail("ERR_BRIEFING_NOT_PUBLISHABLE",
             "a briefing in %s may not be published" % briefing["status"])

    fund = db.funds.get(briefing["fund_id"])
    last = fund.get("last_transaction_at") if fund else None
    if last is not None:
        blackout_end = parse_dt(last) + timedelta(hours=calc.BRIEFING_BLACKOUT_HOURS)
        if now_dt() < blackout_end:
            fail("ERR_BRIEFING_COOLING_PERIOD",
                 "publication is blacked out for %d hours after a ledger movement"
                 % calc.BRIEFING_BLACKOUT_HOURS)

    stale_snapshot = (fund is None
                      or briefing["snapshot_fund_version"] != fund["version"]
                      or briefing["status"] == "STALE")
    if stale_snapshot and not refresh:
        fail("ERR_ADEQUACY_STALE",
             "the briefing snapshot is behind the fund; set refresh_snapshot to publish")

    if refresh and fund is not None:
        briefing["snapshot_fund_version"] = fund["version"]
        briefing["snapshot_adequacy_band"] = fund["adequacy_band"]
        briefing["snapshot_coverage_ratio_bps"] = fund["coverage_ratio_bps"]

    briefing["status"] = "PUBLISHED"
    briefing["published_at"] = now_iso()
    briefing["stale_reason"] = None
    touch(briefing)
    return object_response(briefing)


@bp.post("/rating-briefings/<briefing_id>/retract")
@authorize("ForecastDirector")
def retract_briefing(briefing_id):
    briefing = briefing_or_404(briefing_id)
    if briefing["status"] == "RETRACTED":
        fail("ERR_BRIEFING_TERMINAL", "the briefing is already RETRACTED")
    briefing["status"] = "RETRACTED"
    briefing["retracted_at"] = now_iso()
    touch(briefing)
    return object_response(briefing)
