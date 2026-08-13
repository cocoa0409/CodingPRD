"""Entity serializers: strip internal helper fields (prefixed with _) before output."""

import db
from errors import err_not_found


def serialize(record: dict) -> dict:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def get_or_404(store: dict, entity_id, label: str):
    record = store.get(entity_id)
    if record is None:
        raise err_not_found(f"{label} '{entity_id}' does not exist")
    return record


def bump_version(record: dict):
    """Increment version (and updated_at) on a common-fields entity."""
    record["version"] = record.get("version", 1) + 1
    if "updated_at" in record:
        record["updated_at"] = _now()


def _now():
    from helpers import now_timestamp
    return now_timestamp()
