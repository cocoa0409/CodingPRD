"""Campaign endpoints (PRD 3.1, 3.8, 3.9, 3.10)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import calc, domain

bp = Blueprint("campaigns", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
CAMPAIGN_STATUSES = ["DRAFT", "PUBLISHED", "CLOSED"]


@bp.post("/api/campaigns")
def create_campaign():
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    organization_id = v.req_str(body, "organization_id")
    title = v.req_str(body, "title")
    goal_amount_cents = v.req_int(body, "goal_amount_cents", minimum=1)
    fundraising_minimum_cents = v.opt_int(
        body, "fundraising_minimum_cents", default=0, minimum=0
    )
    organization = domain.get_organization(organization_id)
    domain.require_manager_owns_organization(user_id, organization)
    rec = db.new_record(
        organization_id=organization_id,
        title=title,
        goal_amount_cents=goal_amount_cents,
        fundraising_minimum_cents=fundraising_minimum_cents,
        status="DRAFT",
        published_at=None,
        closed_at=None,
        raised_credited_cents=0,
        lifetime_net_cents=0,
        reserved_payout_cents=0,
        paid_out_cents=0,
        available_balance_cents=0,
        donor_count=0,
        receipt_seq=0,
    )
    store.campaigns[rec["id"]] = rec
    return response.object_response(domain.ser_campaign(rec), 201)


@bp.get("/api/campaigns/<campaign_id>")
def read_campaign(campaign_id):
    authorize(PUBLIC)
    rec = domain.get_campaign(campaign_id)
    return response.object_response(domain.ser_campaign(rec))


@bp.get("/api/campaigns")
def list_campaigns():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    organization_id = v.q("organization_id")
    status = v.q_enum("status", CAMPAIGN_STATUSES)
    rows = list(store.campaigns.values())
    if organization_id is not None:
        rows = [r for r in rows if r["organization_id"] == organization_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_campaign, limit, offset)


@bp.post("/api/campaigns/<campaign_id>/publish")
def publish_campaign(campaign_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_campaign(campaign_id)
    domain.require_manager_owns_campaign(user_id, rec)
    if rec["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE")
    if rec["goal_amount_cents"] < 1:
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "PUBLISHED"
    rec["published_at"] = db.now_iso()
    db.touch(rec)
    return response.object_response(domain.ser_campaign(rec))


@bp.post("/api/campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_campaign(campaign_id)
    domain.require_manager_owns_campaign(user_id, rec)
    if rec["status"] != "PUBLISHED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "CLOSED"
    rec["closed_at"] = db.now_iso()
    db.touch(rec)
    # Cascade step 1: events OPEN/FULL -> CLOSED.
    for event in db.ordered(domain.campaign_events(campaign_id)):
        domain.refresh_event(event)
        if event["status"] in ("OPEN", "FULL"):
            event["status"] = "CLOSED"
            db.touch(event)
    # Cascade step 2: match pools ACTIVE/EXHAUSTED -> CLOSED.
    for pool in db.ordered(domain.campaign_pools(campaign_id)):
        domain.refresh_pool(pool)
        if pool["status"] in ("ACTIVE", "EXHAUSTED"):
            pool["status"] = "CLOSED"
            db.touch(pool)
    return response.object_response(domain.ser_campaign(rec))


@bp.get("/api/campaigns/<campaign_id>/thermometer")
def campaign_thermometer(campaign_id):
    authorize(PUBLIC)
    rec = domain.get_campaign(campaign_id)
    domain.refresh_campaign(rec)
    participant_count = len(
        [
            p
            for p in domain.campaign_participants(campaign_id)
            if p["status"] in domain.MEMBER_STATUSES
        ]
    )
    percent_bp = calc.basis_points(
        rec["raised_credited_cents"], rec["goal_amount_cents"]
    )
    percent_bp = min(percent_bp, config.PERCENT_BP_DISPLAY_CAP)
    return response.object_response(
        {
            "goal_amount_cents": rec["goal_amount_cents"],
            "raised_credited_cents": rec["raised_credited_cents"],
            "percent_bp": percent_bp,
            "donor_count": rec["donor_count"],
            "participant_count": participant_count,
        }
    )


@bp.get("/api/campaigns/<campaign_id>/leaderboard")
def campaign_leaderboard(campaign_id):
    authorize(PUBLIC)
    limit, offset = v.pagination()
    scope = v.q("scope")
    if scope is None:
        raise_error("ERR_INVALID_REQUEST", "Query parameter 'scope' is required.")
    if scope not in ("TEAM", "PARTICIPANT"):
        raise_error(
            "ERR_INVALID_REQUEST",
            "Query parameter 'scope' must be one of TEAM, PARTICIPANT.",
        )
    variant = v.q("variant") or "RAW_TOTAL"
    if variant not in ("RAW_TOTAL", "GOAL_PERCENT"):
        raise_error(
            "ERR_INVALID_REQUEST",
            "Query parameter 'variant' must be one of RAW_TOTAL, GOAL_PERCENT.",
        )
    rec = domain.get_campaign(campaign_id)

    entries = []
    if scope == "TEAM":
        for team in domain.campaign_teams(rec["id"]):
            domain.refresh_team(team)
            if team["status"] != "ACTIVE":
                continue
            row = db.serialize(team)
            row["goal_percent_bp"] = calc.basis_points(
                team["credited_cents"], team["goal_amount_cents"]
            )
            entries.append((team, row))
    else:
        for participant in domain.campaign_participants(rec["id"]):
            domain.refresh_participant(participant)
            row = db.serialize(participant)
            row["goal_percent_bp"] = calc.basis_points(
                participant["credited_cents"], participant["personal_goal_cents"]
            )
            entries.append((participant, row))

    if variant == "GOAL_PERCENT":
        entries.sort(
            key=lambda e: (-e[1]["goal_percent_bp"], e[0]["created_at"], e[0]["_seq"])
        )
    else:
        entries.sort(
            key=lambda e: (-e[0]["credited_cents"], e[0]["created_at"], e[0]["_seq"])
        )

    total_count = len(entries)
    window = entries[offset:offset + limit]
    rows = []
    for index, (_rec, row) in enumerate(window):
        row["rank"] = offset + index + 1
        rows.append(row)

    return response.object_response_paginated(
        {"scope": scope, "variant": variant, "rows": rows},
        limit,
        offset,
        total_count,
    )


@bp.get("/api/campaigns/<campaign_id>/report")
def campaign_report(campaign_id):
    user_id, role = authorize(
        [
            config.ROLE_PLATFORM_ADMIN,
            config.ROLE_CAMPAIGN_MANAGER,
            config.ROLE_FINANCE_REVIEWER,
        ]
    )
    rec = domain.get_campaign(campaign_id)
    domain.require_actor_owns_campaign(user_id, role, rec)

    donations = db.ordered(domain.campaign_donations(campaign_id))[
        : config.REPORT_ROW_LIMIT
    ]
    settled = [d for d in donations if d["payment_status"] == "SETTLED"]
    refunded = [d for d in donations if d["payment_status"] == "REFUNDED"]
    receipts = db.ordered(domain.campaign_receipts(campaign_id))[
        : config.REPORT_ROW_LIMIT
    ]
    registrations = []
    for event in domain.campaign_events(campaign_id):
        registrations.extend(domain.event_registrations(event["id"]))
    registrations = db.ordered(registrations)[: config.REPORT_ROW_LIMIT]
    awards = []
    for participant in domain.campaign_participants(campaign_id):
        awards.extend(domain.participant_awards(participant["id"]))
    awards = db.ordered(awards)[: config.REPORT_ROW_LIMIT]

    data = {
        "settled_donation_count": len(settled),
        "refunded_donation_count": len(refunded),
        "gross_amount_cents": sum(d["amount_cents"] for d in settled),
        "fee_total_cents": sum(d["fee_cents"] for d in settled + refunded),
        "match_total_cents": sum(d["matched_amount_cents"] for d in settled),
        "deductible_total_cents": sum(
            r["deductible_amount_cents"] for r in receipts if r["status"] == "ISSUED"
        ),
        "confirmed_registrations": len(
            [r for r in registrations if r["status"] in ("CONFIRMED", "CHECKED_IN")]
        ),
        "checked_in_registrations": len(
            [r for r in registrations if r["status"] == "CHECKED_IN"]
        ),
        "awards_earned_count": len(
            [a for a in awards if a["status"] in ("EARNED", "FULFILLED")]
        ),
    }
    return response.object_response(data)


@bp.post("/api/campaigns/<campaign_id>/payouts")
def create_payout(campaign_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    amount_cents = v.req_int(body, "amount_cents", minimum=1)
    expected_campaign_version = v.req_int(body, "expected_campaign_version")
    note = v.opt_str(body, "note", default="")
    campaign = domain.get_campaign(campaign_id)
    domain.require_manager_owns_campaign(user_id, campaign)

    # PRD 2.8 step 13: fiscal floor.
    if amount_cents < config.MIN_PAYOUT_CENTS:
        raise_error("ERR_PAYOUT_BELOW_MINIMUM")

    superseded = [
        p
        for p in domain.campaign_payouts(campaign_id)
        if p["status"] in ("REQUESTED", "CHANGES_REQUESTED")
    ]
    domain.refresh_campaign(campaign)
    released_reservation = sum(p["amount_cents"] for p in superseded)
    # PRD 2.8 step 14: balance measured AFTER the superseded reservation is released.
    available_after = campaign["available_balance_cents"] + released_reservation
    if amount_cents > available_after:
        raise_error("ERR_INSUFFICIENT_CAMPAIGN_BALANCE")

    # PRD 2.8 step 16: stale-version rejection runs last.
    if expected_campaign_version != campaign["version"]:
        raise_error("ERR_STALE_CAMPAIGN_VERSION")

    for payout in db.ordered(superseded):
        payout["status"] = "SUPERSEDED"
        db.touch(payout)

    rec = db.new_record(
        campaign_id=campaign_id,
        amount_cents=amount_cents,
        note=note,
        requested_by_user_id=user_id,
        reviewed_by_user_id=None,
        approved_by_user_id=None,
        status="REQUESTED",
        released_at=None,
    )
    store.payouts[rec["id"]] = rec
    db.touch(campaign)
    domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_payout(rec), 201)
