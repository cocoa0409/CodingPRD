"""GalaEvent routes: lifecycle, settings PATCH (OCC), reconcile, summary,
plus FK-reverse lists of bidders / solicitations / bundles."""

from flask import Blueprint

import errors
import middleware as mw
import response
from db import stores
from services import workflows as wf

bp = Blueprint("gala_events", __name__)

ADMIN = ["GalaAdmin"]
READ = mw.ALL_ROLES

_EVENT_INT_FIELDS = [
    "min_bid_pct_bps",
    "min_bid_increment_cents",
    "min_bid_floor_cents",
    "ack_threshold_cents",
    "solicitation_cooldown_days",
    "cert_validity_months",
    "cert_grace_days",
]

_ADVANCE_CHAIN = {
    "DRAFT": "SOLICITING",
    "SOLICITING": "CATALOGING",
    "CATALOGING": "BIDDING_OPEN",
    "BIDDING_OPEN": "BIDDING_CLOSED",
    "BIDDING_CLOSED": "SETTLEMENT",
}


def _require_tiers(body, name="bid_increment_tiers"):
    v = mw.require_field(body, name)
    if not isinstance(v, list) or not v:
        raise errors.err_invalid_request(f"{name} must be a non-empty array")
    out = []
    for t in v:
        if not isinstance(t, dict):
            raise errors.err_invalid_request(f"{name} entries must be objects")
        if "increment_cents" not in t or not mw.is_int(t["increment_cents"]):
            raise errors.err_invalid_request("tier increment_cents must be an integer")
        up_to = t.get("up_to_cents")
        if up_to is not None and not mw.is_int(up_to):
            raise errors.err_invalid_request("tier up_to_cents must be an integer or null")
        out.append({"up_to_cents": up_to, "increment_cents": t["increment_cents"]})
    return out


@bp.post("/gala-events")
def create_gala_event():
    mw.require_auth(ADMIN)
    body = mw.get_json_body()
    rec = mw.new_record()
    rec["name"] = mw.require_string(body, "name")
    rec["gala_date"] = mw.require_date(body, "gala_date")
    opens = mw.require_datetime(body, "bidding_opens_at")
    closes = mw.require_datetime(body, "bidding_closes_at")
    if not opens < closes:
        raise errors.err_invalid_request("bidding_opens_at must be earlier than bidding_closes_at")
    rec["bidding_opens_at"] = opens
    rec["bidding_closes_at"] = closes
    for f in _EVENT_INT_FIELDS:
        rec[f] = mw.require_int(body, f)
    rec["bid_increment_tiers"] = _require_tiers(body)
    rec["status"] = "DRAFT"
    stores["gala_events"][rec["id"]] = rec
    return response.success_object(mw.serialize(rec), 201)


@bp.get("/gala-events/<rid>")
def get_gala_event(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("gala_events", rid)))


@bp.patch("/gala-events/<rid>")
def patch_gala_event(rid):
    mw.require_auth(ADMIN)
    ev = mw.get_or_404("gala_events", rid)
    body = mw.get_json_body()
    # Request shape (priority 5) before OCC (6) before phase (8).
    expected = mw.require_int(body, "expected_gala_event_version")
    updates = {}
    for f in _EVENT_INT_FIELDS:
        if f in body and body[f] is not None:
            updates[f] = mw.require_int(body, f)
    if "bid_increment_tiers" in body and body["bid_increment_tiers"] is not None:
        updates["bid_increment_tiers"] = _require_tiers(body)
    opens = ev["bidding_opens_at"]
    closes = ev["bidding_closes_at"]
    if "bidding_opens_at" in body and body["bidding_opens_at"] is not None:
        opens = mw.require_datetime(body, "bidding_opens_at")
        updates["bidding_opens_at"] = opens
    if "bidding_closes_at" in body and body["bidding_closes_at"] is not None:
        closes = mw.require_datetime(body, "bidding_closes_at")
        updates["bidding_closes_at"] = closes
    if not opens < closes:
        raise errors.err_invalid_request("bidding_opens_at must be earlier than bidding_closes_at")
    if expected != ev["version"]:
        raise errors.err_stale_version()
    if ev["status"] not in ("DRAFT", "SOLICITING", "CATALOGING"):
        raise errors.err_event_phase_forbidden("Gala settings are locked past CATALOGING")
    ev.update(updates)
    mw.touch(ev)
    return response.success_object(mw.serialize(ev))


