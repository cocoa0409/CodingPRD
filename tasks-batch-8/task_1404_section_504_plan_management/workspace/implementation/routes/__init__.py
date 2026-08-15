"""Route blueprints."""
from middleware import parse_pagination
from response import success


def list_response(items, out_fn):
    """Sort by created_at ascending (insertion order breaks ties), then paginate."""
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success([out_fn(r) for r in page], 200, pagination)


from routes import schools, staff, students, referrals, evaluations, plans, \
    accommodations, acks, logs, reviews, testing, consents, grievances, audit, clock  # noqa: E402,F401
