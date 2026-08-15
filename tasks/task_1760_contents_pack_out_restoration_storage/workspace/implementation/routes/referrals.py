"""SpecialtyReferral + CustodyEvent endpoints."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import (
    validation,
    invalid_transition,
    item_terminal,
    subcontractor_at_capacity,
    not_referral_subcontractor,
    custody_out_of_order,
)
from helpers import (
    get_body,
    require_string,
    require_enum,
    require_int,
    optional_int,
    optional_string,
    make_common_fields,
    new_id,
    now_stamp,
    get_item,
    get_subcontractor,
    get_referral,
    touch,
    parse_iso8601,
)
from middleware import require_roles, parse_pagination, paginate
from response import success_object, success_list, success
from services.cascade import release_active_placement
from services.recompute import (
    recompute_subcontractor,
    recompute_provisional_statements_for_job,
    recompute_job_accrued,
    recompute_room,
)
from helpers import job_of_item

bp = Blueprint("referrals", __name__)

SPECIALTY_TYPES = {
    "ART_CONSERVATION",
    "ELECTRONICS_DATA_RECOVERY",
    "DOCUMENT_FREEZE_DRYING",
    "FUR_CLEANING",
    "JEWELRY_APPRAISAL",
}
REFERRAL_ACTIONS = {"DISPATCH", "RECEIVE", "RETURN", "QA_ACCEPT", "QA_REJECT"}
CUSTODY_EVENT_TYPES = {"PICKED_UP", "IN_TRANSIT", "RECEIVED_BY_SUB", "RETURNED_BY_SUB", "RECEIVED_BACK"}
TERMINAL_ITEM_STATUSES = {"DISPOSED", "DELIVERED", "CLAIM_SETTLED"}
DISPATCHABLE_ITEM_STATUSES = {"AWAITING_CLEANING", "CLEANED", "IN_STORAGE"}


def serialize_referral(r):
    return dict(r)


def serialize_event(e):
    return dict(e)


@bp.route("/api/items/<item_id>/specialty-referrals", methods=["POST"])
def create_referral(item_id):
    user_id, role = require_roles("ProjectManager")
    body = get_body()
    subcontractor_id = require_string(body, "subcontractor_id")
    specialty_type = require_enum(body, "specialty_type", SPECIALTY_TYPES)
    quoted_cost_cents = require_int(body, "quoted_cost_cents", min_v=0)
    markup_pct = optional_int(body, "markup_pct", default=15)

    item = get_item(item_id)
    sub = get_subcontractor(subcontractor_id)

    if item["processing_status"] in TERMINAL_ITEM_STATUSES:
        raise item_terminal()
    if specialty_type not in sub["specialty_types"]:
        raise validation(f"Subcontractor does not offer specialty_type {specialty_type}")

    referral = make_common_fields()
    referral.update({
        "item_id": item["id"],
        "subcontractor_id": sub["id"],
        "specialty_type": specialty_type,
        "quoted_cost_cents": quoted_cost_cents,
        "markup_pct": markup_pct,
        "billed_cost_cents": None,
        "status": "DRAFT",
    })
    store.referrals[referral["id"]] = referral
    return success_object(serialize_referral(referral), status=201)


@bp.route("/api/specialty-referrals", methods=["GET"])
def list_referrals():
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "SubcontractorContact")
    limit, offset = parse_pagination()
    item_id = request.args.get("item_id")
    subcontractor_id = request.args.get("subcontractor_id")
    referrals = list(store.referrals.values())
    if role == "SubcontractorContact":
        referrals = [r for r in referrals if r["subcontractor_id"] == user_id]
    if item_id is not None:
        referrals = [r for r in referrals if r["item_id"] == item_id]
    if subcontractor_id is not None:
        referrals = [r for r in referrals if r["subcontractor_id"] == subcontractor_id]
    page, total = paginate([serialize_referral(r) for r in referrals], limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/specialty-referrals/<ref_id>", methods=["GET"])
def read_referral(ref_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "SubcontractorContact")
    referral = get_referral(ref_id)
    if role == "SubcontractorContact" and referral["subcontractor_id"] != user_id:
        raise not_referral_subcontractor()
    return success_object(serialize_referral(referral))


@bp.route("/api/specialty-referrals/<ref_id>/transition", methods=["POST"])
def transition_referral(ref_id):
    user_id, role = require_roles("ProjectManager", "SubcontractorContact")
    body = get_body()
    action = require_enum(body, "action", REFERRAL_ACTIONS)
    referral = get_referral(ref_id)
    item = store.items.get(referral["item_id"])
    sub = store.subcontractors.get(referral["subcontractor_id"])

    # SubcontractorContact ownership gate (priority 3)
    if role == "SubcontractorContact":
        if referral["subcontractor_id"] != user_id:
            raise not_referral_subcontractor()
        if action not in ("RECEIVE", "RETURN"):
            from errors import forbidden_role
            raise forbidden_role(f"SubcontractorContact may not perform {action}")
    else:  # ProjectManager
        if action in ("RECEIVE", "RETURN"):
            from errors import forbidden_role
            raise forbidden_role(f"ProjectManager may not perform {action}")

    if action == "DISPATCH":
        if referral["status"] == "DRAFT":
            if item is None or item["processing_status"] not in DISPATCHABLE_ITEM_STATUSES:
                raise invalid_transition("Item processing_status does not permit DISPATCH")
            if sub is not None and sub["active_referral_count"] >= sub["max_concurrent_referrals"]:
                raise subcontractor_at_capacity()
            was_in_storage = item["processing_status"] == "IN_STORAGE"
            referral["status"] = "DISPATCHED"
            touch(referral)
            if sub is not None:
                recompute_subcontractor(sub)
            item["processing_status"] = "OUT_FOR_SPECIALTY"
            touch(item)
            if was_in_storage:
                release_active_placement(item, "SPECIALTY")
        elif referral["status"] == "QA_REJECTED":
            # resend cycle; slot retained
            referral["status"] = "DISPATCHED"
            touch(referral)
            if sub is not None:
                recompute_subcontractor(sub)
            # item stays OUT_FOR_SPECIALTY
        else:
            raise invalid_transition("Referral cannot be DISPATCHED from current status")
    elif action == "RECEIVE":
        if referral["status"] != "DISPATCHED":
            raise invalid_transition("Referral is not DISPATCHED")
        referral["status"] = "IN_CUSTODY"
        touch(referral)
        if sub is not None:
            recompute_subcontractor(sub)
    elif action == "RETURN":
        if referral["status"] != "IN_CUSTODY":
            raise invalid_transition("Referral is not IN_CUSTODY")
        referral["status"] = "RETURNED"
        touch(referral)
        if sub is not None:
            recompute_subcontractor(sub)
    elif action == "QA_ACCEPT":
        if referral["status"] != "RETURNED":
            raise invalid_transition("Referral is not RETURNED")
        billed = (Decimal(referral["quoted_cost_cents"]) * (100 + referral["markup_pct"]) / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        referral["billed_cost_cents"] = int(billed)
        referral["status"] = "QA_ACCEPTED"
        touch(referral)
        if sub is not None:
            recompute_subcontractor(sub)
        if item is not None:
            item["processing_status"] = "CLEANED"
            touch(item)
    elif action == "QA_REJECT":
        if referral["status"] != "RETURNED":
            raise invalid_transition("Referral is not RETURNED")
        referral["status"] = "QA_REJECTED"
        touch(referral)
        if sub is not None:
            recompute_subcontractor(sub)
        # item stays OUT_FOR_SPECIALTY

    if item is not None:
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)
    return success_object(serialize_referral(referral))


@bp.route("/api/specialty-referrals/<ref_id>/custody-events", methods=["POST"])
def create_custody_event(ref_id):
    user_id, role = require_roles("InventoryTechnician", "SubcontractorContact")
    body = get_body()
    event_type = require_enum(body, "event_type", CUSTODY_EVENT_TYPES)
    event_at_raw = body.get("event_at")
    if event_at_raw is None:
        raise validation("event_at is required")
    event_at_dt = parse_iso8601(event_at_raw, field="event_at")
    actor_name = require_string(body, "actor_name")
    note = optional_string(body, "note")

    referral = get_referral(ref_id)

    if role == "SubcontractorContact" and referral["subcontractor_id"] != user_id:
        raise not_referral_subcontractor()

    prior_events = [e for e in store.custody_events.values() if e["referral_id"] == referral["id"]]
    for e in prior_events:
        prior_dt = parse_iso8601(e["event_at"], field="event_at")
        if not (event_at_dt > prior_dt):
            raise custody_out_of_order()
    next_seq = max([e["sequence"] for e in prior_events], default=0) + 1

    from db import format_iso
    event = {
        "id": new_id(),
        "created_at": now_stamp(),
        "referral_id": referral["id"],
        "event_type": event_type,
        "event_at": format_iso(event_at_dt),
        "actor_name": actor_name,
        "note": note,
        "sequence": next_seq,
    }
    store.custody_events[event["id"]] = event
    return success_object(serialize_event(event), status=201)


@bp.route("/api/specialty-referrals/<ref_id>/custody-events", methods=["GET"])
def list_custody_events(ref_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician", "SubcontractorContact")
    referral = get_referral(ref_id)
    if role == "SubcontractorContact" and referral["subcontractor_id"] != user_id:
        raise not_referral_subcontractor()
    events = [e for e in store.custody_events.values() if e["referral_id"] == referral["id"]]
    events.sort(key=lambda e: e["sequence"])
    return success([serialize_event(e) for e in events], status=200, response_type="array")
