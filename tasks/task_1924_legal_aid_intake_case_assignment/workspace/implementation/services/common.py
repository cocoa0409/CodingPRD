"""Shared store helpers: lookup, stamping, unmet-need creation, list queries."""
from db import db, new_id, next_seq, now
from errors import ERR_NOT_FOUND, fail
from response import ok_list
from validators import pagination_params


def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        fail(ERR_NOT_FOUND, "Resource not found: {}".format(rid))
    return rec


def stamp_new(rec):
    """Common fields for the nine primary resources."""
    rec["created_at"] = now()
    rec["updated_at"] = now()
    rec["version"] = 1
    rec["_seq"] = next_seq()


def stamp_new_aux(rec):
    """Auxiliary resources carry only id + created_at (no updated_at/version)."""
    rec["created_at"] = now()
    rec["_seq"] = next_seq()


def touch(rec):
    """Refresh updated_at and bump version (where the entity carries one)."""
    rec["updated_at"] = now()
    if "version" in rec:
        rec["version"] += 1


def create_unmet_record(app, reason_code):
    rec = {
        "id": new_id(),
        "application_id": app["id"],
        "reason_code": reason_code,
        "case_type": app["case_type"],
        "incident_county": app["incident_county"],
    }
    stamp_new_aux(rec)
    db.unmet_records[rec["id"]] = rec
    return rec


def delete_waitlist_entry_for(application_id):
    for wid, entry in list(db.waitlist_entries.items()):
        if entry["application_id"] == application_id:
            del db.waitlist_entries[wid]


def list_response(records, serializer, order="created"):
    """Sort (created_at ASC by default; 'ranked' for the waitlist) and paginate."""
    if order == "ranked":
        records = sorted(records,
                         key=lambda r: (-r["priority_score_snapshot"],
                                        r["created_at"], r["_seq"]))
    else:
        records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
