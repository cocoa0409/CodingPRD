"""Donation endpoints: intake, settlement and refund (PRD 3.4, 3.5, 3.6, 3.7)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import calc, domain

bp = Blueprint("donations", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
DESIGNATION_TYPES = ["CAMPAIGN", "TEAM", "PARTICIPANT"]
PAYMENT_STATUSES = ["PENDING", "SETTLED", "REFUNDED", "FAILED"]


def _resolve_designation(campaign_id, designation_type, designation_id):
    """PRD 3.4: the target must be a row of the named type inside the campaign."""
    if designation_type == "CAMPAIGN":
        target = store.campaigns.get(designation_id)
        if target is None or target["id"] != campaign_id:
            raise_error("ERR_DESIGNATION_UNRESOLVABLE")
        return target
    if designation_type == "TEAM":
        target = store.teams.get(designation_id)
        if target is None or target["campaign_id"] != campaign_id:
            raise_error("ERR_DESIGNATION_UNRESOLVABLE")
        return target
    target = store.participants.get(designation_id)
    if target is None or target["campaign_id"] != campaign_id:
        raise_error("ERR_DESIGNATION_UNRESOLVABLE")
    return target


@bp.post("/api/donations")
def create_donation():
    user_id, role = authorize([config.ROLE_DONOR, config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    campaign_id = v.req_str(body, "campaign_id")
    donor_id = v.req_str(body, "donor_id")
    designation_type = v.req_enum(body, "designation_type", DESIGNATION_TYPES)
    designation_id = v.req_str(body, "designation_id")
    amount_cents = v.req_int(body, "amount_cents", minimum=100)
    cover_fees = v.opt_bool(body, "cover_fees", default=False)
    benefit_value_cents = v.opt_int(body, "benefit_value_cents", default=0, minimum=0)

    campaign = domain.get_campaign(campaign_id)
    donor = domain.get_donor(donor_id)
    if role == config.ROLE_DONOR:
        domain.require_donor_is(user_id, donor["id"])

    _resolve_designation(campaign_id, designation_type, designation_id)

    if campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")

    fee_cents, net_cents = calc.donation_fee_and_net(amount_cents, cover_fees)
    charged_amount_cents = calc.donation_charged_amount(
        amount_cents, fee_cents, cover_fees
    )
    rec = db.new_record(
        campaign_id=campaign_id,
        donor_id=donor_id,
        match_pool_id=None,
        designation_type=designation_type,
        designation_id=designation_id,
        amount_cents=amount_cents,
        cover_fees=cover_fees,
        benefit_value_cents=benefit_value_cents,
        fee_cents=fee_cents,
        net_cents=net_cents,
        charged_amount_cents=charged_amount_cents,
        matched_amount_cents=0,
        payment_status="PENDING",
        match_status="UNMATCHED",
        settled_at=None,
        refunded_at=None,
    )
    store.donations[rec["id"]] = rec
    return response.object_response(domain.ser_donation(rec), 201)


@bp.get("/api/donations/<donation_id>")
def read_donation(donation_id):
    authorize(PUBLIC)
    rec = domain.get_donation(donation_id)
    return response.object_response(domain.ser_donation(rec))


@bp.get("/api/donations")
def list_donations():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    donor_id = v.q("donor_id")
    match_pool_id = v.q("match_pool_id")
    designation_type = v.q_enum("designation_type", DESIGNATION_TYPES)
    designation_id = v.q("designation_id")
    payment_status = v.q_enum("payment_status", PAYMENT_STATUSES)
    rows = list(store.donations.values())
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if donor_id is not None:
        rows = [r for r in rows if r["donor_id"] == donor_id]
    if match_pool_id is not None:
        rows = [r for r in rows if r["match_pool_id"] == match_pool_id]
    if designation_type is not None:
        rows = [r for r in rows if r["designation_type"] == designation_type]
    if designation_id is not None:
        rows = [r for r in rows if r["designation_id"] == designation_id]
    if payment_status is not None:
        rows = [r for r in rows if r["payment_status"] == payment_status]
    return response.paged(rows, domain.ser_donation, limit, offset)


# --------------------------------------------------------------- settlement
def _credit_targets(donation, campaign):
    """Recompute and version-bump the designation target's credited totals."""
    if donation["designation_type"] == "PARTICIPANT":
        participant = store.participants.get(donation["designation_id"])
        if participant is not None:
            domain.refresh_participant(participant)
            db.touch(participant)
            if participant["team_id"]:
                team = store.teams.get(participant["team_id"])
                if team is not None:
                    domain.refresh_team(team)
                    db.touch(team)
    elif donation["designation_type"] == "TEAM":
        team = store.teams.get(donation["designation_id"])
        if team is not None:
            domain.refresh_team(team)
            db.touch(team)
    domain.refresh_campaign(campaign)


def _issue_receipt(donation, campaign):
    campaign["receipt_seq"] = campaign["receipt_seq"] + 1
    deductible = donation["amount_cents"] - donation["benefit_value_cents"]
    if deductible < 0:
        deductible = 0
    settled_at = db.dt_of(donation["settled_at"])
    receipt = db.new_record(
        donation_id=donation["id"],
        campaign_id=campaign["id"],
        receipt_number=calc.receipt_number(campaign["receipt_seq"]),
        deductible_amount_cents=deductible,
        tax_year=settled_at.year,
        status="ISSUED",
        issued_at=db.now_iso(),
        voided_at=None,
        reissue_count=0,
    )
    store.receipts[receipt["id"]] = receipt
    return receipt


