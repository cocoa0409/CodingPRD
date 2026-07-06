"""Report routes: generation with period-overlap (+1 day buffer) validation."""
from datetime import timedelta

from flask import Blueprint

import services
from auth import require_auth, require_role
from clock import parse_iso8601, iso_format
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, find, assert_owns_client, paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("reports", __name__)

REPORT_GAP = timedelta(days=1)


@bp.route("/clients/<cid>/reports", methods=["POST"])
def create_report(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    client = find("client", cid)
    body = get_body()
    period_start_raw = require_str(body, "period_start")
    period_end_raw = require_str(body, "period_end")
    period_start = parse_iso8601(period_start_raw)
    period_end = parse_iso8601(period_end_raw)
    if period_start is None or period_end is None:
        raise err("ERR_INVALID_REQUEST", "period_start and period_end must be valid ISO-8601 datetimes")
    if not (period_end > period_start):
        raise err("ERR_INVALID_REQUEST", "period_end must be after period_start")

    # period overlap with 1-day buffer vs all prior reports of this client.
    # Each prior period is CLOSED [p_start, p_end]; require a strict 1-day gap
    # on each side: new start > prior_end + 1d  AND  new end < prior_start - 1d.
    for r in store.reports.values():
        if r["client_id"] != cid:
            continue
        p_start = parse_iso8601(r["period_start"])
        p_end = parse_iso8601(r["period_end"])
        after_prior = period_start > (p_end + REPORT_GAP)
        before_prior = period_end < (p_start - REPORT_GAP)
        if not (after_prior or before_prior):
            raise err("ERR_REPORT_PERIOD_OVERLAP", "Report period overlaps or violates the 1-day buffer")

    avg_rank, total_traffic, rank_momentum = services.compute_report_figures(
        client, period_start, period_end
    )

    rec = base_record(versioned=False)
    rec.update({
        "client_id": cid,
        "period_start": iso_format(period_start),
        "period_end": iso_format(period_end),
        "avg_rank": avg_rank,
        "total_traffic": total_traffic,
        "rank_momentum": rank_momentum,
    })
    store.reports[rec["id"]] = rec

    # recompute client health (now factors in the new latest report momentum)
    services.recompute_open_dispute_count(client)
    services.recompute_health_score(client)
    touch(client)
    return ok_object(rec, 201)


@bp.route("/reports/<rid>", methods=["GET"])
def get_report(rid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    report = find("report", rid)
    client = find("client", report["client_id"])
    assert_owns_client(principal, client)
    return ok_object(report, 200)


@bp.route("/clients/<cid>/reports", methods=["GET"])
def list_reports(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    client = find("client", cid)
    assert_owns_client(principal, client)
    parse_pagination()
    records = [r for r in store.reports.values() if r["client_id"] == cid]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)
