"""Ad campaigns and ad creatives."""

from db import store, new_id, next_seq, now_str, today, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REFERENCE_NOT_FOUND,
    ERR_CATEGORY_MISMATCH,
    ERR_AD_QUALITY_RULE,
    ERR_INVALID_FLIGHT,
    ERR_BUDGET_BELOW_SPENT,
    ERR_BUDGET_EXHAUSTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import (
    caller,
    require_roles,
    body,
    ROLE_AD_OPS,
    ROLE_AD_QUALITY_REVIEWER,
)
from response import created, ok, paginate
from serializers import ser_campaign, ser_creative
from services.core import (
    get_or_404,
    void_campaign_provisionals,
    maybe_revive_campaign,
    break_decisions,
    recompute_break_fill,
)
from util import req_str, req_int, opt_int, req_date, is_int
from flask import Blueprint, request

bp = Blueprint("campaigns", __name__)

ADOPS = [ROLE_AD_OPS]


def _create_record(fields):
    ts = now_str()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}
    rec.update(fields)
    return rec


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@bp.route("/v1/ad-campaigns", methods=["POST"])
def create_campaign():
    _, role = caller()
    b = body()
    advertiser_name = req_str(b, "advertiser_name")
    iab_category = req_str(b, "iab_category")
    total = req_int(b, "total_budget_cents")
    if total <= 0:
        raise_err(ERR_INVALID_REQUEST, "total_budget_cents must be > 0")
    daily = req_int(b, "daily_budget_cents")
    if daily <= 0 or daily > total:
        raise_err(ERR_INVALID_REQUEST, "daily_budget_cents must be > 0 and <= total_budget_cents")
    cpm = req_int(b, "cpm_cents")
    if cpm <= 0:
        raise_err(ERR_INVALID_REQUEST, "cpm_cents must be > 0")
    flight_start = req_date(b, "flight_start_date")
    flight_end = req_date(b, "flight_end_date")
    priority = opt_int(b, "priority")
    if priority is None:
        priority = 0
    require_roles(role, ADOPS)
    if flight_end < flight_start:
        raise_err(ERR_INVALID_FLIGHT, "flight_end_date must not precede flight_start_date")
    rec = _create_record(
        {
            "advertiser_name": advertiser_name,
            "iab_category": iab_category,
            "total_budget_cents": total,
            "daily_budget_cents": daily,
            "cpm_cents": cpm,
            "flight_start_date": flight_start.isoformat(),
            "flight_end_date": flight_end.isoformat(),
            "priority": priority,
            "spent_cents": 0,
            "campaign_status": "DRAFT",
            "_flight_start": flight_start,
            "_flight_end": flight_end,
        }
    )
    store.ad_campaigns[rec["id"]] = rec
    return created(ser_campaign(rec))


@bp.route("/v1/ad-campaigns", methods=["GET"])
def list_campaigns():
    caller()
    recs = list(store.ad_campaigns.values())
    fs = request.args.get("campaign_status")
    fi = request.args.get("iab_category")
    if fs is not None:
        recs = [r for r in recs if r["campaign_status"] == fs]
    if fi is not None:
        recs = [r for r in recs if r["iab_category"] == fi]
    return paginate(recs, ser_campaign)


@bp.route("/v1/ad-campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    caller()
    rec = get_or_404(store.ad_campaigns, campaign_id, "AdCampaign")
    return ok(ser_campaign(rec))


def _campaign_transition(campaign_id, from_states, to_state, pre=None, cascade=None):
    _, role = caller()
    body()
    require_roles(role, ADOPS)
    rec = get_or_404(store.ad_campaigns, campaign_id, "AdCampaign")
    if rec["campaign_status"] not in from_states:
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Campaign in %s cannot perform this transition" % rec["campaign_status"],
        )
    if pre:
        pre(rec)
    rec["campaign_status"] = to_state
    touch(rec)
    if cascade:
        cascade(rec)
    return ok(ser_campaign(rec))


