"""Shared helpers: auth, common-field stamping, versioning, derived-field
recomputation, and the cross-aggregate cascades."""
from datetime import datetime, timedelta, timezone

from db import db, new_id, next_seq
from errors import err
from response import now_iso
import calc

VALID_ROLES = {"PlatformOps", "ProgramAdmin", "Driver", "Rider"}
ENTITY_ROLES = {"Driver", "Rider"}

RIDER_BUFFER_MIN = 15          # PRD §3.6: "fifteen minutes"
MATCH_EXPIRY_DAYS = 14         # PRD §3.4: "fourteen days"


# =========================================================================
# Auth
# =========================================================================
class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth(headers):
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers")
    return Auth(user_id, role)


def require_roles(auth, allowed):
    if auth.role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")


def require_ownership(auth, owner_id):
    """For entity-backed roles (Driver/Rider), X-User-ID must equal owner_id."""
    if auth.role in ENTITY_ROLES and auth.user_id != owner_id:
        raise err("ERR_FORBIDDEN", "Acting principal does not own this resource")


# =========================================================================
# Common fields / versioning
# =========================================================================
def clock_iso():
    """ISO 8601 UTC timestamp (three fractional digits) from the simulation clock.

    PRD §2.10: the platform reads "now" from a controllable logical clock rather
    than the wall clock; resources are persisted relative to that clock so the
    periodic batch's "more than fourteen days before the current clock" comparison
    against `created_at` is coherent.
    """
    dt = db.clock_now
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_new(obj, versioned=True):
    ts = clock_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["_seq"] = next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Mutation bump: refresh updated_at and increment version (if versioned)."""
    if "version" in obj:
        obj["updated_at"] = clock_iso()
        obj["version"] += 1


def public(obj):
    """Strip internal fields (those prefixed with '_') for serialization."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# =========================================================================
