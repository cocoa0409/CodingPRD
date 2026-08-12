"""The 51-rung validation ladder of PRD 2.9, the four ordered account gates of
PRD 2.8 and the per-request version ledger of PRD 2.4.

Rungs are evaluated strictly in ascending order; the first rung that fails is
the error reported and no later rung is evaluated.  Every handler calls the
helpers below in ladder order, which is why they are named for their rung.
"""

from flask import g, request

from errors import ApiError
from store import clock, db
from timeutil import render_instant, try_parse_instant

# --------------------------------------------------------------------------
# Roles (PRD 2.1) -- exactly six, spellings fixed.
# --------------------------------------------------------------------------
ROLES = ("Owner", "Member", "BillingAdmin", "SupportAgent", "Technician", "PlatformAdmin")
HOUSEHOLD_ROLES = {"Owner": "OWNER", "Member": "MEMBER", "BillingAdmin": "BILLING_ADMIN"}
ENTITY_BACKED = ("Owner", "Member", "BillingAdmin", "Technician")


# --------------------------------------------------------------------------
# The version ledger (PRD 2.4): a single request bumps a given row's version
# by at most 1, no matter how many fields it touches or how many state-machine
# hops that row traverses inside the request.
# --------------------------------------------------------------------------
def touch(row):
    if row is None:
        return
    bumped = getattr(g, "_bumped", None)
    if bumped is None:
        bumped = set()
        g._bumped = bumped
    key = id(row)
    row["updated_at"] = clock.now_iso()
    if key in bumped:
        return
    bumped.add(key)
    if "version" in row:
        row["version"] = row["version"] + 1


# --------------------------------------------------------------------------
# Request context -- rungs 1 to 4
# --------------------------------------------------------------------------
class Ctx(object):
    __slots__ = ("role", "user_id", "member", "technician", "body")

    def __init__(self, role, user_id, member, technician, body):
        self.role = role
        self.user_id = user_id
        self.member = member
        self.technician = technician
        self.body = body


def _read_body():
    raw = request.get_json(silent=True)
    if isinstance(raw, dict):
        return raw
    return {}


