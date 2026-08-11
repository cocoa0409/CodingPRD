"""Inventory catalogue, the disposition mesh, handling axis and family holds."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import store
from errors import ApiError
from routes.helpers import one, listing, filtered
from util import D

bp = Blueprint("inventory", __name__)

ITEM_READ = ["MOVE_MANAGER", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY", "CREW_LEAD"]
HOLD_ROLES = ["MOVE_MANAGER", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]
HOLD_TERMINAL = ["RESOLVED_KEEP", "RESOLVED_RELEASE", "WITHDRAWN"]
SORT_PHASES = ["ASSESSMENT", "SORT_PLAN"]

HANDLING_FROM = {
    "PACKED": ["AT_ORIGIN"],
    "LOADED": ["PACKED"],
    "DELIVERED": ["LOADED"],
    "UNPACKED": ["DELIVERED"],
    "STAGED_FOR_PICKUP": ["AT_ORIGIN"],
    "REMOVED": ["STAGED_FOR_PICKUP"],
    "AT_ORIGIN": [],
}
HANDLING_TERMINAL = ["UNPACKED", "REMOVED"]

DISPOSAL_SERVICE_FAMILY = {
    "HAUL_AWAY": "HAUL_AWAY",
    "SELL": "CONSIGNMENT_PICKUP",
    "DONATE": "HAUL_AWAY",
}


# ---------------------------------------------------------------------------
# inventory items
# ---------------------------------------------------------------------------

@bp.route("/inventory-items", methods=["POST"])
def create_item():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"), ("label", "string"),
                                    ("category", "string"),
                                    ("footprint_linear_inches", "number"),
                                    ("volume_cft", "number")],
                          optional=[("appraised_value_cents", "int"),
                                    ("appraisal_source", "string")])
    engagement = gates.resolve_body_fks(req.body)["engagement_id"]
    gates.gate3(engagement)
    gates.gate5_phase(engagement, SORT_PHASES)

    value = req.body.get("appraised_value_cents")
    source = req.body.get("appraisal_source")
    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "assigned_room_id": None,
        "consignment_lot_id": None,
        "unpack_session_id": None,
        "label": req.body["label"],
        "category": req.body["category"],
        "footprint_linear_inches": req.body["footprint_linear_inches"],
        "volume_cft": req.body["volume_cft"],
        "appraised_value_cents": 0 if value is None else value,
        "appraisal_source": "NONE" if source is None else source,
        "disposition": "UNDECIDED",
        "disposition_locked": False,
        "handling_state": "AT_ORIGIN",
        "redesignation_count": 0,
    })
    store.insert("inventory_items", record)
    store.touch(engagement)
    return one("inventory_items", record, 201)


@bp.route("/inventory-items", methods=["GET"])
def list_items():
    req = gates.preflight(ITEM_READ, is_list=True)
    rows = filtered(store.all_of("inventory_items"), req.args,
                    ["engagement_id", "assigned_room_id", "consignment_lot_id",
                     "unpack_session_id", "disposition", "handling_state"])
    return listing("inventory_items", req, rows)


@bp.route("/inventory-items/<iid>", methods=["GET"])
def read_item(iid):
    req = gates.preflight(ITEM_READ)
    record = gates.path_record("inventory_items", iid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("inventory_items", record)


@bp.route("/inventory-items/<iid>/designate", methods=["POST"])
def designate_item(iid):
    body_peek = None
    try:
        from flask import request
        body_peek = request.get_json(silent=True)
    except Exception:
        body_peek = None
    conditional_required = []
    if isinstance(body_peek, dict) and body_peek.get("disposition") == "KEEP":
        conditional_required = [("assigned_room_id", "string")]

    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"],
                          required=[("disposition", "string")] + conditional_required,
                          optional=[("assigned_room_id", "string"),
                                    ("acting_party_id", "string")])
    item = gates.path_record("inventory_items", iid)
    fks = gates.resolve_body_fks(req.body)
    engagement = store.get("engagements", item["engagement_id"])
    target = req.body["disposition"]

    gates.gate3(engagement)

    # gate 4 - actor authority
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body.get("acting_party_id")])
    # the SELL -> HAUL_AWAY leg is reserved to the move manager (PRD 3.4)
    if item["disposition"] == "SELL" and target == "HAUL_AWAY" and req.role != "MOVE_MANAGER":
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    gates.gate4_authority(req, "DISPOSITION",
                          subject_value=item["appraised_value_cents"],
                          high_value_subject=item["appraised_value_cents"])

    gates.gate5_phase(engagement, SORT_PHASES)
    gates.gate6_inventory_frozen(engagement)

    # gate 7
    if item["disposition_locked"]:
        raise ApiError("ERR_DISPOSITION_LOCKED")
    gates.gate7_not_held(item)
    if item["consignment_lot_id"] is not None and target != "SELL":
        raise ApiError("ERR_ITEM_ALREADY_CONSIGNED")

    # gate 12
    room = fks.get("assigned_room_id")
    if target == "KEEP":
        capacity = derive.room_effective_capacity(room)
        prospective = (derive.room_keep_load_linear(room["id"], exclude_item_id=item["id"])
                       + D(item["footprint_linear_inches"]))
        if prospective > capacity:
            raise ApiError("ERR_ROOM_CAPACITY_EXCEEDED")
        allowance = calc.room_volume_allowance(room["nominal_volume_cft"])
        prospective_volume = (derive.room_keep_load_volume(room["id"], exclude_item_id=item["id"])
                              + D(item["volume_cft"]))
        if prospective_volume > allowance:
            raise ApiError("ERR_ROOM_VOLUME_EXCEEDED")
    if target == "SELL" and item["appraised_value_cents"] < K.CONSIGN_MIN_VALUE_CENTS:
        raise ApiError("ERR_ITEM_BELOW_CONSIGN_MINIMUM")

    previous = item["disposition"]
    if target == "KEEP":
        item["assigned_room_id"] = room["id"]
    elif target == "SELL":
        item["assigned_room_id"] = None
    elif target == "DONATE" and previous == "KEEP":
        item["assigned_room_id"] = None
    item["disposition"] = target
    if previous != "UNDECIDED":
        item["redesignation_count"] = item["redesignation_count"] + 1
    store.touch(item)
    store.touch(engagement)
    return one("inventory_items", item)


@bp.route("/inventory-items/<iid>/appraise", methods=["POST"])
def appraise_item(iid):
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("appraised_value_cents", "int"),
                                    ("appraisal_source", "string")])
    item = gates.path_record("inventory_items", iid)
    engagement = store.get("engagements", item["engagement_id"])
    gates.gate3(engagement)
    gates.gate6_inventory_frozen(engagement)
    gates.gate7_not_held(item)

    item["appraised_value_cents"] = req.body["appraised_value_cents"]
    item["appraisal_source"] = req.body["appraisal_source"]
    store.touch(item)
    return one("inventory_items", item)


@bp.route("/inventory-items/<iid>/advance-handling", methods=["POST"])
def advance_handling(iid):
    req = gates.preflight(["MOVE_MANAGER", "CREW_LEAD"],
                          required=[("target_handling_state", "string")],
                          optional=[("unpack_session_id", "string")])
    item = gates.path_record("inventory_items", iid)
    fks = gates.resolve_body_fks(req.body)
    engagement = store.get("engagements", item["engagement_id"])
    target = req.body["target_handling_state"]

    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    if target == "STAGED_FOR_PICKUP":
        gates.gate7_not_held(item)

    gates.gate10_state(item["handling_state"], HANDLING_FROM[target], HANDLING_TERMINAL)

    sort_plan = derive.sort_plan_of(engagement["id"])
    plan = derive.move_day_plan_of(engagement["id"])
    if target == "PACKED":
        gates.require_state(item["disposition"] == "KEEP")
        gates.require_state(sort_plan is not None
                            and sort_plan["status"] in ("APPROVED", "FROZEN"))
    elif target == "LOADED":
        gates.require_state(plan is not None and plan["status"] == "IN_PROGRESS")
    elif target == "DELIVERED":
        gates.require_state(plan is not None and plan["status"] in ("IN_PROGRESS", "COMPLETED"))
        gates.require_state(item["assigned_room_id"] is not None)
    elif target == "UNPACKED":
        session = fks.get("unpack_session_id")
        gates.require_state(session is not None
                            and session["engagement_id"] == engagement["id"]
                            and session["status"] == "IN_PROGRESS")
    elif target == "STAGED_FOR_PICKUP":
        gates.require_state(item["disposition"] in ("DONATE", "SELL", "HAUL_AWAY"))
        gates.require_state(sort_plan is not None
                            and sort_plan["status"] in ("APPROVED", "FROZEN"))
    elif target == "REMOVED":
        family = DISPOSAL_SERVICE_FAMILY.get(item["disposition"])
        matched = False
        for assignment in store.where("vendor_assignments", engagement_id=engagement["id"]):
            if assignment["service_kind"] == family and \
                    assignment["status"] in ("PERFORMED", "SIGNED_OFF", "PAID"):
                matched = True
                break
        gates.require_state(matched)

    item["handling_state"] = target
    if target == "UNPACKED":
        item["unpack_session_id"] = fks["unpack_session_id"]["id"]
    store.touch(item)
    return one("inventory_items", item)


# ---------------------------------------------------------------------------
# family holds
# ---------------------------------------------------------------------------

@bp.route("/family-holds", methods=["POST"])
def create_hold():
    req = gates.preflight(HOLD_ROLES,
                          required=[("inventory_item_id", "string"),
                                    ("raised_by_party_id", "string"),
                                    ("reason", "nes")])
    fks = gates.resolve_body_fks(req.body)
    item = fks["inventory_item_id"]
    engagement = store.get("engagements", item["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body["raised_by_party_id"]])

    record = store.base_record()
    record.update({
        "inventory_item_id": item["id"],
        "raised_by_party_id": req.body["raised_by_party_id"],
        "resolved_by_party_id": None,
        "status": "OPEN",
        "reason": req.body["reason"],
        "resolution_note": None,
        "escalation_count": 0,
        "remand_count": 0,
    })
    store.insert("family_holds", record)
    store.touch(item)
    return one("family_holds", record, 201)


@bp.route("/family-holds", methods=["GET"])
def list_holds():
    req = gates.preflight(HOLD_ROLES, is_list=True)
    rows = filtered(store.all_of("family_holds"), req.args,
                    ["inventory_item_id", "raised_by_party_id", "resolved_by_party_id",
                     "status"])
    return listing("family_holds", req, rows)


@bp.route("/family-holds/<hid>", methods=["GET"])
def read_hold(hid):
    req = gates.preflight(HOLD_ROLES)
    record = gates.path_record("family_holds", hid)
    item = store.get("inventory_items", record["inventory_item_id"])
    gates.gate4_ownership(req, engagement=store.get("engagements", item["engagement_id"]))
    return one("family_holds", record)


def _hold_context(hid):
    record = gates.path_record("family_holds", hid)
    item = store.get("inventory_items", record["inventory_item_id"])
    engagement = store.get("engagements", item["engagement_id"])
    return record, item, engagement


@bp.route("/family-holds/<hid>/escalate", methods=["POST"])
def escalate_hold(hid):
    req = gates.preflight(["MOVE_MANAGER", "FAMILY_MEMBER"], required=[("note", "string")])
    record, item, engagement = _hold_context(hid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate10_state(record["status"], ["OPEN"], HOLD_TERMINAL)
    if record["escalation_count"] >= K.MAX_HOLD_ESCALATIONS:
        raise ApiError("ERR_HOLD_ESCALATION_LIMIT")
    record["status"] = "ESCALATED"
    record["escalation_count"] = record["escalation_count"] + 1
    store.touch(record)
    return one("family_holds", record)


@bp.route("/family-holds/<hid>/remand", methods=["POST"])
def remand_hold(hid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("note", "string")])
    record, item, engagement = _hold_context(hid)
    gates.gate3(engagement)
    gates.gate10_state(record["status"], ["ESCALATED"], HOLD_TERMINAL)
    if record["remand_count"] >= K.MAX_HOLD_ESCALATIONS:
        raise ApiError("ERR_HOLD_ESCALATION_LIMIT")
    record["status"] = "OPEN"
    record["remand_count"] = record["remand_count"] + 1
    record["resolution_note"] = req.body["note"]
    store.touch(record)
    return one("family_holds", record)


@bp.route("/family-holds/<hid>/resolve", methods=["POST"])
def resolve_hold(hid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"],
                          required=[("resolution", "string"),
                                    ("resolved_by_party_id", "string")],
                          optional=[("resolution_note", "string")],
                          enum_fields=["resolution"])
    record, item, engagement = _hold_context(hid)
    gates.resolve_body_fks(req.body)
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body["resolved_by_party_id"]])
    gates.gate4_authority(req, "DISPOSITION",
                          subject_value=item["appraised_value_cents"],
                          high_value_subject=item["appraised_value_cents"])
    gates.gate10_state(record["status"], ["OPEN", "ESCALATED"], HOLD_TERMINAL)

    record["resolved_by_party_id"] = req.body["resolved_by_party_id"]
    if req.body.get("resolution_note") is not None:
        record["resolution_note"] = req.body["resolution_note"]
    if req.body["resolution"] == "KEEP":
        record["status"] = "RESOLVED_KEEP"
        item["disposition"] = "KEEP"
        store.touch(item)
    else:
        record["status"] = "RESOLVED_RELEASE"
    store.touch(record)
    return one("family_holds", record)


@bp.route("/family-holds/<hid>/withdraw", methods=["POST"])
def withdraw_hold(hid):
    req = gates.preflight(["MOVE_MANAGER", "FAMILY_MEMBER"])
    record, item, engagement = _hold_context(hid)
    gates.gate3(engagement)
    if req.role == "FAMILY_MEMBER" and req.user_id != record["raised_by_party_id"]:
        raise ApiError("ERR_ACTOR_NOT_OWNER")
    gates.gate10_state(record["status"], ["OPEN"], HOLD_TERMINAL)
    record["status"] = "WITHDRAWN"
    store.touch(record)
    return one("family_holds", record)
