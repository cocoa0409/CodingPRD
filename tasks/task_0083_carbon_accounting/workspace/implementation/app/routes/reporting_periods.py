"""ReportingPeriod endpoints."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import store, now_ts
from ..utils import (
    check_version,
    decimal_places,
    get_json_body,
    parse_iso_datetime,
    require_int,
    require_str,
    to_decimal,
)
from ._helpers import get_org_or_404, get_period_or_404


reporting_periods_bp = Blueprint("reporting_periods", __name__)


def _validate_revenue(val) -> Decimal:
    d = to_decimal(val, "revenue", err="ERR_DENOMINATOR_INVALID")
    if d < 0:
        raise api_error("ERR_DENOMINATOR_INVALID", "revenue must be >= 0")
    if decimal_places(d) > 2:
        raise api_error("ERR_DENOMINATOR_INVALID", "revenue must have at most 2 decimal places")
    return d


def _validate_headcount(val) -> int:
    if not isinstance(val, int) or isinstance(val, bool):
        raise api_error("ERR_DENOMINATOR_INVALID", "headcount must be an integer")
    if val < 0:
        raise api_error("ERR_DENOMINATOR_INVALID", "headcount must be >= 0")
    return val


def _validate_unit_output(val) -> Decimal:
    d = to_decimal(val, "unit_output", err="ERR_DENOMINATOR_INVALID")
    if d < 0:
        raise api_error("ERR_DENOMINATOR_INVALID", "unit_output must be >= 0")
    if decimal_places(d) > 4:
        raise api_error("ERR_DENOMINATOR_INVALID", "unit_output must have at most 4 decimal places")
    return d


def _intervals_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open [start, end) overlap check."""
    return a_start < b_end and b_start < a_end


def _check_period_overlap(org_id: str, start: datetime, end: datetime, exclude_id: str | None = None):
    for p in store.reporting_periods.values():
        if p.get("organization_id") != org_id:
            continue
        if exclude_id is not None and p["id"] == exclude_id:
            continue
        if p.get("status") == "CANCELLED":
            continue
        ps = parse_iso_datetime(p["start_date"])
        pe = parse_iso_datetime(p["end_date"])
        if _intervals_overlap(start, end, ps, pe):
            raise api_error("ERR_PERIOD_OVERLAP", "Reporting period overlaps an existing period")


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


@reporting_periods_bp.route("/organizations/<org_id>/reporting-periods", methods=["POST"])
@require_auth(["DataSteward", "PlatformAdmin"])
def create_reporting_period(org_id):
    get_org_or_404(org_id)
    body = get_json_body()
    label = require_str(body, "label", min_len=1, max_len=50)
    start = parse_iso_datetime(body.get("start_date"))
    end = parse_iso_datetime(body.get("end_date"))
    if not (end > start):
        raise api_error("ERR_VALIDATION_FAILED", "end_date must be strictly greater than start_date")
    revenue = _validate_revenue(body.get("revenue"))
    headcount = _validate_headcount(body.get("headcount"))
    unit_output = _validate_unit_output(body.get("unit_output"))

    # Label unique
    for p in store.reporting_periods.values():
        if p.get("organization_id") == org_id and p.get("label") == label:
            raise api_error("ERR_VALIDATION_FAILED", "label must be unique within organization")

    _check_period_overlap(org_id, start, end)

    payload = {
        "organization_id": org_id,
        "label": label,
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "revenue": float(revenue),
        "headcount": headcount,
        "unit_output": float(unit_output),
        "status": "OPEN",
    }
    with store.lock:
        store.stamp_create(payload)
        store.reporting_periods[payload["id"]] = payload
    return success_envelope(payload, status=201)


@reporting_periods_bp.route("/organizations/<org_id>/reporting-periods/<period_id>", methods=["PATCH"])
@require_auth(["DataSteward", "PlatformAdmin"])
def update_reporting_period(org_id, period_id):
    get_org_or_404(org_id)
    period = get_period_or_404(org_id, period_id)
    body = get_json_body()
    check_version(body, period)

    if period.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Only OPEN periods can be patched")

    if "revenue" in body:
        period["revenue"] = float(_validate_revenue(body["revenue"]))
    if "headcount" in body:
        period["headcount"] = _validate_headcount(body["headcount"])
    if "unit_output" in body:
        period["unit_output"] = float(_validate_unit_output(body["unit_output"]))

    with store.lock:
        _bump(period)
    return success_envelope(period)


@reporting_periods_bp.route(
    "/organizations/<org_id>/reporting-periods/<period_id>/close", methods=["POST"]
)
@require_auth(["DataSteward", "PlatformAdmin"])
def close_reporting_period(org_id, period_id):
    get_org_or_404(org_id)
    period = get_period_or_404(org_id, period_id)
    body = get_json_body()

    if period.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Period must be OPEN")

    check_version(body, period)

    # Server clock must be >= end_date
    end_dt = parse_iso_datetime(period["end_date"])
    if clock.now() < end_dt:
        raise api_error("ERR_INVALID_STATE", "Server clock has not yet reached end_date")

    actor_user_id = g.user_id
    actor_role = g.user_role

    with store.lock:
        period["status"] = "CLOSED"
        _bump(period)

        # Mass-archive ActivityData
        for ad in store.activity_data.values():
            if ad.get("reporting_period_id") == period_id and ad.get("status") == "RECORDED":
                ad["status"] = "ARCHIVED"
                _bump(ad)
        # Mass-archive EmissionRecord
        for er in store.emission_records.values():
            if er.get("reporting_period_id") == period_id and er.get("status") in ("FRESH", "STALE"):
                er["status"] = "ARCHIVED"
                _bump(er)
        # Auto-transition reports
        for rep in store.reports.values():
            if rep.get("reporting_period_id") == period_id and rep.get("status") in ("DRAFT", "UNDER_REVIEW"):
                rep["status"] = "REVISIONS_REQUIRED"
                _bump(rep)

        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="ACTIVITY_ARCHIVE",
            target_entity="ReportingPeriod",
            target_id=period_id,
            payload_json={"label": period.get("label")},
        )

    return success_envelope(period)


@reporting_periods_bp.route(
    "/organizations/<org_id>/reporting-periods/<period_id>/cancel", methods=["POST"]
)
@require_auth(["PlatformAdmin"])
def cancel_reporting_period(org_id, period_id):
    get_org_or_404(org_id)
    period = get_period_or_404(org_id, period_id)
    body = get_json_body()

    if period.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Only OPEN periods can be cancelled")
    check_version(body, period)

    # No PUBLISHED report may reference the period
    for r in store.reports.values():
        if r.get("reporting_period_id") == period_id and r.get("status") == "PUBLISHED":
            raise api_error("ERR_INVALID_STATE", "A PUBLISHED report references this period")

    with store.lock:
        period["status"] = "CANCELLED"
        _bump(period)
        # Mass-archive AD + ER
        for ad in store.activity_data.values():
            if ad.get("reporting_period_id") == period_id and ad.get("status") == "RECORDED":
                ad["status"] = "ARCHIVED"
                _bump(ad)
        for er in store.emission_records.values():
            if er.get("reporting_period_id") == period_id and er.get("status") in ("FRESH", "STALE"):
                er["status"] = "ARCHIVED"
                _bump(er)
    return success_envelope(period)
