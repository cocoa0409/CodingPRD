"""Common-field stamping, pagination, and body-field validation helpers."""
import math
from datetime import timedelta

from db import store, new_id, iso
from errors import err

# Non-terminal lifecycle states used by queue_depth (PRD §3.1).
QUEUE_DEPTH_STATES = {"NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CHANGE", "ON_HOLD"}
# Non-terminal lifecycle states used by load score (PRD §3.9) — same set.
LOAD_STATES = {"NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CHANGE", "ON_HOLD"}


def stamp_create(rec, with_version=True):
    """Set id/created_at/updated_at/version on a freshly created record."""
    now = store.now()
    rec["id"] = new_id()
    rec["created_at"] = now
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version on a mutation (PRD §2.4, §2.6)."""
    rec["updated_at"] = store.now()
    rec["version"] = rec.get("version", 1) + 1


def paginate(items, args):
    """Apply limit/offset pagination (PRD §2.3). items pre-sorted by caller."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            offset = 0

    total = len(items)
    window = items[offset : offset + limit]
    return window, limit, offset, total


def require_fields(body, fields):
    """ERR_VALIDATION if any required field is missing or None."""
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", "Missing required field: {}.".format(f))


def require_string(body, field):
    require_fields(body, [field])
    if not isinstance(body[field], str):
        raise err("ERR_VALIDATION", "Field {} must be a string.".format(field))
    return body[field]


def sorted_by_created(records):
    """Sort records by created_at ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


# --- counter recomputations (PRD §2.6: recomputed, not blindly incremented) ---

def recompute_queue_depth(group_id):
    grp = store.assignment_groups.get(group_id)
    if grp is None:
        return
    count = 0
    for t in store.tickets.values():
        if t.get("assignment_group_id") == group_id and t["lifecycle_state"] in QUEUE_DEPTH_STATES:
            count += 1
    grp["queue_depth"] = count


def recompute_linked_ticket_count(problem_id):
    prob = store.problems.get(problem_id)
    if prob is None:
        return
    count = 0
    for t in store.tickets.values():
        if t.get("problem_id") == problem_id and t["lifecycle_state"] not in ("CLOSED", "CANCELLED"):
            count += 1
    prob["linked_ticket_count"] = count


def recompute_open_incident_count(asset_id):
    asset = store.assets.get(asset_id)
    if asset is None:
        return
    count = 0
    for t in store.tickets.values():
        if t.get("asset_id") == asset_id and t["lifecycle_state"] not in ("RESOLVED", "CLOSED", "CANCELLED"):
            count += 1
    asset["open_incident_count"] = count


def recompute_change_tally(cr):
    """approve_count/reject_count from distinct voters (PRD §3.5)."""
    approvers = set()
    rejecters = set()
    for v in store.cab_votes.values():
        if v["change_request_id"] != cr["id"]:
            continue
        if v["decision"] == "APPROVE":
            approvers.add(v["voter_user_id"])
        elif v["decision"] == "REJECT":
            rejecters.add(v["voter_user_id"])
    cr["approve_count"] = len(approvers)
    cr["reject_count"] = len(rejecters)