def _award_incentives(donation, campaign):
    if donation["designation_type"] != "PARTICIPANT":
        return
    participant = store.participants.get(donation["designation_id"])
    if participant is None:
        return
    credited = participant["credited_cents"]
    existing = domain.participant_awards(participant["id"])
    for tier in db.ordered(domain.campaign_tiers(campaign["id"])):
        if tier["threshold_cents"] > credited:
            continue
        held = [
            a
            for a in existing
            if a["tier_id"] == tier["id"] and a["status"] != "REVOKED"
        ]
        if held:
            continue
        award = db.new_record(
            participant_id=participant["id"],
            tier_id=tier["id"],
            status="EARNED",
            earned_at=db.now_iso(),
            fulfilled_at=None,
            revoked_at=None,
        )
        store.incentive_awards[award["id"]] = award
        existing.append(award)


@bp.post("/api/donations/<donation_id>/settle")
def settle_donation(donation_id):
    authorize([config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    outcome = v.req_enum(body, "outcome", ["SETTLED", "FAILED"])
    rec = domain.get_donation(donation_id)
    if rec["payment_status"] != "PENDING":
        raise_error("ERR_INVALID_STATE")
    campaign = store.campaigns.get(rec["campaign_id"])

    if outcome == "FAILED":
        rec["payment_status"] = "FAILED"
        rec["match_status"] = "NOT_ELIGIBLE"
        db.touch(rec)
        return response.object_response(domain.ser_donation(rec))

    if campaign is None or campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")

    # Step 1: stamp the settled instant.
    rec["payment_status"] = "SETTLED"
    rec["settled_at"] = db.now_iso()

    # Step 2: sponsor match allocation.
    pool = domain.select_pool(rec["campaign_id"], rec["amount_cents"])
    matched = calc.match_amount(rec["amount_cents"], pool) if pool else 0
    if pool is not None and matched >= config.MIN_APPLIED_MATCH_CENTS:
        rec["match_pool_id"] = pool["id"]
        rec["match_status"] = "MATCHED"
        rec["matched_amount_cents"] = matched
        domain.refresh_pool(pool)
        db.touch(pool)
    else:
        rec["match_status"] = "NOT_ELIGIBLE"
        rec["matched_amount_cents"] = 0
    db.touch(rec)

    # Step 3: credited totals of the designation target.
    _credit_targets(rec, campaign)

    # Step 4: the tax receipt.
    _issue_receipt(rec, campaign)

    # Step 5: incentive awards for newly crossed tiers.
    _award_incentives(rec, campaign)

    db.touch(campaign)
    domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_donation(rec))


# ------------------------------------------------------------------ refunds
@bp.post("/api/donations/<donation_id>/refund")
def refund_donation(donation_id):
    authorize([config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    v.opt_str(body, "reason")
    rec = domain.get_donation(donation_id)
    if rec["payment_status"] != "SETTLED":
        raise_error("ERR_DONATION_NOT_REFUNDABLE")

    settled_at = db.dt_of(rec["settled_at"])
    if db.now() > settled_at + db.days(config.REFUND_WINDOW_DAYS):
        raise_error("ERR_REFUND_WINDOW_EXPIRED")

    campaign = store.campaigns.get(rec["campaign_id"])
    domain.refresh_campaign(campaign)
    owed = rec["net_cents"] + rec["matched_amount_cents"]
    if campaign["available_balance_cents"] < owed:
        raise_error("ERR_INSUFFICIENT_CAMPAIGN_BALANCE")

    rec["payment_status"] = "REFUNDED"
    rec["refunded_at"] = db.now_iso()

    # Cascade A: reverse the sponsor match.
    pool = store.match_pools.get(rec["match_pool_id"]) if rec["match_pool_id"] else None
    if rec["match_status"] == "MATCHED":
        rec["match_status"] = "REVERSED"
        rec["matched_amount_cents"] = 0
        if pool is not None:
            domain.refresh_pool(pool)
            db.touch(pool)
    db.touch(rec)

    # Cascade B step 1: credited totals fall.
    _credit_targets(rec, campaign)

    # Cascade B step 2: revoke earned awards below their threshold again.
    if rec["designation_type"] == "PARTICIPANT":
        participant = store.participants.get(rec["designation_id"])
        if participant is not None:
            credited = participant["credited_cents"]
            for award in db.ordered(domain.participant_awards(participant["id"])):
                if award["status"] != "EARNED":
                    continue
                tier = store.incentive_tiers.get(award["tier_id"])
                if tier is None:
                    continue
                if tier["threshold_cents"] > credited:
                    award["status"] = "REVOKED"
                    award["revoked_at"] = db.now_iso()
                    db.touch(award)

    # The receipt attached to the refunded gift is voided.
    receipt = domain.receipt_of_donation(rec["id"])
    if receipt is not None and receipt["status"] == "ISSUED":
        receipt["status"] = "VOIDED"
        receipt["voided_at"] = db.now_iso()
        db.touch(receipt)

    db.touch(campaign)
    domain.refresh_campaign(campaign)
    return response.object_response(domain.ser_donation(rec))
