"""Lockbox placements: hanging a box on a listing and recording removal (PRD §3.4)."""
from flask import Blueprint

import calc
import serialize
from core import (
    ADMIN, MEMBER, READ_ROLES, authenticate, body, db, fail, iso, lookup,
    new_common, now, ok, ordered, paginate, present, qfilter, touch,
)
from ladder import (
    assert_not_terminal, assert_owner, assert_transition, assert_version,
    require_action, require_version_field,
)

bp = Blueprint("placement", __name__)

PLACEMENT_TRANSITIONS = {"REMOVE": ("PLACED", "REMOVAL_DUE", "DELINQUENT")}


@bp.post("/lockbox-placements")
def create_placement():
    user_id, role = authenticate([ADMIN, MEMBER])
    payload = body()

    # Rung 4 — body foreign keys, in declared input order.
    lockbox = None
    listing = None
    if present(payload, "lockbox_id"):
        lockbox = lookup("lockboxes", payload["lockbox_id"])
    if present(payload, "listing_id"):
        listing = lookup("listings", payload["listing_id"])

    # Rung 5 — request shape.
    if lockbox is None:
        fail("ERR_INVALID_REQUEST", "lockbox_id is required.")
    if listing is None:
        fail("ERR_INVALID_REQUEST", "listing_id is required.")
    if listing["association_id"] != lockbox["association_id"]:
        fail("ERR_INVALID_REQUEST", "The listing belongs to a different association.")

    # Rung 6 — Member ownership of the unit.
    assert_owner(role, user_id, lockbox.get("assigned_member_id"))

    # Rung 9 — the addressed entity for the transition check is the Lockbox.
    if lockbox["status"] != "PLACED":
        assert_transition(lockbox["status"], {"PLACE": ("ASSIGNED",)}, "PLACE")
    if listing["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The listing is not ACTIVE.")

    # Rung 12 — physical-safety gate.
    if lockbox["status"] == "MISSING":
        fail("ERR_LOCKBOX_MISSING", "The lockbox is reported missing.")

    # Rung 13 — association posture gate.
    if calc.association_posture(lockbox["association_id"]) == "FROZEN":
        fail("ERR_ASSOCIATION_FROZEN", "The association posture is FROZEN.")

    # Rung 16 — linkage integrity.
    for existing in db.placements.values():
        if (existing["lockbox_id"] == lockbox["id"]
                and existing["placement_status"] in calc.ACTIVE_PLACEMENT_STATES):
            fail("ERR_PLACEMENT_ALREADY_ACTIVE", "The lockbox already carries an active placement.")

    placed_by = user_id if role == MEMBER else lockbox.get("assigned_member_id")
    rec = new_common()
    rec.update({
        "lockbox_id": lockbox["id"],
        "listing_id": listing["id"],
        "placed_by_member_id": placed_by,
        "placement_status": "PLACED",
        "billing_status": "NONE",
        "placed_at": iso(now()),
        "removal_deadline": None,
        "removed_at": None,
        "late_days": 0,
    })
    db.placements[rec["id"]] = rec

    lockbox["status"] = "PLACED"
    lockbox["current_listing_id"] = listing["id"]
    touch(lockbox)

    return ok(serialize.placement(rec), 201)


@bp.get("/lockbox-placements/<placement_id>")
def read_placement(placement_id):
    authenticate(READ_ROLES)
    return ok(serialize.placement(lookup("placements", placement_id)))


@bp.get("/lockbox-placements")
def list_placements():
    authenticate(READ_ROLES)
    rows = ordered(db.placements)
    rows = qfilter(rows, "lockbox_id")
    rows = qfilter(rows, "listing_id")
    rows = qfilter(rows, "placed_by_member_id")
    rows = qfilter(rows, "placement_status")
    rows = qfilter(rows, "billing_status")
    return paginate(rows, serialize.placement)


@bp.post("/lockbox-placements/<placement_id>/state")
def placement_state(placement_id):
    user_id, role = authenticate([ADMIN, MEMBER])
    placement = lookup("placements", placement_id)
    payload = body()

    action = require_action(payload, tuple(PLACEMENT_TRANSITIONS))
    expected = require_version_field(payload, "expected_placement_version")

    assert_owner(role, user_id, placement.get("placed_by_member_id"))
    assert_version(expected, placement)
    assert_not_terminal("placement", placement["placement_status"])
    assert_transition(placement["placement_status"], PLACEMENT_TRANSITIONS, action)

    placement["placement_status"] = "REMOVED"
    placement["removed_at"] = iso(now())
    touch(placement)

    lockbox = db.lockboxes.get(placement["lockbox_id"])
    if lockbox is not None:
        if lockbox["status"] == "PLACED":
            lockbox["status"] = "ASSIGNED"
            lockbox["current_listing_id"] = None
            touch(lockbox)
        association = db.associations.get(lockbox["association_id"])
        if association is not None:
            calc.recompute_recovery_rate(association)

    return ok(serialize.placement(placement))
