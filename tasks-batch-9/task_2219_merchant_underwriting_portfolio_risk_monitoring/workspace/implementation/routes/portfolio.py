"""Merchant portfolio reads, activity ingest, the monitoring sweep and triage."""
from flask import Blueprint

from db import db, new_row, serialize, serialize_all
from errors import fail
from middleware import (
    authenticate,
    body,
    filter_bool,
    filter_date,
    filter_enum,
    find_alert,
    find_merchant,
    opt_enum,
    opt_str,
    own_merchant,
    pagination,
    req_date,
    req_enum,
    req_id,
    req_int,
    touch,
)
from response import array_response, object_response, paged_response
from services.calc import evaluate_detectors, gating_band
from services.cascades import alert_escalation, cb_breach, hold_funding, release_funding
from services.metrics import (
    OPEN_ALERT_STATES,
    active_book,
    merchant_activity,
    merchant_alerts,
    ratio_bps,
    recompute_open_alert_count,
    recompute_trailing_metrics,
    releasable_balance,
    reserve_account_of,
    unpaid_exposure,
    window_totals,
)
from util import rhu_div

bp = Blueprint("portfolio", __name__)

ACCOUNT_STATES = ("ACTIVE", "RESTRICTED", "TERMINATED")
FUNDING_STATES = ("NORMAL", "DELAYED", "HELD")
ALERT_STATES = ("OPEN", "UNDER_REVIEW", "ESCALATED", "DISMISSED", "CLOSED")
ALERT_TYPES = ("VELOCITY_SPIKE", "CARD_TESTING", "LAUNDERING_PATTERN", "CHARGEBACK_THRESHOLD")
HOLD_REASONS = ("SUSPECTED_LAUNDERING", "CARD_TESTING", "EXCESSIVE_CHARGEBACKS",
                "TERMINATION_PENDING")
NETWORKS = ("VISA", "MASTERCARD", "AMEX", "DISCOVER")
STAFF = ("UnderwritingOfficer", "RiskAnalyst", "RiskCommitteeApprover", "PortfolioController")


def _not_terminated(merchant):
    if merchant["account_state"] == "TERMINATED":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state is TERMINATED.")


# --------------------------------------------------------------------------
# merchant reads
# --------------------------------------------------------------------------
@bp.get("/merchants/<merchant_id>")
def get_merchant(merchant_id):
    authenticate(["MerchantUser"] + list(STAFF))
    merchant = find_merchant(merchant_id)
    own_merchant(merchant_id)
    return object_response(serialize(merchant))


@bp.get("/merchants")
def list_merchants():
    authenticate(list(STAFF))
    account_state = filter_enum("account_state", ACCOUNT_STATES)
    funding_state = filter_enum("funding_state", FUNDING_STATES)
    remediation_required = filter_bool("remediation_required")
    limit, offset = pagination()
    rows = sorted(db.merchants.values(), key=lambda m: m["_seq"])
    if account_state:
        rows = [r for r in rows if r["account_state"] == account_state]
    if funding_state:
        rows = [r for r in rows if r["funding_state"] == funding_state]
    if remediation_required is not None:
        rows = [r for r in rows if r["remediation_required"] == remediation_required]
    return paged_response(serialize_all(rows), limit, offset)


