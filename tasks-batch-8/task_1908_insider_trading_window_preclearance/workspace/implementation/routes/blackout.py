"""BlackoutWindow endpoints: create (with merge), get, list, cancel, extend."""
from flask import Blueprint, request

from db import STORE
from errors import (err, ERR_DATE_RANGE_INVALID, ERR_DUPLICATE_QUARTER_WINDOW,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION)
from middleware import require_roles
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created, get_or_404,
                           create_event_window, WINDOW_KINDS, FISCAL_QUARTERS)
from util import Body, fmt_ts

bp = Blueprint("blackout", __name__)

READ_ROLES = ("Insider", "ComplianceOfficer", "CommitteeMember", "LegalAdmin")


@bp.post("/blackout-windows")
def create_window():
    require_roles("ComplianceOfficer")
    body = Body()
    kind = body.get_enum("kind", WINDOW_KINDS)
    fiscal_year = body.get_int("fiscal_year", required=False)
    fiscal_quarter = body.get_enum("fiscal_quarter", FISCAL_QUARTERS, required=False)
    ticker = body.get_str("security_ticker", required=False)
    start = body.get_dt("start_at")
    end = body.get_dt("end_at")
    # Date-range sanity (temporal; fires before kind-specific conflict checks).
    if start is not None and end is not None and end <= start:
        raise err(ERR_DATE_RANGE_INVALID, "end_at must be strictly after start_at")
    # Quarterly windows are exclusive: half-open overlap with an existing
    # SCHEDULED/ACTIVE QUARTERLY window is a conflict; adjacency is allowed.
    if kind == "QUARTERLY" and start is not None and end is not None:
        for w in STORE.blackout_windows.values():
            if w["kind"] == "QUARTERLY" and w["status"] in ("SCHEDULED", "ACTIVE") \
                    and start < w["_end_dt"] and end > w["_start_dt"]:
                raise err(ERR_DUPLICATE_QUARTER_WINDOW,
                          "new QUARTERLY window overlaps an existing SCHEDULED/ACTIVE QUARTERLY window")
    # Kind-specific required fields are part of the body schema (bottom of the
    # ladder): a quarterly window without fiscal fields, or an event window
    # without a ticker, is a malformed body.
    if kind == "QUARTERLY":
        if fiscal_year is None and not body.has("fiscal_year"):
            body._mark(ERR_INVALID_REQUEST, "fiscal_year is required for QUARTERLY windows")
        if fiscal_quarter is None and not body.has("fiscal_quarter"):
            body._mark(ERR_INVALID_REQUEST, "fiscal_quarter is required for QUARTERLY windows")
    if kind == "EVENT_DRIVEN":
        if ticker is None and not body.has("security_ticker"):
            body._mark(ERR_INVALID_REQUEST, "security_ticker is required for EVENT_DRIVEN windows")
    body.flush()
    if kind == "QUARTERLY":
        w = new_entity()
        w.update({
            "kind": "QUARTERLY",
            "fiscal_year": fiscal_year,
            "fiscal_quarter": fiscal_quarter,
            "security_ticker": None,
            "deal_id": None,
            "start_at": fmt_ts(start),
            "end_at": fmt_ts(end),
            "status": "SCHEDULED",
            "merged_into_id": None,
            "applicability_note": "QUARTERLY window applies to all tickers",
            "_start_dt": start,
            "_end_dt": end,
        })
        STORE.blackout_windows[w["id"]] = w
    else:
        # EVENT_DRIVEN: created via the shared helper so deal-spawned and
        # officer-created windows follow the identical merge rule.
        w = create_event_window(ticker, start, end, deal_id=None)
    return success(serialize(w), 201)


@bp.get("/blackout-windows/<wid>")
def get_window(wid):
    require_roles(*READ_ROLES)
    w = get_or_404("blackout_windows", wid, "blackout window")
    return success(serialize(w))


@bp.get("/blackout-windows")
def list_windows():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.blackout_windows.values())
    for field in ("kind", "status", "security_ticker", "deal_id", "merged_into_id"):
        v = request.args.get(field)
        if v is not None:
            items = [w for w in items if w[field] == v]
    return paginate([serialize(w) for w in items])


@bp.post("/blackout-windows/<wid>/cancel")
def cancel_window(wid):
    require_roles("ComplianceOfficer")
    w = get_or_404("blackout_windows", wid, "blackout window")
    if w["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "only a SCHEDULED window can be cancelled")
    w["status"] = "CANCELLED"
    touch(w)
    return success(serialize(w))


@bp.post("/blackout-windows/<wid>/extend")
def extend_window(wid):
    require_roles("ComplianceOfficer")
    w = get_or_404("blackout_windows", wid, "blackout window")
    # State first (SCHEDULED or ACTIVE), then OCC (rides with the state
    # group), then the temporal date-range check, then body schema.
    if w["status"] not in ("SCHEDULED", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "only a SCHEDULED or ACTIVE window can be extended")
    body = Body()
    expected = body.get_int("expected_blackout_window_version")
    new_end = body.get_dt("new_end_at")
    if expected is not None and expected != w["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_blackout_window_version does not match the window's current version")
    if new_end is not None and new_end <= w["_end_dt"]:
        raise err(ERR_DATE_RANGE_INVALID, "new_end_at must be strictly later than the current end_at")
    body.flush()
    w["_end_dt"] = new_end
    w["end_at"] = fmt_ts(new_end)
    touch(w)
    return success(serialize(w))
