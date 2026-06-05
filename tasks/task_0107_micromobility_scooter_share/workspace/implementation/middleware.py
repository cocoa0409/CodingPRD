"""Auth header extraction and role/ownership checking (PRD §2.1, §2.8).

Auth headers (PRD §2.1):
  X-User-ID   — acting principal id
  X-User-Role — Anonymous | Rider | Technician | PlatformAdmin | CityRegulator

Validation ordering (PRD §2.8):
  1. ERR_UNAUTHENTICATED (401) — headers missing/malformed on a protected endpoint
  2. ERR_FORBIDDEN_ROLE  (403) — role not permitted for this endpoint
  3. ERR_NOT_RESOURCE_OWNER (403) — entity-backed rider/technician acts on a
     resource they do not own (only for rider-owned trip/fine/application actions
     and technician task completion)
"""
from flask import request

import errors

VALID_ROLES = {"Anonymous", "Rider", "Technician", "PlatformAdmin", "CityRegulator"}


def authenticate():
    """Return (role, user_id). Raise ERR_UNAUTHENTICATED on malformed auth.

    For every role other than Anonymous, X-User-ID must also be present and
    non-empty. (Anonymous carries an opaque caller id that may be present but is
    not tied to any entity; we still accept it whether present or not.)
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role.strip() == "" or role not in VALID_ROLES:
        raise errors.unauthenticated("X-User-Role missing or malformed")

    if role != "Anonymous":
        if user_id is None or user_id.strip() == "":
            raise errors.unauthenticated("X-User-ID missing or malformed")

    return role, user_id


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE when the authenticated role is not in `allowed`."""
    if role not in allowed:
        raise errors.forbidden_role(f"Role {role} is not permitted for this operation")


def require_rider_owner(role, user_id, owner_rider_id):
    """A Rider may act only on resources whose rider foreign key is their own id.

    PlatformAdmin (and any non-Rider role) is not subject to the rider-ownership
    check (PRD §2.1).
    """
    if role == "Rider" and user_id != owner_rider_id:
        raise errors.not_resource_owner("Rider may act only on their own resources")


def require_technician_owner(role, user_id, technician_id):
    """A Technician may only complete a task assigned to them (PRD §2.1)."""
    if role == "Technician" and user_id != technician_id:
        raise errors.not_resource_owner("Technician may act only on their own task")
