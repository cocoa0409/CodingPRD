"""The basis-point waterfall for cue-sheet shares (PRD 3.8).

sum(share_bps of ALLOCATED entries) + Deliverable.unallocated_bps == 10000
after every request.
"""

import db

CUE_TOTAL_BPS = 10000
REQUIRED_STEM_NAMES = ("DRUMS", "BASS", "KEYS", "VOX", "MIX")


def deliverable_entries(deliverable_id, status=None):
    rows = [e for e in db.cue_entries.values() if e["deliverable_id"] == deliverable_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return db.by_created(rows)


def allocate(deliverable):
    """Re-run the waterfall across the package's ALLOCATED lines."""
    entries = deliverable_entries(deliverable["id"], "ALLOCATED")
    previous_unallocated = deliverable["unallocated_bps"]
    if not entries:
        deliverable["unallocated_bps"] = CUE_TOTAL_BPS
        if deliverable["unallocated_bps"] != previous_unallocated:
            db.touch(deliverable)
        return

    total_weight = sum(e["declared_weight"] for e in entries)
    shares = {}
    for entry in entries:
        shares[entry["id"]] = (CUE_TOTAL_BPS * entry["declared_weight"]) // total_weight
    remainder = CUE_TOTAL_BPS - sum(shares.values())

    order = sorted(entries, key=lambda e: (-e["declared_weight"], e["created_at"], e["_seq"]))
    for entry in order[:remainder]:
        shares[entry["id"]] += 1

    for entry in entries:
        if entry["share_bps"] != shares[entry["id"]]:
            entry["share_bps"] = shares[entry["id"]]
            db.touch(entry)
    deliverable["unallocated_bps"] = 0
    if previous_unallocated != 0:
        db.touch(deliverable)
