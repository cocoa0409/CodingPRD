"""AdtEvent append-only log helper. AdtEvent carries only id + created_at."""

from db import store, iso
from services import common


def append_adt(encounter_id, event_type, from_bed_id=None, to_bed_id=None):
    now = store.clock_now()
    ev = {
        "id": store.new_id(),
        "created_at": iso(now),
        "encounter_id": encounter_id,
        "event_type": event_type,
        "from_bed_id": from_bed_id,
        "to_bed_id": to_bed_id,
        "event_at": iso(now),
        "_created_clock": now,
    }
    store.adt_events[ev["id"]] = ev
    return ev
