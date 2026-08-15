from flask import Blueprint, request

from db import STORE, CLOCK, next_seq, new_id, bump, is_int
from errors import (ApiError, ERR_INVALID_REQUEST,
                    ERR_CAMPAIGN_INVALID_STATE, ERR_CAMPAIGN_HAS_ACTIVE_WORK,
                    ERR_REKEY_SCOPE_EMPTY, ERR_INCIDENT_NOT_REVIEWED,
                    ERR_CROSS_BUILDING_REFERENCE, ERR_BILL_TARGET_INVALID,
                    ERR_WORK_ORDER_INVALID_STATE, ERR_DOOR_UNDER_MAINTENANCE,
                    ERR_WORK_ORDER_OVERLAP, ERR_SCHEDULE_INVALID)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_campaign, ser_work_order
from validators import get_or_404, req_str, opt_str, req_enum, req_ts
from services import (create_campaign, compute_scope, approve_campaign_effects,
                      maybe_complete_campaign, deactivate_credential,
                      cred_sort_key)

bp = Blueprint("campaigns", __name__)

STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]
ADMIN = ["SecurityAdmin"]
WO_ROLES = ["SecurityOfficer", "SecurityAdmin"]
MANUAL_WO_TYPES = ["HARDWARE_REPAIR", "INSPECTION", "BATTERY_REPLACE"]


# ---------------------------------------------------------- rekey campaigns
@bp.route("/rekey-campaigns", methods=["POST"])
def create_campaign_route():
    ctx = authenticate()
    require_roles(ctx, ADMIN)
    b = body()
    building_id = req_str(b, "building_id")
    key_node_id = req_str(b, "key_node_id")
    incident_id = opt_str(b, "incident_id")
    bill_to = b.get("bill_to", "BUILDING")
    if bill_to not in ("BUILDING", "PERSON"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid bill_to")
    bill_person_id = opt_str(b, "bill_person_id")
    building = get_or_404("buildings", building_id, "Building")
    node = get_or_404("key_nodes", key_node_id, "KeyNode")
    if incident_id is not None:
        get_or_404("incidents", incident_id, "Incident")
    if bill_person_id is not None:
        get_or_404("persons", bill_person_id, "Person")
    if node["building_id"] != building_id:
        raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                       "key_node_id belongs to a different building")
    if bill_to == "PERSON" and bill_person_id is None:
        raise ApiError(ERR_BILL_TARGET_INVALID, 422,
                       "bill_person_id required when bill_to is PERSON")
    if bill_to == "BUILDING" and bill_person_id is not None:
        raise ApiError(ERR_BILL_TARGET_INVALID, 422,
                       "bill_person_id forbidden when bill_to is BUILDING")
    c = create_campaign(building, key_node_id, incident_id, bill_to,
                        bill_person_id)
    return ok_object(ser_campaign(c), 201)


@bp.route("/rekey-campaigns", methods=["GET"])
def list_campaigns():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["campaigns"].values())
    for f in ("building_id", "key_node_id", "incident_id", "status",
              "bill_person_id"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_campaign)


