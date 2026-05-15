"""Conversion / attribution endpoints."""
from flask import Blueprint

from .. import store
from ..auth import require_auth
from ..errors import ApiError
from ..response import success
from ..validators import get_json_body, require_fields, require_enum
from ..services.attribution import run_attribution
from ..services.paths import resolve_advertiser, resolve_conversion


bp = Blueprint("conversions", __name__)


SOURCES = ["WEB_PIXEL", "APP_SDK", "S2S", "OFFLINE_UPLOAD"]
MODELS = ["LAST_CLICK", "POSITION_BASED", "DATA_DRIVEN"]


@bp.post("/conversions")
@require_auth(["MeasurementPartner", "ExchangeService"])
def create_conversion():
    body = get_json_body()
    require_fields(body, ["source", "user_id", "advertiser_id", "conversion_type"])
    require_enum(body, "source", SOURCES)

    advertiser_id = body["advertiser_id"]
    resolve_advertiser(advertiser_id)

    if "attribution_window_days" in body and body["attribution_window_days"] is not None:
        window = body["attribution_window_days"]
    else:
        window = 7
    if not isinstance(window, int) or isinstance(window, bool) or window < 1 or window > 90:
        raise ApiError("ERR_INVALID_ATTRIBUTION_WINDOW")

    model = body.get("attribution_model", "LAST_CLICK") or "LAST_CLICK"
    if model not in MODELS:
        raise ApiError("ERR_INVALID_REQUEST", f"attribution_model must be one of {MODELS}.")

    rec = {
        "id": store.gen_uuid(),
        "source": body["source"],
        "user_id": body["user_id"],
        "advertiser_id": advertiser_id,
        "conversion_type": body["conversion_type"],
        "value_cents": int(body.get("value_cents") or 0),
        "attribution_window_days": int(window),
        "attribution_model": model,
        "attributed_touchpoints": [],
        "attribution_status": "PENDING",
    }
    store.stamp_common(rec, with_version=False)
    store.insert("ConversionEvent", rec)
    # Auto-run attribution on ingest.
    run_attribution(rec)
    return success(rec, status=201)


@bp.post("/conversions/<conversion_id>/attribute")
@require_auth(["MeasurementPartner", "PlatformAdmin"])
def attribute(conversion_id):
    rec = resolve_conversion(conversion_id)
    # Validate window again on demand.
    w = rec.get("attribution_window_days", 7)
    if not isinstance(w, int) or w < 1 or w > 90:
        raise ApiError("ERR_INVALID_ATTRIBUTION_WINDOW")
    run_attribution(rec)
    return success(rec)
