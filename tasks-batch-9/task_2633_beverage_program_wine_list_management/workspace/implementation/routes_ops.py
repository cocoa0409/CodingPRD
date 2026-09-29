"""The by-the-glass rail and spoilage write-offs."""
from flask import Blueprint

from core import (
    API_PREFIX,
    authorize,
    check_venue_scope,
    fail,
    get_body,
    get_list_entry,
    get_lot,
    get_slot,
    get_venue,
    get_write_off,
    new_record,
    now,
    paginate,
    q,
    respond_list,
    respond_object,
    serialize,
    sort_default,
    store,
    touch,
    validate_body,
)
from calc import (
    LIVE_VERSION_STATES,
    btg_close_split,
    cost_pinned_lot,
    lot_available,
    preservation_expires_at,
)
from cascade import (
    apply_ledger_totals,
    recompute_bin_of_lot,
    refresh_availability,
    refresh_contest_points_for_entries,
    venue_id_of_entry,
    write_depletion,
)

bp = Blueprint("ops", __name__)

OPS_READ_ROLES = ["BeverageDirector", "VenueSommelier", "Controller", "ComplianceOfficer"]

SLOT_SPEC = [
    {"name": "venue_id", "type": "string", "required": True},
    {"name": "list_entry_id", "type": "string", "required": True},
    {"name": "lot_id", "type": "string", "required": True},
    {"name": "slot_index", "type": "int", "required": True, "min": 1, "max": 24},
    {
        "name": "preservation_method",
        "type": "string",
        "required": True,
        "enum": ["ARGON", "VACUUM", "COOLER", "NONE"],
    },
]


@bp.post(API_PREFIX + "/btg-slots")
def create_slot():
    user_id, role = authorize("VenueSommelier")
    body = get_body()
    check_venue_scope(role, user_id, body.get("venue_id"))
    if body.get("venue_id") is not None:
        get_venue(body["venue_id"])
    entry = None
    if body.get("list_entry_id") is not None:
        entry = get_list_entry(body["list_entry_id"])
    lot = None
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    validate_body(body, SLOT_SPEC)

    version = store.list_versions.get(entry["list_version_id"])
    if version is None or version["state"] not in LIVE_VERSION_STATES:
        fail("ERR_LIST_VERSION_NOT_PUBLISHED", "The listing is not on a live list version.")
    if lot["state"] != "ON_HAND":
        fail("ERR_LOT_NOT_ON_HAND", "That lot is not on hand.")

    instant = now()
    occupants = [
        s
        for s in store.btg_slots.values()
        if s["venue_id"] == body["venue_id"]
        and int(s["slot_index"]) == int(body["slot_index"])
        and s["state"] in ("OPEN", "EXPIRED")
    ]
    for occupant in occupants:
        if occupant["opened_at"] <= instant <= occupant["preservation_expires_at"]:
            fail("ERR_SLOT_OCCUPIED", "That rail position is occupied.")

    if lot["wine_id"] != entry["wine_id"] or lot["venue_id"] != body["venue_id"]:
        fail("ERR_SLOT_WINE_MISMATCH", "The lot does not match the listing's wine and venue.")
    if not entry["by_the_glass"]:
        fail("ERR_ENTRY_NOT_BY_THE_GLASS", "That listing is not in the by-the-glass rotation.")
    if lot_available(lot) < 1:
        fail("ERR_INSUFFICIENT_BOTTLES", "That lot has no bottle left to commit.")

    # Accepting the new slot sweeps any stale OPEN occupant of the position.
    for occupant in occupants:
        if occupant["state"] == "OPEN" and instant > occupant["preservation_expires_at"]:
            occupant["state"] = "EXPIRED"
            touch(occupant)

    wine = store.wines.get(entry["wine_id"])
    rec = new_record(
        {
            "venue_id": body["venue_id"],
            "list_entry_id": body["list_entry_id"],
            "lot_id": body["lot_id"],
            "slot_index": body["slot_index"],
            "preservation_method": body["preservation_method"],
            "opened_at": instant,
            "preservation_expires_at": preservation_expires_at(
                instant, wine["category"], body["preservation_method"]
            ),
            "effective_pours": entry["effective_pours"],
            "pours_sold": 0,
            "staff_education_pours": 0,
            "spoiled_pours": 0,
            "state": "OPEN",
        }
    )
    store.btg_slots[rec["id"]] = rec
    lot["bottles_committed"] = int(lot["bottles_committed"]) + 1
    touch(lot)
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/btg-slots/<btg_slot_id>")
def read_slot(btg_slot_id):
    authorize(OPS_READ_ROLES)
    return respond_object(serialize(get_slot(btg_slot_id)))