@bp.get("/merchants/<merchant_id>/risk-summary")
def risk_summary(merchant_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    merchant = find_merchant(merchant_id)
    own_merchant(merchant_id)

    as_of = merchant["metrics_as_of_date"]
    if as_of is None:
        count_ratio = 0
        amount_ratio = 0
    else:
        totals = window_totals(merchant_id, as_of)
        count_ratio = ratio_bps(totals["chargeback_count"], totals["txn_count"])
        amount_ratio = ratio_bps(totals["chargeback_amount_cents"], totals["volume_cents"])

    account = reserve_account_of(merchant_id)
    data = {
        "merchant_id": merchant_id,
        "account_state": merchant["account_state"],
        "funding_state": merchant["funding_state"],
        "rolling_chargeback_ratio_bps": count_ratio,
        "amount_based_chargeback_ratio_bps": amount_ratio,
        "gating_ratio_band": gating_band(count_ratio),
        "open_alert_count": sum(
            1 for a in merchant_alerts(merchant_id) if a["state"] in OPEN_ALERT_STATES),
        "reserve_account_id": account["id"] if account else None,
        "reserve_type": account["reserve_type"] if account else None,
        "reserve_held_balance_cents": account["held_balance_cents"] if account else 0,
        "reserve_releasable_cents": releasable_balance(account, db.clock_date()),
        "unpaid_settlement_exposure_cents": unpaid_exposure(merchant_id),
        "remediation_required": merchant["remediation_required"],
    }
    return object_response(data)


@bp.get("/merchants/<merchant_id>/reserve-accounts")
def list_merchant_reserve_accounts(merchant_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    account = reserve_account_of(merchant_id)
    rows = [account] if account is not None else []
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# activity ingest
# --------------------------------------------------------------------------
@bp.post("/merchant-day-activity")
def ingest_activity():
    user_id, _ = authenticate(["RiskAnalyst"])
    payload = body()
    merchant_id = req_id(payload, "merchant_id")
    business_date = req_date(payload, "business_date")
    txn_count = req_int(payload, "txn_count", lo=0)
    volume_cents = req_int(payload, "volume_cents", lo=0)
    decline_count = req_int(payload, "decline_count", lo=0)
    distinct_card_count = req_int(payload, "distinct_card_count", lo=0)
    cross_border_count = req_int(payload, "cross_border_count", lo=0)
    refund_cents = req_int(payload, "refund_cents", lo=0)
    unique_bin_count = req_int(payload, "unique_bin_count", lo=0)
    chargeback_count = req_int(payload, "chargeback_count", lo=0)
    chargeback_amount_cents = req_int(payload, "chargeback_amount_cents", lo=0)
    chargeback_network = opt_enum(payload, "chargeback_network", NETWORKS)
    if chargeback_count > 0 and chargeback_network is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'chargeback_network' is required when chargeback_count is greater than 0.")

    merchant = find_merchant(merchant_id)
    _not_terminated(merchant)

    if business_date > db.clock_date():
        fail("ERR_ACTIVITY_DATE_IN_FUTURE",
             "business_date '%s' is later than the logical clock date." % business_date)
    for row in merchant_activity(merchant_id):
        if row["business_date"] == business_date:
            fail("ERR_DUPLICATE_ACTIVITY_DATE",
                 "Activity for merchant '%s' on '%s' has already been ingested."
                 % (merchant_id, business_date))

    activity = new_row(versioned=False)
    activity.update({
        "merchant_id": merchant_id,
        "business_date": business_date,
        "txn_count": txn_count,
        "volume_cents": volume_cents,
        "distinct_card_count": distinct_card_count,
        "decline_count": decline_count,
        "cross_border_count": cross_border_count,
        "refund_cents": refund_cents,
        "unique_bin_count": unique_bin_count,
        "chargeback_count": chargeback_count,
        "chargeback_amount_cents": chargeback_amount_cents,
        "chargeback_network": chargeback_network,
        "avg_ticket_cents": rhu_div(volume_cents, txn_count) if txn_count > 0 else 0,
        "ingested_by_user_id": user_id,
    })
    db.day_activity[activity["id"]] = activity

    recompute_trailing_metrics(merchant, business_date)
    return object_response(serialize(activity), 201)


@bp.get("/merchants/<merchant_id>/day-activity")
def list_activity(merchant_id):
    authenticate(["MerchantUser", "RiskAnalyst", "PortfolioController"])
    from_date = filter_date("from_date")
    to_date = filter_date("to_date")
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    rows = sorted(merchant_activity(merchant_id), key=lambda r: (r["business_date"], r["_seq"]))
    if from_date:
        rows = [r for r in rows if r["business_date"] >= from_date]
    if to_date:
        rows = [r for r in rows if r["business_date"] <= to_date]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# the monitoring sweep
# --------------------------------------------------------------------------
@bp.post("/monitoring-runs")
def monitoring_run():
    authenticate(["RiskAnalyst"])
    payload = body()
    as_of_date = req_date(payload, "as_of_date")

    if as_of_date > db.clock_date():
        fail("ERR_MONITORING_RUN_DATE_REGRESSION",
             "as_of_date '%s' is later than the logical clock date." % as_of_date)
    previous = [m["last_monitoring_run_date"] for m in db.merchants.values()
                if m["last_monitoring_run_date"] is not None]
    if previous and as_of_date < max(previous):
        fail("ERR_MONITORING_RUN_DATE_REGRESSION",
             "as_of_date '%s' precedes the portfolio's latest monitoring run." % as_of_date)

    produced = []
    for merchant in active_book():
        recompute_trailing_metrics(merchant, as_of_date)
        for hit in evaluate_detectors(merchant, as_of_date):
            alert = _raise_alert(merchant, hit, as_of_date)
            produced.append(alert)
            if (hit["alert_type"] == "CHARGEBACK_THRESHOLD"
                    and hit["severity_score"] >= 90
                    and merchant["account_state"] == "ACTIVE"):
                cb_breach(merchant, as_of_date)
        merchant["last_monitoring_run_date"] = as_of_date
        touch(merchant)
        recompute_open_alert_count(merchant)

    return array_response(serialize_all(produced), 201)


def _raise_alert(merchant, hit, as_of_date):
    for alert in merchant_alerts(merchant["id"]):
        if (alert["alert_type"] == hit["alert_type"]
                and alert["state"] in ("OPEN", "UNDER_REVIEW")):
            alert["recurrence_count"] += 1
            alert["severity_score"] = hit["severity_score"]
            alert["observed_metric_bps"] = hit["observed_metric_bps"]
            alert["last_detected_on_date"] = as_of_date
            touch(alert)
            return alert

    alert = new_row()
    alert.update({
        "merchant_id": merchant["id"],
        "alert_type": hit["alert_type"],
        "severity_score": hit["severity_score"],
        "observed_metric_bps": hit["observed_metric_bps"],
        "state": "OPEN",
        "detected_on_date": as_of_date,
        "last_detected_on_date": as_of_date,
        "recurrence_count": 1,
        "reviewed_by_user_id": None,
        "review_note": None,
    })
    db.alerts[alert["id"]] = alert
    return alert


@bp.get("/merchants/<merchant_id>/monitoring-alerts")
def list_alerts(merchant_id):
    authenticate(["MerchantUser", "RiskAnalyst", "RiskCommitteeApprover", "PortfolioController"])
    state = filter_enum("state", ALERT_STATES)
    alert_type = filter_enum("alert_type", ALERT_TYPES)
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    rows = merchant_alerts(merchant_id)
    if state:
        rows = [r for r in rows if r["state"] == state]
    if alert_type:
        rows = [r for r in rows if r["alert_type"] == alert_type]
    return paged_response(serialize_all(rows), limit, offset)


@bp.post("/monitoring-alerts/<alert_id>/review")
def review_alert(alert_id):
    user_id, _ = authenticate(["RiskAnalyst"])
    payload = body()
    disposition = req_enum(payload, "disposition", ("ACKNOWLEDGE", "DISMISS", "ESCALATE"))
    review_note = opt_str(payload, "review_note", max_len=2000)

    alert = find_alert(alert_id)
    required_state = "OPEN" if disposition == "ACKNOWLEDGE" else "UNDER_REVIEW"
    if alert["state"] != required_state:
        fail("ERR_ALERT_STATE_INVALID",
             "Disposition '%s' is not permitted from alert state '%s'."
             % (disposition, alert["state"]))

    merchant = db.merchants.get(alert["merchant_id"])
    alert["reviewed_by_user_id"] = user_id
    alert["review_note"] = review_note
    if disposition == "ACKNOWLEDGE":
        alert["state"] = "UNDER_REVIEW"
    elif disposition == "DISMISS":
        alert["state"] = "DISMISSED"
    else:
        alert["state"] = "ESCALATED"
    touch(alert)

    if merchant is not None:
        recompute_open_alert_count(merchant)
        if disposition == "ESCALATE":
            alert_escalation(merchant, alert)
    return object_response(serialize(alert))


# --------------------------------------------------------------------------
# funding posture
# --------------------------------------------------------------------------
@bp.post("/merchants/<merchant_id>/funding-holds")
def place_funding_hold(merchant_id):
    authenticate(["RiskAnalyst"])
    payload = body()
    reason_code = req_enum(payload, "reason_code", HOLD_REASONS)
    merchant = find_merchant(merchant_id)
    _not_terminated(merchant)
    if merchant["funding_state"] not in ("NORMAL", "DELAYED"):
        fail("ERR_FUNDING_STATE_INVALID",
             "funding_state '%s' does not permit a manual hold." % merchant["funding_state"])
    hold_funding(merchant, reason_code)
    return object_response(serialize(merchant))


@bp.post("/merchants/<merchant_id>/funding-release")
def lift_funding_hold(merchant_id):
    authenticate(["RiskCommitteeApprover"])
    merchant = find_merchant(merchant_id)
    _not_terminated(merchant)
    if merchant["funding_state"] != "HELD":
        fail("ERR_FUNDING_STATE_INVALID",
             "funding_state '%s' is not HELD." % merchant["funding_state"])
    release_funding(merchant, db.clock_date())
    return object_response(serialize(merchant))
