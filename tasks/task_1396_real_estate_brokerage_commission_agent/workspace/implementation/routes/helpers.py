"""Route helpers: the guard decorator and public serializers.

Internal storage fields are prefixed with '_' (e.g. parsed dates) and are
stripped from every API representation.
"""

from functools import wraps

import db
from middleware import get_context, require_roles, resolve_agent_identity
from response import success_obj, success_list
from middleware import parse_pagination


def guard(roles):
    """Runs guard steps 1-3 (headers, role admission, Agent identity)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_context()
            require_roles(role, roles)
            resolve_agent_identity(user_id, role)
            return fn(user_id, role, *args, **kwargs)
        return wrapper
    return deco


def public(resource):
    if resource is None:
        return None
    return {k: v for k, v in resource.items() if not k.startswith("_")}


def list_response(items):
    """items: full filtered+sorted list; applies pagination envelope."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([public(i) for i in page], limit, offset, total)


def by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))
