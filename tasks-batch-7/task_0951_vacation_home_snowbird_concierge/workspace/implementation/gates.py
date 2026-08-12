"""Gate machinery: G1 auth, G2 role/scope, G3 existence, G10 payload validation.

The write-gate ladder (PRD 2.7) is a total order of ten gates and the numbered
68-rung ladder (PRD 2.8) refines it.  Each route calls the helpers below in
ascending gate order; the first failure raises ApiError and nothing later runs.
"""
from decimal import Decimal

from flask import request

import core
from core import ApiError, D, fail, get, parse_iso

# ---------------------------------------------------------------------------
# G1 / G2
# ---------------------------------------------------------------------------


def authenticate():
    """Rungs 1 and 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip() or not role or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in core.ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role '%s'." % role)
    return role, user_id


def require_roles(role, allowed):
    """Rung 3."""
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role '%s' may not perform this operation." % role)


def begin(allowed_roles):
    role, user_id = authenticate()
    require_roles(role, allowed_roles)
    return role, user_id


def owner_scope(role, user_id, owner_id):
    """Rung 4 - only meaningful once the target resource has been resolved."""
    if role == "Owner" and owner_id is not None and user_id != owner_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This resource does not belong to the acting owner.")


def vendor_scope(role, user_id, vendor_id):
    """Rung 5."""
    if role == "Vendor" and vendor_id is not None and user_id != vendor_id:
        fail("ERR_NOT_ASSIGNED_VENDOR", "This assignment does not belong to the acting vendor.")


# ---------------------------------------------------------------------------
# G3 existence
# ---------------------------------------------------------------------------
def fetch_path(collection, row_id):
    """Rung 7."""
    row = get(collection, row_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "No such resource '%s'." % row_id)
    return row


def fetch_body_fk(collection, row_id, error_id):
    row = get(collection, row_id)
    if row is None:
        fail(error_id, "Referenced resource '%s' does not exist." % row_id)
    return row


def fetch_optional_fk(collection, row_id):
    """Rung 14 - optional foreign keys, resolved in request-body field order."""
    if row_id is None:
        return None
    row = get(collection, row_id)
    if row is None:
        fail("ERR_LINKED_RESOURCE_NOT_FOUND", "Linked resource '%s' does not exist." % row_id)
    return row


OPTIONAL_FK_COLLECTIONS = {
    "away_period_id": "away_periods",
    "rental_turnover_id": "rental_turnovers",
    "storm_response_id": "storm_responses",
    "key_asset_id": "key_assets",
    "key_issuance_id": "key_issuances",
    "visit_id": "visits",
    "security_incident_id": "security_incidents",
    "mail_hold_id": "mail_holds",
    "work_order_id": "work_orders",
}


def resolve_optional_fks(body, field_names):
    """Rung 14: resolve each supplied optional FK in the declared body order."""
    resolved = {}
    for name in field_names:
        value = body.get(name)
        if value is None:
            resolved[name] = None
            continue
        if not isinstance(value, str):
            # a wrong-typed id is a rung-60 type failure, adjudicated at G10
            resolved[name] = None
            continue
        resolved[name] = fetch_optional_fk(OPTIONAL_FK_COLLECTIONS[name], value)
    return resolved


# ---------------------------------------------------------------------------
# G5 shared helpers
# ---------------------------------------------------------------------------
def check_state(machine, row, allowed_sources):
    """Rungs 19 then 18.

    ERR_ALREADY_TERMINAL is raised first when the row sits in a terminal state
    of its machine; a terminal state is never a declared source state, so the
    literal 18-before-19 order would leave rung 19 permanently dead.
    """
    status = row.get("status")
    if status in core.TERMINAL_STATES.get(machine, []):
        fail("ERR_ALREADY_TERMINAL", "The resource is already in the terminal state '%s'." % status)
    if status not in allowed_sources:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Status '%s' is not a declared source state for this transition." % status)


# ---------------------------------------------------------------------------
# G10 payload
# ---------------------------------------------------------------------------
def body_json():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


# rung 61: EXACTLY these request fields route to ERR_INVALID_ENUM_VALUE.
ENUM_MEMBERS = {
    "visit_type": core.VISIT_TYPES,
    "trigger_source": core.TRIGGER_SOURCES,
    "defer_reason": core.DEFER_REASONS,
    "severity": core.SEVERITIES,
    "category": core.CATEGORIES,
    "incident_type": core.INCIDENT_TYPES,
    "key_type": core.KEY_TYPES,
    "line_type": core.LINE_TYPES,
    "tier": core.TIERS,
    "entitlement_rollover_policy": core.ROLLOVER_POLICIES,
    "billing_mode": core.BILLING_MODES,
    "trade": core.TRADES,
    "work_type": core.WORK_TYPES,
    "damage_level": core.DAMAGE_LEVELS,
    "reopen_reason": core.REOPEN_REASONS,
    "notification_preference": core.NOTIFICATION_PREFERENCES,
    "to_state": core.OCCUPANCY_STATES,
    "action": core.SEASONAL_ACTIONS,
    "revoke_reason": core.REVOKE_REASONS,
    # `to_status` members are endpoint-specific and supplied via `enum_overrides`
    # `step_code` is routed to ERR_WINTERIZATION_STEP_INVALID by PRD 3.8
    # `disposition` is never accepted as a request field anywhere
}

# rung 62: declared numeric ranges.  (lo, hi, lo_strict, hi_strict)
NUMERIC_RANGES = {
    "travel_distance_miles": (Decimal("0"), None, False, False),
    "freeze_setpoint_f": (Decimal("40"), Decimal("80"), False, False),
    "rating": (Decimal("0"), Decimal("5"), False, False),
    "cadence_days": (Decimal(core.CADENCE_MIN_DAYS), Decimal(core.CADENCE_MAX_DAYS), False, False),
    "copies_total": (Decimal("1"), None, False, False),
    "copies_issued": (Decimal("1"), None, False, False),
    "hourly_rate_cents": (Decimal("0"), None, True, False),
    "monthly_fee_cents": (Decimal("0"), None, True, False),
    "included_visit_units": (Decimal("0"), None, False, False),
    "estimated_labour_hours": (Decimal("0"), None, False, False),
    "estimated_parts_cents": (Decimal("0"), None, False, False),
    # PRD 3.1: an owner-specific ceiling "must be zero or greater" when supplied
    "approval_ceiling_override_cents": (Decimal("0"), None, False, False),
}


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "datetime":
        return isinstance(value, str) and parse_iso(value) is not None
    if kind == "string_array":
        return isinstance(value, list) and all(isinstance(x, str) for x in value)
    return True


def validate_payload(body, spec, enum_overrides=None):
    """Rungs 59, 60, 61, 62 in that order.

    `spec` is an ordered list of (field_name, kind, required) tuples.
    """
    # rung 59 - required fields present
    for name, _kind, required in spec:
        if required and body.get(name, None) is None:
            fail("ERR_MISSING_REQUIRED_FIELD", "Field '%s' is required." % name)
    # rung 60 - declared JSON types
    for name, kind, _required in spec:
        if name in body and body[name] is not None:
            if not _type_ok(body[name], kind):
                fail("ERR_INVALID_FIELD_TYPE", "Field '%s' has the wrong type." % name)
    # rung 61 - enum membership (closed routing list)
    for name, _kind, _required in spec:
        if name in body and body[name] is not None:
            members = None
            if enum_overrides and name in enum_overrides:
                members = enum_overrides[name]
            elif name in ENUM_MEMBERS:
                members = ENUM_MEMBERS[name]
            if members is not None and body[name] not in members:
                fail("ERR_INVALID_ENUM_VALUE", "Field '%s' holds an undeclared enum member." % name)
    # rung 62 - numeric ranges
    for name, _kind, _required in spec:
        if name in body and body[name] is not None and name in NUMERIC_RANGES:
            value = body[name]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            lo, hi, lo_strict, hi_strict = NUMERIC_RANGES[name]
            v = D(value)
            if lo is not None and (v <= lo if lo_strict else v < lo):
                fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is below its declared range." % name)
            if hi is not None and (v >= hi if hi_strict else v > hi):
                fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' is above its declared range." % name)


def check_interval(body, start_field, end_field):
    """Rung 64 - the end instant must be strictly after the start instant."""
    start = body.get(start_field)
    end = body.get(end_field)
    if start is None or end is None:
        return
    s = parse_iso(start)
    e = parse_iso(end)
    if s is None or e is None:
        return
    if not e > s:
        fail("ERR_INTERVAL_MALFORMED", "'%s' must be strictly after '%s'." % (end_field, start_field))


def enum_discriminator(body, field, members):
    """Read a payload enum that a pre-G10 gate depends on.

    When the discriminator is absent or not a declared member the earlier gates
    cannot be evaluated at all, so the request falls straight through to the
    G10 rung that rejects it.
    """
    value = body.get(field, None)
    if value is None:
        fail("ERR_MISSING_REQUIRED_FIELD", "Field '%s' is required." % field)
    if not isinstance(value, str):
        fail("ERR_INVALID_FIELD_TYPE", "Field '%s' has the wrong type." % field)
    if value not in members:
        fail("ERR_INVALID_ENUM_VALUE", "Field '%s' holds an undeclared enum member." % field)
    return value


# ---------------------------------------------------------------------------
# Pagination and collection filters (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_PAGINATION_INVALID", "limit must be an integer between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_PAGINATION_INVALID", "offset must be a non-negative integer.")
    if limit < 1 or limit > 100:
        fail("ERR_PAGINATION_INVALID", "limit must be between 1 and 100 inclusive.")
    if offset < 0:
        fail("ERR_PAGINATION_INVALID", "offset must be zero or greater.")
    return limit, offset


def _match(row, field, raw):
    value = row.get(field)
    if isinstance(value, bool):
        return str(value).lower() == str(raw).lower()
    if value is None:
        return raw in ("", "null")
    return str(value) == str(raw)


def apply_filters(items, filter_fields):
    args = request.args
    out = items
    for field in filter_fields:
        raw = args.get(field)
        if raw is None:
            continue
        out = [r for r in out if _match(r, field, raw)]
    return out


def paginate(items):
    limit, offset = pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return window, limit, offset, total


def list_response(collection, filter_fields, serializer, extra_filter=None):
    items = core.rows(collection)
    if extra_filter is not None:
        items = [r for r in items if extra_filter(r)]
    items = apply_filters(items, filter_fields)
    window, limit, offset, total = paginate(items)
    return core.ok_list([serializer(r) for r in window], limit, offset, total)
