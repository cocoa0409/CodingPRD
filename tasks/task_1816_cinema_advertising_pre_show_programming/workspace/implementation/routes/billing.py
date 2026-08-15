"""Invoices and make-good credits (PRD 3.6, 3.7)."""
import db
import calc
from auth import require, ALL_ROLES
from envelope import success_object, success_list
from errors import (ApiError, not_found, bad_request, conflict, unprocessable,
                    ERR_INVALID_STATE_TRANSITION, ERR_INVOICE_PERIOD_OVERLAP,
                    ERR_INVOICE_NOT_CERTIFIABLE, ERR_INVOICE_NOT_SETTLABLE,
                    ERR_MAKE_GOOD_NOT_REVIEWABLE, ERR_MAKE_GOOD_THRESHOLD_NOT_MET,
                    ERR_SOD_CERTIFIER_IS_ISSUER, ERR_SOD_REVIEWER_IS_PROPOSER,
                    ERR_STALE_VERSION)
from serializers import ser_invoice, ser_make_good
from validate import (get_body, req_date, req_int, req_enum,
                      parse_date_value, pagination)

from . import bp

SALES = {"SalesManager"}
AUDITOR = {"Auditor"}


def _get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise not_found("invoice not found")
    return inv


def _get_make_good_or_404(make_good_id):
    mg = db.make_goods.get(make_good_id)
    if mg is None:
        raise not_found("make-good credit not found")
    return mg


# ------------------------------- Invoices -----------------------------------

@bp.post("/network/campaigns/<campaign_id>/invoices")
def create_invoice(campaign_id):
    require(SALES)
    body = get_body()
    # Priority 4: shape before existence.
    start_raw = req_date(body, "period_start_date")
    end_raw = req_date(body, "period_end_date")
    p_start = parse_date_value("period_start_date", start_raw)
    p_end = parse_date_value("period_end_date", end_raw)
    if p_end < p_start:
        raise bad_request("period_end_date must not be earlier than "
                          "period_start_date")
    # Priority 5: path existence.
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise not_found("campaign not found")
    # Priority 9: period overlap with any non-VOID invoice of this campaign.
    for inv in db.invoices.values():
        if (inv["campaign_id"] == campaign_id
                and inv["billing_status"] != "VOID"):
            if p_start <= inv["_period_end"] and inv["_period_start"] <= p_end:
                raise conflict(ERR_INVOICE_PERIOD_OVERLAP,
                               "period overlaps an existing non-VOID invoice "
                               "of this campaign")

    # Provisional snapshot: slots in RESERVED/CONFIRMED/PLAYED whose showtime
    # date is in period; per-line round-half-up, then sum (pinned order).
    lines = [s for s in calc.in_period_slots(campaign_id, p_start, p_end)
             if s["slot_status"] in ("RESERVED", "CONFIRMED", "PLAYED")]
    provisional_impressions = 0
    provisional_amount = 0
    for s in lines:
        reel = db.reels[s["reel_id"]]
        st = db.showtimes[reel["showtime_id"]]
        forecast = st["forecast_attendance"]
        provisional_impressions += forecast
        provisional_amount += calc.line_amount_cents(forecast,
                                                     campaign["cpm_cents"])

    rec = db.new_record()
    rec.update({"campaign_id": campaign_id,
                "period_start_date": start_raw, "period_end_date": end_raw,
                "_period_start": p_start, "_period_end": p_end,
                "billing_status": "DRAFT", "audit_status": "UNAUDITED",
                "provisional_impressions": provisional_impressions,
                "provisional_amount_cents": provisional_amount,
                "audited_impressions": None, "audited_amount_cents": None,
                "applied_credit_cents": 0, "final_amount_cents": None,
                "issued_by_user_id": None, "certified_by_user_id": None})
    db.invoices[rec["id"]] = rec
    return success_object(ser_invoice(rec), 201)


@bp.get("/network/invoices/<invoice_id>")
def get_invoice(invoice_id):
    require(ALL_ROLES)
    return success_object(ser_invoice(_get_invoice_or_404(invoice_id)))


