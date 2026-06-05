"""Cross-entity state-machine orchestration shared across routes.

These helpers implement the cascading side effects from scaffold §1.2 and
PRD §3 (LPN flips, order/wave bubbling, allocation release).
"""
from common import touch
from db import store
import calc


# ---------------------------------------------------------------------------
# LPN reservation-driven flips (PRD §3.5)
# ---------------------------------------------------------------------------
def maybe_flip_lpn_on_reserve(lpn):
    """After creating/committing a reservation: if the LPN is now fully reserved
    and STORED, drive STORED -> ALLOCATED."""
    if lpn["disposition"] != "STORED":
        return
    if calc.lpn_reserved(lpn["id"]) == lpn["qty"]:
        lpn["disposition"] = "ALLOCATED"
        touch(lpn)


def maybe_flip_lpn_on_release(lpn):
    """After releasing a reservation: if the LPN is ALLOCATED and no longer fully
    reserved, revert ALLOCATED -> STORED."""
    if lpn["disposition"] != "ALLOCATED":
        return
    if calc.lpn_reserved(lpn["id"]) < lpn["qty"]:
        lpn["disposition"] = "STORED"
        touch(lpn)


# ---------------------------------------------------------------------------
# Allocation release (used by allocation cancel, pick short, pick cancel)
# PRD §3.6, §3.9
# ---------------------------------------------------------------------------
def release_allocation(alloc):
    """RESERVED -> RELEASED with full cascade. Caller guarantees status==RESERVED."""
    alloc["status"] = "RELEASED"
    touch(alloc)
    line = store.order_lines.get(alloc["order_line_id"])
    if line is not None:
        calc.refresh_order_line(line)
    lpn = store.license_plates.get(alloc["lpn_id"])
    if lpn is not None:
        maybe_flip_lpn_on_release(lpn)


# ---------------------------------------------------------------------------
# Order bubbling (PRD §3.9)
# ---------------------------------------------------------------------------
def maybe_bubble_order_picked(order):
    """If order is PICKING and every line fully picked, bubble PICKING -> PICKED."""
    if order["status"] != "PICKING":
        return
    lines = [l for l in store.order_lines.values() if l["order_id"] == order["id"]]
    if not lines:
        return
    for line in lines:
        calc.refresh_order_line(line)
        if line["picked_qty"] != line["ordered_qty"]:
            return
    order["status"] = "PICKED"
    touch(order)


# ---------------------------------------------------------------------------
# Wave bubbling (PRD §3.7)
# ---------------------------------------------------------------------------
def maybe_bubble_wave_picked(wave):
    """If wave fulfillment is PICKING and no pick task is PENDING/IN_PROGRESS with
    >=1 PICKED, bubble fulfillment PICKING->PICKED and release RELEASED->CLOSED."""
    if wave["fulfillment_status"] != "PICKING":
        return
    tasks = [t for t in store.pick_tasks.values() if t["wave_id"] == wave["id"]]
    if not tasks:
        return
    if any(t["status"] in ("PENDING", "IN_PROGRESS") for t in tasks):
        return
    if not any(t["status"] == "PICKED" for t in tasks):
        return
    wave["fulfillment_status"] = "PICKED"
    touch(wave)
    if wave["release_status"] == "RELEASED":
        wave["release_status"] = "CLOSED"
        touch(wave)


# ---------------------------------------------------------------------------
# ASN bubbling (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def maybe_bubble_asn_closed(asn):
    """If ASN is PUT_AWAY and every putaway task of its LPNs is terminal with
    >=1 COMPLETED, bubble PUT_AWAY -> CLOSED."""
    if asn["status"] != "PUT_AWAY":
        return
    lpn_ids = {
        lp["id"]
        for lp in store.license_plates.values()
        if lp["source_asn_id"] == asn["id"]
    }
    tasks = [t for t in store.putaway_tasks.values() if t["lpn_id"] in lpn_ids]
    if not tasks:
        return
    if any(t["status"] not in ("COMPLETED", "CANCELLED") for t in tasks):
        return
    if not any(t["status"] == "COMPLETED" for t in tasks):
        return
    asn["status"] = "CLOSED"
    touch(asn)
