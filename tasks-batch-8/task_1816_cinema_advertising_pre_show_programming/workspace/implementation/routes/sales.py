"""Advertisers and campaigns (PRD 3.2)."""
import db
from auth import require, ALL_ROLES
from envelope import success_object, success_list
from errors import (ApiError, not_found, bad_request, conflict,
                    ERR_INVALID_STATE_TRANSITION,
                    ERR_CAMPAIGN_HAS_ACTIVE_SLOTS,
                    ERR_CAMPAIGN_HAS_OPEN_INVOICES,
                    ERR_SOD_APPROVER_IS_CREATOR)
from serializers import ser_advertiser, ser_campaign
from validate import (get_body, req_str, req_int, req_enum, req_date, opt_str,
                      opt_int, opt_enum, opt_date, parse_date_value,
                      pagination)

from . import bp

ADVERTISER_TYPES = {"NATIONAL", "LOCAL"}
CATEGORIES = {"AUTOMOTIVE", "QSR", "RETAIL", "ENTERTAINMENT", "TECH",
              "ALCOHOL", "POLITICAL"}
PARTIAL_CREDIT_MODES = {"STRICT", "LENIENT"}
SALES = {"SalesManager"}


# ------------------------------ Advertisers ---------------------------------

@bp.post("/network/advertisers")
def create_advertiser():
    require(SALES)
    body = get_body()
    name = req_str(body, "name")
    atype = req_enum(body, "advertiser_type", ADVERTISER_TYPES)
    category = req_enum(body, "category", CATEGORIES)
    rec = db.new_record()
    rec.update({"name": name, "advertiser_type": atype, "category": category,
                "advertiser_status": "ACTIVE"})
    db.advertisers[rec["id"]] = rec
    return success_object(ser_advertiser(rec), 201)


@bp.get("/network/advertisers/<advertiser_id>")
def get_advertiser(advertiser_id):
    require(ALL_ROLES)
    a = db.advertisers.get(advertiser_id)
    if a is None:
        raise not_found("advertiser not found")
    return success_object(ser_advertiser(a))