def begin(roles):
    """Rungs 1-4.  ``roles`` is the endpoint's authorised-role tuple."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # Rung 1 -- X-User-Role present and non-blank; X-User-ID present and
    # non-blank whenever the role is one of the entity-backed roles.
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or blank.")
    role = role.strip()
    # Rung 2 -- the role is exactly one of the six.
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if role in ENTITY_BACKED and (user_id is None or not user_id.strip()):
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is missing or blank.")
    user_id = user_id.strip() if isinstance(user_id, str) else user_id

    # Rung 3 -- the role is listed among the endpoint's authorised roles.
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")

    # Rung 4 -- the entity-backed identity resolves.
    member = None
    technician = None
    if role in HOUSEHOLD_ROLES:
        member = db.household_members.get(user_id)
        if (member is None or not member.get("is_active")
                or member.get("member_role") != HOUSEHOLD_ROLES[role]):
            raise ApiError("ERR_MEMBER_NOT_FOUND")
    elif role == "Technician":
        technician = db.technicians.get(user_id)
        if technician is None:
            raise ApiError("ERR_MEMBER_NOT_FOUND")

    return Ctx(role, user_id, member, technician, _read_body())


# --------------------------------------------------------------------------
# Existence rungs 5 to 18, in ascending rung order
# --------------------------------------------------------------------------
_EXISTENCE = [
    ("household", "households", "ERR_HOUSEHOLD_NOT_FOUND"),          # rung 5
    ("plan", "subscription_plans", "ERR_PLAN_NOT_FOUND"),            # rung 6
    ("subscription", "subscriptions", "ERR_SUBSCRIPTION_NOT_FOUND"),  # rung 7
    ("catalog", "device_catalog", "ERR_CATALOG_ENTRY_NOT_FOUND"),    # rung 8
    ("device", "devices", "ERR_DEVICE_NOT_FOUND"),                   # rung 9
    ("ticket", "tickets", "ERR_TICKET_NOT_FOUND"),                   # rung 10
    ("session", "remote_sessions", "ERR_SESSION_NOT_FOUND"),         # rung 11
    ("technician", "technicians", "ERR_TECHNICIAN_NOT_FOUND"),       # rung 12
    ("slot", "visit_slots", "ERR_SLOT_NOT_FOUND"),                   # rung 13
    ("visit", "visits", "ERR_VISIT_NOT_FOUND"),                      # rung 14
    ("campaign", "firmware_campaigns", "ERR_CAMPAIGN_NOT_FOUND"),    # rung 15
    ("rollout", "firmware_rollouts", "ERR_ROLLOUT_NOT_FOUND"),       # rung 16
    ("order", "addon_orders", "ERR_ORDER_NOT_FOUND"),                # rung 17
    ("rma", "rma_cases", "ERR_RMA_NOT_FOUND"),                       # rung 18
]

NOT_FOUND_FOR = {kind: err for kind, _, err in _EXISTENCE}


def resolve(**kwargs):
    """Run existence rungs 5-18 in ascending rung order.

    Each keyword takes either a single id or a list of ids.  Non-string values
    are skipped: a field of the wrong JSON type is a rung-20 shape error, not
    a rung-5..18 existence error.  A key that is absent from the request names
    nothing, so its rung has nothing to check.
    """
    out = {}
    for kind, collection, error_id in _EXISTENCE:
        if kind not in kwargs:
            continue
        value = kwargs[kind]
        table = getattr(db, collection)
        if isinstance(value, list):
            rows = []
            for item in value:
                if not isinstance(item, str):
                    continue
                row = table.get(item)
                if row is None:
                    raise ApiError(error_id)
                rows.append(row)
            out[kind] = rows
        else:
            if value is None or not isinstance(value, str):
                out[kind] = None
                continue
            row = table.get(value)
            if row is None:
                raise ApiError(error_id)
            out[kind] = row
    return out


# --------------------------------------------------------------------------
# Rung 19 -- row scope (PRD 2.1)
# --------------------------------------------------------------------------
def scope_household(ctx, household_id):
    """Owner / Member / BillingAdmin: the acting member's household_id must
    equal the household that owns the target row."""
    if ctx.member is None:
        return
    if household_id is None or ctx.member.get("household_id") != household_id:
        raise ApiError("ERR_ROW_SCOPE_DENIED")


def scope_technician(ctx, technician_id):
    """Technician: the acting technician's id must equal the technician_id of
    the slot behind the target visit or the target slot."""
    if ctx.technician is None:
        return
    if technician_id is None or ctx.technician.get("id") != technician_id:
        raise ApiError("ERR_ROW_SCOPE_DENIED")


# --------------------------------------------------------------------------
# Rungs 20 and 21 -- request-body shape and enum membership
# --------------------------------------------------------------------------
ENUMS = {
    "tier": ("BASIC", "PLUS", "PRO"),
    "coverage_mode": ("BUSINESS_HOURS", "TWENTY_FOUR_SEVEN"),
    "member_role": ("OWNER", "MEMBER", "BILLING_ADMIN"),
    "account_status": ("ACTIVE", "SUSPENDED", "CLOSED"),
    "device_class": ("HUB", "CAMERA", "SENSOR", "THERMOSTAT", "LOCK"),
    "skills": ("HUB", "CAMERA", "SENSOR", "THERMOSTAT", "LOCK"),
    "severity": ("P1", "P2", "P3"),
    "outcome": ("RESOLVED", "FAILED", "HARDWARE_FAULT"),
    "kind": ("SECURITY_MANDATORY", "FEATURE_OPTIONAL"),
    "result": ("SUCCESS", "FAILURE"),
    "payment_outcome": ("SUCCEEDED", "FAILED"),
    "lifecycle_status": ("CLAIMED", "ACTIVE", "RECLAIMABLE", "SERVICE_HOLD",
                         "SUSPENDED_RMA", "TRANSFER_PENDING", "DECOMMISSIONED"),
    "workflow_status": ("NEW", "TRIAGED", "REMOTE_DIAG", "AWAITING_CUSTOMER",
                        "DISPATCH_PENDING", "ONSITE", "RESOLVED", "REOPENED", "CLOSED"),
    "slot_status": ("OPEN", "BOOKED", "BLOCKED"),
}


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def req_str(body, name, min_len=1, max_len=None):
    value = body.get(name)
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if len(value) < min_len:
        bad_request("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' is too long." % name)
    return value


def opt_str(body, name, max_len=None):
    if name not in body or body.get(name) is None:
        return None
    value = body.get(name)
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' is too long." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        bad_request("Field '%s' is above its maximum." % name)
    return value


def req_bool(body, name):
    value = body.get(name)
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    return req_bool(body, name)


def req_id(body, name):
    value = body.get(name)
    if not isinstance(value, str) or not value:
        bad_request("Field '%s' must be a non-empty string." % name)
    return value


def req_enum(body, name, enum_key=None):
    """Rung 21.  A present field of the correct JSON type whose value is
    outside the enumeration is ERR_INVALID_ENUM; a missing field or a field of
    the wrong JSON type is the rung-20 shape error."""
    value = body.get(name)
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    allowed = ENUMS[enum_key or name]
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM", "Field '%s' is outside its enumeration." % name)
    return value


def filter_enum(args, name, enum_key=None):
    """Rung 21 for the three list filters that carry a closed enumeration:
    lifecycle_status, workflow_status and the slot status filter."""
    value = args.get(name)
    if value is None:
        return None
    if value not in ENUMS[enum_key or name]:
        raise ApiError("ERR_INVALID_ENUM", "Filter '%s' is outside its enumeration." % name)
    return value


def req_instant(body, name):
    """A required instant field.  The verbatim string is returned alongside
    the parsed datetime -- caller-supplied instants are stored verbatim (G2)."""
    value = body.get(name)
    if not isinstance(value, str):
        bad_request("Field '%s' must be an ISO 8601 instant string." % name)
    dt = try_parse_instant(value)
    if dt is None:
        bad_request("Field '%s' is not a valid ISO 8601 instant." % name)
    return value, dt


REGION_RE_LEN = 3


def req_region(body, name="region_code"):
    value = req_str(body, name)
    if len(value) != REGION_RE_LEN or not value.isalpha() or not value.isupper():
        bad_request("Field '%s' must be exactly three uppercase letters." % name)
    return value


# --------------------------------------------------------------------------
# Rung 22 -- optimistic concurrency (PRD 2.7)
# --------------------------------------------------------------------------
def occ(body, field, row):
    expected = body.get(field)
    if isinstance(expected, bool) or not isinstance(expected, int):
        bad_request("Field '%s' must be an integer." % field)
    if expected != row.get("version"):
        raise ApiError("ERR_STALE_VERSION")


# --------------------------------------------------------------------------
# Rungs 23 to 26 -- the four ordered account gates (PRD 2.8)
# --------------------------------------------------------------------------
def gates(household=None, device=None, ticket=None,
          skip_account=False, skip_device=False, skip_ticket=False,
          skip_subscription=False):
    """The first gate whose condition holds wins; lower gates and every
    downstream state error are never reported for that request."""
    # Gate 1 -- account suspended.
    if not skip_account and household is not None:
        if household.get("account_status") == "SUSPENDED":
            raise ApiError("ERR_ACCOUNT_SUSPENDED")
    # Gate 2 -- device decommissioned.
    if not skip_device and device is not None:
        if device.get("lifecycle_status") == "DECOMMISSIONED":
            raise ApiError("ERR_DEVICE_DECOMMISSIONED")
    # Gate 3 -- ticket closed.
    if not skip_ticket and ticket is not None:
        if ticket.get("workflow_status") == "CLOSED":
            raise ApiError("ERR_TICKET_CLOSED")
    # Gate 4 -- subscription cancelled.
    if not skip_subscription and household is not None:
        sub = household_subscription(household["id"])
        if sub is not None and sub.get("status") == "CANCELLED":
            raise ApiError("ERR_SUBSCRIPTION_CANCELLED")


# --------------------------------------------------------------------------
# Subscription / plan lookups
# --------------------------------------------------------------------------
def household_subscription(household_id):
    """The household's subscription.  Exactly one non-CANCELLED subscription
    may exist per household (PRD 3.2); when only cancelled rows remain the
    most recent one is returned so gate 4 can see it."""
    live = None
    cancelled = None
    for sub in db.subscriptions.values():
        if sub.get("household_id") != household_id:
            continue
        if sub.get("status") != "CANCELLED":
            if live is None or sub["created_at"] > live["created_at"] or (
                    sub["created_at"] == live["created_at"] and sub["id"] > live["id"]):
                live = sub
        else:
            if cancelled is None or sub["created_at"] > cancelled["created_at"] or (
                    sub["created_at"] == cancelled["created_at"] and sub["id"] > cancelled["id"]):
                cancelled = sub
    return live if live is not None else cancelled


def in_force_subscription(household_id):
    """The household's in-force (non-CANCELLED) subscription, or None."""
    sub = household_subscription(household_id)
    if sub is None or sub.get("status") == "CANCELLED":
        return None
    return sub


def require_subscription(household_id):
    """Rung 7: the same error is reported when an operation needs the
    household's in-force subscription and the household HAS NONE.

    A household whose subscription is CANCELLED is not a household with no
    subscription -- it has one, and gate 4 (rung 26) is the rung that reports
    it.  Raising the rung-7 error here instead would pre-empt gate 4 on every
    endpoint that needs the subscription and leave ERR_SUBSCRIPTION_CANCELLED
    unreachable on all of them.
    """
    sub = household_subscription(household_id)
    if sub is None:
        raise ApiError("ERR_SUBSCRIPTION_NOT_FOUND")
    return sub


def plan_of(subscription):
    return db.subscription_plans.get(subscription.get("plan_id"))


def invalid_state(message=None):
    raise ApiError("ERR_INVALID_STATE", message)