@bp.route("/v1/ad-campaigns/<campaign_id>/activate", methods=["POST"])
def activate_campaign(campaign_id):
    def pre(rec):
        if rec["_flight_end"] < today():
            raise_err(ERR_INVALID_STATE_TRANSITION, "Campaign flight has ended")
        for c in store.ad_creatives.values():
            if c["campaign_id"] == rec["id"] and c["creative_status"] == "APPROVED":
                return
        raise_err(ERR_INVALID_STATE_TRANSITION, "Campaign requires at least one APPROVED creative")

    return _campaign_transition(campaign_id, ("DRAFT",), "ACTIVE", pre)


@bp.route("/v1/ad-campaigns/<campaign_id>/pause", methods=["POST"])
def pause_campaign(campaign_id):
    return _campaign_transition(
        campaign_id, ("ACTIVE",), "PAUSED", cascade=void_campaign_provisionals
    )


@bp.route("/v1/ad-campaigns/<campaign_id>/resume", methods=["POST"])
def resume_campaign(campaign_id):
    def pre(rec):
        if rec["_flight_end"] < today():
            raise_err(ERR_INVALID_STATE_TRANSITION, "Campaign flight has ended")
        if rec["spent_cents"] >= rec["total_budget_cents"]:
            raise_err(ERR_BUDGET_EXHAUSTED, "Campaign spend is not below its total budget")

    return _campaign_transition(campaign_id, ("PAUSED",), "ACTIVE", pre)


@bp.route("/v1/ad-campaigns/<campaign_id>/complete", methods=["POST"])
def complete_campaign(campaign_id):
    return _campaign_transition(
        campaign_id,
        ("ACTIVE", "PAUSED", "EXHAUSTED"),
        "COMPLETED",
        cascade=void_campaign_provisionals,
    )


@bp.route("/v1/ad-campaigns/<campaign_id>/adjust-budget", methods=["POST"])
def adjust_budget(campaign_id):
    _, role = caller()
    b = body()
    new_total = req_int(b, "new_total_budget_cents")
    if new_total <= 0:
        raise_err(ERR_INVALID_REQUEST, "new_total_budget_cents must be > 0")
    require_roles(role, ADOPS)
    rec = get_or_404(store.ad_campaigns, campaign_id, "AdCampaign")
    if new_total < rec["spent_cents"]:
        raise_err(ERR_BUDGET_BELOW_SPENT, "new_total_budget_cents must not fall below spent_cents")
    rec["total_budget_cents"] = new_total
    touch(rec)
    if (
        rec["campaign_status"] == "EXHAUSTED"
        and new_total > rec["spent_cents"]
        and rec["_flight_end"] >= today()
    ):
        rec["campaign_status"] = "ACTIVE"
        touch(rec)
    return ok(ser_campaign(rec))


# ---------------------------------------------------------------------------
# Creatives
# ---------------------------------------------------------------------------

@bp.route("/v1/ad-creatives", methods=["POST"])
def create_creative():
    user_id, role = caller()
    b = body()
    campaign_id = req_str(b, "campaign_id")
    brand = req_str(b, "brand")
    iab_category = req_str(b, "iab_category")
    duration = req_int(b, "duration_seconds")
    require_roles(role, ADOPS)
    if campaign_id not in store.ad_campaigns:
        raise_err(ERR_REFERENCE_NOT_FOUND, "campaign_id does not reference an existing campaign")
    rec = _create_record(
        {
            "campaign_id": campaign_id,
            "brand": brand,
            "iab_category": iab_category,
            "duration_seconds": duration,
            "creative_status": "PENDING_REVIEW",
            "created_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "rejection_reason": None,
        }
    )
    store.ad_creatives[rec["id"]] = rec
    return created(ser_creative(rec))


