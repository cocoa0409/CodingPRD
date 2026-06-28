"""Shared route helpers: listing/sorting/pagination, body field coercion,
and Parent ownership scoping (PRD §2.1, §2.3, §2.8)."""
from datetime import datetime, timezone

from db import db, public
import errors
from middleware import parse_pagination


def parse_iso8601(s):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None if it does
    not parse. Accepts a trailing 'Z'."""
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sorted_by_creation(items):
    """Default list sort: created_at ASC (PRD §2.3). Insertion-order (_seq)
    tie-break keeps results deterministic when timestamps collide."""
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))


def paginate_and_respond(items):
    """Apply default sort + pagination, return a list envelope."""
    from response import list_success
    limit, offset = parse_pagination()
    ordered = sorted_by_creation(items)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_success([public(o) for o in page], limit, offset, total)


def require_int(body, field, *, minimum=None, maximum=None, default=None, required=True):
    if field not in body or body[field] is None:
        if required and default is None:
            raise errors.invalid_request(f"Missing required field: {field}.")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field {field} must be <= {maximum}.")
    return val


def require_str(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}.")
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string.")
    return val


# -------------------------------------------------------------------------
# Parent ownership scoping (PRD §2.1)
# A Parent's X-User-ID equals the id of the acting Family.
# -------------------------------------------------------------------------
def family_id_of_student(student_id):
    s = db.students.get(student_id)
    return s["family_id"] if s else None


def family_id_of_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if not e:
        return None
    return family_id_of_student(e["student_id"])


def parent_owns_family(user_id, family_id):
    return user_id == family_id
