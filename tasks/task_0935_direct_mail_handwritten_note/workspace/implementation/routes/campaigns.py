"""Campaigns, their three parallel status axes, and the two reports."""
from flask import Blueprint, request

import derive
import envelope
import serial
import services
from errors import ApiError
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("campaigns", __name__)

READ_ROLES = ["PlatformAdmin", "AccountOwner", "CampaignManager", "ComplianceOfficer",
              "ListOperator", "ProductionOperator"]


@bp.route("/mail/campaigns", methods=["POST"])
def create_campaign():
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager"])
    ctx.fk("account", "account_id")
    ctx.scope(lambda: ctx.get("account")["id"] if ctx.get("account") else None)
    ctx.fields(required=[("account_id", "str"), ("name", "str")])
    ctx.run()
    row = new_row({
        "account_id": ctx.body["account_id"],
        "name": ctx.body["name"],
        "lifecycle_status": "DRAFT",
        "compliance_status": "CLEAR",
        "billing_status": "OPEN",
        "hold_reason": None,
    })
    db.campaigns[row["id"]] = row
    return envelope.object_response(serial.campaign(row), 201)


@bp.route("/mail/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    ctx = Ctx(READ_ROLES)
    ctx.path("campaign", campaign_id)
    ctx.scope(lambda: ctx.get("campaign")["account_id"])
    ctx.run()
    return envelope.object_response(serial.campaign(ctx.get("campaign")), 200)


@bp.route("/mail/campaigns", methods=["GET"])
def list_campaigns():
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager", "ComplianceOfficer"])
    ctx.run()
    rows = list(db.campaigns.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    lifecycle = request.args.get("lifecycle_status")
    if lifecycle is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lifecycle]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.campaign(r) for r in page], limit, offset, total)


