"""Panel design endpoints: OCC-guarded revision creation, submit, and the
customer decide action that cascades into work-order approval / parts release."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    pagination_args,
    paginate,
    req_equipment_list,
    req_enum,
    req_int,
    req_str,
    require_role,
)
from response import success
from serializers import ser_panel_design
from services.core import (
    check_customer_ownership,
    children_of,
    next_order_seq,
    recompute_work_order,
)
from util import D, rhu

bp = Blueprint("panel_designs", __name__)


def _get_design(panelDesignId):
    d = db.panel_designs.get(panelDesignId)
    if d is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Panel design not found")
    return d


@bp.post("/avionics/panel-designs")
def create_panel_design():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    work_order_id = req_str(b, "work_order_id")
    expected_version = req_int(b, "expected_work_order_version")
    layout_notes = req_str(b, "layout_notes")
    equipment_list = req_equipment_list(b)

    # existence (priority 4)
    wo = db.work_orders.get(work_order_id)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")

    # optimistic concurrency (scaffold 1.2.1): the only OCC-guarded write
    if expected_version != wo.version:
        errors.raise_err(
            errors.ERR_STALE_VERSION,
            "expected_work_order_version does not match the work order version",
        )

    # state (priority 5): scope locks once the customer has approved
    if wo.status not in ("DRAFT", "PENDING_APPROVAL"):
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Work order no longer accepts new design revisions",
        )

    # supersede every earlier live revision (APPROVED is terminal and stands)
    for d in children_of(db.panel_designs, wo.id):
        if d.status in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED"):
            d.status = "SUPERSEDED"
            touch(d)

    revision = len(children_of(db.panel_designs, wo.id)) + 1
    total_added_weight = float(
        rhu(
            sum(
                (D(line["quantity"]) * D(str(line["weight_lb"])) for line in equipment_list),
                Decimal(0),
            ),
            1,
        )
    )
    d = db.new_entity(
        work_order_id=wo.id,
        revision=revision,
        layout_notes=layout_notes,
        equipment_list=equipment_list,
        total_added_weight_lb=total_added_weight,
        status="DRAFT",
    )
    db.panel_designs[d.id] = d
    # authoring a revision advances the work order's version (PRD 2.9)
    touch(wo)
    return success(ser_panel_design(d), 201)


@bp.get("/avionics/panel-designs/<panelDesignId>")
def get_panel_design(panelDesignId):
    authenticate()
    return success(ser_panel_design(_get_design(panelDesignId)), 200)


@bp.get("/avionics/panel-designs")
def list_panel_designs():
    authenticate()
    limit, offset = pagination_args()
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    items = sorted(db.panel_designs.values(), key=lambda d: d._seq)
    if work_order_id is not None:
        items = [d for d in items if d.work_order_id == work_order_id]
    if status is not None:
        items = [d for d in items if d.status == status]
    page, meta = paginate([ser_panel_design(d) for d in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/panel-designs/<panelDesignId>/submit")
def submit_panel_design(panelDesignId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    d = _get_design(panelDesignId)
    wo = db.work_orders[d.work_order_id]
    if d.status != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a DRAFT design can be submitted")
    if wo.status not in ("DRAFT", "PENDING_APPROVAL"):
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Parent work order no longer accepts design submission",
        )
    d.status = "SUBMITTED"
    touch(d)
    return success(ser_panel_design(d), 200)


@bp.post("/avionics/panel-designs/<panelDesignId>/decide")
def decide_panel_design(panelDesignId):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    d = db.panel_designs.get(panelDesignId)
    if d is not None:
        check_customer_ownership(db.work_orders[d.work_order_id], uid)
    b = body()
    outcome = req_enum(b, "outcome", {"APPROVE", "REQUEST_CHANGES"})
    if d is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Panel design not found")
    wo = db.work_orders[d.work_order_id]

    if d.status != "SUBMITTED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a SUBMITTED design can be decided")
    if wo.status != "PENDING_APPROVAL":
        errors.raise_err(
            errors.ERR_INVALID_STATE, "Parent work order is not awaiting approval"
        )

    if outcome == "REQUEST_CHANGES":
        # work order stays PENDING_APPROVAL; no version advance
        d.status = "CHANGES_REQUESTED"
        touch(d)
        return success(ser_panel_design(d), 200)

    # APPROVE: design becomes terminally APPROVED and cascades into the work order
    d.status = "APPROVED"
    touch(d)
    if not d.equipment_list:
        wo.status = "APPROVED"
        touch(wo)
    else:
        wo.status = "PARTS_PENDING"
        touch(wo)
        seq = next_order_seq(wo.id)
        for line in d.equipment_list:
            o = db.new_entity(
                work_order_id=wo.id,
                seq=seq,
                source="DESIGN_RELEASE",
                source_design_revision=d.revision,
                part_number=line["part_number"],
                description=line["description"],
                quantity=line["quantity"],
                unit_price_cents=line["unit_price_cents"],
                lead_time_days=line["lead_time_days"],
                ordered_at=None,
                promised_date=None,
                received_at=None,
                status="PLANNED",
            )
            db.equipment_orders[o.id] = o
            seq += 1
        recompute_work_order(wo)
    return success(ser_panel_design(d), 200)
