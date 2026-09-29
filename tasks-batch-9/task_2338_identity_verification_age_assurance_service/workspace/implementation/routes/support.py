"""Helpers shared by the route modules."""
from flask import request

import db
import schema
from errors import fail


def raw_body_dict():
    """Best-effort body read used by the ownership check, which precedes schema checks."""
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def scope_check_body_client(caller, field="client_id"):
    """Check 11 for creation endpoints whose client reference travels in the body."""
    if not caller.is_client_integrator:
        return
    value = raw_body_dict().get(field)
    if isinstance(value, str) and value != caller.user_id:
        fail("ERR_CLIENT_SCOPE_VIOLATION")


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Filter %s must be one of %s." % (name, ", ".join(allowed)))
    return value


def string_filter(name):
    return request.args.get(name)


def client_of_session(session):
    return db.get(db.CLIENTS, session["client_id"])


def paginated(records):
    limit, offset = schema.pagination()
    total = len(records)
    return schema.paginate(records, limit, offset), limit, offset, total