@bp.route("/rekey-campaigns/<campaignId>", methods=["GET"])
def get_campaign(campaignId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    c = get_or_404("campaigns", campaignId, "RekeyCampaign")
    return ok_object(ser_campaign(c))


@bp.route("/rekey-campaigns/<campaignId>/approve", methods=["POST"])
def approve_campaign(campaignId):
    ctx = authenticate()
    require_roles(ctx, ADMIN)
    c = get_or_404("campaigns", campaignId, "RekeyCampaign")
    if c["status"] != "PROPOSED":
        raise ApiError(ERR_CAMPAIGN_INVALID_STATE, 409,
                       "Campaign is not PROPOSED")
    dc, cc, est = compute_scope(c)
    # PRD guard order: state -> refreshed scope non-empty -> incident reviewed
    if dc == 0:
        raise ApiError(ERR_REKEY_SCOPE_EMPTY, 422,
                       "Campaign scope has no affected doors")
    if c["incident_id"] is not None:
        inc = STORE["incidents"].get(c["incident_id"])
        if inc is not None and inc["status"] not in ("UNDER_REVIEW",
                                                     "RESOLVED"):
            raise ApiError(ERR_INCIDENT_NOT_REVIEWED, 422,
                           "Linked incident is still OPEN")
    c["affected_door_count"] = dc
    c["affected_credential_count"] = cc
    c["estimated_cost_cents"] = est
    approve_campaign_effects(c)
    return ok_object(ser_campaign(c))


@bp.route("/rekey-campaigns/<campaignId>/cancel", methods=["POST"])
def cancel_campaign(campaignId):
    ctx = authenticate()
    require_roles(ctx, ADMIN)
    c = get_or_404("campaigns", campaignId, "RekeyCampaign")
    if c["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(ERR_CAMPAIGN_INVALID_STATE, 409,
                       "Campaign is not PROPOSED or APPROVED")
    linked = [w for w in STORE["work_orders"].values()
              if w["campaign_id"] == c["id"]]
    # A linked work order IN_PROGRESS blocks cancellation; because the first
    # start auto-tips the campaign to IN_PROGRESS, this guard surfaces for
    # both APPROVED and IN_PROGRESS campaigns with active work.
    if any(w["status"] == "IN_PROGRESS" for w in linked):
        raise ApiError(ERR_CAMPAIGN_HAS_ACTIVE_WORK, 409,
                       "Campaign has a work order IN_PROGRESS")
    if c["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError(ERR_CAMPAIGN_INVALID_STATE, 409,
                       "Campaign is not PROPOSED or APPROVED")
    if c["status"] == "APPROVED":
        for w in linked:
            if w["status"] == "OPEN":
                w["status"] = "CANCELLED"
                bump(w)
    c["status"] = "CANCELLED"
    bump(c)
    return ok_object(ser_campaign(c))


# ------------------------------------------------------------- work orders
@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    ctx = authenticate()
    require_roles(ctx, WO_ROLES)
    b = body()
    building_id = req_str(b, "building_id")
    door_id = req_str(b, "door_id")
    type_ = req_enum(b, "type",
                     MANUAL_WO_TYPES + ["REKEY"])
    if type_ == "REKEY":
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "REKEY is reserved for campaign-generated orders")
    sched_start = req_ts(b, "scheduled_start")
    sched_end = req_ts(b, "scheduled_end")
    bill_person_id = opt_str(b, "bill_person_id")
    get_or_404("buildings", building_id, "Building")
    door = get_or_404("doors", door_id, "Door")
    if bill_person_id is not None:
        get_or_404("persons", bill_person_id, "Person")
    if door["building_id"] != building_id:
        raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                       "door_id belongs to a different building")
    for w in STORE["work_orders"].values():
        if (w["door_id"] == door_id
                and w["status"] in ("OPEN", "IN_PROGRESS")
                and w["scheduled_start"] is not None
                and w["scheduled_end"] is not None):
            # Half-open windows; touching endpoints do not intersect.
            if sched_start < w["scheduled_end"] and \
                    w["scheduled_start"] < sched_end:
                raise ApiError(ERR_WORK_ORDER_OVERLAP, 422,
                               "Window overlaps an existing work order")
    if sched_end <= sched_start:
        raise ApiError(ERR_SCHEDULE_INVALID, 422,
                       "scheduled_end must be strictly after scheduled_start")
    now = CLOCK.now()
    wo = {
        "id": new_id(),
        "building_id": building_id,
        "door_id": door_id,
        "campaign_id": None,
        "target_key_node_id": None,
        "type": type_,
        "status": "OPEN",
        "scheduled_start": sched_start,
        "scheduled_end": sched_end,
        "actual_cost_cents": None,
        "bill_person_id": bill_person_id,
        "seq": next_seq(building_id, "work_orders"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["work_orders"][wo["id"]] = wo
    return ok_object(ser_work_order(wo), 201)


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["work_orders"].values())
    for f in ("building_id", "door_id", "campaign_id", "status", "type",
              "bill_person_id", "target_key_node_id"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_work_order)


@bp.route("/work-orders/<workOrderId>", methods=["GET"])
def get_work_order(workOrderId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    w = get_or_404("work_orders", workOrderId, "MaintenanceWorkOrder")
    return ok_object(ser_work_order(w))


@bp.route("/work-orders/<workOrderId>/start", methods=["POST"])
def start_work_order(workOrderId):
    ctx = authenticate()
    require_roles(ctx, WO_ROLES)
    w = get_or_404("work_orders", workOrderId, "MaintenanceWorkOrder")
    if w["status"] != "OPEN":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, 409,
                       "Work order is not OPEN")
    door = STORE["doors"].get(w["door_id"])
    if door is not None and door["hardware_status"] != "OPERATIONAL":
        raise ApiError(ERR_DOOR_UNDER_MAINTENANCE, 409,
                       "Door is UNDER_MAINTENANCE")
    w["status"] = "IN_PROGRESS"
    bump(w)
    if door is not None:
        door["hardware_status"] = "UNDER_MAINTENANCE"
        bump(door)
    if w["campaign_id"] is not None:
        campaign = STORE["campaigns"].get(w["campaign_id"])
        if campaign is not None and campaign["status"] == "APPROVED":
            campaign["status"] = "IN_PROGRESS"
            bump(campaign)
    return ok_object(ser_work_order(w))


@bp.route("/work-orders/<workOrderId>/complete", methods=["POST"])
def complete_work_order(workOrderId):
    ctx = authenticate()
    require_roles(ctx, WO_ROLES)
    w = get_or_404("work_orders", workOrderId, "MaintenanceWorkOrder")
    b = body()
    actual = b.get("actual_cost_cents")
    if not is_int(actual):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "actual_cost_cents is required at completion")
    if w["status"] != "IN_PROGRESS":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, 409,
                       "Work order is not IN_PROGRESS")
    w["actual_cost_cents"] = actual
    w["status"] = "COMPLETED"
    bump(w)
    door = STORE["doors"].get(w["door_id"])
    campaign = (STORE["campaigns"].get(w["campaign_id"])
                if w["campaign_id"] else None)
    if door is not None:
        door["hardware_status"] = "OPERATIONAL"
        if w["type"] == "REKEY" and w["target_key_node_id"] is not None:
            pre_node_id = door["key_node_id"]
            target = STORE["key_nodes"].get(w["target_key_node_id"])
            door["key_node_id"] = w["target_key_node_id"]
            if target is not None:
                door["bitting_code"] = target["label"]
            door["core_status"] = "ACTIVE"
            # Hop 2: deactivate every credential on the pre-rekey node
            creds = [c for c in STORE["credentials"].values()
                     if c["key_node_id"] == pre_node_id
                     and c["status"] != "DEACTIVATED"]
            for cred in sorted(creds, key=cred_sort_key):
                deactivate_credential(cred, "REKEY", campaign=campaign)
        bump(door)
    if campaign is not None:
        maybe_complete_campaign(campaign)
    return ok_object(ser_work_order(w))


@bp.route("/work-orders/<workOrderId>/cancel", methods=["POST"])
def cancel_work_order(workOrderId):
    ctx = authenticate()
    require_roles(ctx, WO_ROLES)
    w = get_or_404("work_orders", workOrderId, "MaintenanceWorkOrder")
    if w["status"] != "OPEN":
        raise ApiError(ERR_WORK_ORDER_INVALID_STATE, 409,
                       "Work order is not OPEN")
    w["status"] = "CANCELLED"
    bump(w)
    if w["campaign_id"] is not None:
        campaign = STORE["campaigns"].get(w["campaign_id"])
        maybe_complete_campaign(campaign)
    return ok_object(ser_work_order(w))