@bp.route("/mail/campaigns/<campaign_id>/activate", methods=["POST"])
def activate_campaign(campaign_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("campaign", campaign_id)
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.at(15, lambda: _lifecycle(ctx.get("campaign"), ("DRAFT", "PAUSED")))
    ctx.run()
    campaign = ctx.get("campaign")
    campaign["lifecycle_status"] = "ACTIVE"
    touch(campaign)
    return envelope.object_response(serial.campaign(campaign), 200)


@bp.route("/mail/campaigns/<campaign_id>/pause", methods=["POST"])
def pause_campaign(campaign_id):
    ctx = Ctx(["PlatformAdmin", "CampaignManager"])
    ctx.path("campaign", campaign_id)
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.at(15, lambda: _lifecycle(ctx.get("campaign"), ("ACTIVE",)))
    ctx.run()
    campaign = ctx.get("campaign")
    campaign["lifecycle_status"] = "PAUSED"
    schedule_ids = set(s["id"] for s in db.drip_schedules.values()
                       if s["campaign_id"] == campaign["id"])
    for step in list(db.drip_steps.values()):
        if step["drip_schedule_id"] in schedule_ids and step["status"] == "SCHEDULED":
            services.unschedule_step(step)
    touch(campaign)
    return envelope.object_response(serial.campaign(campaign), 200)


@bp.route("/mail/campaigns/<campaign_id>/compliance-holds", methods=["POST"])
def hold_campaign(campaign_id):
    ctx = Ctx(["PlatformAdmin", "ComplianceOfficer"])
    ctx.path("campaign", campaign_id)
    ctx.fields(required=[("hold_reason", "str")])
    # Not exempt from rung 9: a second hold on a held campaign is pre-empted
    # there and never reaches rung 15 (PRD 2.6).
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.at(15, lambda: _compliance(ctx.get("campaign"), "CLEAR"))
    ctx.run()
    campaign = ctx.get("campaign")
    campaign["compliance_status"] = "HOLD"
    campaign["hold_reason"] = ctx.body["hold_reason"]
    touch(campaign)
    return envelope.object_response(serial.campaign(campaign), 200)


@bp.route("/mail/campaigns/<campaign_id>/compliance-releases", methods=["POST"])
def release_campaign(campaign_id):
    ctx = Ctx(["PlatformAdmin", "ComplianceOfficer"])
    ctx.path("campaign", campaign_id)
    # The ONLY write endpoint exempt from rung 9; still bound by rung 10.
    ctx.gate(lambda: ctx.get("campaign"), exempt_compliance=True)
    ctx.at(15, lambda: _compliance(ctx.get("campaign"), "HOLD"))
    ctx.run()
    campaign = ctx.get("campaign")
    campaign["compliance_status"] = "CLEAR"
    touch(campaign)
    return envelope.object_response(serial.campaign(campaign), 200)


@bp.route("/mail/campaigns/<campaign_id>/billing-close", methods=["POST"])
def billing_close(campaign_id):
    ctx = Ctx(["PlatformAdmin", "ComplianceOfficer"])
    ctx.path("campaign", campaign_id)
    ctx.gate(lambda: ctx.get("campaign"))
    ctx.at(15, lambda: _lifecycle(ctx.get("campaign"), ("ACTIVE", "PAUSED")))
    ctx.run()
    campaign = ctx.get("campaign")
    services.cascade_c(campaign)
    return envelope.object_response(serial.campaign(campaign), 200)


def _lifecycle(campaign, allowed):
    if campaign["lifecycle_status"] not in allowed:
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")


def _compliance(campaign, expected):
    if campaign["compliance_status"] != expected:
        raise ApiError("ERR_CAMPAIGN_INVALID_STATE")


# ----------------------------------------------------------------- reports
@bp.route("/mail/campaigns/<campaign_id>/postage-reconciliation", methods=["GET"])
def postage_reconciliation(campaign_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager", "ComplianceOfficer"])
    ctx.path("campaign", campaign_id)
    ctx.scope(lambda: ctx.get("campaign")["account_id"])
    ctx.run()
    rows = [r for r in db.ledger_entries.values() if r["campaign_id"] == campaign_id]
    rows = envelope.sort_rows(rows)
    draw = sum(r["amount_cents"] for r in rows if r["entry_type"] == "DRAW")
    refund = sum(r["amount_cents"] for r in rows if r["entry_type"] == "REFUND")
    forfeit = sum(r["amount_cents"] for r in rows if r["entry_type"] == "FORFEIT")
    return envelope.object_response({
        "draw_cents": draw,
        "refund_cents": refund,
        "forfeit_cents": forfeit,
        "net_postage_cents": draw - refund + forfeit,
        "account_delta_cents": refund - draw - forfeit,
        "row_count": len(rows),
    }, 200)


@bp.route("/mail/campaigns/<campaign_id>/deliverability-report", methods=["GET"])
def deliverability_report(campaign_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager", "ListOperator"])
    ctx.path("campaign", campaign_id)
    ctx.scope(lambda: ctx.get("campaign")["account_id"])
    ctx.run()
    automation = retail = unmailable = duplicate = record_total = 0
    eddm_pieces = 0
    job_ids = []
    for job in derive.campaign_jobs(campaign_id):
        job_ids.append(job["id"])
        if job["job_kind"] == "EDDM":
            eddm_pieces += job["eddm_piece_count"]
            continue
        if not job["mailing_list_id"]:
            continue
        for record in derive.list_records_of(job["mailing_list_id"]):
            record_total += 1
            # The unmailable bucket is evaluated FIRST; the four buckets are
            # mutually exclusive and sum to record_total (PRD 2.10 / 3.9).
            if record["deliverability_tier"] == "UNMAILABLE":
                unmailable += 1
            elif record["dedupe_status"] in derive.DUPLICATE_DEDUPE:
                duplicate += 1
            elif (record["deliverability_tier"] == "AUTOMATION"
                  and record["dedupe_status"] in derive.SURVIVING_DEDUPE):
                automation += 1
            elif (record["deliverability_tier"] == "RETAIL"
                  and record["dedupe_status"] in derive.SURVIVING_DEDUPE):
                retail += 1
    returned = sum(1 for e in db.return_events.values() if e["mail_job_id"] in job_ids)
    return envelope.object_response({
        "automation_pieces": automation,
        "retail_pieces": retail,
        "unmailable_pieces": unmailable,
        "duplicate_pieces": duplicate,
        "record_total": record_total,
        "eddm_pieces": eddm_pieces,
        "returned_pieces": returned,
    }, 200)
