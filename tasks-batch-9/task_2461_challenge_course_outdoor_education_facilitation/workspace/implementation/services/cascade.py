"""The three named cascades of PRD 2.6 and their compensating halves."""
from db import store, touch, clock_date, by_created_at

from services import constants as C
from services import derive


def _bookings_in_created_order(booking_ids):
    rows = [store.bookings[bid] for bid in set(booking_ids) if bid in store.bookings]
    return by_created_at(rows)


def block_scheduled_blocks(element):
    """SCHEDULED blocks on the element move to BLOCKED_UNSAFE, then their
    CONFIRMED bookings move to AT_RISK.

    Blocks are processed in ascending sequence_index then ascending created_at.
    """
    blocks = [b for b in derive.blocks_of_element(element["id"]) if b["status"] == "SCHEDULED"]
    touched_bookings = []
    for block in blocks:
        block["status"] = "BLOCKED_UNSAFE"
        touch(block)
        touched_bookings.append(block["booking_id"])
    for booking in _bookings_in_created_order(touched_bookings):
        if booking["status"] == "CONFIRMED":
            booking["status"] = "AT_RISK"
            touch(booking)
    return bool(blocks)


def restore_blocked_blocks(element):
    """The compensating half: BLOCKED_UNSAFE blocks walk back to SCHEDULED and
    bookings whose blocked_block_count has fallen to zero return to CONFIRMED."""
    blocks = [b for b in derive.blocks_of_element(element["id"]) if b["status"] == "BLOCKED_UNSAFE"]
    touched_bookings = []
    for block in blocks:
        block["status"] = "SCHEDULED"
        touch(block)
        touched_bookings.append(block["booking_id"])
    for booking in _bookings_in_created_order(touched_bookings):
        if booking["status"] == "AT_RISK" and derive.blocked_block_count(booking["id"]) == 0:
            booking["status"] = "CONFIRMED"
            touch(booking)


def quarantine_rigged_equipment(element):
    """IN_SERVICE hardware rigged to the element moves to QUARANTINED, in
    ascending created_at order."""
    items = [
        i for i in derive.equipment_of_element(element["id"])
        if i["status"] == "IN_SERVICE"
    ]
    for item in items:
        item["status"] = "QUARANTINED"
        touch(item)
    return bool(items)


def release_rigged_equipment(element):
    """QUARANTINED hardware returns to IN_SERVICE, but only while still viable."""
    items = [
        i for i in derive.equipment_of_element(element["id"])
        if i["status"] == "QUARANTINED"
    ]
    for item in items:
        if derive.equipment_viable(item):
            item["status"] = "IN_SERVICE"
            touch(item)


def element_to_restricted(element, restricting_log_id=None):
    """Cascade A core: element leaves SERVICEABLE for RESTRICTED."""
    element["status"] = "RESTRICTED"
    element["restricting_log_id"] = restricting_log_id
    touch(element)
    block_scheduled_blocks(element)


def element_to_out_of_service(element):
    """Cascade B in full: quarantine hardware, lose belay readiness, then fan the
    SCHEDULED blocks and their CONFIRMED bookings out."""
    element["status"] = "OUT_OF_SERVICE"
    element["restricting_log_id"] = None
    touch(element)
    quarantine_rigged_equipment(element)
    block_scheduled_blocks(element)


def cascade_weather_closed(course):
    """Cascade C: IN_PROGRESS blocks suspend, their CONFIRMED bookings hold."""
    blocks = []
    for booking in derive.bookings_of_course(course["id"]):
        blocks.extend(derive.blocks_of_booking(booking["id"]))
    blocks = [b for b in blocks if b["status"] == "IN_PROGRESS"]
    blocks.sort(key=lambda b: (b["sequence_index"], b["created_at"], b["_seq"]))
    touched_bookings = []
    for block in blocks:
        block["status"] = "SUSPENDED"
        touch(block)
        touched_bookings.append(block["booking_id"])
    for booking in _bookings_in_created_order(touched_bookings):
        if booking["status"] == "CONFIRMED":
            booking["status"] = "WEATHER_HOLD"
            touch(booking)


def release_weather_holds(course):
    """Daily-open step eight: WEATHER_HOLD bookings return to CONFIRMED in
    ascending created_at order."""
    for booking in derive.bookings_of_course(course["id"]):
        if booking["status"] == "WEATHER_HOLD":
            booking["status"] = "CONFIRMED"
            touch(booking)


def propagate_belay_loss(element, was_ready):
    """When readiness stops being true, dependent SCHEDULED blocks are pushed to
    BLOCKED_UNSAFE and their CONFIRMED bookings to AT_RISK."""
    if not was_ready:
        return False
    if derive.belay_ready(element):
        return False
    return block_scheduled_blocks(element)


def abandon_open_blocks(booking):
    """Cancellation: every non-terminal block of the booking moves to ABANDONED."""
    for block in derive.blocks_of_booking(booking["id"]):
        if block["status"] not in C.TERMINAL_BLOCK_STATUSES:
            block["status"] = "ABANDONED"
            touch(block)


def maybe_deliver(booking):
    """Bubble-up: CONFIRMED -> DELIVERED once every block is terminal."""
    if booking["status"] != "CONFIRMED":
        return False
    blocks = derive.blocks_of_booking(booking["id"])
    if not blocks:
        return False
    for block in blocks:
        if block["status"] not in C.TERMINAL_BLOCK_STATUSES:
            return False
    booking["status"] = "DELIVERED"
    booking["retained_cents"] = booking["deposit_allocated_cents"]
    booking["deposit_allocated_cents"] = 0
    touch(booking)
    client = store.group_clients.get(booking["group_client_id"])
    if client is not None:
        touch(client)
    return True
