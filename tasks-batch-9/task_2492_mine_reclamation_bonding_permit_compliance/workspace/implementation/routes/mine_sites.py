"""Mine sites, the abandoned legacy inventory and its funding queue (PRD 3.8)."""

from flask import Blueprint

import calculations as calc
import constants as C
import serialization as ser
from db import D, ZERO, base_row, db, money, money_floor0
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import apply_filters, collection_filtered, paged, paged_ordered
from validation import (
    authorize,
    enum_field,
    get_body,
    int_field,
    lookup,
    number_field,
    str_field,
)

bp = Blueprint("mine_sites", __name__)

LIST_FILTERS = [
    ("site_class", "site_class", C.SITE_CLASSES),
    ("funding_status", "funding_status", C.FUNDING_STATUSES),
    ("county", "county", None),
    ("hazard_class", "hazard_class", C.HAZARD_CLASSES),
]


@bp.post("/mining/mine-sites")
def create_mine_site():
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    name = str_field(body, "name")
    county = str_field(body, "county")
    total_acres = number_field(body, "total_acres", gt=0)
    site_class = enum_field(
        body, "site_class", C.SITE_CLASSES, required=False, default="ACTIVE_PERMITTED"
    )

    row = base_row()
    row.update(
        {
            "name": name,
            "county": county,
            "total_acres": total_acres,
            "site_class": site_class,
            "hazard_class": "H3_MODERATE",
            "public_safety_score": 0,
            "water_quality_score": 0,
            "acres_affected": ZERO,
            "legacy_priority_score": ZERO,
            "funding_status": "NOT_APPLICABLE",
            "awarded_funding_amount": ZERO,
            "unfunded_reclamation_need": ZERO,
        }
    )
    db.mine_sites[row["id"]] = row
    return created_response(ser.mine_site_out(row))


@bp.get("/mining/mine-sites/<site_id>")
def get_mine_site(site_id):
    authorize(C.ALL_ROLES)
    row = lookup(db.mine_sites, site_id, "ERR_MINE_SITE_NOT_FOUND")
    return object_response(ser.mine_site_out(row))


@bp.get("/mining/mine-sites")
def list_mine_sites():
    authorize(C.ALL_ROLES)
    return collection_filtered(db.mine_sites.values(), LIST_FILTERS, ser.mine_site_out)


@bp.post("/mining/mine-sites/<site_id>/nominate-legacy")
def nominate_legacy(site_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    hazard_class = enum_field(body, "hazard_class", C.HAZARD_CLASSES)
    public_safety_score = int_field(body, "public_safety_score", ge=0, le=100)
    water_quality_score = int_field(body, "water_quality_score", ge=0, le=100)
    acres_affected = number_field(body, "acres_affected", ge=0)
    unfunded = number_field(body, "unfunded_reclamation_need", ge=0)

    row = lookup(db.mine_sites, site_id, "ERR_MINE_SITE_NOT_FOUND")
    if row["funding_status"] != "NOT_APPLICABLE" or row["site_class"] != "ABANDONED_LEGACY":
        raise ApiError(
            "ERR_SITE_FUNDING_STATE_INVALID",
            "Only an abandoned legacy site with funding_status NOT_APPLICABLE may be nominated.",
        )

    row["hazard_class"] = hazard_class
    row["public_safety_score"] = public_safety_score
    row["water_quality_score"] = water_quality_score
    row["acres_affected"] = acres_affected
    row["unfunded_reclamation_need"] = unfunded
    row["funding_status"] = "NOMINATED"
    row["legacy_priority_score"] = calc.legacy_priority_score(row)
    bump(row)
    return object_response(ser.mine_site_out(row))


@bp.post("/mining/mine-sites/<site_id>/award-legacy-funding")
def award_legacy_funding(site_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    award_amount = number_field(body, "award_amount", ge=0)

    row = lookup(db.mine_sites, site_id, "ERR_MINE_SITE_NOT_FOUND")

    # Band 9 — own funding state.
    if row["funding_status"] != "NOMINATED":
        raise ApiError(
            "ERR_SITE_FUNDING_STATE_INVALID",
            "Only a NOMINATED site may be awarded legacy funding.",
        )

    # Band 14 — the award may only go to the current head of the queue.
    queue = calc.funding_queue()
    if not queue or queue[0]["id"] != row["id"]:
        raise ApiError(
            "ERR_FUNDING_QUEUE_ORDER",
            "Legacy funding may only be awarded to the current head of the funding queue.",
        )

    # Band 15 — the annual appropriation ceiling.
    projected = money(calc.total_awarded_funding() + D(award_amount))
    if projected > C.LEGACY_FUND_ANNUAL_CAP:
        raise ApiError(
            "ERR_LEGACY_FUND_CAP_EXCEEDED",
            "The award would carry total legacy funding beyond the annual cap.",
        )

    row["awarded_funding_amount"] = money(award_amount)
    row["unfunded_reclamation_need"] = money_floor0(
        D(row["unfunded_reclamation_need"]) - D(award_amount)
    )
    row["funding_status"] = "FUNDED"
    bump(row)
    return object_response(ser.mine_site_out(row))


@bp.get("/mining/mine-sites/<site_id>/permits")
def site_permits(site_id):
    authorize(C.ROLES_OP_STAFF_PUBLIC)
    lookup(db.mine_sites, site_id, "ERR_MINE_SITE_NOT_FOUND")
    rows = [p for p in db.permits.values() if p["mine_site_id"] == site_id]
    rows = apply_filters(rows, [("status", "status", C.PERMIT_STATUSES)])
    return paged(rows, ser.permit_out)


@bp.get("/mining/legacy-funding-queue")
def legacy_funding_queue():
    authorize(C.ROLES_QUEUE_READ)
    return paged_ordered(calc.funding_queue(), ser.mine_site_out)
