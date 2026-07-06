"""PledgeCampaign endpoints."""

from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso_date,
    clock_now_dt, parse_iso8601,
)
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE

bp = Blueprint("pledge_campaigns", __name__)


def _round_half_up_2(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@bp.route("/pledge-campaigns", methods=["POST"])
def create_campaign():
    require_role({"FinanceAdmin", "PlatformAdmin"})
    body = get_json_body()
    for k in ("name", "target_amount_cents", "starts_on", "ends_on"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["name"], str) or body["name"] == "":
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if not isinstance(body["target_amount_cents"], int) or isinstance(body["target_amount_cents"], bool):
        raise_err(ERR_INVALID_REQUEST, "target_amount_cents must be an integer")
    if body["target_amount_cents"] <= 0:
        raise_err(ERR_INVALID_REQUEST, "target_amount_cents must be > 0")
    try:
        so = parse_iso_date(body["starts_on"])
        eo = parse_iso_date(body["ends_on"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "starts_on/ends_on must be YYYY-MM-DD")
    if eo < so:
        raise_err(ERR_INVALID_REQUEST, "ends_on must be >= starts_on")

    rec = {
        "name": body["name"],
        "target_amount_cents": body["target_amount_cents"],
        "starts_on": body["starts_on"],
        "ends_on": body["ends_on"],
        "status": "DRAFT",
        "pledged_total_cents": 0,
        "received_total_cents": 0,
        "fulfilled_pledge_count": 0,
    }
    stamp_common_create(rec)
    db.pledge_campaigns[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/pledge-campaigns/<pid>/activate", methods=["POST"])
def activate_campaign(pid):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.pledge_campaigns, pid, "PledgeCampaign")
    if rec["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "campaign must be DRAFT to activate")
    rec["status"] = "ACTIVE"
    bump(rec)
    return success(rec, 200)


@bp.route("/pledge-campaigns/<pid>/close", methods=["POST"])
def close_campaign(pid):
    require_role({"FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.pledge_campaigns, pid, "PledgeCampaign")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "campaign must be ACTIVE to close")
    rec["status"] = "CLOSED"
    bump(rec)
    return success(rec, 200)


def _projected_progress(campaign):
    pledged = 0
    for p in db.pledges.values():
        if p.get("campaign_id") != campaign["id"]:
            continue
        if p.get("status") in ("ACTIVE", "FULFILLED"):
            pledged += p["pledged_amount_cents"]
    target = campaign["target_amount_cents"]
    shortfall = max(0, target - pledged)
    if target > 0:
        pct = _round_half_up_2(Decimal(100) * Decimal(pledged) / Decimal(target))
    else:
        pct = Decimal("0.00")
    return {
        "projected_total_cents": pledged,
        "projected_shortfall_cents": shortfall,
        "projected_fulfillment_pct": float(pct),
    }


def _chronological_progress(campaign):
    now = clock_now_dt()
    posted_donations = []
    for d in db.donations.values():
        if d.get("campaign_id") != campaign["id"]:
            continue
        if d.get("status") != "POSTED":
            continue
        pa = d.get("posted_at")
        if pa is None:
            continue
        pa_dt = parse_iso8601(pa)
        if pa_dt > now:
            continue
        posted_donations.append(d)
    # Iterate in ASC donation_date, tie on ASC created_at.
    posted_donations.sort(key=lambda d: (d["donation_date"], d["created_at"]))
    running = 0
    series = []
    for d in posted_donations:
        running += d["amount_cents"]
        series.append({
            "donation_id": d["id"],
            "donation_date": d["donation_date"],
            "amount_cents": d["amount_cents"],
            "running_total_cents": running,
        })
    total = running
    target = campaign["target_amount_cents"]
    if target > 0:
        pct = _round_half_up_2(Decimal(100) * Decimal(total) / Decimal(target))
    else:
        pct = Decimal("0.00")
    return {
        "received_total_cents": total,
        "chronological_series": series,
        "chronological_fulfillment_pct": float(pct),
    }


@bp.route("/pledge-campaigns/<pid>", methods=["GET"])
def get_campaign(pid):
    require_role({"FinanceAdmin", "Coordinator", "PlatformAdmin"})
    rec = must_exist(db.pledge_campaigns, pid, "PledgeCampaign")
    variant = request.args.get("variant", "PROJECTED")
    if variant not in ("PROJECTED", "CHRONOLOGICAL"):
        raise_err(ERR_INVALID_REQUEST, "variant must be PROJECTED or CHRONOLOGICAL")
    out = dict(rec)
    # Recompute fields to stay reconciled with the ledger.
    projected = _projected_progress(rec)
    out["projected_total_cents"] = projected["projected_total_cents"]
    out["projected_shortfall_cents"] = projected["projected_shortfall_cents"]
    out["projected_fulfillment_pct"] = projected["projected_fulfillment_pct"]
    if variant == "CHRONOLOGICAL":
        chrono = _chronological_progress(rec)
        out["chronological_received_total_cents"] = chrono["received_total_cents"]
        out["chronological_series"] = chrono["chronological_series"]
        out["chronological_fulfillment_pct"] = chrono["chronological_fulfillment_pct"]
    return success(out, 200)