# Body / field validation helpers
# =========================================================================
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def as_int(body, key, required=True, default=None, minimum=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {key} below minimum {minimum}")
    return v


def as_number(body, key, required=True, default=None, gt=None, ge=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be a number")
    if gt is not None and not v > gt:
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be > {gt}")
    if ge is not None and not v >= ge:
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be >= {ge}")
    return v


def as_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be a boolean")
    return v


def as_enum(body, key, choices, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", f"Field {key} not a valid enum member")
    return v


def as_fraction(body, key):
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be a number")
    if not (0.0 <= v <= 1.0):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be in [0.0, 1.0]")
    return v


def lookup(collection, _id, label="resource"):
    obj = collection.get(_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", f"{label} not found: {_id}")
    return obj


# =========================================================================
# Clock helpers
# =========================================================================
def parse_iso(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return db.clock_now


# =========================================================================
# Derived-field recomputation. Each recompute that lands on a versioned row
# is itself a mutation (PRD §2.5), so it bumps version + updated_at.
# =========================================================================
def recompute_trip_seats(trip):
    total = 0
    for r in db.reservations.values():
        if r["trip_id"] == trip["id"] and r["reservation_status"] in (
            "RESERVED", "CHECKED_IN", "COMPLETED"
        ):
            total += r["seat_count"]
    if trip.get("seats_reserved") != total:
        trip["seats_reserved"] = total
    touch(trip)


def recompute_pool_committed(pool):
    total = 0
    for m in db.memberships.values():
        if m["pool_id"] == pool["id"] and m["status"] == "ACTIVE":
            total += m["recurring_seats"]
    pool["committed_seat_count"] = total
    touch(pool)


def recompute_program_consumed(program):
    total = 0
    for e in db.subsidy_ledger_entries.values():
        if e["employer_program_id"] == program["id"]:
            total += e["amount_cents"]
    program["subsidy_consumed_cents"] = total
    touch(program)


def member_completed_count(member_id):
    return sum(
        1 for r in db.reservations.values()
        if r["rider_member_id"] == member_id and r["reservation_status"] == "COMPLETED"
    )


def member_no_show_count(member_id):
    return sum(
        1 for r in db.reservations.values()
        if r["rider_member_id"] == member_id and r["reservation_status"] == "NO_SHOW"
    )


def member_reliability_deltas(member_id):
    deltas = []
    for e in sorted(db.reliability_events.values(), key=lambda x: x["_seq"]):
        if e["member_id"] == member_id:
            deltas.append(e["weight_delta"])
    return deltas


def recompute_member_reliability(member):
    deltas = member_reliability_deltas(member["id"])
    member["reliability_score"] = calc.reliability_score(deltas)
    touch(member)


def recompute_member_counters(member):
    member["completed_trip_count"] = member_completed_count(member["id"])
    member["no_show_count"] = member_no_show_count(member["id"])
    touch(member)


def _current_month_year(member):
    """Clock month/year bucket as (year, month) and (year,) keys."""
    now = clock_now()
    return (now.year, now.month), now.year


def recompute_member_month_benefit(member):
    """month_benefit_used_cents = signed sum of subsidy ledger entries applied
    to this member whose ledger entry falls in the current clock month."""
    (cy, cm), _ = _current_month_year(member)
    total = 0
    for e in db.subsidy_ledger_entries.values():
        if e["member_id"] != member["id"]:
            continue
        if e["reason"] not in ("RESERVATION_FINALIZED", "RESERVATION_CANCELLED"):
            continue
        et = parse_iso(e["_clock_at"])
        if (et.year, et.month) == (cy, cm):
            total += e["amount_cents"]
    member["month_benefit_used_cents"] = max(0, total)
    touch(member)


def recompute_member_grh(member):
    """grh_year_used_cents + grh_year_event_count over the current clock year."""
    _, cy = _current_month_year(member)
    used = 0
    count = 0
    for e in db.subsidy_ledger_entries.values():
        if e["member_id"] != member["id"] or e["reason"] != "GRH_REIMBURSED":
            continue
        et = parse_iso(e["_clock_at"])
        if et.year == cy:
            used += e["amount_cents"]
            count += 1
    member["grh_year_used_cents"] = used
    member["grh_year_event_count"] = count
    touch(member)


def reload_time_buckets(member):
    """Re-bucket month/year derived counters against the current clock."""
    recompute_member_month_benefit(member)
    recompute_member_grh(member)


# =========================================================================
# Ledger / reliability event append (immutable rows)
# =========================================================================
def append_ledger(program_id, member_id, reservation_id, amount_cents,
                  entry_type, reason):
    entry = {
        "employer_program_id": program_id,
        "member_id": member_id,
        "reservation_id": reservation_id,
        "amount_cents": amount_cents,
        "entry_type": entry_type,
        "reason": reason,
    }
    stamp_new(entry, versioned=False)
    entry["_clock_at"] = clock_now().isoformat()
    db.subsidy_ledger_entries[entry["id"]] = entry
    return entry


def append_reliability_event(member_id, reservation_id, event_type):
    event = {
        "member_id": member_id,
        "reservation_id": reservation_id,
        "event_type": event_type,
        "weight_delta": float(calc.EVENT_WEIGHT[event_type]),
    }
    stamp_new(event, versioned=False)
    event["_clock_at"] = clock_now().isoformat()
    db.reliability_events[event["id"]] = event
    return event


# =========================================================================
# Pagination
# =========================================================================
def paginate(args):
    def _parse(name, default, lo, hi):
        raw = args.get(name)
        if raw is None:
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", f"Invalid {name}")
        if name == "limit":
            if v < lo or v > hi:
                raise err("ERR_INVALID_REQUEST", f"limit out of range [{lo},{hi}]")
        if name == "offset" and v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
        return v

    limit = _parse("limit", 10, 1, 100)
    offset = _parse("offset", 0, 0, None)
    return limit, offset


def sorted_by_created(items):
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))
