"""Inspection and InspectionItem endpoints (PRD §3.2, §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INSPECTOR_SCHEDULE_CONFLICT,
    ERR_ITEM_LINK_MISMATCH,
    ERR_ITEM_NOT_ASSESSED,
    ERR_PHOTO_DOCUMENTATION_REQUIRED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.calculations import (
    damage_charge, deposit_interest, key_fob_lock_charges,
)
from services.core import (
    jurisdiction_for_tenancy, new_record, property_for_tenancy, public,
    recompute_tenancy_money, recompute_unit_occupancy,
    refresh_draft_statement_projection, touch, unit_for_tenancy,
)
from util import CLOCK, parse_datetime
from validate import (
    get_body, opt_enum, opt_int, opt_str, req_datetime, req_enum, req_int,
    req_str, require_body_ref, require_path_resource,
)

bp = Blueprint("inspections", __name__)

PHOTO_REQUIRED_CONDITIONS = ("WORN", "DAMAGED", "MISSING")


def _check_photo_rule(item):
    """Photographic evidence is mandatory for anything below move-in-ready."""
    if item["condition"] in PHOTO_REQUIRED_CONDITIONS and item["photo_count"] < 1:
        raise_error(
            ERR_PHOTO_DOCUMENTATION_REQUIRED,
            f"condition {item['condition']} requires photo_count >= 1",
        )


@bp.post("/pm/inspections")
def create_inspection():
    authorized(["PropertyManager"])
    body = get_body()
    fields = {
        "tenancy_id": req_str(body, "tenancy_id"),
        "kind": req_enum(body, "kind", ("MOVE_IN", "MOVE_OUT")),
        "inspector_user_id": req_str(body, "inspector_user_id"),
        "scheduled_start_at": req_datetime(body, "scheduled_start_at"),
        "scheduled_end_at": req_datetime(body, "scheduled_end_at"),
    }
    start = parse_datetime(fields["scheduled_start_at"])
    end = parse_datetime(fields["scheduled_end_at"])
    if not start <= end:
        raise_error(ERR_INVALID_REQUEST,
                    "scheduled_start_at must be at or before scheduled_end_at")
    require_body_ref("tenancies", fields["tenancy_id"], "tenancy_id")
    # Priority 8: an inspector's DRAFT windows are closed intervals that must
    # not touch or overlap — adjacency at an endpoint already conflicts.
    for other in db["inspections"].values():
        if other["inspector_user_id"] != fields["inspector_user_id"]:
            continue
        if other["status"] != "DRAFT":
            continue
        o_start = parse_datetime(other["scheduled_start_at"])
        o_end = parse_datetime(other["scheduled_end_at"])
        if start <= o_end and o_start <= end:
            raise_error(ERR_INSPECTOR_SCHEDULE_CONFLICT,
                        "inspector already has a DRAFT inspection window that "
                        "touches or overlaps this one")
    fields["completed_at"] = None
    fields["status"] = "DRAFT"
    rec = new_record("inspections", fields)
    return success_object(public(rec), status=201)


@bp.get("/pm/inspections/<rid>")
def get_inspection(rid):
    return get_one("inspections", rid)


@bp.get("/pm/inspections")
def list_inspections():
    return list_response("inspections", {
        "tenancy_id": request.args.get("tenancy_id"),
        "inspector_user_id": request.args.get("inspector_user_id"),
        "status": request.args.get("status"),
    })


@bp.post("/pm/inspections/<rid>/items")
def add_inspection_item(rid):
    authorized(["Inspector"])
    body = get_body()
    fields = {
        "area_name": req_str(body, "area_name"),
        "category": req_enum(body, "category", ("CARPET", "PAINT", "OTHER")),
        "condition": req_enum(body, "condition",
                              ("NEW", "GOOD", "FAIR", "WORN", "DAMAGED", "MISSING")),
        "photo_count": req_int(body, "photo_count", non_negative=True),
        "determination": opt_enum(body, "determination",
                                  ("UNASSESSED", "NORMAL_WEAR", "TENANT_DAMAGE"),
                                  default="UNASSESSED"),
        "linked_move_in_item_id": opt_str(body, "linked_move_in_item_id"),
        "replacement_cost_cents": opt_int(body, "replacement_cost_cents", non_negative=True),
        "actual_repair_cents": opt_int(body, "actual_repair_cents", non_negative=True),
        "notes": opt_str(body, "notes"),
    }
    inspection = require_path_resource("inspections", rid)
    # Body-referenced id existence (priority 4) for the link.
    linked = None
    if fields["linked_move_in_item_id"] is not None:
        linked = require_body_ref("inspection_items", fields["linked_move_in_item_id"],
                                  "linked_move_in_item_id")
    # Priority 5: items may only be added while the inspection is DRAFT.
    if inspection["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "items may only be added to a DRAFT inspection")
    # replacement_cost_cents is required whenever determination is
    # TENANT_DAMAGE (ERR_INVALID_REQUEST).
    if (fields["determination"] == "TENANT_DAMAGE"
            and fields["replacement_cost_cents"] is None):
        raise_error(ERR_INVALID_REQUEST,
                    "replacement_cost_cents is required when determination is "
                    "TENANT_DAMAGE")
    # Priority 7: the link must point to an item of this tenancy's COMPLETED
    # MOVE_IN inspection.
    if linked is not None:
        link_insp = db["inspections"].get(linked["inspection_id"])
        if (link_insp is None
                or link_insp["tenancy_id"] != inspection["tenancy_id"]
                or link_insp["kind"] != "MOVE_IN"
                or link_insp["status"] != "COMPLETED"):
            raise_error(ERR_ITEM_LINK_MISMATCH,
                        "linked_move_in_item_id is not an item of this tenancy's "
                        "COMPLETED MOVE_IN inspection")
    # Priority 9: compliance documentation.
    _check_photo_rule(fields)
    fields["inspection_id"] = inspection["id"]
    rec = new_record("inspection_items", fields)
    return success_object(public(rec), status=201)


@bp.post("/pm/inspections/<rid>/complete")
def complete_inspection(rid):
    authorized(["Inspector"])
    get_body()
    inspection = require_path_resource("inspections", rid)
    if inspection["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"inspection is {inspection['status']}, not DRAFT")
    tenancy = db["tenancies"].get(inspection["tenancy_id"])
    items = [i for i in db["inspection_items"].values()
             if i["inspection_id"] == inspection["id"]]
    # Cross-entity gate (priority 5): the tenancy lifecycle state must match
    # the inspection kind.
    if inspection["kind"] == "MOVE_IN":
        if tenancy["status"] != "PENDING_MOVE_IN":
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        "MOVE_IN completion requires tenancy PENDING_MOVE_IN")
    else:  # MOVE_OUT
        if tenancy["status"] != "NOTICE_GIVEN":
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        "MOVE_OUT completion requires tenancy NOTICE_GIVEN")
        # Priority 9: every item must have been assessed.
        if any(i["determination"] == "UNASSESSED" for i in items):
            raise_error(ERR_ITEM_NOT_ASSESSED,
                        "MOVE_OUT completion blocked: an item still has "
                        "determination UNASSESSED")
    # Priority 9: the photo rule is re-checked at completion.
    for i in items:
        _check_photo_rule(i)

    # --- Effects -----------------------------------------------------------
    now = CLOCK.now()
    # Completing supersedes any prior COMPLETED inspection of same tenancy+kind.
    for other in db["inspections"].values():
        if (other["id"] != inspection["id"]
                and other["tenancy_id"] == inspection["tenancy_id"]
                and other["kind"] == inspection["kind"]
                and other["status"] == "COMPLETED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    inspection["status"] = "COMPLETED"
    inspection["completed_at"] = CLOCK.now_iso()
    touch(inspection)

    if inspection["kind"] == "MOVE_IN":
        tenancy["status"] = "OCCUPIED"
        tenancy["move_in_on"] = now.date().isoformat()
        touch(tenancy)
        recompute_unit_occupancy(tenancy["unit_id"])
        return success_object(public(inspection))

    # MOVE_OUT: tenancy NOTICE_GIVEN -> VACATED, then the deduction cascade.
    tenancy["status"] = "VACATED"
    tenancy["move_out_on"] = now.date().isoformat()

    unit = unit_for_tenancy(tenancy)
    prop = property_for_tenancy(tenancy)
    jur = jurisdiction_for_tenancy(tenancy)

    # Cascade link 1: one deduction per TENANT_DAMAGE item with charge > 0.
    for item in sorted((i for i in items if i["determination"] == "TENANT_DAMAGE"),
                       key=lambda i: i["_seq"]):
        charge = damage_charge(item, unit, jur, tenancy["move_out_on"])
        if charge <= 0:
            continue
        new_record("deductions", {
            "tenancy_id": tenancy["id"],
            "inspection_item_id": item["id"],
            "statement_id": None,
            "source": "MOVE_OUT_DAMAGE",
            "description": f"Move-out damage: {item['area_name']}",
            "quantity": 1,
            "amount_cents": charge,
            "status": "DRAFT",
        })
    # Key/fob/lock lines from the snapshot counts, after damage lines.
    for source, quantity, amount, description in key_fob_lock_charges(tenancy, prop, jur):
        new_record("deductions", {
            "tenancy_id": tenancy["id"],
            "inspection_item_id": None,
            "statement_id": None,
            "source": source,
            "description": description,
            "quantity": quantity,
            "amount_cents": amount,
            "status": "DRAFT",
        })

    # Deposit interest accrual runs at move-out completion.
    tenancy["interest_accrued_cents"] = deposit_interest(tenancy, jur)

    # Cascade link 2/3: pending recompute, then DRAFT statement projections.
    recompute_tenancy_money(tenancy["id"])
    refresh_draft_statement_projection(tenancy)
    touch(tenancy)
    recompute_unit_occupancy(tenancy["unit_id"])
    return success_object(public(inspection))
