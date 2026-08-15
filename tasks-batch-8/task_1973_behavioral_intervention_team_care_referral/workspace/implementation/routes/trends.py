from flask import Blueprint

import errors as E
import response
from db import store, new_record, serialize, parse_dt
from errors import ApiError
from middleware import require_auth, ALL_ROLES
from routes.util import body, get_or_404
from services.trends import compute_trend_metrics

bp = Blueprint("trends", __name__)


@bp.post("/bit/trend-reports")
def create_trend_report():
    require_auth(["SystemAdmin"])
    b = body()
    term_code = b.get("term_code")
    if not isinstance(term_code, str) or not term_code:
        raise ApiError(E.ERR_VALIDATION, 400, "term_code is required")
    window_start = parse_dt(b.get("window_start"))
    if window_start is None:
        raise ApiError(E.ERR_VALIDATION, 400, "window_start must be an ISO 8601 UTC timestamp")
    window_end = parse_dt(b.get("window_end"))
    if window_end is None:
        raise ApiError(E.ERR_VALIDATION, 400, "window_end must be an ISO 8601 UTC timestamp")
    variant = b.get("variant")
    if variant not in ("ENTRY_COHORT", "ACTIVE_IN_WINDOW"):
        raise ApiError(E.ERR_VALIDATION, 400, "variant must be ENTRY_COHORT or ACTIVE_IN_WINDOW")
    if not window_end > window_start:
        raise ApiError(
            E.ERR_TREND_WINDOW_INVALID, 400, "window_end must be later than window_start"
        )

    metrics = compute_trend_metrics(window_start, window_end, variant)
    rec = new_record()
    rec.update(
        {
            "term_code": term_code,
            "window_start": window_start,
            "window_end": window_end,
            "variant": variant,
            "total_cases": metrics["total_cases"],
            "closed_in_window": metrics["closed_in_window"],
            "closure_rate_pct": metrics["closure_rate_pct"],
            "avg_days_to_close": metrics["avg_days_to_close"],
            "category_distribution": metrics["category_distribution"],
        }
    )
    store.trends[rec["id"]] = rec
    return response.obj(serialize(rec), 201)


@bp.get("/bit/trend-reports/<tid>")
def get_trend_report(tid):
    require_auth(list(ALL_ROLES))
    rec = get_or_404(store.trends, tid, "trend report")
    return response.obj(serialize(rec))
