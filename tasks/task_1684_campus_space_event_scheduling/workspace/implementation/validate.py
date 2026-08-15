"""Body validation helpers (ladder rung 4) and existence/ownership resolution
helpers (rung 3, including the OrgRequester ownership masking of PRD 2.10).
"""

import db
from clock import parse_hhmm, parse_instant
from errors import ApiError

_MISSING = object()


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def not_found(message="The referenced resource does not exist."):
    raise ApiError("ERR_NOT_FOUND", message)


# ------------------------------------------------------------- field readers
def req_str(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, str):
        invalid("%s is required and must be a string." % name)
    return value


def opt_str(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        invalid("%s must be a string." % name)
    return value


def req_int(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None or isinstance(value, bool) or not isinstance(value, int):
        invalid("%s is required and must be an integer." % name)
    return value


def opt_int(body, name, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("%s must be an integer." % name)
    return value


def req_dt(body, name):
    """Required caller-supplied instant.  Returns (raw_string, datetime)."""
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, str):
        invalid("%s is required and must be an ISO 8601 datetime string." % name)
    dt = parse_instant(value)
    if dt is None:
        invalid("%s must be an ISO 8601 datetime string." % name)
    return value, dt


def opt_dt(body, name):
    """Optional caller-supplied instant; explicit null clears.  Returns
    (raw_string_or_None, datetime_or_None)."""
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return None, None
    if not isinstance(value, str):
        invalid("%s must be an ISO 8601 datetime string." % name)
    dt = parse_instant(value)
    if dt is None:
        invalid("%s must be an ISO 8601 datetime string." % name)
    return value, dt


def req_enum(body, name, members):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, str) or value not in members:
        invalid("%s is required and must be one of %s." % (name, ", ".join(members)))
    return value


def opt_enum_array(body, name, members, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return list(default) if default is not None else []
    if not isinstance(value, list):
        invalid("%s must be an array." % name)
    for entry in value:
        if not isinstance(entry, str) or entry not in members:
            invalid("%s entries must be one of %s." % (name, ", ".join(members)))
    return list(value)


def req_str_array(body, name, members):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, list):
        invalid("%s is required and must be an array." % name)
    for entry in value:
        if not isinstance(entry, str) or entry not in members:
            invalid("%s entries must be one of %s." % (name, ", ".join(members)))
    return list(value)


def req_hhmm(body, name):
    """Required ``HH:MM`` time-of-day.  Returns (raw_string, minutes)."""
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, str):
        invalid("%s is required and must be an HH:MM string." % name)
    minutes = parse_hhmm(value)
    if minutes is None:
        invalid("%s must be an HH:MM string." % name)
    return value, minutes


# ----------------------------------------------------------- existence helpers
def get_org(org_id):
    row = db.organizations.get(org_id)
    if row is None:
        not_found("The referenced organization does not exist.")
    return row


def get_room(room_id):
    row = db.rooms.get(room_id)
    if row is None:
        not_found("The referenced room does not exist.")
    return row


def get_term(term_id):
    row = db.terms.get(term_id)
    if row is None:
        not_found("The referenced term does not exist.")
    return row


def get_block(block_id):
    row = db.academic_blocks.get(block_id)
    if row is None:
        not_found("The referenced academic block does not exist.")
    return row


def get_run(run_id):
    row = db.scheduling_runs.get(run_id)
    if row is None:
        not_found("The referenced scheduling run does not exist.")
    return row


def get_event(event_id):
    row = db.event_reservations.get(event_id)
    if row is None:
        not_found("The referenced event reservation does not exist.")
    return row


def get_order(order_id):
    row = db.service_orders.get(order_id)
    if row is None:
        not_found("The referenced service order does not exist.")
    return row


def get_crew(crew_id):
    row = db.service_crews.get(crew_id)
    if row is None:
        not_found("The referenced service crew does not exist.")
    return row


def get_invoice(invoice_id):
    row = db.invoices.get(invoice_id)
    if row is None:
        not_found("The referenced invoice does not exist.")
    return row


def get_grant(grant_id):
    row = db.access_grants.get(grant_id)
    if row is None:
        not_found("The referenced access grant does not exist.")
    return row


# ---------------------------------------------------------- ownership masking
def owning_org_id_of_event(event):
    return event.get("requester_org_id")


def owning_org_id_of_order(order):
    event = db.event_reservations.get(order.get("event_id"))
    return event.get("requester_org_id") if event else None


def owning_org_id_of_invoice(invoice):
    return invoice.get("org_id")


def owning_org_id_of_grant(grant):
    event = db.event_reservations.get(grant.get("event_id"))
    return event.get("requester_org_id") if event else None


def mask_owned(ctx, owner_org_id):
    """PRD 2.10: an OrgRequester addressing another organization's resource is
    answered exactly as if the resource did not exist."""
    if ctx.is_org_requester and owner_org_id != ctx.user_id:
        not_found("The referenced resource does not exist.")


def get_event_masked(ctx, event_id):
    event = get_event(event_id)
    mask_owned(ctx, owning_org_id_of_event(event))
    return event


def get_order_masked(ctx, order_id):
    order = get_order(order_id)
    mask_owned(ctx, owning_org_id_of_order(order))
    return order


def get_invoice_masked(ctx, invoice_id):
    invoice = get_invoice(invoice_id)
    mask_owned(ctx, owning_org_id_of_invoice(invoice))
    return invoice


def get_grant_masked(ctx, grant_id):
    grant = get_grant(grant_id)
    mask_owned(ctx, owning_org_id_of_grant(grant))
    return grant