@bp.get("/network/advertisers/<advertiser_id>/campaigns")
def list_advertiser_campaigns(advertiser_id):
    require(ALL_ROLES)
    a = db.advertisers.get(advertiser_id)
    if a is None:
        raise not_found("advertiser not found")
    limit, offset = pagination()
    items = sorted((c for c in db.campaigns.values()
                    if c["advertiser_id"] == advertiser_id),
                   key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_campaign(c) for c in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


# ------------------------------- Campaigns ----------------------------------

def _check_flight_order(start_raw, end_raw):
    s = parse_date_value("flight_start_date", start_raw)
    e = parse_date_value("flight_end_date", end_raw)
    if e < s:
        raise bad_request("flight_end_date must not be earlier than "
                          "flight_start_date")
    return s, e


@bp.post("/network/campaigns")
def create_campaign():
    user_id = require(SALES)
    body = get_body()
    advertiser_id = req_str(body, "advertiser_id")
    name = req_str(body, "name")
    flight_start = req_date(body, "flight_start_date")
    flight_end = req_date(body, "flight_end_date")
    contracted = req_int(body, "contracted_impressions", minimum=1)
    cpm = req_int(body, "cpm_cents", minimum=1)
    budget = req_int(body, "budget_cents", minimum=1)
    pcm = opt_enum(body, "partial_credit_mode", PARTIAL_CREDIT_MODES,
                   default="STRICT")
    fs_dt, fe_dt = _check_flight_order(flight_start, flight_end)

    advertiser = db.advertisers.get(advertiser_id)
    if advertiser is None:
        raise not_found("advertiser not found")

    rec = db.new_record()
    rec.update({"advertiser_id": advertiser_id, "name": name,
                "flight_start_date": flight_start, "flight_end_date": flight_end,
                "_flight_start": fs_dt, "_flight_end": fe_dt,
                "contracted_impressions": contracted, "cpm_cents": cpm,
                "budget_cents": budget, "partial_credit_mode": pcm,
                "campaign_status": "DRAFT", "created_by_user_id": user_id,
                "approved_by_user_id": None,
                "reserved_estimated_cents": 0, "delivered_impressions": 0})
    db.campaigns[rec["id"]] = rec
    return success_object(ser_campaign(rec), 201)


@bp.get("/network/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    require(ALL_ROLES)
    c = db.campaigns.get(campaign_id)
    if c is None:
        raise not_found("campaign not found")
    return success_object(ser_campaign(c))


@bp.patch("/network/campaigns/<campaign_id>")
def edit_campaign(campaign_id):
    require(SALES)
    body = get_body()
    # Shape first (priority 4), then existence (priority 5).
    name = opt_str(body, "name")
    flight_start = opt_date(body, "flight_start_date")
    flight_end = opt_date(body, "flight_end_date")
    contracted = opt_int(body, "contracted_impressions", minimum=1)
    cpm = opt_int(body, "cpm_cents", minimum=1)
    budget = opt_int(body, "budget_cents", minimum=1)
    pcm = opt_enum(body, "partial_credit_mode", PARTIAL_CREDIT_MODES)

    c = db.campaigns.get(campaign_id)
    if c is None:
        raise not_found("campaign not found")

    # Merged flight window must remain ordered.
    new_start_raw = flight_start if flight_start is not None else c["flight_start_date"]
    new_end_raw = flight_end if flight_end is not None else c["flight_end_date"]
    fs_dt, fe_dt = _check_flight_order(new_start_raw, new_end_raw)

    if c["campaign_status"] not in ("DRAFT", "REJECTED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "campaign may only be edited while DRAFT or REJECTED")

    if name is not None:
        c["name"] = name
    if flight_start is not None:
        c["flight_start_date"] = flight_start
    if flight_end is not None:
        c["flight_end_date"] = flight_end
    c["_flight_start"] = fs_dt
    c["_flight_end"] = fe_dt
    if contracted is not None:
        c["contracted_impressions"] = contracted
    if cpm is not None:
        c["cpm_cents"] = cpm
    if budget is not None:
        c["budget_cents"] = budget
    if pcm is not None:
        c["partial_credit_mode"] = pcm
    # Editing a REJECTED campaign reopens it to DRAFT.
    if c["campaign_status"] == "REJECTED":
        c["campaign_status"] = "DRAFT"
    db.touch(c)
    return success_object(ser_campaign(c))


def _get_campaign_or_404(campaign_id):
    c = db.campaigns.get(campaign_id)
    if c is None:
        raise not_found("campaign not found")
    return c


@bp.post("/network/campaigns/<campaign_id>/submit")
def submit_campaign(campaign_id):
    require(SALES)
    c = _get_campaign_or_404(campaign_id)
    if c["campaign_status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a DRAFT campaign can be submitted")
    c["campaign_status"] = "SUBMITTED"
    db.touch(c)
    return success_object(ser_campaign(c))


@bp.post("/network/campaigns/<campaign_id>/approve")
def approve_campaign(campaign_id):
    user_id = require(SALES)
    c = _get_campaign_or_404(campaign_id)
    # SoD (priority 6) precedes state preconditions (priority 7).
    if user_id == c["created_by_user_id"]:
        raise ApiError(ERR_SOD_APPROVER_IS_CREATOR, 403,
                       "approver must differ from the campaign creator")
    if c["campaign_status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a SUBMITTED campaign can be approved")
    advertiser = db.advertisers[c["advertiser_id"]]
    if advertiser["advertiser_status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "a suspended advertiser's campaign cannot be approved")
    c["campaign_status"] = "APPROVED"
    c["approved_by_user_id"] = user_id
    db.touch(c)
    return success_object(ser_campaign(c))


@bp.post("/network/campaigns/<campaign_id>/reject")
def reject_campaign(campaign_id):
    user_id = require(SALES)
    get_body()  # optional reason; not persisted
    c = _get_campaign_or_404(campaign_id)
    if user_id == c["created_by_user_id"]:
        raise ApiError(ERR_SOD_APPROVER_IS_CREATOR, 403,
                       "rejecter must differ from the campaign creator")
    if c["campaign_status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a SUBMITTED campaign can be rejected")
    c["campaign_status"] = "REJECTED"
    db.touch(c)
    return success_object(ser_campaign(c))


@bp.post("/network/campaigns/<campaign_id>/cancel")
def cancel_campaign(campaign_id):
    require(SALES)
    c = _get_campaign_or_404(campaign_id)
    if c["campaign_status"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a DRAFT, SUBMITTED, or APPROVED campaign can be "
                       "canceled")
    for s in db.slots.values():
        if s["campaign_id"] == campaign_id and s["slot_status"] in (
                "RESERVED", "CONFIRMED"):
            raise conflict(ERR_CAMPAIGN_HAS_ACTIVE_SLOTS,
                           "campaign has slots in RESERVED or CONFIRMED")
    c["campaign_status"] = "CANCELED"
    db.touch(c)
    return success_object(ser_campaign(c))


@bp.post("/network/campaigns/<campaign_id>/complete")
def complete_campaign(campaign_id):
    require(SALES)
    c = _get_campaign_or_404(campaign_id)
    if c["campaign_status"] != "APPROVED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only an APPROVED campaign can be completed")
    for s in db.slots.values():
        if s["campaign_id"] == campaign_id and s["slot_status"] not in (
                "PLAYED", "MISSED", "CANCELED"):
            raise conflict(ERR_CAMPAIGN_HAS_ACTIVE_SLOTS,
                           "campaign has slots that have not reached a "
                           "terminal state")
    for inv in db.invoices.values():
        if inv["campaign_id"] == campaign_id and inv["billing_status"] in (
                "DRAFT", "ISSUED"):
            raise conflict(ERR_CAMPAIGN_HAS_OPEN_INVOICES,
                           "campaign has an invoice in DRAFT or ISSUED")
    c["campaign_status"] = "COMPLETED"
    db.touch(c)
    return success_object(ser_campaign(c))