@bp.route("/v1/ad-creatives", methods=["GET"])
def list_creatives():
    caller()
    recs = list(store.ad_creatives.values())
    fc = request.args.get("campaign_id")
    fs = request.args.get("creative_status")
    if fc is not None:
        recs = [r for r in recs if r["campaign_id"] == fc]
    if fs is not None:
        recs = [r for r in recs if r["creative_status"] == fs]
    return paginate(recs, ser_creative)


@bp.route("/v1/ad-creatives/<creative_id>", methods=["GET"])
def get_creative(creative_id):
    caller()
    rec = get_or_404(store.ad_creatives, creative_id, "AdCreative")
    return ok(ser_creative(rec))


@bp.route("/v1/ad-creatives/<creative_id>/approve", methods=["POST"])
def approve_creative(creative_id):
    user_id, role = caller()
    body()
    require_roles(role, [ROLE_AD_QUALITY_REVIEWER])
    rec = get_or_404(store.ad_creatives, creative_id, "AdCreative")
    # Tier 6: segregation of duties — reviewer must differ from the creator.
    if user_id == rec["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "A reviewer must not approve a creative they trafficked")
    # Tier 7: state.
    if rec["creative_status"] != "PENDING_REVIEW":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a PENDING_REVIEW creative can be approved",
        )
    # Tier 9: category match with the campaign.
    campaign = store.ad_campaigns.get(rec["campaign_id"])
    if campaign is None or rec["iab_category"] != campaign["iab_category"]:
        raise_err(ERR_CATEGORY_MISMATCH, "Creative iab_category differs from the campaign's")
    # Tier 10: ad quality — duration exactly 30 or 60.
    if rec["duration_seconds"] not in (30, 60):
        raise_err(ERR_AD_QUALITY_RULE, "Creative duration_seconds must be 30 or 60")
    rec["creative_status"] = "APPROVED"
    rec["reviewed_by_user_id"] = user_id
    touch(rec)
    return ok(ser_creative(rec))


@bp.route("/v1/ad-creatives/<creative_id>/reject", methods=["POST"])
def reject_creative(creative_id):
    user_id, role = caller()
    b = body()
    reason = req_str(b, "reason")
    require_roles(role, [ROLE_AD_QUALITY_REVIEWER])
    rec = get_or_404(store.ad_creatives, creative_id, "AdCreative")
    if user_id == rec["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "A reviewer must not reject a creative they trafficked")
    if rec["creative_status"] != "PENDING_REVIEW":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a PENDING_REVIEW creative can be rejected",
        )
    rec["creative_status"] = "REJECTED"
    rec["rejection_reason"] = reason
    rec["reviewed_by_user_id"] = user_id
    touch(rec)
    return ok(ser_creative(rec))


@bp.route("/v1/ad-creatives/<creative_id>/resubmit", methods=["POST"])
def resubmit_creative(creative_id):
    _, role = caller()
    body()
    require_roles(role, ADOPS)
    rec = get_or_404(store.ad_creatives, creative_id, "AdCreative")
    if rec["creative_status"] != "REJECTED":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a REJECTED creative can be resubmitted",
        )
    rec["creative_status"] = "PENDING_REVIEW"
    rec["rejection_reason"] = None
    touch(rec)
    return ok(ser_creative(rec))


@bp.route("/v1/ad-creatives/<creative_id>/retire", methods=["POST"])
def retire_creative(creative_id):
    _, role = caller()
    body()
    require_roles(role, ADOPS)
    rec = get_or_404(store.ad_creatives, creative_id, "AdCreative")
    if rec["creative_status"] != "APPROVED":
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only an APPROVED creative can be retired",
        )
    rec["creative_status"] = "RETIRED"
    touch(rec)
    # Void PROVISIONAL decisions using this creative; COMMITTED/RECONCILED are
    # untouched (already bought).
    from services.core import void_decision

    for d in list(store.fill_decisions.values()):
        if d["creative_id"] == rec["id"] and d["decision_status"] == "PROVISIONAL":
            void_decision(d)
    return ok(ser_creative(rec))