@bp.get(API_PREFIX + "/btg-slots")
def list_slots():
    authorize(OPS_READ_ROLES)
    rows = list(store.btg_slots.values())
    for field in ("venue_id", "list_entry_id", "lot_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = sorted(rows, key=lambda r: (r["slot_index"], r["created_at"], r["_seq"]))
    page, meta = paginate(rows)
    return respond_list([serialize(r) for r in page], meta)


CLOSE_SPEC = [
    {"name": "pours_sold", "type": "int", "required": True, "min": 0},
    {"name": "staff_education_pours", "type": "int", "min": 0},
]


@bp.post(API_PREFIX + "/btg-slots/<btg_slot_id>/close")
def close_slot(btg_slot_id):
    user_id, role = authorize("VenueSommelier")
    slot = get_slot(btg_slot_id)
    check_venue_scope(role, user_id, slot["venue_id"])
    body = get_body()
    validate_body(body, CLOSE_SPEC)

    if slot["state"] != "OPEN":
        fail("ERR_SLOT_NOT_OPEN", "Only an open slot may be closed.")
    pours_sold = int(body["pours_sold"])
    education_pours = int(body.get("staff_education_pours") or 0)
    effective_pours = int(slot["effective_pours"])
    if pours_sold + education_pours > effective_pours:
        fail("ERR_POURS_EXCEED_BOTTLE", "The submitted pours exceed what the bottle holds.")

    slot["pours_sold"] = pours_sold
    slot["staff_education_pours"] = education_pours

    if now() > slot["preservation_expires_at"]:
        # No ledger entry, no revenue, and the bottle stays committed to the slot.
        slot["spoiled_pours"] = effective_pours
        slot["state"] = "EXPIRED"
        touch(slot)
        return respond_object(serialize(slot))

    lot = store.inventory_lots.get(slot["lot_id"])
    entry = store.list_entries.get(slot["list_entry_id"])
    venue = store.venues.get(slot["venue_id"])
    bottle_cogs = cost_pinned_lot(venue, lot, 1)
    spoiled_pours = effective_pours - pours_sold - education_pours
    sale_cogs, edu_cogs, spoil_cogs = btg_close_split(
        bottle_cogs, effective_pours, pours_sold, education_pours
    )
    revenue = pours_sold * int(entry["glass_price_cents"] or 0)

    written = []
    if pours_sold > 0:
        written.append(
            write_depletion(
                slot["venue_id"], lot["wine_id"], lot["id"], "SALE_BTG", 1, pours_sold,
                sale_cogs, revenue, list_entry_id=entry["id"], btg_slot_id=slot["id"],
            )
        )
    if education_pours > 0:
        written.append(
            write_depletion(
                slot["venue_id"], lot["wine_id"], lot["id"], "STAFF_EDUCATION", 0,
                education_pours, edu_cogs, 0, list_entry_id=entry["id"],
                btg_slot_id=slot["id"],
            )
        )
    if spoiled_pours > 0:
        written.append(
            write_depletion(
                slot["venue_id"], lot["wine_id"], lot["id"], "SPOILAGE", 0, spoiled_pours,
                spoil_cogs, 0, list_entry_id=entry["id"], btg_slot_id=slot["id"],
            )
        )

    slot["spoiled_pours"] = spoiled_pours
    slot["state"] = "CLOSED"
    touch(slot)

    lot["bottles_committed"] = int(lot["bottles_committed"]) - 1
    lot["bottles_on_hand"] = int(lot["bottles_on_hand"]) - 1
    depleted = int(lot["bottles_on_hand"]) <= 0
    if depleted:
        lot["state"] = "DEPLETED"
    touch(lot)
    recompute_bin_of_lot(lot)
    if depleted:
        refresh_availability(
            lot["venue_id"], lot["wine_id"], live_only=True, direction="deplete"
        )
    apply_ledger_totals(venue, written)
    refresh_contest_points_for_entries(written)
    return respond_object(serialize(slot))


# ---------------------------------------------------------------------------
# Spoilage write-offs (PRD 3.8)
# ---------------------------------------------------------------------------
WRITE_OFF_SPEC = [
    {"name": "venue_id", "type": "string", "required": True},
    {"name": "lot_id", "type": "string", "required": True},
    {"name": "btg_slot_id", "type": "string"},
    {"name": "bottles", "type": "int", "required": True, "min": 1},
    {
        "name": "reason_code",
        "type": "string",
        "required": True,
        "enum": ["CORKED", "OXIDIZED", "BREAKAGE", "PRESERVATION_EXPIRY", "TEMPERATURE"],
    },
    {"name": "narrative", "type": "string", "required": True, "min_len": 1, "max_len": 500},
]

TERMINAL_REASONS = ("PRESERVATION_EXPIRY", "TEMPERATURE")


@bp.post(API_PREFIX + "/spoilage-write-offs")
def create_write_off():
    user_id, role = authorize("VenueSommelier", "Controller")
    body = get_body()
    check_venue_scope(role, user_id, body.get("venue_id"))
    if body.get("venue_id") is not None:
        get_venue(body["venue_id"])
    lot = None
    if body.get("lot_id") is not None:
        lot = get_lot(body["lot_id"])
    slot = None
    if body.get("btg_slot_id") is not None:
        slot = get_slot(body["btg_slot_id"])
    validate_body(body, WRITE_OFF_SPEC)

    if lot["state"] != "ON_HAND":
        fail("ERR_LOT_NOT_ON_HAND", "That lot is not on hand.")
    if lot["venue_id"] != body["venue_id"]:
        fail("ERR_LOT_VENUE_MISMATCH", "That lot belongs to another venue.")
    if slot is not None:
        if (
            slot["state"] != "EXPIRED"
            or slot["lot_id"] != body["lot_id"]
            or int(body["bottles"]) != 1
        ):
            fail("ERR_SLOT_WRITE_OFF_INVALID", "The named slot cannot back this write-off.")
    if int(body["bottles"]) > lot_available(lot):
        fail("ERR_INSUFFICIENT_BOTTLES", "The lot cannot give up that many bottles.")

    rec = new_record(
        {
            "venue_id": body["venue_id"],
            "lot_id": body["lot_id"],
            "btg_slot_id": body.get("btg_slot_id"),
            "bottles": body["bottles"],
            "reason_code": body["reason_code"],
            "narrative": body["narrative"],
            "state": "SUBMITTED",
            "submitted_by_user_id": user_id,
            "approved_by_user_id": None,
            "cogs_cents": 0,
            "resolution_note": None,
        }
    )
    store.spoilage_write_offs[rec["id"]] = rec
    return respond_object(serialize(rec), 201)


@bp.get(API_PREFIX + "/spoilage-write-offs/<write_off_id>")
def read_write_off(write_off_id):
    authorize(OPS_READ_ROLES)
    return respond_object(serialize(get_write_off(write_off_id)))


@bp.get(API_PREFIX + "/spoilage-write-offs")
def list_write_offs():
    authorize(OPS_READ_ROLES)
    rows = list(store.spoilage_write_offs.values())
    for field in ("venue_id", "lot_id", "btg_slot_id", "state"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, meta = paginate(sort_default(rows))
    return respond_list([serialize(r) for r in page], meta)


@bp.post(API_PREFIX + "/spoilage-write-offs/<write_off_id>/approve")
def approve_write_off(write_off_id):
    user_id, role = authorize("Controller")
    write_off = get_write_off(write_off_id)
    if write_off["state"] != "SUBMITTED":
        fail("ERR_WRITE_OFF_NOT_SUBMITTED", "Only a submitted write-off may be approved.")
    if str(user_id) == str(write_off["submitted_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES", "The approver must differ from the submitter.")
    lot = store.inventory_lots.get(write_off["lot_id"])
    if lot is None or lot["state"] != "ON_HAND":
        fail("ERR_LOT_NOT_ON_HAND", "That lot is not on hand.")
    bottles = int(write_off["bottles"])
    allowance = lot_available(lot)
    if write_off.get("btg_slot_id"):
        # The expired slot is holding precisely the bottle being written off.
        allowance += 1
    if bottles > allowance:
        fail("ERR_INSUFFICIENT_BOTTLES", "The lot cannot give up that many bottles.")

    venue = store.venues.get(write_off["venue_id"])
    cogs = cost_pinned_lot(venue, lot, bottles)
    entry = write_depletion(
        write_off["venue_id"], lot["wine_id"], lot["id"], "SPOILAGE", bottles, 0, cogs, 0,
        write_off_id=write_off["id"],
    )

    write_off["state"] = "APPROVED"
    write_off["approved_by_user_id"] = user_id
    write_off["cogs_cents"] = cogs
    touch(write_off)

    lot["bottles_on_hand"] = int(lot["bottles_on_hand"]) - bottles
    depleted = False
    if int(lot["bottles_on_hand"]) <= 0:
        lot["state"] = (
            "WRITTEN_OFF" if write_off["reason_code"] in TERMINAL_REASONS else "DEPLETED"
        )
        depleted = True
    slot = store.btg_slots.get(write_off.get("btg_slot_id")) if write_off.get("btg_slot_id") else None
    if slot is not None and slot["state"] == "EXPIRED":
        slot["state"] = "WRITTEN_OFF"
        touch(slot)
        lot["bottles_committed"] = int(lot["bottles_committed"]) - 1
    touch(lot)
    recompute_bin_of_lot(lot)
    apply_ledger_totals(venue, [entry])
    if depleted:
        refresh_availability(
            lot["venue_id"], lot["wine_id"], live_only=True, direction="deplete"
        )
    return respond_object(serialize(write_off))


NOTE_SPEC = [{"name": "note", "type": "string", "required": True, "min_len": 1, "max_len": 500}]


@bp.post(API_PREFIX + "/spoilage-write-offs/<write_off_id>/reject")
def reject_write_off(write_off_id):
    user_id, role = authorize("Controller")
    write_off = get_write_off(write_off_id)
    body = get_body()
    validate_body(body, NOTE_SPEC)
    if write_off["state"] != "SUBMITTED":
        fail("ERR_WRITE_OFF_NOT_SUBMITTED", "Only a submitted write-off may be rejected.")
    if str(user_id) == str(write_off["submitted_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES", "The rejecter must differ from the submitter.")
    write_off["state"] = "REJECTED"
    write_off["resolution_note"] = body["note"]
    touch(write_off)
    return respond_object(serialize(write_off))


@bp.post(API_PREFIX + "/spoilage-write-offs/<write_off_id>/reverse")
def reverse_write_off(write_off_id):
    user_id, role = authorize("Controller")
    write_off = get_write_off(write_off_id)
    body = get_body()
    validate_body(body, NOTE_SPEC)
    if write_off["state"] != "APPROVED":
        fail("ERR_WRITE_OFF_NOT_APPROVED", "Only an approved write-off may be reversed.")
    lot = store.inventory_lots.get(write_off["lot_id"])
    if lot is None or lot["state"] not in ("ON_HAND", "DEPLETED"):
        fail("ERR_LOT_NOT_ON_HAND", "That lot is frozen and cannot be restored.")

    bottles = int(write_off["bottles"])
    cogs = int(write_off["cogs_cents"] or 0)
    venue = store.venues.get(write_off["venue_id"])
    entry = write_depletion(
        write_off["venue_id"], lot["wine_id"], lot["id"], "REVERSAL", -bottles, 0, -cogs, 0,
        write_off_id=write_off["id"],
    )

    write_off["state"] = "REVERSED"
    write_off["resolution_note"] = body["note"]
    touch(write_off)

    lot["bottles_on_hand"] = int(lot["bottles_on_hand"]) + bottles
    if lot["state"] == "DEPLETED":
        lot["state"] = "ON_HAND"
    slot = store.btg_slots.get(write_off.get("btg_slot_id")) if write_off.get("btg_slot_id") else None
    if slot is not None and slot["state"] == "WRITTEN_OFF":
        slot["state"] = "EXPIRED"
        touch(slot)
        lot["bottles_committed"] = int(lot["bottles_committed"]) + 1
    touch(lot)
    recompute_bin_of_lot(lot)
    apply_ledger_totals(venue, [entry])
    refresh_availability(lot["venue_id"], lot["wine_id"], live_only=True, direction="restock")
    return respond_object(serialize(write_off))
