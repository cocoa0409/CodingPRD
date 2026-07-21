from flask import Blueprint

import store
import context as ctx
import envelope as env

bp = Blueprint("reports", __name__)


@bp.get("/reports/portfolio-summary")
def portfolio_summary():
    ctx.authenticate(["ProgramAdmin"])
    total_awards = len(store.awards)
    total_reserved = sum(a["amount_cents"] for a in store.allocations.values()
                         if a["status"] == "RESERVED")
    total_disbursed = sum(a["amount_cents"] for a in store.allocations.values()
                          if a["status"] == "DISBURSED")
    total_recaptured = sum((sa.get("recapture_amount_cents") or 0)
                           for sa in store.servicing.values()
                           if sa["lifecycle_status"] == "CLOSED")
    awards_by_status = {}
    for a in store.awards.values():
        awards_by_status[a["status"]] = awards_by_status.get(a["status"], 0) + 1

    data = {
        "total_awards": total_awards,
        "total_reserved_cents": total_reserved,
        "total_disbursed_cents": total_disbursed,
        "total_recaptured_cents": total_recaptured,
        "awards_by_status": awards_by_status,
    }
    return env.success(data, 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Test-driving capability: no authentication headers required.
    data = ctx.body()
    _, dt = ctx.req_datetime(data, "to_iso8601")
    store.set_clock(dt)
    return env.success({}, 200)