@bp.post("/gala-events/<rid>/advance")
def advance_gala_event(rid):
    mw.require_auth(ADMIN)
    ev = mw.get_or_404("gala_events", rid)
    nxt = _ADVANCE_CHAIN.get(ev["status"])
    if nxt is None:
        raise errors.err_invalid_state("Event cannot be advanced from " + ev["status"])
    if ev["status"] == "CATALOGING":
        if not any(
            b["gala_event_id"] == ev["id"] and b["status"] == "PUBLISHED"
            for b in stores["bundles"].values()
        ):
            raise errors.err_no_published_bundles()
    if ev["status"] == "BIDDING_OPEN":
        wf.close_cascade(ev)
    ev["status"] = nxt
    mw.touch(ev)
    return response.success_object(mw.serialize(ev))


@bp.post("/gala-events/<rid>/reconcile")
def reconcile_gala_event(rid):
    mw.require_auth(["FinanceOfficer"])
    ev = mw.get_or_404("gala_events", rid)
    if ev["status"] != "SETTLEMENT":
        raise errors.err_invalid_state("Reconcile requires status SETTLEMENT")
    for inv in stores["invoices"].values():
        if inv["gala_event_id"] != ev["id"]:
            continue
        if inv["payment_status"] not in ("PAID", "REFUNDED", "WRITTEN_OFF"):
            raise errors.err_reconcile_blocked()
        if inv["payment_status"] == "PAID" and inv["fulfillment_status"] not in ("FULFILLED", "EXPIRED"):
            raise errors.err_reconcile_blocked()
    for d in stores["dispositions"].values():
        if d["gala_event_id"] == ev["id"] and d["status"] != "EXECUTED":
            raise errors.err_reconcile_blocked()
    ev["status"] = "RECONCILED"
    mw.touch(ev)
    return response.success_object(mw.serialize(ev))


@bp.get("/gala-events/<rid>/summary")
def gala_event_summary(rid):
    mw.require_auth(["GalaAdmin", "FinanceOfficer"])
    ev = mw.get_or_404("gala_events", rid)
    invoices = [i for i in stores["invoices"].values() if i["gala_event_id"] == ev["id"]]

    def paid(inv):
        return wf.invoice_amount_paid(inv["id"])

    data = {
        "gross_winning_bids_cents": sum(i["winning_bid_cents"] for i in invoices),
        "collected_cents": sum(paid(i) for i in invoices),
        "outstanding_cents": sum(
            i["winning_bid_cents"] - paid(i)
            for i in invoices
            if i["payment_status"] in ("UNPAID", "PARTIALLY_PAID")
        ),
        "written_off_cents": sum(
            i["winning_bid_cents"] for i in invoices if i["payment_status"] == "WRITTEN_OFF"
        ),
        "refunded_cents": sum(
            i["winning_bid_cents"] for i in invoices if i["payment_status"] == "REFUNDED"
        ),
        "recognized_revenue_cents": sum(
            i["revenue_portion_cents"] for i in invoices if i["payment_status"] == "PAID"
        ),
        "recognized_contribution_cents": sum(
            i["contribution_portion_cents"] for i in invoices if i["payment_status"] == "PAID"
        ),
        "prorata_contribution_cents": sum(
            i["contribution_prorata_cents"] for i in invoices if i["payment_status"] == "PAID"
        ),
        "unsold_item_count": sum(
            1 for i in stores["items"].values()
            if i["gala_event_id"] == ev["id"] and i["status"] == "UNSOLD"
        ),
        "open_disposition_count": sum(
            1 for d in stores["dispositions"].values()
            if d["gala_event_id"] == ev["id"] and d["status"] in ("PROPOSED", "DONOR_NOTIFIED")
        ),
    }
    return response.success_object(data)


# ------------------------------------------------------------- FK reverse lists

@bp.get("/gala-events/<rid>/bidders")
def list_event_bidders(rid):
    mw.require_auth(READ)
    ev = mw.get_or_404("gala_events", rid)
    limit, offset = mw.parse_pagination()
    items = [b for b in stores["bidders"].values() if b["gala_event_id"] == ev["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(b) for b in page], limit, offset, total)


@bp.get("/gala-events/<rid>/solicitations")
def list_event_solicitations(rid):
    mw.require_auth(READ)
    ev = mw.get_or_404("gala_events", rid)
    limit, offset = mw.parse_pagination()
    items = [s for s in stores["solicitations"].values() if s["gala_event_id"] == ev["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([mw.serialize(s) for s in page], limit, offset, total)


@bp.get("/gala-events/<rid>/bundles")
def list_event_bundles(rid):
    mw.require_auth(READ)
    ev = mw.get_or_404("gala_events", rid)
    limit, offset = mw.parse_pagination()
    items = [b for b in stores["bundles"].values() if b["gala_event_id"] == ev["id"]]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array([wf.serialize_bundle(b) for b in page], limit, offset, total)
