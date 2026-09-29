"""The budget waterfall and the append-only ledger of record (PRD 2.6)."""

import db
from errors import ApiError
from services import calc


def buckets_for(source_type, channel):
    order = [calc.FAMILY_DEDICATED]
    if source_type == "MEDIA_FLIGHT":
        order.append(calc.POOL_BY_TYPE[channel["channel_type"]])
    order.append("FLEX_RESERVE")
    return order


def write_entry(program, family, bucket, entry_type, delta_cents,
                source_type, source_id, reason):
    entry = {
        "id": db.new_id(),
        "program_id": program["id"],
        "job_family_id": family["id"],
        "bucket": bucket,
        "entry_type": entry_type,
        "delta_cents": delta_cents,
        "source_type": source_type,
        "source_id": source_id,
        "reason": reason,
        "sequence_no": calc.next_sequence_no(program["id"]),
        "created_at": db.wall_now(),
        "_released": False,
    }
    db.ledger[entry["id"]] = entry
    return entry


def plan(program, family, need, source_type, channel=None):
    """Walk the waterfall; raises ERR_MEDIA_BUDGET_EXHAUSTED before any write."""
    remaining = need
    draws = []
    for bucket in buckets_for(source_type, channel):
        if remaining == 0:
            break
        available = calc.bucket_available(program, family, bucket)
        draw = max(0, min(remaining, available))
        if draw > 0:
            draws.append((bucket, draw))
            remaining -= draw
    if remaining > 0:
        raise ApiError("ERR_MEDIA_BUDGET_EXHAUSTED",
                       "The budget waterfall cannot fund %d cents in full." % need)
    return draws


def reserve(program, family, need, source_type, source_id, reason, channel=None):
    """Fund `need` in full or raise; writes one RESERVE entry per drawn bucket."""
    draws = plan(program, family, need, source_type, channel)
    for bucket, amount in draws:
        write_entry(program, family, bucket, "RESERVE", amount,
                    source_type, source_id, reason)
    return draws


def open_reserves(source_id):
    entries = [e for e in db.ledger.values()
               if e["source_id"] == source_id
               and e["entry_type"] == "RESERVE"
               and not e["_released"]]
    return sorted(entries, key=lambda e: e["sequence_no"])


def release(program, source_id, reason):
    """Mirror every outstanding RESERVE of a source; True when money moved."""
    outstanding = open_reserves(source_id)
    for entry in outstanding:
        family = db.job_families[entry["job_family_id"]]
        write_entry(program, family, entry["bucket"], "RELEASE",
                    -entry["delta_cents"], entry["source_type"],
                    source_id, reason)
        entry["_released"] = True
    return bool(outstanding)