@bp.get("/network/campaigns/<campaign_id>/invoices")
def list_campaign_invoices(campaign_id):
    require(ALL_ROLES)
    c = db.campaigns.get(campaign_id)
    if c is None:
        raise not_found("campaign not found")
    limit, offset = pagination()
    items = sorted((i for i in db.invoices.values()
                    if i["campaign_id"] == campaign_id),
                   key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_invoice(i) for i in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.post("/network/invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    user_id = require(SALES)
    inv = _get_invoice_or_404(invoice_id)
    if inv["billing_status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a DRAFT invoice can be issued")
    inv["billing_status"] = "ISSUED"
    inv["issued_by_user_id"] = user_id
    db.touch(inv)
    return success_object(ser_invoice(inv))


@bp.post("/network/invoices/<invoice_id>/certify")
def certify_invoice(invoice_id):
    user_id = require(AUDITOR)
    inv = _get_invoice_or_404(invoice_id)
    # Priority 6: SoD before state.
    if inv["issued_by_user_id"] is not None and \
            user_id == inv["issued_by_user_id"]:
        raise ApiError(ERR_SOD_CERTIFIER_IS_ISSUER, 403,
                       "certifier must differ from the issuer")
    # Priority 7: certification gates.
    if inv["billing_status"] != "ISSUED":
        raise conflict(ERR_INVOICE_NOT_CERTIFIABLE,
                       "invoice billing status is not ISSUED")
    if inv["audit_status"] != "UNAUDITED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "invoice has already been certified")
    campaign = db.campaigns[inv["campaign_id"]]
    in_period = calc.in_period_slots(campaign["id"], inv["_period_start"],
                                     inv["_period_end"])
    for s in in_period:
        if s["slot_status"] not in ("PLAYED", "MISSED"):
            raise conflict(ERR_INVOICE_NOT_CERTIFIABLE,
                           "an in-period slot has not reached PLAYED or "
                           "MISSED")
    carrying = {}
    for s in in_period:
        st = db.showtimes[db.reels[s["reel_id"]]["showtime_id"]]
        carrying[st["id"]] = st
    for st in carrying.values():
        reports = sorted((r for r in db.attendance_reports.values()
                          if r["showtime_id"] == st["id"]),
                         key=lambda r: r["_seq"])
        if not reports or reports[-1]["report_status"] not in (
                "ACCEPTED", "AUDITED"):
            raise conflict(ERR_INVOICE_NOT_CERTIFIABLE,
                           "a showtime carrying an in-period slot lacks an "
                           "ACCEPTED or AUDITED attendance report")

    # Audited picture: PLAYED in-period slots only; per-line rounding, then sum.
    played = [s for s in in_period if s["slot_status"] == "PLAYED"]
    audited_impressions = 0
    audited_amount = 0
    for s in played:
        attributed = s["attributed_impressions"] or 0
        audited_impressions += attributed
        audited_amount += calc.line_amount_cents(attributed,
                                                 campaign["cpm_cents"])
    inv["audited_impressions"] = audited_impressions
    inv["audited_amount_cents"] = audited_amount
    inv["final_amount_cents"] = audited_amount
    inv["certified_by_user_id"] = user_id
    inv["audit_status"] = "CERTIFIED"
    db.touch(inv)
    return success_object(ser_invoice(inv))


@bp.post("/network/invoices/<invoice_id>/settle")
def settle_invoice(invoice_id):
    require(SALES)
    inv = _get_invoice_or_404(invoice_id)
    if inv["audit_status"] != "CERTIFIED":
        raise conflict(ERR_INVOICE_NOT_SETTLABLE,
                       "invoice audit status is not CERTIFIED")
    for mg in db.make_goods.values():
        if (mg["invoice_id"] == invoice_id
                and mg["credit_status"] in ("PROPOSED", "APPROVED")):
            raise conflict(ERR_INVOICE_NOT_SETTLABLE,
                           "invoice has a make-good credit in PROPOSED or "
                           "APPROVED")
    if inv["billing_status"] != "ISSUED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only an ISSUED invoice can be settled")
    inv["billing_status"] = "SETTLED"
    db.touch(inv)
    return success_object(ser_invoice(inv))


@bp.post("/network/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    require(SALES)
    inv = _get_invoice_or_404(invoice_id)
    if inv["audit_status"] != "UNAUDITED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "a certified invoice cannot be voided")
    if inv["billing_status"] not in ("DRAFT", "ISSUED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a DRAFT or ISSUED invoice can be voided")
    inv["billing_status"] = "VOID"
    db.touch(inv)
    return success_object(ser_invoice(inv))


# ---------------------------- Make-good credits -----------------------------

@bp.post("/network/invoices/<invoice_id>/make-goods")
def propose_make_good(invoice_id):
    user_id = require(AUDITOR)
    inv = _get_invoice_or_404(invoice_id)
    # Priority 7: invoice must be CERTIFIED with no open make-good.
    if inv["audit_status"] != "CERTIFIED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "make-goods may only be proposed against a CERTIFIED "
                       "invoice")
    for mg in db.make_goods.values():
        if (mg["invoice_id"] == invoice_id
                and mg["credit_status"] in ("PROPOSED", "APPROVED")):
            raise conflict(ERR_INVALID_STATE_TRANSITION,
                           "an open make-good credit already exists for this "
                           "invoice")
    campaign = db.campaigns[inv["campaign_id"]]
    shortfall = max(0, campaign["contracted_impressions"]
                    - campaign["delivered_impressions"])
    # Strict threshold, exact rational arithmetic: pct > 0.05.
    if not calc.threshold_met(shortfall, campaign["contracted_impressions"]):
        raise unprocessable(ERR_MAKE_GOOD_THRESHOLD_NOT_MET,
                            "under-delivery ratio is not strictly greater "
                            "than 0.05")
    credit = calc.make_good_credit_cents(shortfall, campaign["cpm_cents"],
                                         inv["audited_amount_cents"])
    pct = shortfall / campaign["contracted_impressions"]
    rec = db.new_record()
    rec.update({"invoice_id": invoice_id, "shortfall_impressions": shortfall,
                "under_delivery_pct": pct, "credit_cents": credit,
                "credit_status": "PROPOSED", "proposed_by_user_id": user_id,
                "reviewed_by_user_id": None, "applied_by_user_id": None})
    db.make_goods[rec["id"]] = rec
    return success_object(ser_make_good(rec), 201)


@bp.get("/network/invoices/<invoice_id>/make-goods")
def list_invoice_make_goods(invoice_id):
    require(ALL_ROLES)
    _get_invoice_or_404(invoice_id)
    limit, offset = pagination()
    items = sorted((m for m in db.make_goods.values()
                    if m["invoice_id"] == invoice_id),
                   key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_make_good(m) for m in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


@bp.post("/network/make-goods/<make_good_id>/review")
def review_make_good(make_good_id):
    user_id = require(AUDITOR)
    body = get_body()
    decision = req_enum(body, "decision", {"APPROVE", "DECLINE"})
    mg = _get_make_good_or_404(make_good_id)
    # Priority 6: SoD before state.
    if user_id == mg["proposed_by_user_id"]:
        raise ApiError(ERR_SOD_REVIEWER_IS_PROPOSER, 403,
                       "reviewer must differ from the proposer")
    if mg["credit_status"] != "PROPOSED":
        raise conflict(ERR_MAKE_GOOD_NOT_REVIEWABLE,
                       "only a PROPOSED make-good can be reviewed")
    mg["credit_status"] = "APPROVED" if decision == "APPROVE" else "DECLINED"
    mg["reviewed_by_user_id"] = user_id
    db.touch(mg)
    return success_object(ser_make_good(mg))


@bp.post("/network/make-goods/<make_good_id>/apply")
def apply_make_good(make_good_id):
    user_id = require(SALES)
    body = get_body()
    expected_version = req_int(body, "expected_invoice_version")
    mg = _get_make_good_or_404(make_good_id)
    inv = db.invoices[mg["invoice_id"]]
    # PRD 3.7 prose order: OCC, then credit state, then invoice state.
    if expected_version != inv["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_invoice_version does not match the invoice's "
                       "current version")
    if mg["credit_status"] != "APPROVED":
        raise conflict(ERR_MAKE_GOOD_NOT_REVIEWABLE,
                       "only an APPROVED make-good can be applied")
    if not (inv["billing_status"] == "ISSUED"
            and inv["audit_status"] == "CERTIFIED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "invoice must be ISSUED and CERTIFIED to post a credit")
    inv["applied_credit_cents"] += mg["credit_cents"]
    inv["final_amount_cents"] -= mg["credit_cents"]
    mg["credit_status"] = "APPLIED"
    mg["applied_by_user_id"] = user_id
    db.touch(inv)
    db.touch(mg)
    return success_object(ser_make_good(mg))
