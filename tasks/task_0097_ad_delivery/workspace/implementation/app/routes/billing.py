"""Billing event endpoints."""
from flask import Blueprint, request

from .. import store
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import get_json_body, require_fields, require_non_empty_string
from ..services.billing import ingest_billing_event, reverse_billing_event
from ..services.paths import resolve_billing_event


bp = Blueprint("billing", __name__)


@bp.post("/billing-events")
@require_auth(["ExchangeService", "MeasurementPartner"])
def create_billing_event():
    body = get_json_body()
    require_fields(body, ["event_type", "auction_event_id", "ad_group_id", "dedup_key", "ivt_score"])
    rec = ingest_billing_event(body)
    return success(rec, status=201)


@bp.post("/billing-events/<event_id>/reverse")
@require_auth(["AntiFraudService", "PlatformAdmin"])
def reverse_event(event_id):
    rec = resolve_billing_event(event_id)
    body = get_json_body()
    require_non_empty_string(body, "reversal_reason")
    rec = reverse_billing_event(rec, body["reversal_reason"])
    return success(rec)


@bp.get("/billing-events")
@require_auth(["PlatformAdmin", "AccountOwner", "FinanceOfficer"])
def list_billing_events():
    limit, offset = get_pagination()
    rows = store.list_all("BillingEvent")
    advertiser_id = request.args.get("advertiser_id")
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    frm = request.args.get("from")
    to = request.args.get("to")
    if advertiser_id:
        rows = [r for r in rows if r.get("advertiser_id") == advertiser_id]
    if campaign_id:
        rows = [r for r in rows if r.get("campaign_id") == campaign_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if frm:
        rows = [r for r in rows if r.get("created_at", "") >= frm]
    if to:
        rows = [r for r in rows if r.get("created_at", "") <= to]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)
