"""Traffic factor filings, review, audit and the re-rate cascade (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate,
                  carrier_of_factor_filing, check_carrier_version, scope_check,
                  scope_filter)
from constants import FACTOR_DECISIONS, QUARTER_PATTERN
from dec import q2
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_carrier, get_factor_filing, invoice_for_batch
from services import reserve
from services.invoicing import recompute_open_balance
from services.rating import jurisdictionalize, rate_batch
from store import base_record, db, now, ordered, touch

bp = Blueprint("factors", __name__)

HUNDRED = Decimal("100.00")


def _refresh_effective(filing):
    if filing["status"] == "AUDITED":
        filing["effective_piu_pct"] = filing["audited_piu_pct"]
        filing["effective_plu_pct"] = filing["audited_plu_pct"]
    else:
        filing["effective_piu_pct"] = filing["reported_piu_pct"]
        filing["effective_plu_pct"] = filing["reported_plu_pct"]
    return filing


@bp.post("/traffic-factor-filings")
def report_factors():
    actor = authenticate((CARRIER_REPRESENTATIVE, ACCESS_BILLING_ANALYST))
    payload = v.body()
    carrier_id = v.string(payload, "carrier_id")
    expected_version = v.integer(payload, "expected_carrier_version")
    quarter = v.string(payload, "quarter", pattern=QUARTER_PATTERN)
    piu = v.number(payload, "reported_piu_pct", 2, ge=0, le=100)
    plu = v.number(payload, "reported_plu_pct", 2, ge=0, le=100)

    carrier = get_carrier(carrier_id)
    scope_check(actor, carrier["id"])
    check_carrier_version(carrier, expected_version)

    if piu + plu > HUNDRED:
        raise ApiError("ERR_FACTOR_SUM_EXCEEDS_TOTAL",
                       "reported_piu_pct plus reported_plu_pct may not exceed 100.00")

    priors = [f for f in ordered(db.factor_filings)
              if f["carrier_id"] == carrier["id"] and f["quarter"] == quarter]
    for prior in priors:
        if prior["status"] == "DISPUTED":
            raise ApiError("ERR_FACTOR_FILING_DISPUTE_OPEN",
                           "an open factor dispute exists for this carrier and quarter")

    filing = base_record()
    filing.update({
        "carrier_id": carrier["id"],
        "quarter": quarter,
        "reported_piu_pct": piu,
        "reported_plu_pct": plu,
        "audited_piu_pct": None,
        "audited_plu_pct": None,
        "effective_piu_pct": piu,
        "effective_plu_pct": plu,
        "status": "REPORTED",
        "dispute_reason": None,
        "audit_completed_at": None,
        "superseded_at": None,
    })
    db.factor_filings[filing["id"]] = filing

    for prior in priors:
        if prior["status"] in ("REPORTED", "ACCEPTED", "DISPUTED", "AUDITED"):
            prior["status"] = "SUPERSEDED"
            prior["superseded_at"] = now()
            _refresh_effective(prior)
            touch(prior)

    touch(carrier)
    return object_response(filing, 201)


@bp.get("/traffic-factor-filings/<factor_filing_id>")
def read_factor_filing(factor_filing_id):
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    filing = get_factor_filing(factor_filing_id)
    scope_check(actor, filing["carrier_id"])
    return object_response(filing)


@bp.get("/traffic-factor-filings")
def list_factor_filings():
    actor = authenticate((PLATFORM_ADMIN, ACCESS_BILLING_ANALYST,
                          REVENUE_ASSURANCE_CONTROLLER, CARRIER_REPRESENTATIVE))
    rows = ordered(db.factor_filings)
    carrier_id = request.args.get("carrier_id")
    if carrier_id:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    quarter = request.args.get("quarter")
    if quarter:
        rows = [r for r in rows if r["quarter"] == quarter]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = scope_filter(actor, rows, carrier_of_factor_filing)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/traffic-factor-filings/<factor_filing_id>/review")
def review_factor_filing(factor_filing_id):
    authenticate((ACCESS_BILLING_ANALYST,))
    filing = get_factor_filing(factor_filing_id)
    payload = v.body()
    decision = v.enum(payload, "decision", FACTOR_DECISIONS)
    dispute_reason = v.string(payload, "dispute_reason", required=False)
    if decision == "DISPUTE" and not dispute_reason:
        v.bad("dispute_reason is required when the decision is DISPUTE")

    if decision == "ACCEPT":
        if filing["status"] not in ("REPORTED", "AUDITED"):
            raise ApiError("ERR_INVALID_FACTOR_FILING_STATE",
                           "this filing may not be accepted from its current status")
        filing["status"] = "ACCEPTED"
    else:
        if filing["status"] not in ("REPORTED", "ACCEPTED", "AUDITED"):
            raise ApiError("ERR_INVALID_FACTOR_FILING_STATE",
                           "this filing may not be disputed from its current status")
        filing["status"] = "DISPUTED"
        filing["dispute_reason"] = dispute_reason

    _refresh_effective(filing)
    touch(filing)
    return object_response(filing)


@bp.post("/traffic-factor-filings/<factor_filing_id>/audit")
def audit_factor_filing(factor_filing_id):
    authenticate((REVENUE_ASSURANCE_CONTROLLER,))
    filing = get_factor_filing(factor_filing_id)
    payload = v.body()
    audited_piu = v.number(payload, "audited_piu_pct", 2, ge=0, le=100)
    audited_plu = v.number(payload, "audited_plu_pct", 2, ge=0, le=100)

    if filing["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_FACTOR_FILING_STATE",
                       "only a DISPUTED factor filing may be audited")
    if audited_piu + audited_plu > HUNDRED:
        raise ApiError("ERR_FACTOR_SUM_EXCEEDS_TOTAL",
                       "audited_piu_pct plus audited_plu_pct may not exceed 100.00")

    filing["audited_piu_pct"] = audited_piu
    filing["audited_plu_pct"] = audited_plu
    filing["status"] = "AUDITED"
    filing["audit_completed_at"] = now()
    _refresh_effective(filing)
    touch(filing)

    _rerate_cascade(filing)
    return object_response(filing)


def _rerate_cascade(filing):
    """Hops 1 to 4: re-rate every batch already priced on this filing, refresh
    its issued invoice, re-provision the carrier's reserve and book the delta."""
    batches = [b for b in ordered(db.usage_batches)
               if b["traffic_factor_filing_id"] == filing["id"]
               and b["status"] in ("RATED", "INVOICED")]
    for batch in batches:
        jurisdictionalize(batch)
        rate_batch(batch, enforce=False)
        batch["rating_variant"] = "FINAL"
        batch["rerate_count"] += 1
        batch["rated_at"] = now()
        touch(batch)

        invoice = invoice_for_batch(batch["id"])
        if invoice is None or invoice["lifecycle_status"] != "ISSUED":
            continue
        invoice["billed_amount_usd"] = q2(batch["rated_amount_usd"])
        invoice["interstate_amount_usd"] = batch["interstate_amount_usd"]
        invoice["intrastate_amount_usd"] = batch["intrastate_amount_usd"]
        invoice["local_amount_usd"] = batch["local_amount_usd"]
        invoice["rating_variant"] = batch["rating_variant"]
        recompute_open_balance(invoice)
        invoice["adjustment_count"] += 1
        touch(invoice)

        carrier = db.carriers.get(invoice["carrier_id"])
        if carrier is not None:
            reserve.recompute(carrier, "FACTOR_AUDIT_RERATE", invoice["id"])
