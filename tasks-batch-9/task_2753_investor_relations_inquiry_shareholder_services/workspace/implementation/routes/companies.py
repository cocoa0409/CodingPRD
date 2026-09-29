"""Logical clock (PRD §2.4) and Company endpoints (§3.1, §3.7 consensus read)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import validation as V
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from serializers import company_out
from store import (ESTIMATE_STALENESS_DAYS, METRICS, OUTLIER_BAND_PCT, iso,
                   new_row, rhu, sorted_rows, store, touch)

bp = Blueprint("companies", __name__)


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    V.authorize("IRAdmin")
    b = V.body()
    if "to_iso8601" not in b or b["to_iso8601"] is None:
        V.bad("to_iso8601 is required")
    moment = V.parse_iso(b["to_iso8601"], "to_iso8601")
    store.clock = moment
    return ok({"current_utc": iso(moment)})


# ------------------------------------------------------------------------ Company
@bp.post("/companies")
def create_company():
    V.authorize("IRAdmin")
    b = V.body()
    ticker = V.f_str(b, "ticker", required=True, max_len=8)
    if len(ticker) < 1 or len(ticker) > 8 or ticker != ticker.upper():
        V.bad("ticker must be 1-8 uppercase characters")
    legal_name = V.f_str(b, "legal_name", required=True, max_len=200)
    shares_outstanding = V.f_int(b, "shares_outstanding", required=True, minimum=1)
    dividend_reserve_cents = V.f_int(b, "dividend_reserve_cents", default=0, minimum=0)
    blackout_start = V.f_dt(b, "blackout_window_start", default=None)
    blackout_end = V.f_dt(b, "blackout_window_end", default=None)

    for existing in store.companies.values():
        if existing["ticker"] == ticker:
            raise ApiError("ERR_DUPLICATE_TICKER", "ticker %s is already registered" % ticker)

    company = new_row({
        "ticker": ticker,
        "legal_name": legal_name,
        "shares_outstanding": shares_outstanding,
        "blackout_window_start": blackout_start,
        "blackout_window_end": blackout_end,
        "dividend_reserve_cents": dividend_reserve_cents,
        "dividend_paid_cents": 0,
        "disclosure_posture": "OPEN",
        "open_inquiry_count": 0,
        "posture_recomputed_at": None,
    })
    calc.refresh_posture(company)
    store.companies[company["id"]] = company
    return created(company_out(company))


@bp.get("/companies")
def list_companies():
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison")
    limit, offset = V.q_pagination()
    ticker = V.q_str("ticker")
    posture = V.q_enum("disclosure_posture", ["OPEN", "RESTRICTED", "BLACKOUT"])
    rows = sorted_rows(store.companies)
    if ticker is not None:
        rows = [r for r in rows if r["ticker"] == ticker]
    if posture is not None:
        rows = [r for r in rows if r["disclosure_posture"] == posture]
    page, total = paginate(rows, limit, offset)
    return ok_list([company_out(r) for r in page], limit, offset, total)


@bp.get("/companies/<cid>")
def read_company(cid):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer", "TransferAgentLiaison", "Investor")
    company = V.get_company(cid)
    return ok(company_out(company))


@bp.post("/companies/<cid>/recompute-posture")
def recompute_posture(cid):
    V.authorize("IRAdmin", "DisclosureOfficer")
    company = V.get_company(cid)
    calc.posture_write(company, recount=True)
    return ok(company_out(company))


# ------------------------------------------------------- §3.7 the consensus read
@bp.get("/companies/<cid>/consensus")
def consensus(cid):
    V.authorize("IRAdmin", "IRAnalyst", "DisclosureOfficer")
    company = V.get_company(cid)
    metric = V.q_enum("metric", METRICS, required=True)
    period_label = V.q_str("period_label", required=True)
    variant = V.q_enum("variant", ["SIMPLE", "ANCHORED"], default="ANCHORED")

    # ---- step 1: the eligible set
    cutoff = store.now() - timedelta(days=ESTIMATE_STALENESS_DAYS)
    eligible = []
    for e in sorted_rows(store.estimates):
        if e["status"] != "ACCEPTED":
            continue
        contact = store.contacts.get(e["contact_id"])
        if contact is None or contact["company_id"] != company["id"]:
            continue
        if contact["contact_type"] != "SELL_SIDE_ANALYST":
            continue
        if contact["coverage_status"] != "INITIATED":
            continue
        if contact["model_access_status"] == "REVOKED":
            continue
        if e["metric"] != metric or e["period_label"] != period_label:
            continue
        if e["submitted_at"] < cutoff:
            continue
        eligible.append(e)

    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_ESTIMATES",
                       "no eligible estimate survives the filter for %s/%s" % (metric, period_label))

    # ---- step 2: the simple mean
    total = sum((e["value"] for e in eligible), Decimal(0))
    simple_mean = rhu(total / Decimal(len(eligible)), 4)

    # ---- step 3: the band anchor (computed exactly once)
    guidance = None
    for d in sorted_rows(store.disclosures):
        if (d["company_id"] == company["id"] and d["status"] == "PUBLISHED"
                and d["is_guidance"] and d["metric"] == metric
                and d["period_label"] == period_label):
            guidance = d
            break
    low_factor = Decimal(1) - OUTLIER_BAND_PCT
    high_factor = Decimal(1) + OUTLIER_BAND_PCT
    if guidance is not None:
        guidance_anchored = True
        band_low = rhu(guidance["guidance_low"] * low_factor, 4)
        band_high = rhu(guidance["guidance_high"] * high_factor, 4)
    else:
        guidance_anchored = False
        band_low = rhu(simple_mean * low_factor, 4)
        band_high = rhu(simple_mean * high_factor, 4)

    # ---- step 4: the trim
    kept = [e for e in eligible if band_low <= e["value"] <= band_high]
    outlier_excluded_count = len(eligible) - len(kept)
    if not kept:
        anchored_mean = simple_mean
        trimmed_applied = False
    else:
        kept_total = sum((e["value"] for e in kept), Decimal(0))
        anchored_mean = rhu(kept_total / Decimal(len(kept)), 4)
        trimmed_applied = True

    # ---- step 5: the reported numbers
    consensus_mean = simple_mean if variant == "SIMPLE" else anchored_mean
    if not kept or consensus_mean == 0:
        dispersion_pct = None
    else:
        spread = max(e["value"] for e in kept) - min(e["value"] for e in kept)
        dispersion_pct = float(rhu(spread / consensus_mean * Decimal(100), 2))

    return ok({
        "company_id": company["id"],
        "metric": metric,
        "period_label": period_label,
        "variant": variant,
        "eligible_count": len(eligible),
        "outlier_excluded_count": outlier_excluded_count,
        "guidance_anchored": guidance_anchored,
        "band_low": float(band_low),
        "band_high": float(band_high),
        "simple_mean": float(simple_mean),
        "consensus_mean": float(consensus_mean),
        "trimmed_applied": trimmed_applied,
        "dispersion_pct": dispersion_pct,
    })
