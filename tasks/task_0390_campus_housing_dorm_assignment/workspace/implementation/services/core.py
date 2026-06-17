"""Core entity lifecycle helpers: creation, mutation/versioning, serialization,
derived-field reconciliation (rollups), and lookup."""

import db
import errors

# ---------------------------------------------------------------------------
# Constant tables
# ---------------------------------------------------------------------------
ROOM_BED_CAPACITY = {"SINGLE": 1, "DOUBLE": 2, "TRIPLE": 3, "SUITE_DOUBLE": 2}
CLASS_YEAR_RANK = {"SENIOR": 1, "JUNIOR": 2, "SOPHOMORE": 3, "FRESHMAN": 4}
TIER_FEE = {"NONE": 0, "COMMUTER": 4000, "STANDARD": 9000, "UNLIMITED": 13500}

# Audit fields that are part of every entity's public representation.
_AUDIT_FIELDS = ("id", "created_at", "updated_at", "version")


# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------
def init_record(fields):
    """Build a new record with audit fields populated."""
    ts = db.now_iso()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a record mutated: bump version, refresh updated_at."""
    rec["version"] += 1
    rec["updated_at"] = db.now_iso()


def serialize(rec):
    """Public representation: strip private bookkeeping keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(coll, entity_id):
    rec = coll.get(entity_id)
    if rec is None:
        raise errors.not_found()
    return rec


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------
def room_occupied_count(room_id):
    """occupied_bed_count = OFFERED apps reserving this room +
    Assignments on this room in {ACTIVE, SWAP_PENDING}."""
    offers = sum(
        1 for a in db.applications.values()
        if a["status"] == "OFFERED" and a["offered_room_id"] == room_id
    )
    live = sum(
        1 for a in db.assignments.values()
        if a["room_id"] == room_id and a["status"] in ("ACTIVE", "SWAP_PENDING")
    )
    return offers + live


def room_open_incident_count(room_id):
    return sum(
        1 for i in db.incident_reports.values()
        if i["room_id"] == room_id and i["status"] in ("OPEN", "ESCALATED")
    )


def derive_room_status(room):
    """Re-derive a room's posture (PRD §2.5).

    OFFLINE is sticky until restore. Otherwise: RESTRICTED when fully booked
    or carrying an open incident; OPEN when free beds and no open incidents.
    """
    if room["status"] == "OFFLINE":
        return "OFFLINE"
    if room["open_incident_count"] > 0:
        return "RESTRICTED"
    if room["occupied_bed_count"] >= room["bed_capacity"]:
        return "RESTRICTED"
    return "OPEN"


def reconcile_room(room):
    """Recompute a room's derived fields. Mark the room mutated only when a
    derived value actually changes (PRD §2.4: recomputation that changes a
    rollup is a mutation). Returns True if a mutation was recorded."""
    new_occ = room_occupied_count(room["id"])
    new_inc = room_open_incident_count(room["id"])
    prev_occ, prev_inc = room["occupied_bed_count"], room["open_incident_count"]
    room["occupied_bed_count"] = new_occ
    room["open_incident_count"] = new_inc
    new_status = derive_room_status(room)
    changed = (
        prev_occ != new_occ
        or prev_inc != new_inc
        or room["status"] != new_status
    )
    room["status"] = new_status
    if changed:
        touch(room)
        reconcile_building_for_room(room)
        return True
    # Even with no room-level change, building rollups might depend on it; the
    # building reconcile is itself no-op when nothing changed.
    reconcile_building_for_room(room)
    return False


def reconcile_building(building):
    """Recompute a building's derived bed rollups and mark it mutated."""
    rooms = [r for r in db.rooms.values() if r["building_id"] == building["id"]]
    total = sum(r["bed_capacity"] for r in rooms if r["status"] != "OFFLINE")
    occupied = sum(r["occupied_bed_count"] for r in rooms)
    changed = (
        building["total_bed_count"] != total
        or building["occupied_bed_count"] != occupied
    )
    building["total_bed_count"] = total
    building["occupied_bed_count"] = occupied
    if changed:
        touch(building)


def reconcile_building_for_room(room):
    building = db.buildings.get(room["building_id"])
    if building is not None:
        reconcile_building(building)
