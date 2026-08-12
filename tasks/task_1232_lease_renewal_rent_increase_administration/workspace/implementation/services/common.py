"""Shared helpers: entity common-field management, lookup, mutation bookkeeping."""

from db import new_id, utc_now_iso

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def new_entity():
    now = utc_now_iso()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    entity["updated_at"] = utc_now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1
