"""Season statistics reporting to the sponsoring program (PRD §3.9).

Aggregates are lifetime-to-date snapshots computed once at creation and frozen;
period_start/period_end are labels only.
"""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles, require_site_coordinator_of
from response import created, ok, paginate
from services import calcs
from services.serialize import report_json
from validation import parse_body, require_entity

bp = Blueprint("reports", __name__)

REPORT_STATUSES = ["DRAFT", "SUBMITTED", "ACKNOWLEDGED"]

CREATE_SCHEMA = {
    "period_start": {"kind": "datetime", "required": True},
    "period_end": {"kind": "datetime", "required": True},
}

STATE_SCHEMA = {
    "to_status": {"kind": "enum", "required": True, "values": REPORT_STATUSES},
}


def _compute_aggregates(site_id):
    returns = [r for r in store.tax_returns.values() if r["site_id"] == site_id]
    prepared = sum(1 for r in returns if r["reached_preparation"])
    transmitted = sum(1 for r in returns if r["submission_count"] >= 1)
    accepted = sum(1 for r in returns if r["status"] in ("ACCEPTED", "COMPLETED"))
    rejected_open = sum(1 for r in returns if r["status"] == "REJECTED")
    referred = sum(1 for r in returns if r["status"] == "REFERRED")
    withdrawn = sum(1 for r in returns if r["status"] == "WITHDRAWN")
    qr_rework = sum(r["qr_failure_count"] for r in returns)
    first_pass = sum(1 for r in returns if r["first_ack_outcome"] == "ACCEPTED")
    return_ids = {r["id"] for r in returns}
    fin_refs = sum(1 for f in store.financial_referrals.values()
                   if f["tax_return_id"] in return_ids
                   and f["status"] in ("ACCEPTED", "ENROLLED"))
    match_total = sum(calcs.savings_match_cents(r["id"]) for r in returns
                      if r["status"] in ("TRANSMITTED", "ACCEPTED", "COMPLETED"))
    return {
        "returns_prepared_count": prepared,
        "returns_transmitted_count": transmitted,
        "returns_accepted_count": accepted,
        "returns_rejected_open_count": rejected_open,
        "returns_referred_count": referred,
        "returns_withdrawn_count": withdrawn,
        "qr_rework_total": qr_rework,
        "first_pass_accepted_count": first_pass,
        "first_pass_acceptance_rate_bp": calcs.rate_bp(first_pass, transmitted),
        "final_resolution_rate_bp": calcs.rate_bp(accepted, transmitted),
        "financial_referrals_accepted_count": fin_refs,
        "savings_match_total_cents": match_total,
    }


@bp.post("/sites/<site_id>/reports")
def create_report(site_id):
    get_context()
    require_site_coordinator_of(site_id)
    require_entity(store.sites, site_id)
    body = parse_body(CREATE_SCHEMA)
    # Temporal rule (tier 8): period end must be strictly after the start.
    if body["period_end"] <= body["period_start"]:
        raise ApiError("ERR_REPORT_PERIOD_INVALID", 422,
                       "period_end must be strictly after period_start")
    report = db.new_common({
        "site_id": site_id,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "status": "DRAFT",
        "generated_at": db.logical_dt(),
        **_compute_aggregates(site_id),
    })
    store.site_reports[report["id"]] = report
    return created(report_json(report))


@bp.get("/sites/<site_id>/reports")
def list_reports(site_id):
    get_context()
    require_roles(["SiteCoordinator", "SponsorAdmin"])
    require_entity(store.sites, site_id)
    rows = [r for r in store.site_reports.values() if r["site_id"] == site_id]
    page = paginate(rows)
    return ok([report_json(r) for r in page], rtype="array", pagination=paginate)


@bp.post("/site-reports/<report_id>/state")
def transition_report(report_id):
    uid, role, volunteer = get_context()
    require_roles(["SiteCoordinator", "SponsorAdmin"])
    report = require_entity(store.site_reports, report_id)
    body = parse_body(STATE_SCHEMA)
    current = report["status"]
    target = body["to_status"]

    # Transition-level actor rules (tier 2): submission is the site's
    # coordinator duty; acknowledgement belongs to the SponsorAdmin.
    if target == "SUBMITTED":
        if role != "SiteCoordinator":
            raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                           "Only a SiteCoordinator submits a report")
        if (not volunteer.get("is_coordinator")
                or volunteer.get("site_id") != report["site_id"]):
            raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                           "SiteCoordinator must belong to and be a coordinator "
                           "of the report's site")
    elif target == "ACKNOWLEDGED":
        if role != "SponsorAdmin":
            raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                           "Only a SponsorAdmin acknowledges a report")

    if (current, target) in (("DRAFT", "SUBMITTED"),
                             ("SUBMITTED", "ACKNOWLEDGED")):
        report["status"] = target
        db.touch(report)
    else:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Cannot move report from %s to %s" % (current, target))
    return ok(report_json(report))
