"""ActivityData entry + cascade to EmissionRecord."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from ..auth import require_auth
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..services.calculations import DQ_SCORES, GWP_TABLE, compute_kg_co2e
from ..store import store, now_ts
from ..utils import (
    decimal_places,
    get_json_body,
    page_slice,
    parse_iso_datetime,
    parse_pagination,
    require_enum,
    require_str,
    to_decimal,
)
from ._helpers import get_org_or_404, get_period_or_404


activity_data_bp = Blueprint("activity_data", __name__)


DATA_SOURCES = {"METER_READING", "INVOICE", "SUPPLIER_DATA", "ESTIMATION"}


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


@activity_data_bp.route(
    "/organizations/<org_id>/reporting-periods/<period_id>/activity-data",
    methods=["POST"],
)
@require_auth(["DataSteward"])
def post_activity_data(org_id, period_id):
    get_org_or_404(org_id)
    period = get_period_or_404(org_id, period_id)

    if period.get("status") != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Reporting period must be OPEN to enter activity data")

    body = get_json_body()
    emission_source_id = body.get("emission_source_id")
    if not isinstance(emission_source_id, str) or not emission_source_id:
        raise api_error("ERR_VALIDATION_FAILED", "emission_source_id is required")
    src = store.emission_sources.get(emission_source_id)
    if not src:
        raise api_error("ERR_NOT_FOUND", "emission_source_id not found")
    if src.get("organization_id") != org_id:
        raise api_error("ERR_CROSS_ORG_REFERENCE", "emission_source_id belongs to a different organization")

    data_source = require_enum(body, "data_source", DATA_SOURCES)
    quantity = to_decimal(body.get("quantity"), "quantity")
    if quantity < 0:
        raise api_error("ERR_VALIDATION_FAILED", "quantity must be >= 0")
    if decimal_places(quantity) > 4:
        raise api_error("ERR_VALIDATION_FAILED", "quantity must have at most 4 decimal places")
    unit = require_str(body, "unit", min_len=1, max_len=20)
    activity_start = parse_iso_datetime(body.get("activity_start"))
    activity_end = parse_iso_datetime(body.get("activity_end"))

    period_start = parse_iso_datetime(period["start_date"])
    period_end = parse_iso_datetime(period["end_date"])

    estimation_basis = body.get("estimation_basis")
    # Estimation basis rule (priority 13)
    if data_source == "ESTIMATION":
        if not isinstance(estimation_basis, str) or not (5 <= len(estimation_basis) <= 500):
            raise api_error(
                "ERR_ESTIMATION_BASIS_REQUIRED",
                "estimation_basis required and 5..500 chars for ESTIMATION",
            )
    else:
        if estimation_basis is not None:
            raise api_error(
                "ERR_ESTIMATION_BASIS_REQUIRED",
                "estimation_basis must be null when data_source != ESTIMATION",
            )

    # Boundary check (priority 14)
    facility = store.facilities.get(src.get("facility_id"))
    if not facility or not facility.get("included_in_boundary") or facility.get("status") != "ACTIVE" or src.get("status") != "ACTIVE":
        raise api_error("ERR_FACILITY_OUT_OF_BOUNDARY", "Facility/Source not in boundary or not ACTIVE")

    # Temporal window (priority 9)
    if not (activity_end > activity_start):
        raise api_error("ERR_ACTIVITY_OUTSIDE_PERIOD", "activity_end must be > activity_start")
    if not (period_start <= activity_start and activity_end <= period_end):
        raise api_error("ERR_ACTIVITY_OUTSIDE_PERIOD", "activity window must lie inside the reporting period")

    # Overlap check (priority 10): half-open [activity_start, activity_end) per source
    for ad in store.activity_data.values():
        if ad.get("emission_source_id") != emission_source_id:
            continue
        if ad.get("status") != "RECORDED":
            continue
        a_s = parse_iso_datetime(ad["activity_start"])
        a_e = parse_iso_datetime(ad["activity_end"])
        if activity_start < a_e and a_s < activity_end:
            raise api_error("ERR_ACTIVITY_INTERVAL_OVERLAP", "Activity intervals overlap on this source")

    # Pin factor (priority 12)
    factor_code = src["factor_code"]
    candidates = [
        ef for ef in store.emission_factors.values()
        if ef.get("organization_id") == org_id
        and ef.get("code") == factor_code
        and ef.get("status") == "ACTIVE"
    ]
    pinned = None
    for ef in candidates:
        eff_from = parse_iso_datetime(ef["effective_from"])
        eff_to = ef.get("effective_to")
        if eff_from <= activity_start and (eff_to is None or parse_iso_datetime(eff_to) > activity_start):
            pinned = ef
            break
    if not pinned:
        raise api_error("ERR_NO_APPLICABLE_FACTOR", "No ACTIVE factor applies to this activity window")

    # All good — create rows in a single transaction
    actor_user_id = g.user_id
    actor_role = g.user_role
    gas_type = src["gas_type"]
    kg_per_unit = Decimal(str(pinned["kg_per_unit"]))
    kg_co2e = compute_kg_co2e(quantity, kg_per_unit, gas_type)

    scope_value = src.get("scope")
    scope2_method = pinned.get("scope2_method") if scope_value == "SCOPE_2" else None

    ad_payload = {
        "reporting_period_id": period_id,
        "emission_source_id": emission_source_id,
        "data_source": data_source,
        "quantity": float(quantity),
        "unit": unit,
        "activity_start": body.get("activity_start"),
        "activity_end": body.get("activity_end"),
        "data_quality_score": float(DQ_SCORES[data_source]),
        "estimation_basis": estimation_basis,
        "entered_by_user_id": actor_user_id,
        "status": "RECORDED",
    }

    with store.lock:
        store.stamp_create(ad_payload)
        store.activity_data[ad_payload["id"]] = ad_payload

        er_payload = {
            "reporting_period_id": period_id,
            "activity_data_id": ad_payload["id"],
            "emission_factor_id": pinned["id"],
            "gas_type": gas_type,
            "gwp_factor": float(GWP_TABLE[gas_type]),
            "kg_co2e": float(kg_co2e),
            "scope2_method": scope2_method,
            "status": "FRESH",
        }
        store.stamp_create(er_payload)
        store.emission_records[er_payload["id"]] = er_payload

        store.append_audit(
            organization_id=org_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            event_type="ACTIVITY_ENTRY",
            target_entity="ActivityData",
            target_id=ad_payload["id"],
            payload_json={"emission_source_id": emission_source_id, "quantity": float(quantity)},
        )

    return success_envelope(ad_payload, status=201)


@activity_data_bp.route(
    "/organizations/<org_id>/reporting-periods/<period_id>/activity-data", methods=["GET"]
)
@require_auth(["DataSteward", "Verifier"])
def list_activity_data(org_id, period_id):
    get_org_or_404(org_id)
    get_period_or_404(org_id, period_id)
    limit, offset = parse_pagination()
    src_f = request.args.get("emission_source_id")
    ds_f = request.args.get("data_source")
    status_f = request.args.get("status")
    items = [
        ad for ad in store.activity_data.values()
        if ad.get("reporting_period_id") == period_id
        and (src_f is None or ad.get("emission_source_id") == src_f)
        and (ds_f is None or ad.get("data_source") == ds_f)
        and (status_f is None or ad.get("status") == status_f)
    ]
    items.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
