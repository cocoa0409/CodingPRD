"""Dealer endpoints: CRUD, status, terminate, parts purchases, stock audit,
scorecard."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_DEALER_NOT_FOUND,
    ERR_DUPLICATE_DEALER_CODE,
    ERR_DEALER_NOT_ACTIVE,
    ERR_DEALER_NOT_SUSPENDED,
    ERR_REINSTATE_BLOCKED,
    ERR_SCORECARD_THRESHOLD_NOT_MET,
)
from middleware import require_roles
from response import success_object, success_list
from services.calculations import compute_scorecard, TERMINATION_SCORE_THRESHOLD
from services.cascades import requeue_leads_for_dealer, terminate_agreement_cascade
from services.serializers import serialize_dealer, serialize_dealer_list
from util import (
    apply_filters,
    get_json_body,
    get_param,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)
from decimal import Decimal

bp = Blueprint("dealers", __name__)

DEALER_STATUSES = {"ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"}
CHARGEBACK_SUSPEND_THRESHOLD = 50000


def get_dealer_or_404(dealer_id: str) -> dict:
    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")
    return dealer


@bp.route("/dealers", methods=["POST"])
@require_roles("OemNetworkAdmin")
def create_dealer(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    dealer_code = require_string(body, "dealer_code")
    region = require_string(body, "region")
    credit_limit_cents = require_int(body, "credit_limit_cents")
    if credit_limit_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "credit_limit_cents must be > 0")
    min_stock_value_cents = require_int(body, "min_stock_value_cents")
    if min_stock_value_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "min_stock_value_cents must be >= 0")

    # Priority 8: uniqueness of dealer_code across all dealers.
    if any(d["dealer_code"] == dealer_code for d in db.dealers.values()):
        raise_err(ERR_DUPLICATE_DEALER_CODE, "dealer_code already exists")

    dealer = {
        "name": name,
        "dealer_code": dealer_code,
        "region": region,
        "credit_limit_cents": credit_limit_cents,
        "min_stock_value_cents": min_stock_value_cents,
        "floorplan_utilization_cents": 0,
        "default_loss_cents": 0,
        "chargeback_balance_cents": 0,
        "discount_reconciliation_cents": 0,
        "parts_purchases_ytd_cents": 0,
        "purchases_year": None,
        "stock_observed_value_cents": 0,
        "stock_compliant": False,
        "tier": "BRONZE",
        "status": "ONBOARDING",
    }
    db.stamp_new(dealer)
    db.dealers[dealer["id"]] = dealer
    return success_object(serialize_dealer(dealer), 201)


@bp.route("/dealers", methods=["GET"])
@require_roles("Any")
def list_dealers(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.dealers.values()))
    items = apply_filters(items, ["status", "tier"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_dealer_list(page), limit, offset, total)


@bp.route("/dealers/<dealer_id>", methods=["GET"])
@require_roles("Any")
def get_dealer(dealer_id: str, _user_id: str, _role: str):
    dealer = get_dealer_or_404(dealer_id)
    return success_object(serialize_dealer(dealer))


@bp.route("/dealers/<dealer_id>/status", methods=["POST"])
@require_roles("OemNetworkAdmin")
def set_dealer_status(dealer_id: str, _user_id: str, _role: str):
    body = get_json_body()
    target = require_enum(body, "target", {"SUSPENDED", "ACTIVE"})
    dealer = get_dealer_or_404(dealer_id)

    if target == "SUSPENDED":
        # Priority 6 state: must currently be ACTIVE.
        if dealer["status"] != "ACTIVE":
            raise_err(ERR_DEALER_NOT_ACTIVE, "Suspension requires Dealer.status == ACTIVE")
        dealer["status"] = "SUSPENDED"
        db.touch(dealer)
        requeue_leads_for_dealer(dealer["id"])
    else:  # ACTIVE (reinstate)
        # Priority 6 state: must currently be SUSPENDED.
        if dealer["status"] != "SUSPENDED":
            raise_err(ERR_DEALER_NOT_SUSPENDED, "Reinstate requires Dealer.status == SUSPENDED")
        # Priority 10 referential: chargeback balance must be below threshold.
        if dealer["chargeback_balance_cents"] >= CHARGEBACK_SUSPEND_THRESHOLD:
            raise_err(
                ERR_REINSTATE_BLOCKED,
                "Reinstate requires chargeback_balance_cents < 50000",
            )
        dealer["status"] = "ACTIVE"
        db.touch(dealer)
    return success_object(serialize_dealer(dealer))


@bp.route("/dealers/<dealer_id>/terminate", methods=["POST"])
@require_roles("OemNetworkAdmin")
def terminate_dealer(dealer_id: str, _user_id: str, _role: str):
    dealer = get_dealer_or_404(dealer_id)

    # Priority 6 state: termination allowed only from ACTIVE or SUSPENDED.
    if dealer["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(
            ERR_DEALER_NOT_ACTIVE,
            "Termination requires Dealer.status in {ACTIVE, SUSPENDED}",
        )

    # Priority 7 safety gate: STRICT total_score < 60 for the two most recent
    # closed quarters (ordered by period_year/period_quarter).
    closed = [
        t
        for t in db.targets.values()
        if t["dealer_id"] == dealer["id"] and t["status"] in ("CLOSED_MET", "CLOSED_MISSED")
    ]
    closed.sort(key=lambda t: (t["period_year"], t["period_quarter"]), reverse=True)
    recent = closed[:2]
    if len(recent) < 2:
        raise_err(
            ERR_SCORECARD_THRESHOLD_NOT_MET,
            "Termination requires two most recent closed quarters with STRICT total_score < 60",
        )
    for t in recent:
        score = compute_scorecard(dealer, t["period_year"], t["period_quarter"], "STRICT")
        if Decimal(str(score["total_score"])) >= TERMINATION_SCORE_THRESHOLD:
            raise_err(
                ERR_SCORECARD_THRESHOLD_NOT_MET,
                "Termination requires STRICT total_score < 60 for the two most recent closed quarters",
            )

    # Cascade: ACTIVE agreements -> TERMINATED (link 1), their ACTIVE
    # assignments -> RELEASED (link 2), ROUTED leads via them -> NEW (link 3).
    dealer["status"] = "TERMINATED"
    db.touch(dealer)
    for agreement in list(db.agreements.values()):
        if agreement["dealer_id"] == dealer["id"] and agreement["status"] == "ACTIVE":
            terminate_agreement_cascade(agreement)
    return success_object(serialize_dealer(dealer))


@bp.route("/dealers/<dealer_id>/parts-purchases", methods=["POST"])
@require_roles("OemNetworkAdmin")
def record_parts_purchase(dealer_id: str, _user_id: str, _role: str):
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be > 0")
    dealer = get_dealer_or_404(dealer_id)

    clock_year = db.clock_date().year
    if dealer["purchases_year"] is None or dealer["purchases_year"] != clock_year:
        # Year rollover: YTD resets to the new amount.
        dealer["parts_purchases_ytd_cents"] = amount_cents
        dealer["purchases_year"] = clock_year
    else:
        dealer["parts_purchases_ytd_cents"] += amount_cents
    db.touch(dealer)
    return success_object(serialize_dealer(dealer))


@bp.route("/dealers/<dealer_id>/stock-audit", methods=["POST"])
@require_roles("OemAuditor")
def record_stock_audit(dealer_id: str, _user_id: str, _role: str):
    body = get_json_body()
    observed = require_int(body, "observed_stock_value_cents")
    if observed < 0:
        raise_err(ERR_INVALID_REQUEST, "observed_stock_value_cents must be >= 0")
    dealer = get_dealer_or_404(dealer_id)

    dealer["stock_observed_value_cents"] = observed
    dealer["stock_compliant"] = observed >= dealer["min_stock_value_cents"]
    db.touch(dealer)
    return success_object(serialize_dealer(dealer))


@bp.route("/dealers/<dealer_id>/scorecard", methods=["GET"])
@require_roles("Any")
def get_scorecard(dealer_id: str, _user_id: str, _role: str):
    dealer = get_dealer_or_404(dealer_id)

    raw_year = get_param("period_year")
    raw_quarter = get_param("period_quarter")
    if raw_year is None or raw_quarter is None:
        raise_err(ERR_INVALID_REQUEST, "period_year and period_quarter are required")
    try:
        period_year = int(raw_year)
        period_quarter = int(raw_quarter)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "period_year and period_quarter must be integers")

    variant = get_param("variant")
    if variant is None or variant == "":
        variant = "STRICT"
    if variant not in ("STRICT", "INCLUSIVE"):
        raise_err(ERR_INVALID_REQUEST, "variant must be STRICT or INCLUSIVE")

    return success_object(compute_scorecard(dealer, period_year, period_quarter, variant))
