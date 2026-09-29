"""Record construction, path/FK resolution and pagination helpers."""
from db import new_id, store
from errors import ApiError
from util import fmt_dt


def base(clock_stamp, audited=True):
    record = {
        "id": new_id(),
        "_seq": store.next_seq(),
        "created_at": clock_stamp,
    }
    if audited:
        record["updated_at"] = clock_stamp
        record["version"] = 1
    return record


def resolve(collection, identifier, error_id):
    record = collection.get(identifier) if identifier is not None else None
    if record is None:
        raise ApiError(error_id)
    return record


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def apply_filters(records, spec):
    """spec: iterable of (field_name, query_value); None values are ignored."""
    out = records
    for field, value in spec:
        if value is None:
            continue
        out = [r for r in out if str(r.get(field)) == value]
    return out


def strip(record):
    return dict((k, v) for k, v in record.items() if not k.startswith("_"))


__all__ = ["base", "resolve", "paginate", "apply_filters", "strip", "fmt_dt"]
