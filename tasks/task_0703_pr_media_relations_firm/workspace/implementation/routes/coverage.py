"""Coverage endpoints and lifecycle (PRD 3.8, 3.9, 3.10)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_datetime, require_enum,
                    require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services import calculations as calc, ledger
from services.serialize import coverage_out

bp = Blueprint("coverage", __name__)

SENTIMENTS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}
PROMINENCES = {"FEATURE", "MENTION", "PASSING"}
COVERAGE_STATUSES = {"DRAFT", "VERIFIED", "RETRACTED"}


@bp.post("/agency/coverage")
@authorize(["MediaSpecialist"])
def create_coverage():
    body = get_json_body()
    campaign_id = body.get("campaign_id")
    journalist_id = body.get("journalist_id")
    pitch_id = body.get("pitch_id")
    # Priority 4: FK existence (pitch_id is nullable).
    campaign = ref_or_404(db.campaigns, campaign_id, "campaign_id")
    journalist = ref_or_404(db.journalists, journalist_id, "journalist_id")
    if pitch_id is not None:
        ref_or_404(db.pitches, pitch_id, "pitch_id")
    # Priority 5: well-formedness.
    headline = require_str(body, "headline")
    require_datetime(body, "published_at")
    sentiment = require_enum(body, "sentiment", SENTIMENTS)
    prominence = require_enum(body, "prominence", PROMINENCES)

    client = db.clients[campaign["client_id"]]
    outlet = db.outlets[journalist["outlet_id"]]

    cov = {
        "sentiment": sentiment,
        "prominence": prominence,
    }
    estimated = calc.media_value_estimated(outlet, cov, client)

    rec = new_record({
        "campaign_id": campaign_id,
        "journalist_id": journalist_id,
        "pitch_id": pitch_id,
        "headline": headline,
        "published_at": body["published_at"],
        "sentiment": sentiment,
        "prominence": prominence,
        "estimated_media_value_cents": estimated,
        "media_value_cents": 0,
        "status": "DRAFT",
    })
    db.coverage[rec["id"]] = rec
    return success(coverage_out(rec), status=201)


@bp.get("/agency/coverage/<coverage_id>")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def get_coverage(coverage_id):
    rec = get_or_404(db.coverage, coverage_id)
    return success(coverage_out(rec))


@bp.get("/agency/coverage")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def list_coverage():
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    journalist_id = request.args.get("journalist_id")
    pitch_id = request.args.get("pitch_id")
    status = request.args.get("status")
    if status is not None and status not in COVERAGE_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.coverage.values():
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if journalist_id is not None and r["journalist_id"] != journalist_id:
            continue
        if pitch_id is not None and r.get("pitch_id") != pitch_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([coverage_out(r) for r in page], pagination=meta)


@bp.post("/agency/coverage/<coverage_id>/verify")
@authorize(["MediaSpecialist"])
def verify_coverage(coverage_id):
    rec = get_or_404(db.coverage, coverage_id)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Coverage is not DRAFT")
    campaign = db.campaigns[rec["campaign_id"]]
    if campaign["status"] not in ("ACTIVE", "PAUSED", "COMPLETED"):
        raise err("ERR_INVALID_STATE",
                  "Owning campaign is not in ACTIVE, PAUSED, or COMPLETED")
    journalist = db.journalists[rec["journalist_id"]]
    client = db.clients[campaign["client_id"]]
    outlet = db.outlets[journalist["outlet_id"]]

    rec["media_value_cents"] = calc.media_value_verified(outlet, rec, client)
    rec["status"] = "VERIFIED"
    touch(rec)

    # Conserved-quantity re-derivation (drift-free) on campaign and client.
    ledger.recompute_campaign_ledger(campaign)
    touch(campaign)
    ledger.recompute_client_lifetime(client)
    touch(client)
    return success(coverage_out(rec))


@bp.post("/agency/coverage/<coverage_id>/retract")
@authorize(["MediaSpecialist"])
def retract_coverage(coverage_id):
    rec = get_or_404(db.coverage, coverage_id)
    if rec["status"] not in ("DRAFT", "VERIFIED"):
        raise err("ERR_INVALID_STATE", "Coverage cannot be retracted from its current state")
    was_verified = rec["status"] == "VERIFIED"
    rec["status"] = "RETRACTED"
    if was_verified:
        rec["media_value_cents"] = 0
    touch(rec)

    if was_verified:
        campaign = db.campaigns[rec["campaign_id"]]
        client = db.clients[campaign["client_id"]]
        ledger.recompute_campaign_ledger(campaign)
        touch(campaign)
        ledger.recompute_client_lifetime(client)
        touch(client)
    return success(coverage_out(rec))
