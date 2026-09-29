"""Service network partners and parts distribution (PRD 3.8)."""

from flask import Blueprint

import calc
from auth import get_partner, require
from constants import CATEGORIES, REGIONS
from envelope import created, ok
from errors import ApiError
from store import new_entity, mutate, store
from validation import (
    field_datetime,
    field_decimal,
    field_enum,
    field_enum_array,
    field_int,
    field_str,
    get_body,
)

bp = Blueprint("partners", __name__)


@bp.post("/service-partners")
@require("ServiceOpsAdmin")
def create_service_partner():
    body = get_body()
    name = field_str(body, "name", min_len=1, max_len=120)
    region = field_enum(body, "region", REGIONS)
    certified_categories = field_enum_array(
        body, "certified_categories", CATEGORIES, non_empty=True
    )
    certified_technician_count = field_int(
        body, "certified_technician_count", minimum=1
    )
    certified_hours_capacity = field_decimal(
        body, "certified_hours_capacity", exclusive_min=0
    )
    training_current_until, _ = field_datetime(body, "training_current_until")

    # rung 24 — globally unique partner name
    for row in store.service_partners.values():
        if row["name"] == name:
            raise ApiError(
                "ERR_DUPLICATE_REVISION_CODE", "A service partner name must be unique."
            )

    partner = new_entity(
        {
            "name": name,
            "region": region,
            "certified_categories": certified_categories,
            "certified_technician_count": certified_technician_count,
            "certified_hours_capacity": certified_hours_capacity,
            "training_current_until": training_current_until,
            "committed_hours": 0,
            "coverage_status": "ACTIVE",
            "spare_stock_received_units": 0,
            "spare_stock_on_hand_units": 0,
            "spare_stock_reserved_units": 0,
            "spare_stock_consumed_units": 0,
        }
    )
    store.service_partners[partner["id"]] = partner
    return created(partner)


@bp.get("/service-partners/<partner_id>")
@require(
    "ProductEngineer",
    "ComplianceOfficer",
    "OrderPlanner",
    "FacilityManager",
    "ServicePartnerTech",
    "ServiceOpsAdmin",
)
def read_service_partner(partner_id):
    return ok(get_partner(partner_id))


@bp.post("/service-partners/<partner_id>/parts-receipt")
@require("ServiceOpsAdmin")
def parts_receipt(partner_id):
    partner = get_partner(partner_id)
    body = get_body()
    units = field_int(body, "units", minimum=1)

    with mutate(partner):
        partner["spare_stock_received_units"] += units
    calc.recompute_partner(partner)
    return ok(partner)
