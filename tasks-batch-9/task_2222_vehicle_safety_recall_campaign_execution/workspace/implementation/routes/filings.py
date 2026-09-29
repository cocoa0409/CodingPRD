"""Regulatory filings: Part 573 defect notice, quarterly reports, amendments."""
from flask import Blueprint, g, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import (base_record, clock_now, fmt_instant, parse_instant, store, touch)
from errors import ApiError
from response import collection, single

bp = Blueprint("filings", __name__)


def _snapshot(filing, campaign):
    buckets = calc.population_buckets(campaign["id"])
    filing["completion_rate_snapshot_pct"] = calc.regulatory_completion_rate(
        campaign["id"], buckets)
    filing["remedied_count_snapshot"] = buckets["remedied"]
    filing["recall_population_snapshot"] = buckets["recall_population"]
    filing["effectiveness_score_snapshot"] = campaign["remedy_effectiveness_score"]


@bp.post("/recall-campaigns/<campaign_id>/filings")
@require_roles("ComplianceOfficer")
def create_filing(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    filing_type = v.req_enum(payload, "filing_type", v.FILING_TYPES)
    narrative = v.req_str(payload, "narrative", min_len=1, max_len=4000)
    report_period = None
    if filing_type != "DEFECT_NOTICE":
        report_period = v.req_str(payload, "report_period")
        if not v.REPORT_PERIOD_RE.match(report_period):
            v.bad("report_period must be formatted as YYYYQn, for example 2026Q3.")

    if filing_type == "DEFECT_NOTICE" and g.user_id == campaign["determined_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    siblings = calc.campaign_filings(campaign["id"])

    if filing_type == "DEFECT_NOTICE":
        if campaign["campaign_status"] != "DEFECT_DETERMINED":
            raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
        if any(f["filing_type"] == "DEFECT_NOTICE" for f in siblings):
            raise ApiError("ERR_FILING_PERIOD_DUPLICATE")
    elif filing_type == "QUARTERLY":
        if campaign["campaign_status"] not in ("OWNER_NOTIFIED", "MONITORING"):
            raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
        if any(f["report_period"] == report_period for f in siblings):
            raise ApiError("ERR_FILING_PERIOD_DUPLICATE")
    else:
        h.assert_campaign_writable(campaign)
        prior = None
        for f in siblings:
            if (f["filing_type"] == "QUARTERLY"
                    and f["report_period"] == report_period
                    and f["status"] == "SUBMITTED"):
                prior = f
                break
        if prior is None:
            raise ApiError("ERR_NO_QUARTERLY_FILING_TO_AMEND")

    filed_at = clock_now()
    filing = base_record()
    filing.update({
        "campaign_id": campaign["id"],
        "filing_type": filing_type,
        "report_period": report_period,
        "narrative": narrative,
        "filed_at": fmt_instant(filed_at),
        "filed_by_user_id": g.user_id,
        "days_late": 0,
        "completion_rate_snapshot_pct": None,
        "remedied_count_snapshot": 0,
        "recall_population_snapshot": 0,
        "effectiveness_score_snapshot": None,
        "amendment_required": False,
        "status": "SUBMITTED",
    })
    store.filings[filing["id"]] = filing

    if filing_type == "DEFECT_NOTICE":
        deadline = parse_instant(campaign["filing_deadline_utc"]) \
            if campaign["filing_deadline_utc"] else None
        late, days_late = calc.filing_lateness(filed_at, deadline)
        campaign["filed_at"] = filing["filed_at"]
        campaign["late_filing_flag"] = late
        campaign["days_late"] = days_late
        campaign["campaign_status"] = "FILED"
        filing["days_late"] = days_late
        _snapshot(filing, campaign)
    elif filing_type == "QUARTERLY":
        campaign["quarterly_filing_count"] = campaign["quarterly_filing_count"] + 1
        campaign["campaign_status"] = "MONITORING"
        h.recompute_effectiveness(campaign)
        _snapshot(filing, campaign)
        if (filing["effectiveness_score_snapshot"] < calc.REMEDY_EFFECTIVENESS_MIN
                and campaign["remedy_status"] == "REMEDY_RELEASED"):
            h.cascade_remedy_revision(campaign, filing)
    else:
        prior["status"] = "AMENDED"
        prior["amendment_required"] = False
        touch(prior)
        h.recompute_effectiveness(campaign)
        _snapshot(filing, campaign)

    touch(campaign)
    return single(h.filing_out(filing), 201)


@bp.get("/recall-campaigns/<campaign_id>/filings")
@require_roles(*ALL_ROLES)
def list_filings(campaign_id):
    campaign = h.get_campaign(campaign_id)
    filing_type = v.query_enum("filing_type", v.FILING_TYPES)
    status = v.query_enum("status", v.FILING_STATUSES)
    report_period = request.args.get("report_period")
    rows = calc.campaign_filings(campaign["id"])
    if filing_type is not None:
        rows = [r for r in rows if r["filing_type"] == filing_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if report_period is not None:
        rows = [r for r in rows if r["report_period"] == report_period]
    return collection(rows, h.filing_out)
