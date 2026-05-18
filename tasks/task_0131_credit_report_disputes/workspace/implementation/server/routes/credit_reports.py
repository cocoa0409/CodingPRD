"""CreditReport routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import enforce_consumer_ownership, require_auth
from ..calculations import (
    NON_TERMINAL_DISPUTE_STATUSES,
    compute_fico,
    compute_projected_fico,
)
from ..clock import clock
from ..errors import ApiError
from ..responses import json_object
from ..store import stamp_create, stamp_update, store
from ..utils import check_occ, parse_json_body, require_field


bp_credit_reports = Blueprint("credit_reports", __name__)

VALID_BUREAUS = {"EQUIFAX", "EXPERIAN", "TRANSUNION"}


def _ensure_consumer_exists(consumer_id: str) -> dict:
    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        raise ApiError("ERR_NOT_FOUND", "Consumer not found.", 404)
    return consumer


def _ensure_credit_report(consumer_id: str, credit_report_id: str) -> dict:
    _ensure_consumer_exists(consumer_id)
    report = store.credit_reports.get(credit_report_id)
    if report is None or report["consumer_id"] != consumer_id:
        raise ApiError("ERR_NOT_FOUND", "CreditReport not found.", 404)
    return report


@bp_credit_reports.route("/consumers/<consumer_id>/credit_reports", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_credit_report(consumer_id: str):
    _ensure_consumer_exists(consumer_id)
    body = parse_json_body()
    bureau = require_field(body, "bureau", types=[str])
    if bureau not in VALID_BUREAUS:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            f"bureau must be one of {sorted(VALID_BUREAUS)}.",
            400,
        )
    with store.lock:
        report = stamp_create(
            {
                "consumer_id": consumer_id,
                "bureau": bureau,
                "fico_score": 300,
                "posture": "OPEN",
                "last_pulled_day": None,
                "status": "ACTIVE",
            }
        )
        store.credit_reports[report["id"]] = report
    return json_object(report, 201)


@bp_credit_reports.route(
    "/consumers/<consumer_id>/credit_reports/<credit_report_id>", methods=["GET"]
)
@require_auth(["Consumer", "PlatformAdmin"])
def get_credit_report(consumer_id: str, credit_report_id: str):
    enforce_consumer_ownership(consumer_id)
    report = _ensure_credit_report(consumer_id, credit_report_id)
    return json_object(report, 200)


@bp_credit_reports.route(
    "/consumers/<consumer_id>/credit_reports/<credit_report_id>/projected_fico",
    methods=["GET"],
)
@require_auth(["Consumer"])
def get_projected_fico(consumer_id: str, credit_report_id: str):
    enforce_consumer_ownership(consumer_id)
    report = _ensure_credit_report(consumer_id, credit_report_id)
    # If no non-terminal dispute exists, the projection equals the current score.
    has_active = any(
        d["credit_report_id"] == credit_report_id
        and d["status"] in NON_TERMINAL_DISPUTE_STATUSES
        for d in store.disputes.values()
    )
    if has_active:
        projected = compute_projected_fico(credit_report_id)
    else:
        projected = compute_fico(credit_report_id)
    # PRD §3.5: the projected-FICO endpoint returns the provisional FICO.
    # The CreditReport entity field is `fico_score` (PRD §3.1); we surface
    # the projected value under the same field name.
    return json_object(
        {
            "credit_report_id": credit_report_id,
            "fico_score": projected,
            "projected_fico_score": projected,
            "current_fico_score": report["fico_score"],
        },
        200,
    )


@bp_credit_reports.route(
    "/consumers/<consumer_id>/credit_reports/<credit_report_id>/pull_free",
    methods=["POST"],
)
@require_auth(["Consumer"])
def pull_free_report(consumer_id: str, credit_report_id: str):
    enforce_consumer_ownership(consumer_id)
    report = _ensure_credit_report(consumer_id, credit_report_id)
    body = parse_json_body()
    with store.lock:
        check_occ(report, body)
        consumer = store.consumers[consumer_id]
        if consumer["free_reports_remaining"] <= 0:
            raise ApiError(
                "ERR_NO_FREE_REPORTS_REMAINING",
                "No free reports remaining.",
                409,
            )
        consumer["free_reports_remaining"] -= 1
        stamp_update(consumer)
        report["last_pulled_day"] = clock.day
        stamp_update(report)
    return json_object(report, 200)


@bp_credit_reports.route(
    "/consumers/<consumer_id>/credit_reports/<credit_report_id>/archive",
    methods=["POST"],
)
@require_auth(["PlatformAdmin"])
def archive_credit_report(consumer_id: str, credit_report_id: str):
    report = _ensure_credit_report(consumer_id, credit_report_id)
    body = parse_json_body()
    with store.lock:
        check_occ(report, body)
        if report["status"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Only ACTIVE reports may be archived.",
                409,
            )
        open_disputes = [
            d
            for d in store.disputes.values()
            if d["credit_report_id"] == credit_report_id
            and d["status"] in NON_TERMINAL_DISPUTE_STATUSES
        ]
        if open_disputes:
            raise ApiError(
                "ERR_REPORT_HAS_OPEN_DISPUTES",
                "Cannot archive a report with open disputes.",
                409,
            )
        report["status"] = "ARCHIVED"
        stamp_update(report)
    return json_object(report, 200)
