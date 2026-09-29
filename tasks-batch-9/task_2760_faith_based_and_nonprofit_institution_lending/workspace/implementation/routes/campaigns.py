"""Pledge campaigns and pledges (PRD section 3.3)."""

from flask import Blueprint, request

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import CREDIT_ANALYST, INSTITUTION_REP, LOAN_SERVICER, READ_ALL
from errors import ApiError

bp = Blueprint("campaigns", __name__)

DONOR_TIERS = ("LEAD", "MAJOR", "GENERAL")
OUTCOMES = ("PAID", "MISSED")


# ---------------------------------------------------------------------------
# campaigns
# ---------------------------------------------------------------------------


@bp.route("/pledge-campaigns", methods=["POST"])
def create_campaign():
    ctx = auth.authenticate((INSTITUTION_REP,))
    b = shapes.body()
    auth.scope(ctx, b.get("institution_id"))
    institution = resolve.institution(b.get("institution_id"))
    if institution is None:
        shapes.req_id_field(b, "institution_id")

    row = store.base_record()
    row.update({
        "institution_id": institution["id"],
        "campaign_name": shapes.req_str(b, "campaign_name"),
        "goal_cents": shapes.req_int(b, "goal_cents", exclusive_minimum=0),
        "pledge_period_months": shapes.req_int(b, "pledge_period_months",
                                               exclusive_minimum=0),
        "sponsor_collection_rate_bps": shapes.req_int(
            b, "sponsor_collection_rate_bps", minimum=0, maximum=10000),
        "status": "OPEN",
        "total_pledged_cents": 0,
        "active_pledged_cents": 0,
        "lapsed_pledged_cents": 0,
        "fulfilled_pledged_cents": 0,
        "collected_to_date_cents": 0,
        "attrition_adjusted_value_cents": 0,
        "sponsor_projected_value_cents": 0,
        "close_note": None,
    })
    store.pledge_campaigns[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.pledge_campaign(row))


