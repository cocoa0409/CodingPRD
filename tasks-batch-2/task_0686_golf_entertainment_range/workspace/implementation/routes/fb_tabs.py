"""FBTab routes: open, append item (nested-rounding totals), close
(freeze totals) (PRD §3.9; SCAFFOLD §1.5)."""

from flask import Blueprint, request

from db import db, stamp_common, touch
from response import success, list_success, parse_pagination, paginate
from middleware import get_caller, require_roles
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from services import validate as V
from services import calc
from services.lookup import get_or_404
from services.serialize import fb_tab_out

bp = Blueprint("fb_tabs", __name__)


@bp.post("/golf/fb-tabs")
def open_fb_tab():
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    data = V.body()
    session_id = data.get("session_id")
    event_package_id = data.get("event_package_id")

    if session_id is None and event_package_id is None:
        raise_err(ERR_INVALID_REQUEST, "session_id or event_package_id is required")
    if session_id is not None and event_package_id is not None:
        raise_err(ERR_INVALID_REQUEST, "provide only one of session_id or event_package_id")

    if session_id is not None:
        get_or_404(db.sessions, session_id, "session")
    if event_package_id is not None:
        get_or_404(db.event_packages, event_package_id, "event package")

    tab = stamp_common({
        "session_id": session_id,
        "event_package_id": event_package_id,
        "line_items": [],
        "subtotal_cents": 0,
        "gratuity_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "status": "OPEN",
    })
    db.fb_tabs[tab["id"]] = tab
    return success(fb_tab_out(tab), status=201)


@bp.get("/golf/fb-tabs/<fb_tab_id>")
def get_fb_tab(fb_tab_id):
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    t = get_or_404(db.fb_tabs, fb_tab_id, "F&B tab")
    return success(fb_tab_out(t))


@bp.get("/golf/fb-tabs")
def list_fb_tabs():
    caller = get_caller()
    require_roles(caller, {"Guest", "FrontDesk", "RangeManager"})
    limit, offset = parse_pagination(request.args)
    records = list(db.fb_tabs.values())
    for key in ("session_id", "event_package_id"):
        val = request.args.get(key)
        if val is not None:
            records = [t for t in records if t.get(key) == val]
    window, total = paginate(records, limit, offset)
    return list_success([fb_tab_out(t) for t in window], limit, offset, total)


@bp.post("/golf/fb-tabs/<fb_tab_id>/items")
def append_item(fb_tab_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    t = get_or_404(db.fb_tabs, fb_tab_id, "F&B tab")
    data = V.body()

    if t["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "tab is not OPEN")

    name = V.as_str(V.require(data, "name"), "name")
    unit_price = V.as_int(V.require(data, "unit_price_cents"), "unit_price_cents")
    if unit_price < 0:
        raise_err(ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")
    qty = data.get("qty", 1)
    qty = V.as_int(qty, "qty")
    if qty < 1:
        raise_err(ERR_INVALID_REQUEST, "qty must be >= 1")

    seq = len(t["line_items"]) + 1
    t["line_items"].append({
        "seq": seq, "name": name, "unit_price_cents": unit_price, "qty": qty,
    })
    subtotal, gratuity, tax, total = calc.fb_tab_totals(t["line_items"])
    t["subtotal_cents"] = subtotal
    t["gratuity_cents"] = gratuity
    t["tax_cents"] = tax
    t["total_cents"] = total
    touch(t)
    return success(fb_tab_out(t))


@bp.post("/golf/fb-tabs/<fb_tab_id>/close")
def close_fb_tab(fb_tab_id):
    caller = get_caller()
    require_roles(caller, {"FrontDesk"})
    t = get_or_404(db.fb_tabs, fb_tab_id, "F&B tab")
    V.body()
    if t["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "tab is not OPEN")
    # Totals are already frozen on the record; closing just stops further appends.
    t["status"] = "CLOSED"
    touch(t)
    return success(fb_tab_out(t))
