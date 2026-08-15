"""Auth header extraction, role checking, and common helpers.

Validation tiers (PRD §2.6):
  1. header presence      -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
  2. role permission      -> ERR_INSUFFICIENT_PERMISSIONS
  3. role-staff consistency -> ERR_ROLE_STAFF_MISMATCH
  4. patient ownership    -> ERR_PATIENT_OWNERSHIP_MISMATCH
  5. existence            -> ERR_NOT_FOUND
  6. OCC                  -> ERR_STALE_VERSION
  7. from-state           -> per-resource state errors
  8. business rules
  9. input shape          -> ERR_INVALID_REQUEST (body-only failures)
"""

import uuid

from flask import request

import db
from db import CLOCK, fmt_ts, _parse_dt
from errors import (
    ApiError, raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_ROLE_STAFF_MISMATCH,
    ERR_PATIENT_OWNERSHIP_MISMATCH,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

VALID_ROLES = {"Patient", "TriageNurse", "FrontDesk", "Provider", "BillingSpecialist", "PracticeAdmin"}

ROLE_TO_STAFF_TYPE = {
    "TriageNurse": "NURSE",
    "FrontDesk": "FRONT_DESK",
    "Provider": "PROVIDER",
    "BillingSpecialist": "BILLING_SPECIALIST",
}

STAFF_TYPES = {"PROVIDER", "NURSE", "FRONT_DESK", "BILLING_SPECIALIST", "PRACTICE_ADMIN"}

COUNTED_STATUSES = {"ASSIGNED", "IN_REVIEW", "PENDING_CONSENT", "PENDING_COSIGN", "ESCALATED", "REOPENED"}


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.staff = None      # StaffMember record when staff-backed
        self.patient = None    # Patient record when role == Patient


def authenticate(allowed_roles):
    """Run validation tiers 1-3. Returns a Ctx. Tier 4/5+ are per-endpoint."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers must be present and non-empty")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers must be present and non-empty")

    # Tier 2: role permission. An unrecognized role name is not permitted for
    # any operation.
    if role not in VALID_ROLES or role not in allowed_roles:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this operation")

    ctx = Ctx(user_id, role)

    # Tier 3: role-staff consistency for staff-backed roles.
    if role in ROLE_TO_STAFF_TYPE:
        member = db.staff.get(user_id)
        if member is None or member["staff_type"] != ROLE_TO_STAFF_TYPE[role]:
            raise_err(ERR_ROLE_STAFF_MISMATCH,
                      "Staff-backed role's X-User-ID does not reference a StaffMember with matching staff_type")
        ctx.staff = member
    elif role == "Patient":
        # Existence of the patient is an ownership-tier concern; resolve here
        # so endpoints can use ctx.patient, but raise the ownership error.
        ctx.patient = db.patients.get(user_id)

    return ctx


def require_patient_entity(ctx):
    """For Patient-role calls: X-User-ID must reference an existing Patient."""
    if ctx.patient is None:
        raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH,
                  "Patient role X-User-ID does not reference an existing Patient")


def patient_owns(ctx, patient_id):
    return ctx.role != "Patient" or (ctx.patient is not None and patient_id == ctx.user_id)


def require_patient_ownership(ctx, patient_id):
    if ctx.role == "Patient":
        if ctx.patient is None or patient_id != ctx.user_id:
            raise_err(ERR_PATIENT_OWNERSHIP_MISMATCH,
                      "Patient role may only act on own resources")


# ---------------------------------------------------------------------------
# Body / field helpers (tier 9 — input shape)
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_field(body, name):
    val = body.get(name)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return val


def opt_field(body, name, default=None):
    val = body.get(name)
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return default
    return val


def req_enum(body, name, allowed):
    val = req_field(body, name)
    if val not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Invalid value for %s: %r" % (name, val))
    return val


def opt_enum(body, name, allowed, default=None):
    val = body.get(name)
    if val is None:
        return default
    if val not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Invalid value for %s: %r" % (name, val))
    return val


def req_int(body, name, lo=None, hi=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if lo is not None and val < lo:
        raise_err(ERR_INVALID_REQUEST, "Field %s below minimum" % name)
    if hi is not None and val > hi:
        raise_err(ERR_INVALID_REQUEST, "Field %s above maximum" % name)
    return val


def req_string(body, name):
    val = req_field(body, name)
    if not isinstance(val, str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return val


def req_datetime(body, name):
    val = req_field(body, name)
    if not isinstance(val, str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an ISO-8601 string" % name)
    try:
        return _parse_dt(val)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Field %s is not a valid ISO-8601 timestamp" % name)


def parse_pagination():
    """limit/offset query params with defaults 10/0, min 1, max 100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Entity construction / serialization
# ---------------------------------------------------------------------------

def new_entity(fields):
    now = CLOCK.now_iso()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    ent.update(fields)
    return ent


def touch(ent):
    """Refresh updated_at and bump version on any mutation."""
    ent["updated_at"] = CLOCK.now_iso()
    ent["version"] += 1


def public(ent):
    return dict(ent)


def get_or_404(store, entity_id, what="resource"):
    ent = store.get(entity_id)
    if ent is None:
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (what, entity_id))
    return ent


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))
