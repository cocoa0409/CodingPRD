"""Destination residence placement plans and their rooms."""

from flask import Blueprint

import derive
import gates
import store
from routes.helpers import one, listing, filtered

bp = Blueprint("destination", __name__)

READ_ROLES = ["MOVE_MANAGER", "CLIENT", "FAMILY_MEMBER", "POWER_OF_ATTORNEY"]


@bp.route("/destination-residences", methods=["POST"])
def create_residence():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"), ("name", "string"),
                                    ("unit_type", "string"), ("address_line", "string")])
    engagement = gates.resolve_body_fks(req.body)["engagement_id"]
    gates.gate3(engagement)
    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "name": req.body["name"],
        "unit_type": req.body["unit_type"],
        "address_line": req.body["address_line"],
        "placement_status": "DRAFT",
        "placement_revision": 1,
        "approved_by_party_id": None,
        "approved_at_utc": None,
    })
    store.insert("destination_residences", record)
    return one("destination_residences", record, 201)


@bp.route("/destination-residences", methods=["GET"])
def list_residences():
    req = gates.preflight(READ_ROLES, is_list=True)
    rows = filtered(store.all_of("destination_residences"), req.args,
                    ["engagement_id", "approved_by_party_id", "placement_status"])
    return listing("destination_residences", req, rows)


@bp.route("/destination-residences/<rid>", methods=["GET"])
def read_residence(rid):
    req = gates.preflight(READ_ROLES)
    record = gates.path_record("destination_residences", rid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]))
    return one("destination_residences", record)


@bp.route("/destination-residences/<rid>/propose-placement", methods=["POST"])
def propose_placement(rid):
    gates.preflight(["MOVE_MANAGER"])
    record = gates.path_record("destination_residences", rid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["placement_status"], ["DRAFT"])
    gates.require_state(derive.residence_room_count(record["id"]) >= 1)
    record["placement_status"] = "PROPOSED"
    store.touch(record)
    return one("destination_residences", record)


@bp.route("/destination-residences/<rid>/approve-placement", methods=["POST"])
def approve_placement(rid):
    req = gates.preflight(["MOVE_MANAGER", "CLIENT", "POWER_OF_ATTORNEY"],
                          required=[("approved_by_party_id", "string")])
    record = gates.path_record("destination_residences", rid)
    gates.resolve_body_fks(req.body)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate4_ownership(req, engagement=engagement)
    gates.gate4_party_membership(engagement, [req.body["approved_by_party_id"]])
    gates.gate4_authority(req, "DISPOSITION")
    gates.gate10_state(record["placement_status"], ["PROPOSED"])

    record["placement_status"] = "APPROVED"
    record["approved_by_party_id"] = req.body["approved_by_party_id"]
    record["approved_at_utc"] = store.now_iso()
    store.touch(record)
    return one("destination_residences", record)


@bp.route("/destination-residences/<rid>/revise-placement", methods=["POST"])
def revise_placement(rid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record = gates.path_record("destination_residences", rid)
    engagement = store.get("engagements", record["engagement_id"])
    gates.gate3(engagement)
    gates.gate10_state(record["placement_status"], ["PROPOSED", "APPROVED"])

    if record["placement_status"] == "APPROVED":
        room_ids = {r["id"] for r in derive.rooms_of(record["id"])}
        blocked = any(item["assigned_room_id"] in room_ids
                      and item["handling_state"] in ("DELIVERED", "UNPACKED")
                      for item in store.all_of("inventory_items"))
        gates.require_state(not blocked)
        record["placement_revision"] = record["placement_revision"] + 1
        record["approved_by_party_id"] = None
        record["approved_at_utc"] = None

    record["placement_status"] = "DRAFT"
    store.touch(record)
    return one("destination_residences", record)


# ---------------------------------------------------------------------------
# rooms
# ---------------------------------------------------------------------------

@bp.route("/destination-rooms", methods=["POST"])
def create_room():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("destination_residence_id", "string"),
                                    ("room_type", "string"),
                                    ("nominal_linear_inches", "number"),
                                    ("nominal_volume_cft", "number")],
                          optional=[("approved_addendum_linear_inches", "number")])
    residence = gates.resolve_body_fks(req.body)["destination_residence_id"]
    engagement = store.get("engagements", residence["engagement_id"])
    gates.gate3(engagement)

    addendum = req.body.get("approved_addendum_linear_inches")
    record = store.base_record()
    record.update({
        "destination_residence_id": residence["id"],
        "room_type": req.body["room_type"],
        "nominal_linear_inches": req.body["nominal_linear_inches"],
        "nominal_volume_cft": req.body["nominal_volume_cft"],
        "approved_addendum_linear_inches": 0 if addendum is None else addendum,
    })
    store.insert("destination_rooms", record)
    return one("destination_rooms", record, 201)


@bp.route("/destination-rooms", methods=["GET"])
def list_rooms():
    req = gates.preflight(READ_ROLES, is_list=True)
    rows = filtered(store.all_of("destination_rooms"), req.args,
                    ["destination_residence_id", "room_type"])
    return listing("destination_rooms", req, rows)


@bp.route("/destination-rooms/<rid>", methods=["GET"])
def read_room(rid):
    req = gates.preflight(READ_ROLES)
    record = gates.path_record("destination_rooms", rid)
    residence = store.get("destination_residences", record["destination_residence_id"])
    gates.gate4_ownership(req, engagement=store.get("engagements", residence["engagement_id"]))
    return one("destination_rooms", record)
