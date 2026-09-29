"""Cost line items: recording and the classification cycle (PRD 3.6)."""

from flask import Blueprint

import calc
import services
from auth import own_project, require
from db import base_record, public, store, touch
from errors import ApiError
from response import created_response, object_response
from support import fetch
from validate import as_date, body, req_date, req_enum, req_int, req_str

bp = Blueprint("costs", __name__)

CATEGORIES = (
    "HARD_CONSTRUCTION",
    "ARCHITECTURAL_ENGINEERING",
    "DEVELOPER_FEE",
    "CONSTRUCTION_INTEREST",
    "ACQUISITION",
    "ENLARGEMENT",
    "SITE_WORK",
    "PERSONAL_PROPERTY",
    "FFE",
    "LANDSCAPING",
)
TARGET_CLASSIFICATIONS = ("QRE", "NON_QRE")
EXCLUSION_REASONS = (
    "NONE",
    "NONQUALIFIED_CATEGORY",
    "OUTSIDE_MEASURING_PERIOD",
    "DEVELOPER_FEE_CAP",
    "REVIEWER_DISALLOWED",
)
LOCKED = ("LOCKED_QRE", "LOCKED_NON_QRE")

READ_ROLES = ("PlatformAdmin", "Developer", "ComplianceMonitor", "ShpoReviewer", "NpsReviewer")


def _derive_exclusion_reason(item, supplied):
    if supplied is not None:
        return supplied
    if item["category"] in calc.NON_QRE_CATEGORIES:
        return "NONQUALIFIED_CATEGORY"
    if not item["in_measuring_period"]:
        return "OUTSIDE_MEASURING_PERIOD"
    return "NONE"


def _settle_project(project, previous_status, new_status):
    """Recomputation aftermath shared by create and classify."""
    if (
        previous_status == "MET"
        and new_status == "NOT_MET"
        and project["certification_status"] == "PART3_CERTIFIED"
    ):
        services.substantial_failure_cascade(project)
    touch(project)


@bp.post("/cost-line-items")
def create_cost_line_item():
    uid, _role = require("Developer")
    data = body()
    project_id = req_str(data, "project_id")
    vendor_name = req_str(data, "vendor_name", min_len=1, max_len=120)
    category = req_enum(data, "category", CATEGORIES)
    amount_cents = req_int(data, "amount_cents", min_v=1)
    incurred_date = req_date(data, "incurred_date")
    classification = req_enum(
        data, "classification", TARGET_CLASSIFICATIONS, required=False, default=None
    )

    project = fetch(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(project, uid)

    inside = services.in_measuring_period(project, incurred_date)

    if classification == "QRE":
        if category in calc.NON_QRE_CATEGORIES:
            raise ApiError("ERR_NONQUALIFIED_CATEGORY")
        if not inside:
            raise ApiError("ERR_OUTSIDE_MEASURING_PERIOD")

    record = base_record()
    record.update(
        {
            "project_id": project_id,
            "vendor_name": vendor_name,
            "category": category,
            "amount_cents": amount_cents,
            "incurred_date": incurred_date.isoformat(),
            "classification": classification or "PENDING_CLASSIFICATION",
            "exclusion_reason": "NONE",
            "in_measuring_period": inside,
            "reclassification_count": 0,
        }
    )
    store.cost_line_items[record["id"]] = record

    previous, new = services.recompute_financials(project)
    _settle_project(project, previous, new)
    return created_response(public(record))


@bp.post("/cost-line-items/<item_id>/classify")
def classify_cost_line_item(item_id):
    uid, role = require("Developer", "ComplianceMonitor")
    data = body()
    target = req_enum(data, "classification", TARGET_CLASSIFICATIONS)
    supplied_reason = req_enum(
        data, "exclusion_reason", EXCLUSION_REASONS, required=False, default=None
    )

    item = fetch(store.cost_line_items, item_id, "ERR_COST_LINE_ITEM_NOT_FOUND")
    project = store.projects[item["project_id"]]
    if role == "Developer":
        own_project(project, uid)

    locked = item["classification"] in LOCKED
    if locked:
        if role == "Developer":
            raise ApiError(
                "ERR_COST_ITEM_LOCKED",
                "Costs lock at Part 3 certification; only a compliance monitor may disallow one.",
            )
        if target == "QRE":
            raise ApiError(
                "ERR_COST_ITEM_LOCKED", "A locked cost may never be moved back onto the qualified side."
            )

    if target == "QRE":
        if item["category"] in calc.NON_QRE_CATEGORIES:
            raise ApiError("ERR_NONQUALIFIED_CATEGORY")
        if not item["in_measuring_period"]:
            raise ApiError("ERR_OUTSIDE_MEASURING_PERIOD")

    if locked:
        item["classification"] = "LOCKED_NON_QRE"
        item["exclusion_reason"] = supplied_reason or "REVIEWER_DISALLOWED"
    else:
        item["classification"] = target
        if target == "QRE":
            item["exclusion_reason"] = "NONE"
        else:
            item["exclusion_reason"] = _derive_exclusion_reason(item, supplied_reason)

    item["reclassification_count"] += 1
    touch(item)

    previous, new = services.recompute_financials(project)
    _settle_project(project, previous, new)
    return object_response(public(item))


@bp.get("/cost-line-items/<item_id>")
def read_cost_line_item(item_id):
    require(*READ_ROLES)
    record = fetch(store.cost_line_items, item_id, "ERR_COST_LINE_ITEM_NOT_FOUND")
    return object_response(public(record))
