"""CarbonCredit endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import api_error
from ..response import success_envelope
from ..services.calculations import recompute_open_reports_for_period
from ..store import store, now_ts
from ..utils import (
    check_version,
    decimal_places,
    get_json_body,
    parse_iso_datetime,
    require_enum,
    require_int,
    require_str,
    to_decimal,
)
from ._helpers import get_credit_or_404, get_org_or_404


credits_bp = Blueprint("credits", __name__)


REGISTRIES = {"VCS", "GOLD_STANDARD", "CCER"}


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


@credits_bp.route("/organizations/<org_id>/credits", methods=["POST"])
@require_auth(["Discloser"])
def create_credit(org_id):
    get_org_or_404(org_id)
    body = get_json_body()
    registry = require_enum(body, "registry", REGISTRIES)
    serial_number = require_str(body, "serial_number", min_len=1, max_len=100)
    vintage_year = require_int(body, "vintage_year")
    quantity = to_decimal(body.get("quantity_kg_co2e"), "quantity_kg_co2e")
    if quantity <= 0:
        raise api_error("ERR_VALIDATION_FAILED", "quantity_kg_co2e must be > 0")
    if decimal_places(quantity) > 4:
        raise api_error("ERR_VALIDATION_FAILED", "quantity_kg_co2e must have at most 4 decimal places")

    project_id = body.get("linked_reduction_project_id")
    if not isinstance(project_id, str) or not project_id:
        raise api_error("ERR_VALIDATION_FAILED", "linked_reduction_project_id is required")
    project = store.reduction_projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "linked_reduction_project_id not found")
    if project.get("organization_id") != org_id:
        raise api_error("ERR_CROSS_ORG_REFERENCE", "linked_reduction_project_id belongs to a different organization")
    if project.get("project_type") != "EXTERNAL_OFFSET":
        raise api_error("ERR_VALIDATION_FAILED", "Linked project must be EXTERNAL_OFFSET")

    period_id = body.get("reporting_period_id")
    if not isinstance(period_id, str) or not period_id:
        raise api_error("ERR_VALIDATION_FAILED", "reporting_period_id is required")
    period = store.reporting_periods.get(period_id)
    if not period:
        raise api_error("ERR_NOT_FOUND", "reporting_period_id not found")
    if period.get("organization_id") != org_id:
        raise api_error("ERR_CROSS_ORG_REFERENCE", "reporting_period_id belongs to a different organization")

    # Vintage year bound
    end_dt = parse_iso_datetime(period["end_date"])
    year_end = end_dt.year
    if vintage_year < 1990 or vintage_year > year_end:
        raise api_error("ERR_CREDIT_DOUBLE_COUNTED", "vintage_year out of allowed range")

    # Global uniqueness on serial_number
    if serial_number in store.credit_serials:
        raise api_error("ERR_CREDIT_DOUBLE_COUNTED", "serial_number already recorded")

    payload = {
        "organization_id": org_id,
        "registry": registry,
        "serial_number": serial_number,
        "vintage_year": vintage_year,
        "quantity_kg_co2e": float(quantity),
        "linked_reduction_project_id": project_id,
        "reporting_period_id": period_id,
        "retired_at": None,
        "retirement_certificate_url": None,
        "status": "PURCHASED",
    }
    with store.lock:
        # Re-check serial under lock
        if serial_number in store.credit_serials:
            raise api_error("ERR_CREDIT_DOUBLE_COUNTED", "serial_number already recorded")
        store.stamp_create(payload)
        store.carbon_credits[payload["id"]] = payload
        store.credit_serials[serial_number] = payload["id"]
    return success_envelope(payload, status=201)


@credits_bp.route("/organizations/<org_id>/credits/<credit_id>/retire", methods=["POST"])
@require_auth(["Discloser"])
def retire_credit(org_id, credit_id):
    get_org_or_404(org_id)
    credit = get_credit_or_404(org_id, credit_id)
    body = get_json_body()

    if credit.get("status") != "PURCHASED":
        raise api_error("ERR_INVALID_STATE", "Credit must be PURCHASED to retire")
    check_version(body, credit)

    cert_url = require_str(body, "retirement_certificate_url", min_len=1, max_len=500)

    project = store.reduction_projects.get(credit["linked_reduction_project_id"])
    if not project or project.get("status") != "ACTIVE":
        raise api_error("ERR_INVALID_STATE", "Linked project must be ACTIVE")

    period = store.reporting_periods.get(credit["reporting_period_id"])
    if not period:
        raise api_error("ERR_NOT_FOUND", "Linked period missing")
    end_dt = parse_iso_datetime(period["end_date"])
    if credit["vintage_year"] > end_dt.year:
        raise api_error("ERR_INVALID_STATE", "vintage_year exceeds period end year")

    actor_user_id = g.user_id
    actor_role = g.user_role

    with store.lock:
        if credit.get("status") != "PURCHASED":
            raise api_error("ERR_INVALID_STATE", "Credit no longer PURCHASED")
        credit["status"] = "RETIRED"
        credit["retired_at"] = now_ts()
        credit["retirement_certificate_url"] = cert_url
        _bump(credit)
        recompute_open_reports_for_period(credit["reporting_period_id"])
        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="CREDIT_RETIRE",
            target_entity="CarbonCredit",
            target_id=credit["id"],
            payload_json={"serial_number": credit["serial_number"]},
        )
    return success_envelope(credit)


@credits_bp.route("/organizations/<org_id>/credits/<credit_id>/transfer", methods=["POST"])
@require_auth(["Discloser"])
def transfer_credit(org_id, credit_id):
    get_org_or_404(org_id)
    credit = get_credit_or_404(org_id, credit_id)
    body = get_json_body()

    if credit.get("status") != "PURCHASED":
        raise api_error("ERR_INVALID_STATE", "Credit must be PURCHASED to transfer")
    check_version(body, credit)
    period = store.reporting_periods.get(credit["reporting_period_id"])
    if not period or period.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Parent reporting period must be OPEN")

    with store.lock:
        credit["status"] = "TRANSFERRED"
        _bump(credit)
    return success_envelope(credit)
