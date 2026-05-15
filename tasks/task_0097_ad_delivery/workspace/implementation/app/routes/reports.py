"""Reports + risk score."""
import math
from datetime import timedelta
from flask import Blueprint, request

from .. import store
from ..auth import require_auth
from ..clock import now
from ..errors import ApiError
from ..response import success
from ..services.paths import resolve_advertiser


bp = Blueprint("reports", __name__)


def _parse_ts(s):
    from datetime import datetime
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


@bp.get("/advertisers/<advertiser_id>/reports/attribution")
@require_auth(["PlatformAdmin", "AccountOwner", "CampaignManager"])
def attribution_report(advertiser_id):
    resolve_advertiser(advertiser_id)
    frm = request.args.get("from")
    to = request.args.get("to")
    model_filter = request.args.get("attribution_model")

    rows = []
    for conv in store.list_all("ConversionEvent"):
        if conv.get("advertiser_id") != advertiser_id:
            continue
        if conv.get("attribution_status") != "ATTRIBUTED":
            continue
        if model_filter and conv.get("attribution_model") != model_filter:
            continue
        ts = conv.get("created_at", "")
        if frm and ts < frm:
            continue
        if to and ts > to:
            continue
        for tp in conv.get("attributed_touchpoints", []) or []:
            be = store.get("BillingEvent", tp.get("billing_event_id", ""))
            campaign_id = be.get("campaign_id") if be else None
            rows.append({
                "conversion_id": conv["id"],
                "campaign_id": campaign_id,
                "attribution_model": conv["attribution_model"],
                "billing_event_id": tp.get("billing_event_id"),
                "credit_fraction": tp.get("credit_fraction"),
                "credit_cents": tp.get("credit_cents", 0),
                "value_cents": int(conv.get("value_cents", 0)),
            })

    # Aggregate by (campaign_id, attribution_model)
    agg: dict[tuple[str | None, str], dict] = {}
    for r in rows:
        key = (r["campaign_id"], r["attribution_model"])
        bucket = agg.setdefault(key, {
            "campaign_id": r["campaign_id"],
            "attribution_model": r["attribution_model"],
            "conversion_count": 0,
            "credit_cents": 0,
            "value_cents": 0,
        })
        bucket["conversion_count"] += 1
        bucket["credit_cents"] += int(r["credit_cents"])
        bucket["value_cents"] += int(r["value_cents"])

    return success({"advertiser_id": advertiser_id, "results": list(agg.values())})


@bp.get("/advertisers/<advertiser_id>/risk-score")
@require_auth(["PlatformAdmin", "AntiFraudService"])
def risk_score(advertiser_id):
    resolve_advertiser(advertiser_id)
    mode = request.args.get("mode", "chronic") or "chronic"
    if mode not in ("chronic", "acute"):
        raise ApiError("ERR_INVALID_REQUEST", "mode must be chronic or acute.")
    window = timedelta(days=30) if mode == "chronic" else timedelta(hours=24)
    now_dt = now()
    earliest_dt = now_dt - window

    def _in_window(ts_str: str) -> bool:
        try:
            return earliest_dt <= _parse_ts(ts_str) <= now_dt
        except Exception:
            return False

    # Invalid-traffic rate (BillingEvent)
    be_rows = [b for b in store.list_all("BillingEvent") if b.get("advertiser_id") == advertiser_id and _in_window(b.get("created_at", ""))]
    invalid_count = sum(1 for b in be_rows if b.get("status") in ("INVALID_TRAFFIC", "REVERSED"))
    invalid_rate = invalid_count / max(1, len(be_rows))

    # Reject rate (Creative)
    cr_rows = [c for c in store.list_all("Creative") if c.get("advertiser_id") == advertiser_id and _in_window(c.get("created_at", ""))]
    reject_count = sum(1 for c in cr_rows if c.get("review_status") == "REJECTED")
    reject_rate = reject_count / max(1, len(cr_rows))

    raw = invalid_rate * 0.6 + reject_rate * 0.4
    # round half-up using math
    score = int(min(100, math.floor(raw * 100 + 0.5)))
    return success({
        "advertiser_id": advertiser_id,
        "mode": mode,
        "risk_score": score,
        "invalid_traffic_rate": invalid_rate,
        "reject_rate": reject_rate,
        "billing_event_count": len(be_rows),
        "invalid_count": invalid_count,
        "creative_count": len(cr_rows),
        "reject_count": reject_count,
    })
