import uuid
from clock import now, format_timestamp


def new_id():
    return str(uuid.uuid4())


def make_versioned(fields):
    t = now()
    ts = format_timestamp(t)
    fields["id"] = new_id()
    fields["created_at"] = ts
    fields["updated_at"] = ts
    fields["version"] = 1
    fields["_created_dt"] = t
    return fields


def make_unversioned(fields):
    t = now()
    ts = format_timestamp(t)
    fields["id"] = new_id()
    fields["created_at"] = ts
    fields["_created_dt"] = t
    return fields


def touch(entity):
    t = now()
    entity["updated_at"] = format_timestamp(t)
    entity["version"] = entity.get("version", 0) + 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}