@bp.route("/pledge-campaigns/<pledge_campaign_id>", methods=["GET"])
def get_campaign(pledge_campaign_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.pledge_campaign(pledge_campaign_id)
    auth.scope(ctx, row.get("institution_id"))
    return envelope.ok(serializers.pledge_campaign(row))


@bp.route("/pledge-campaigns", methods=["GET"])
def list_campaigns():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(list(store.pledge_campaigns.values()),
                                {"institution_id": "institution_id",
                                 "status": "status"})
    return envelope.listing(envelope.sort_created_desc(rows),
                            serializers.pledge_campaign)


@bp.route("/pledge-campaigns/<pledge_campaign_id>/close", methods=["POST"])
def close_campaign(pledge_campaign_id):
    ctx = auth.authenticate((INSTITUTION_REP,))
    row = resolve.pledge_campaign(pledge_campaign_id)
    auth.scope(ctx, row.get("institution_id"))
    b = shapes.body()
    note = shapes.opt_str(b, "close_note")
    if row["status"] == "CLOSED":
        raise ApiError("ERR_CAMPAIGN_CLOSED")
    row["status"] = "CLOSED"
    row["close_note"] = note
    store.touch(row)
    return envelope.ok(serializers.pledge_campaign(row))


@bp.route("/pledge-campaigns/<pledge_campaign_id>/valuation", methods=["GET"])
def campaign_valuation(pledge_campaign_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.pledge_campaign(pledge_campaign_id)
    auth.scope(ctx, row.get("institution_id"))
    basis = request.args.get("basis")
    if basis is None or basis == "":
        basis = calc.LENDER_CONSERVATIVE
    if basis not in calc.VALUATION_BASES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter 'basis' is invalid.")
    buckets = calc.campaign_buckets(row)
    return envelope.ok({
        "basis": basis,
        "projected_value_cents": calc.campaign_projected_value(row, basis),
        "collected_to_date_cents": buckets["collected_to_date_cents"],
        "active_pledged_cents": buckets["active_pledged_cents"],
        "lapsed_pledged_cents": buckets["lapsed_pledged_cents"],
        "fulfilled_pledged_cents": buckets["fulfilled_pledged_cents"],
        "total_pledged_cents": buckets["total_pledged_cents"],
        "goal_cents": row["goal_cents"],
        "status": row["status"],
        "underperform_threshold_cents": calc.underperform_threshold_cents(row),
        "maturity_threshold_cents": calc.maturity_threshold_cents(row),
    })


# ---------------------------------------------------------------------------
# pledges
# ---------------------------------------------------------------------------


@bp.route("/pledges", methods=["POST"])
def create_pledge():
    ctx = auth.authenticate((INSTITUTION_REP, CREDIT_ANALYST))
    b = shapes.body()
    campaign = resolve.pledge_campaign(b.get("pledge_campaign_id"))
    auth.scope(ctx, auth.owner_of_campaign(campaign))
    if campaign is None:
        shapes.req_id_field(b, "pledge_campaign_id")

    tier = shapes.req_enum(b, "donor_tier", DONOR_TIERS)
    amount = shapes.req_int(b, "pledged_amount_cents", exclusive_minimum=0)
    installments = shapes.req_int(b, "installment_count", exclusive_minimum=0)
    expected = shapes.req_int(b, "expected_pledge_campaign_version")

    if expected != campaign["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION")
    if campaign["status"] == "CLOSED":
        raise ApiError("ERR_CAMPAIGN_CLOSED")

    row = store.base_record()
    row.update({
        "pledge_campaign_id": campaign["id"],
        "donor_tier": tier,
        "pledged_amount_cents": amount,
        "installment_count": installments,
        "collected_cents": 0,
        "payments_made_count": 0,
        "missed_payments_count": 0,
        "status": "ACTIVE",
        "lapse_reason": None,
        "effective_attrition_pct": None,
        "reinstatement_note": None,
    })
    row["effective_attrition_pct"] = calc.effective_attrition_pct(row)
    store.pledges[row["id"]] = row
    store.mark_created(row)
    calc.recompute_campaign(campaign)
    return envelope.created(serializers.pledge(row))


@bp.route("/pledges/<pledge_id>", methods=["GET"])
def get_pledge(pledge_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.pledge(pledge_id)
    auth.scope(ctx, auth.owner_of_pledge(row))
    return envelope.ok(serializers.pledge(row))


@bp.route("/pledges", methods=["GET"])
def list_pledges():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(list(store.pledges.values()),
                                {"pledge_campaign_id": "pledge_campaign_id",
                                 "donor_tier": "donor_tier",
                                 "status": "status"})
    return envelope.listing(envelope.sort_created_asc(rows),
                            serializers.pledge)


@bp.route("/pledges/<pledge_id>/payments", methods=["POST"])
def record_installment(pledge_id):
    ctx = auth.authenticate((LOAN_SERVICER, INSTITUTION_REP))
    row = resolve.pledge(pledge_id)
    auth.scope(ctx, auth.owner_of_pledge(row))
    b = shapes.body()
    if "installment_month" not in b or b["installment_month"] is None:
        shapes.bad("installment_month", "is required")
    month = b["installment_month"]
    if isinstance(month, bool) or not isinstance(month, (int, str)):
        shapes.bad("installment_month", "must be a month reference")
    outcome = shapes.req_enum(b, "outcome", OUTCOMES)
    amount = shapes.req_int(b, "amount_cents", minimum=0)
    if outcome == "MISSED" and amount != 0:
        shapes.bad("amount_cents", "must be 0 for a MISSED installment")
    if outcome == "PAID" and amount <= 0:
        shapes.bad("amount_cents", "must be greater than 0 for a PAID installment")

    if row["status"] != "ACTIVE":
        raise ApiError("ERR_PLEDGE_INVALID_STATE")
    campaign = store.pledge_campaigns.get(row["pledge_campaign_id"])
    if campaign is not None and campaign["status"] == "CLOSED":
        raise ApiError("ERR_CAMPAIGN_CLOSED")

    if outcome == "PAID":
        row["collected_cents"] += amount
        row["payments_made_count"] += 1
    else:
        row["missed_payments_count"] += 1
    row["effective_attrition_pct"] = calc.effective_attrition_pct(row)

    if outcome == "PAID" and row["collected_cents"] >= row["pledged_amount_cents"]:
        row["status"] = "FULFILLED"
    elif outcome == "MISSED" and \
            row["missed_payments_count"] == calc.AUTO_LAPSE_MISSED_COUNT:
        row["status"] = "LAPSED"
        row["lapse_reason"] = "AUTO_THREE_MISSED_INSTALLMENTS"
    store.touch(row)
    if campaign is not None:
        calc.recompute_campaign(campaign)
    return envelope.ok(serializers.pledge(row))


@bp.route("/pledges/<pledge_id>/lapse", methods=["POST"])
def lapse_pledge(pledge_id):
    auth.authenticate((LOAN_SERVICER,))
    row = resolve.pledge(pledge_id)
    b = shapes.body()
    reason = shapes.req_str(b, "lapse_reason")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_PLEDGE_INVALID_STATE")
    row["status"] = "LAPSED"
    row["lapse_reason"] = reason
    store.touch(row)
    campaign = store.pledge_campaigns.get(row["pledge_campaign_id"])
    if campaign is not None:
        calc.recompute_campaign(campaign)
    return envelope.ok(serializers.pledge(row))


@bp.route("/pledges/<pledge_id>/reinstate", methods=["POST"])
def reinstate_pledge(pledge_id):
    auth.authenticate((LOAN_SERVICER,))
    row = resolve.pledge(pledge_id)
    b = shapes.body()
    note = shapes.req_str(b, "reinstatement_note")
    if row["status"] != "LAPSED":
        raise ApiError("ERR_PLEDGE_INVALID_STATE")
    campaign = store.pledge_campaigns.get(row["pledge_campaign_id"])
    if campaign is not None and campaign["status"] == "CLOSED":
        raise ApiError("ERR_CAMPAIGN_CLOSED")
    row["status"] = "ACTIVE"
    row["lapse_reason"] = None
    row["reinstatement_note"] = note
    row["effective_attrition_pct"] = calc.effective_attrition_pct(row)
    store.touch(row)
    if campaign is not None:
        calc.recompute_campaign(campaign)
    return envelope.ok(serializers.pledge(row))
