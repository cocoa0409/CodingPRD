"""Shared helpers: body parsing, field validation, common fields."""

import re
import uuid
from datetime import datetime, timezone

from db import store, format_iso
from errors import validation, not_found


def new_id():
    return str(uuid.uuid4())


def now_stamp():
    return format_iso(store.now())


def make_common_fields():
    ts = now_stamp()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(record):
    """Bump updated_at and version on a mutation."""
    record["updated_at"] = now_stamp()
    record["version"] += 1


def touch_no_version(record):
    record["updated_at"] = now_stamp()


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise validation(f"Missing required field: {name}")
    return body[name]


def optional_field(body, name, default=None):
    v = body.get(name, default)
    return v


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise validation(f"Field {name} must be a non-empty string")
    return v


def optional_string(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise validation(f"Field {name} must be a string")
    return v


def require_int(body, name, min_v=None, max_v=None):
    v = require_field(body, name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise validation(f"Field {name} must be an integer")
    if min_v is not None and v < min_v:
        raise validation(f"Field {name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise validation(f"Field {name} must be <= {max_v}")
    return v


def optional_int(body, name, default=None, min_v=None, max_v=None):
    v = body.get(name, default)
    if v is None:
        return v
    if not isinstance(v, int) or isinstance(v, bool):
        raise validation(f"Field {name} must be an integer")
    if min_v is not None and v < min_v:
        raise validation(f"Field {name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise validation(f"Field {name} must be <= {max_v}")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise validation(f"Field {name} must be a boolean")
    return v


def optional_bool(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, bool):
        raise validation(f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise validation(f"Field {name} must be one of {sorted(allowed)}")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_date(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise validation(f"Field {name} must be a YYYY-MM-DD date")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise validation(f"Field {name} must be a valid YYYY-MM-DD date")
    return v


def parse_iso8601(value, field="to_iso8601"):
    """Parse an ISO-8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise validation(f"Field {field} must be an ISO 8601 string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise validation(f"Field {field} must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_str(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---- entity lookups (raise ERR_NOT_FOUND) ----

def get_job(job_id):
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("PackOutJob not found")
    return job


def get_room(room_id):
    room = store.rooms.get(room_id)
    if room is None:
        raise not_found("Room not found")
    return room


def get_item(item_id):
    item = store.items.get(item_id)
    if item is None:
        raise not_found("Item not found")
    return item


def get_vault(vault_id):
    vault = store.vaults.get(vault_id)
    if vault is None:
        raise not_found("Vault not found")
    return vault


def get_placement(placement_id):
    p = store.placements.get(placement_id)
    if p is None:
        raise not_found("StoragePlacement not found")
    return p


def get_subcontractor(sub_id):
    s = store.subcontractors.get(sub_id)
    if s is None:
        raise not_found("Subcontractor not found")
    return s


def get_referral(ref_id):
    r = store.referrals.get(ref_id)
    if r is None:
        raise not_found("SpecialtyReferral not found")
    return r


def get_claim(claim_id):
    c = store.claims.get(claim_id)
    if c is None:
        raise not_found("HandlingClaim not found")
    return c


def get_schedule(sched_id):
    s = store.schedules.get(sched_id)
    if s is None:
        raise not_found("PackBackSchedule not found")
    return s


def get_statement(stmt_id):
    s = store.statements.get(stmt_id)
    if s is None:
        raise not_found("StorageStatement not found")
    return s


def get_invoice(inv_id):
    inv = store.invoices.get(inv_id)
    if inv is None:
        raise not_found("CarrierInvoice not found")
    return inv


def get_disposal_record(rec_id):
    r = store.disposal_records.get(rec_id)
    if r is None:
        raise not_found("DisposalRecord not found")
    return r


def get_cleaning_task(task_id):
    t = store.cleaning_tasks.get(task_id)
    if t is None:
        raise not_found("CleaningTask not found")
    return t


def job_of_item(item):
    room = store.rooms.get(item["room_id"])
    if room is None:
        return None
    return store.jobs.get(room["job_id"])


def job_of_placement(placement):
    item = store.items.get(placement["item_id"])
    if item is None:
        return None
    return job_of_item(item)


def items_of_job(job_id):
    room_ids = {r["id"] for r in store.rooms.values() if r["job_id"] == job_id}
    return [i for i in store.items.values() if i["room_id"] in room_ids]


def items_of_room(room_id):
    return [i for i in store.items.values() if i["room_id"] == room_id]


def placements_of_item(item_id):
    return [p for p in store.placements.values() if p["item_id"] == item_id]


def active_placement_of_item(item_id):
    for p in store.placements.values():
        if p["item_id"] == item_id and p["status"] == "ACTIVE":
            return p
    return None


def referrals_of_item(item_id):
    return [r for r in store.referrals.values() if r["item_id"] == item_id]


def claims_of_item(item_id):
    return [c for c in store.claims.values() if c["item_id"] == item_id]
