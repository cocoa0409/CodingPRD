"""Entity construction helpers: common fields + version/timestamp management."""
import db


def base_fields():
    ts = db.now_iso()
    return {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Mutation bookkeeping: bump version and updated_at."""
    entity["version"] += 1
    entity["updated_at"] = db.now_iso()
    return entity
