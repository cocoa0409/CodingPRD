"""Shared box / box-item transitions used from several endpoints (PRD 3.3)."""

import derive
import store

NON_TERMINAL = ("ALLOCATED", "SHIPPED", "WITH_MEMBER", "RETURNING")


def next_slot_index(box_id):
    return len(derive.box_items(box_id))


def maybe_close_box(box):
    """RETURN_STARTED -> CLOSED once no item of the box is still non-terminal."""
    if box["status"] != "RETURN_STARTED":
        return
    for item in derive.box_items(box["id"]):
        if item["fulfillment_status"] in NON_TERMINAL:
            return
    box["status"] = "CLOSED"
    store.touch(box)


def start_return_on_box(box):
    if box["status"] == "DELIVERED":
        box["status"] = "RETURN_STARTED"
        store.touch(box)


def box_of_item(item):
    return store.get("boxes", item["box_id"])


def member_of_item(item):
    box = box_of_item(item)
    if box is None:
        return None
    return store.get("members", box["member_id"])


def cycle_of_item(item):
    box = box_of_item(item)
    if box is None:
        return None
    return store.get("cycles", box["cycle_id"])
