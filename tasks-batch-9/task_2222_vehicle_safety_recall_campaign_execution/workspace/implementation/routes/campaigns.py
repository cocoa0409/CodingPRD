"""Campaign file: creation, determination, advisory, release, closure, metrics."""
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import base_record, clock_now, fmt_instant, sorted_records, store, touch
from errors import ApiError
from response import collection, single

bp = Blueprint("campaigns", __name__)


@bp.post("/recall-campaigns")
@require_roles("SafetyEngineer")
def create_campaign():
    payload = v.body()
    campaign_number = v.req_str(payload, "campaign_number")
    if not v.CAMPAIGN_NUMBER_RE.match(campaign_number):
        v.bad("campaign_number must match the NHTSA pattern NNV-NNN.")
    defect_type = v.req_enum(payload, "defect_type", v.DEFECT_TYPES)
    defect_description = v.req_str(payload, "defect_description", min_len=1, max_len=2000)
    risk_severity = v.opt_enum(payload, "risk_severity", v.RISK_SEVERITIES, "MODERATE")
    supersedes_id = v.opt_str(payload, "supersedes_campaign_id")

    target = None
    if supersedes_id is not None:
        target = store.campaigns.get(supersedes_id)
        if target is None:
            raise ApiError("ERR_CAMPAIGN_NOT_FOUND")
        if target["campaign_status"] in ("DRAFT", "CLOSED", "SUPERSEDED"):
            raise ApiError("ERR_SUPERSEDED_CAMPAIGN_INVALID")

    for row in store.campaigns.values():
        if row["campaign_number"] == campaign_number:
            raise ApiError("ERR_DUPLICATE_CAMPAIGN_NUMBER")

    campaign = base_record()
    campaign.update({
        "campaign_number": campaign_number,
        "defect_type": defect_type,
        "defect_description": defect_description,
        "risk_severity": risk_severity,
        "campaign_status": "DRAFT",
        "remedy_status": "REMEDY_UNDER_DEVELOPMENT",
        "supersedes_campaign_id": supersedes_id,
        "defect_determination_date": None,
        "filing_deadline_utc": None,
        "filed_at": None,
        "days_late": 0,
        "late_filing_flag": False,
        "determined_by_user_id": None,
        "remedy_released_by_user_id": None,
        "remedy_released_at": None,
        "remedy_revision_count": 0,
        "stop_sale_flag": False,
        "do_not_drive_flag": False,
        "quarterly_filing_count": 0,
        "closure_note": None,
        # PRD 3.1 - a new file starts with remedy_effectiveness_score at 100.00.
        # PRD 3.9 - the score is recomputed on every repair-claim approval, on
        # every repair-claim reversal, and on every quarterly or amendment filing.
        "remedy_effectiveness_score": Decimal("100.00"),
    })
    store.campaigns[campaign["id"]] = campaign

    if target is not None:
        h.supersede_campaign(target)

    return single(h.campaign_out(campaign), 201)


@bp.get("/recall-campaigns")
@require_roles(*ALL_ROLES)
def list_campaigns():
    status = v.query_enum("campaign_status", v.CAMPAIGN_STATUSES)
    supersedes = request.args.get("supersedes_campaign_id")
    rows = list(store.campaigns.values())
    if status is not None:
        rows = [r for r in rows if r["campaign_status"] == status]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_campaign_id"] == supersedes]
    return collection(sorted_records(rows), h.campaign_out)


@bp.get("/recall-campaigns/<campaign_id>")
@require_roles(*ALL_ROLES)
def get_campaign(campaign_id):
    return single(h.campaign_out(h.get_campaign(campaign_id)))


