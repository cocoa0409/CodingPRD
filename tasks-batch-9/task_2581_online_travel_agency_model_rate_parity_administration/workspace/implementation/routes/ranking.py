"""Ranking runs, ranking entries and paid-placement disclosure (PRD 3.6)."""
from flask import Blueprint

import auth
import calc
import clock
import response
import store
import validate
from errors import ApiError
from store import created_key, db, touch

from routes import common

bp = Blueprint("ranking", __name__)

PROFILES = ("BEST_VALUE", "PRICE_ASC")
RUN_STATUSES = ("DRAFT", "PUBLISHED", "WITHDRAWN")
CERTIFIED_LEVELS = ("PROVISIONAL", "CERTIFIED")


def _eligible(market_id, travel_date):
    """The six-condition conjunction of PRD §3.6."""
    pool = []
    for offer in sorted(db["offers"].values(), key=lambda r: r["_seq"]):
        if offer["status"] != "LIVE" or offer["travel_date"] != travel_date:
            continue
        plan = db["rate_plans"].get(offer["rate_plan_id"])
        if plan is None or plan["market_id"] != market_id or plan["status"] != "ACTIVE":
            continue
        supplier = db["suppliers"].get(plan["supplier_id"])
        if supplier is None or supplier["visibility_status"] != "ACTIVE":
            continue
        if supplier["certification_level"] not in CERTIFIED_LEVELS:
            continue
        pool.append((offer, plan, supplier))
    return pool


@bp.post("/ranking-runs")
def create_run():
    auth.authenticate(("CommercialManager", "PlatformAdmin"))
    data = validate.body()
    raw_market = data.get("market_id")
    if isinstance(raw_market, str) and raw_market:
        common.find("markets", raw_market)
    market_id = validate.str_req(data, "market_id")
    travel_date = validate.date_req(data, "travel_date")
    sort_profile = validate.enum_req(data, "sort_profile", PROFILES)
    disclosure_version = validate.str_opt(data, "disclosure_version")
    today = clock.today()
    if travel_date < today.isoformat() \
            or travel_date > clock.plus_days(today, calc.MAX_HORIZON_DAYS).isoformat():
        raise ApiError("ERR_TRAVEL_DATE_OUT_OF_RANGE")
    pool = _eligible(market_id, travel_date)
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_OFFERS")
    scored = calc.rank_entries(pool, market_id, travel_date)
    run = store.new_row("ranking_runs", {
        "market_id": market_id,
        "travel_date": travel_date,
        "sort_profile": sort_profile,
        "disclosure_version": disclosure_version,
        "weights_snapshot": {
            "price": calc.num(calc.W_PRICE),
            "content": calc.num(calc.W_CONTENT),
            "parity": calc.num(calc.W_PARITY),
            "conversion": calc.num(calc.W_CONVERSION),
        },
        "entry_count": len(scored),
        "paid_entry_count": sum(1 for row in scored if row["is_paid_placement"]),
        "status": "DRAFT",
        "published_at": None,
        "published_by_user_id": None,
        "withdrawal_reason": None,
    })
    for fields in scored:
        fields = dict(fields)
        fields["ranking_run_id"] = run["id"]
        store.new_row("ranking_entries", fields, versioned=False)
    return response.obj(run, 201)


@bp.get("/ranking-runs/<run_id>")
def read_run(run_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("ranking_runs", run_id), 200)


@bp.get("/ranking-runs")
def list_runs():
    auth.authenticate(auth.ALL_ROLES)
    market_id = validate.filter_str("market_id")
    travel_date = validate.filter_date("travel_date")
    status = validate.filter_enum("status", RUN_STATUSES)
    rows = []
    for row in db["ranking_runs"].values():
        if market_id is not None and row["market_id"] != market_id:
            continue
        if travel_date is not None and row["travel_date"] != travel_date:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return common.paged(rows, reverse=True)


@bp.post("/ranking-runs/<run_id>/publish")
def publish_run(run_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    run = common.find("ranking_runs", run_id)
    data = validate.body()
    validate.str_opt(data, "note")
    if run["status"] != "DRAFT":
        raise ApiError("ERR_RUN_NOT_DRAFT")
    market = db["markets"].get(run["market_id"])
    if market is not None and market["ranking_disclosure_required"] \
            and not run.get("disclosure_version"):
        raise ApiError("ERR_DISCLOSURE_MISSING")
    for entry in sorted(db["ranking_entries"].values(), key=lambda r: r["_seq"]):
        if entry["ranking_run_id"] != run["id"] or not entry["is_paid_placement"]:
            continue
        placement = db["placements"].get(entry["placement_agreement_id"])
        if placement is None or placement["status"] != "ACTIVE":
            raise ApiError("ERR_PLACEMENT_NOT_ACTIVE")
    run["status"] = "PUBLISHED"
    run["published_at"] = clock.now_iso()
    run["published_by_user_id"] = actor.user_id
    touch(run)
    return response.obj(run, 200)


@bp.post("/ranking-runs/<run_id>/withdraw")
def withdraw_run(run_id):
    auth.authenticate(("ComplianceOfficer", "CommercialManager"))
    run = common.find("ranking_runs", run_id)
    data = validate.body()
    reason = validate.str_req(data, "withdrawal_reason")
    if run["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_RUN_NOT_PUBLISHED")
    run["status"] = "WITHDRAWN"
    run["withdrawal_reason"] = reason
    touch(run)
    return response.obj(run, 200)


@bp.get("/ranking-entries/<entry_id>")
def read_entry(entry_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("ranking_entries", entry_id), 200)


@bp.get("/ranking-entries")
def list_entries():
    auth.authenticate(auth.ALL_ROLES)
    run_id = validate.filter_str("ranking_run_id")
    offer_id = validate.filter_str("offer_id")
    placement_id = validate.filter_str("placement_agreement_id")
    is_paid = validate.filter_bool("is_paid_placement")
    rows = []
    for row in db["ranking_entries"].values():
        if run_id is not None and row["ranking_run_id"] != run_id:
            continue
        if offer_id is not None and row["offer_id"] != offer_id:
            continue
        if placement_id is not None and row["placement_agreement_id"] != placement_id:
            continue
        if is_paid is not None and row["is_paid_placement"] != is_paid:
            continue
        rows.append(row)
    return common.paged(rows, key=lambda r: (r["rank_position"], created_key(r)))
