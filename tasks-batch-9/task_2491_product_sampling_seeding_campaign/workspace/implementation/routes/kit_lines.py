"""Kit line composition, inventory receipts, write-offs and retirement."""

from decimal import Decimal

from flask import Blueprint

import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from response import collection, single
from services import calculations as calc
from services.gates import must_exist
from validation import field, invalid, paginate, parse_body, parse_query

bp = Blueprint("kit_lines", __name__)

COMPONENT_ROLES = ("HERO_PRODUCT", "ACCESSORY", "INSERT_CARD", "DISCLOSURE_INSERT")
KIT_LINE_STATUSES = ("ACTIVE", "RETIRED")

CREATE_FIELDS = [
    field("campaign_id", "id", required=True),
    field("component_sku", "string", required=True),
    field("component_role", "enum", required=True, values=COMPONENT_ROLES),
    field("unit_cost_cents", "integer", required=True, minimum=0),
    field("quantity_per_kit", "integer", required=True, minimum=1),
    field("component_discount_pct", "number", default=Decimal(0),
          minimum=0, exclusive_maximum=1, max_decimals=4),
]

RECEIPT_FIELDS = [field("units", "integer", required=True, minimum=1)]

WRITE_OFF_FIELDS = [
    field("units", "integer", required=True, minimum=1),
    field("reason", "string", required=True),
]

LIST_FILTERS = [
    field("campaign_id", "string"),
    field("status", "enum", values=KIT_LINE_STATUSES),
]


@bp.post("/kit-lines")
@endpoint(["CampaignManager"])
def create_kit_line():
    body, _ = parse_body(CREATE_FIELDS)
    campaign = must_exist("campaigns", body["campaign_id"], "Campaign")
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CAMPAIGN_TRANSITION",
                       "Kit lines may only be added while the campaign is DRAFT")
    for existing in store.campaign_kit_lines(campaign["id"]):
        if existing["component_sku"] == body["component_sku"]:
            raise invalid("component_sku '%s' is already used by this campaign"
                          % body["component_sku"])

    row = new_row()
    row.update({
        "campaign_id": campaign["id"],
        "component_sku": body["component_sku"],
        "component_role": body["component_role"],
        "unit_cost_cents": body["unit_cost_cents"],
        "quantity_per_kit": body["quantity_per_kit"],
        "component_discount_pct": body["component_discount_pct"],
        "status": "ACTIVE",
        "units_received": 0,
        "units_available": 0,
        "units_reserved": 0,
        "units_shipped": 0,
        "units_written_off": 0,
    })
    row["extended_cost_cents"] = calc.extended_cost_cents(row)
    db.kit_lines[row["id"]] = row

    calc.refresh_kit_assembly_unit_cost(campaign)
    touch(campaign)
    return single(serializers.kit_line(row), 201)


@bp.get("/kit-lines/<kit_line_id>")
@endpoint(["CampaignManager", "FulfillmentOps", "PlatformAdmin"])
def get_kit_line(kit_line_id):
    parse_body([])
    row = must_exist("kit_lines", kit_line_id, "Kit line")
    return single(serializers.kit_line(row))


@bp.get("/kit-lines")
@endpoint(["CampaignManager", "FulfillmentOps", "PlatformAdmin"])
def list_kit_lines():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.kit_lines.values())
    if query["campaign_id"] is not None:
        rows = [r for r in rows if r["campaign_id"] == query["campaign_id"]]
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.kit_line(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/kit-lines/<kit_line_id>/receipts")
@endpoint(["FulfillmentOps"])
def book_receipt(kit_line_id):
    body, _ = parse_body(RECEIPT_FIELDS)
    line = must_exist("kit_lines", kit_line_id, "Kit line")
    units = body["units"]
    line["units_received"] += units
    line["units_available"] += units
    touch(line)
    return single(serializers.kit_line(line))


@bp.post("/kit-lines/<kit_line_id>/write-offs")
@endpoint(["FulfillmentOps"])
def write_off(kit_line_id):
    body, _ = parse_body(WRITE_OFF_FIELDS)
    line = must_exist("kit_lines", kit_line_id, "Kit line")
    units = body["units"]
    # rung 31
    if units > line["units_available"]:
        raise ApiError("ERR_WRITE_OFF_EXCEEDS_AVAILABLE",
                       "Only %d units are available" % line["units_available"])
    line["units_available"] -= units
    line["units_written_off"] += units
    touch(line)

    campaign = db.campaigns[line["campaign_id"]]
    campaign["write_off_cost_cents"] += units * line["unit_cost_cents"]
    calc.refresh_final_cost(campaign)
    touch(campaign)
    return single(serializers.kit_line(line))


@bp.post("/kit-lines/<kit_line_id>/retire")
@endpoint(["CampaignManager"])
def retire_kit_line(kit_line_id):
    parse_body([])
    line = must_exist("kit_lines", kit_line_id, "Kit line")
    if line["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_KIT_LINE_STATE",
                       "The kit line is already RETIRED")
    campaign = db.campaigns[line["campaign_id"]]
    if campaign["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_CAMPAIGN_TRANSITION",
                       "The owning campaign is CLOSED")
    line["status"] = "RETIRED"
    touch(line)
    calc.refresh_kit_assembly_unit_cost(campaign)
    touch(campaign)
    return single(serializers.kit_line(line))