@bp.post("/recall-campaigns/<campaign_id>/defect-determination")
@require_roles("SafetyEngineer")
def defect_determination(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    _, determined_at = v.req_instant_str(payload, "defect_determination_date")
    risk_severity = v.opt_enum(payload, "risk_severity", v.RISK_SEVERITIES)

    if campaign["campaign_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    campaign["defect_determination_date"] = fmt_instant(determined_at)
    if risk_severity is not None:
        campaign["risk_severity"] = risk_severity
    campaign["filing_deadline_utc"] = calc.fmt_deadline(
        calc.filing_deadline(determined_at))
    campaign["determined_by_user_id"] = g.user_id
    campaign["campaign_status"] = "DEFECT_DETERMINED"
    touch(campaign)
    return single(h.campaign_out(campaign))


@bp.post("/recall-campaigns/<campaign_id>/interim-advisory")
@require_roles("SafetyEngineer")
def interim_advisory(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    stop_sale = v.req_bool(payload, "stop_sale")
    do_not_drive = v.req_bool(payload, "do_not_drive")
    v.req_str(payload, "justification")

    if campaign["campaign_status"] != "FILED":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    if campaign["remedy_status"] != "REMEDY_UNDER_DEVELOPMENT":
        raise ApiError("ERR_REMEDY_ALREADY_AVAILABLE")

    campaign["campaign_status"] = "INTERIM_NOTIFIED"
    campaign["remedy_status"] = "INTERIM_ONLY"
    campaign["stop_sale_flag"] = stop_sale
    campaign["do_not_drive_flag"] = do_not_drive
    if stop_sale:
        for av in calc.campaign_avs(campaign["id"]):
            vehicle = store.vehicles.get(av["vehicle_id"])
            if vehicle is None or vehicle["sale_status"] != "IN_DEALER_STOCK":
                continue
            if not vehicle["stop_sale_hold"]:
                vehicle["stop_sale_hold"] = True
                touch(vehicle)
    touch(campaign)
    return single(h.campaign_out(campaign))


@bp.post("/recall-campaigns/<campaign_id>/remedy-releases")
@require_roles("SafetyEngineer")
def remedy_release(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    v.req_str(payload, "remedy_description")
    labor_operation_id = v.req_str(payload, "labor_operation_id")
    expected_version = v.req_int(payload, "expected_campaign_version")
    revision_reason = v.opt_str(payload, "revision_reason")
    if campaign["remedy_status"] == "REMEDY_REVISED" and revision_reason is None:
        v.bad("revision_reason is required when re-releasing a revised remedy.")

    labor_op = h.get_labor_op(labor_operation_id)

    remedy_status = campaign["remedy_status"]
    if campaign["campaign_status"] in h.TERMINAL_CAMPAIGN_STATES:
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    if remedy_status == "REMEDY_UNDER_DEVELOPMENT":
        allowed = ("DEFECT_DETERMINED", "FILED", "INTERIM_NOTIFIED",
                   "OWNER_NOTIFIED", "MONITORING")
        if campaign["campaign_status"] not in allowed:
            raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    elif remedy_status == "INTERIM_ONLY":
        allowed = ("INTERIM_NOTIFIED", "OWNER_NOTIFIED", "MONITORING")
        if campaign["campaign_status"] not in allowed:
            raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    if expected_version != campaign["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION")

    if remedy_status == "REMEDY_RELEASED":
        raise ApiError("ERR_REMEDY_ALREADY_AVAILABLE")

    if labor_op["campaign_id"] != campaign["id"]:
        raise ApiError("ERR_LABOR_OP_NOT_EFFECTIVE")

    campaign["remedy_status"] = "REMEDY_RELEASED"
    campaign["remedy_released_at"] = fmt_instant(clock_now())
    campaign["remedy_released_by_user_id"] = g.user_id
    campaign["stop_sale_flag"] = False
    for av in calc.campaign_avs(campaign["id"]):
        vehicle = store.vehicles.get(av["vehicle_id"])
        if vehicle is not None and vehicle["stop_sale_hold"]:
            vehicle["stop_sale_hold"] = False
            touch(vehicle)
    touch(campaign)
    return single(h.campaign_out(campaign))


@bp.post("/recall-campaigns/<campaign_id>/close")
@require_roles("ComplianceOfficer")
def close_campaign(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    closure_note = v.req_str(payload, "closure_note")

    if campaign["remedy_released_by_user_id"] is not None \
            and g.user_id == campaign["remedy_released_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if campaign["campaign_status"] != "MONITORING":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    completion = calc.regulatory_completion_rate(campaign["id"])
    score = campaign["remedy_effectiveness_score"]
    open_waves = [w for w in calc.campaign_waves(campaign["id"])
                  if w["status"] in ("PLANNED", "RELEASE_APPROVED")]
    if (campaign["remedy_status"] != "REMEDY_RELEASED"
            or completion < calc.CLOSURE_COMPLETION_MIN
            or score < calc.REMEDY_EFFECTIVENESS_MIN
            or campaign["quarterly_filing_count"] < calc.CLOSURE_QUARTERLY_FILINGS_MIN
            or open_waves):
        raise ApiError("ERR_CLOSURE_CRITERIA_NOT_MET")

    campaign["campaign_status"] = "CLOSED"
    campaign["closure_note"] = closure_note
    touch(campaign)
    return single(h.campaign_out(campaign))


@bp.get("/recall-campaigns/<campaign_id>/completion-metrics")
@require_roles(*ALL_ROLES)
def completion_metrics(campaign_id):
    campaign = h.get_campaign(campaign_id)
    buckets = calc.population_buckets(campaign["id"])
    data = {
        "regulatory_completion_rate_pct": calc.num(
            calc.regulatory_completion_rate(campaign["id"], buckets)),
        "operational_completion_rate_pct": calc.num(
            calc.operational_completion_rate(campaign["id"], buckets)),
        "remedied_count": buckets["remedied"],
        "scheduled_count": buckets["scheduled"],
        "unreachable_count": buckets["unreachable"],
        "removed_count": buckets["removed"],
        "recall_population_count": buckets["recall_population"],
        "affected_vehicle_count": buckets["total"],
        "remedy_effectiveness_score": calc.num(
            campaign["remedy_effectiveness_score"]),
        "repeat_claim_count": calc.repeat_claim_count(campaign["id"]),
    }
    return single(data)
