"""PerformanceReport endpoints: finalize with audited metrics."""

from flask import Blueprint

import db
import errors as err
import response as resp
from middleware import require_roles
from services import calc, helpers as H

bp = Blueprint("performance_reports", __name__)


@bp.route("/performance-reports/<rid>/finalize", methods=["POST"])
@require_roles("BrandManager")
def finalize_report(actor, rid):
    report = H.get_or_404(db.performance_reports, rid, "performance report")
    payload = H.body()
    H.req_fields(payload, ["audited_views", "audited_engagements"])
    audited_views = H.require_int(payload, "audited_views", minimum=0)
    audited_engagements = H.require_int(payload, "audited_engagements",
                                        minimum=0)

    if report["status"] in ("FINAL", "SUPERSEDED"):
        raise err.already_terminal(f"PerformanceReport is {report['status']}")
    if report["status"] != "REPORTED":
        raise err.invalid_state("Finalize requires report REPORTED")

    if audited_views > int(report["views"]):
        raise err.validation("audited_views may not exceed views")

    report["audited_views"] = audited_views
    report["audited_engagements"] = audited_engagements
    report["final_bonus_cents"] = calc.performance_bonus(audited_views,
                                                         audited_engagements)
    report["status"] = "FINAL"
    H.touch(report)

    deal = db.deals.get(report["deal_id"])
    if deal is not None:
        H.recompute_bonus_accrued(deal["id"])

    return resp.ok(report)
