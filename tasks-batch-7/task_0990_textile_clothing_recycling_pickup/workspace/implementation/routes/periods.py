"""ReportingPeriod endpoints: read and close (aggregate freezing)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store, touch, now_dt, now_iso
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import get_body

bp = Blueprint("periods", __name__)


def _zone_tickets(zone_id):
    return [t for t in store.tickets.values()
            if domain.zone_id_of_ticket(t) == zone_id]


def _in_window(dt, start, end):
    return dt is not None and start <= dt < end


def _weight2(total):
    return float(Decimal(total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@bp.route("/reporting-periods/<pid>", methods=["GET"])
@endpoint(["ZoneOperator", "SponsorManager", "CharityAdmin"])
def get_period(user_id, role, pid):
    period = domain.get_or_404(store.periods, pid, "ReportingPeriod")
    return success(domain.period_view(period))


@bp.route("/reporting-periods/<pid>/close", methods=["POST"])
@endpoint(["ZoneOperator"])
def close_period(user_id, role, pid):
    period = store.periods.get(pid)
    get_body()
    if period is None:
        fail("ERR_NOT_FOUND", "ReportingPeriod not found: %s" % pid)
    # p5 dedicated form
    if period["status"] != "OPEN":
        fail("ERR_PERIOD_NOT_OPEN", "Period must be OPEN to close")
    # p9k: no PROVISIONAL tickets whose source belongs to this zone
    tickets = _zone_tickets(period["zone_id"])
    if any(t["status"] == "PROVISIONAL" for t in tickets):
        fail("ERR_OPEN_TICKETS_REMAIN", "Zone still has PROVISIONAL weight tickets")
    start, end = period["_start"], period["_end"]
    # reporting_period_aggregation over the half-open window [start, end)
    certified_in = [t for t in tickets if _in_window(t.get("_certified_at"), start, end)]
    total_certified = sum(calc_dec(t["certified_weight_kg"]) for t in certified_in)
    diverted = sum(calc_dec(t["certified_weight_kg"]) for t in certified_in
                   if t["status"] == "CERTIFIED")
    ticket_ids = {t["id"] for t in tickets}
    settled = [c for c in store.credits.values()
               if c["ticket_id"] in ticket_ids and c["status"] == "SETTLED"
               and _in_window(c.get("_settled_at"), start, end)]
    credits_settled_count = len(settled)
    credits_settled_cents = sum(c["gross_cents"] or 0 for c in settled)
    charity_paid = sum(line["amount_cents"] for c in settled
                       for line in (c.get("charity_allocations") or []))
    severe_reports = sum(1 for r in store.reports.values()
                         if r["ticket_id"] in ticket_ids and r.get("outcome") == "UPHELD"
                         and r["severity"] == "SEVERE"
                         and _in_window(r.get("_adjudicated_at"), start, end))
    box_collections = sum(1 for t in tickets
                          if t["source_type"] == "DROPBOX"
                          and _in_window(_created_dt(t), start, end))
    period["aggregates"] = {
        "total_certified_weight_kg": _weight2(total_certified),
        "diverted_weight_kg": _weight2(diverted),
        "credits_settled_count": credits_settled_count,
        "credits_settled_cents": credits_settled_cents,
        "charity_paid_cents": charity_paid,
        "severe_reports_count": severe_reports,
        "box_collections_count": box_collections,
    }
    period["status"] = "CLOSED"
    period["closed_at"] = now_iso()
    touch(period)
    return success(domain.period_view(period))


def calc_dec(value):
    return Decimal(str(value))


def _created_dt(rec):
    from util import parse_dt
    return parse_dt(rec["created_at"])
