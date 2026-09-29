"""Auth header extraction, RBAC and per-request version accounting."""

import functools

from flask import g, request

from db import new_id, next_seq, now_iso
from errors import fail

# PRD 2.1 - the six declared roles.
RISK_POLICY_ADMIN = "RiskPolicyAdmin"
FUEL_ANALYST = "FuelAnalyst"
TREASURY_RISK_MANAGER = "TreasuryRiskManager"
HEDGE_ACCOUNTANT = "HedgeAccountant"
FUEL_OPS_CONTROLLER = "FuelOpsController"
STATION_COORDINATOR = "StationCoordinator"

ALL_ROLES = (
    RISK_POLICY_ADMIN,
    FUEL_ANALYST,
    TREASURY_RISK_MANAGER,
    HEDGE_ACCOUNTANT,
    FUEL_OPS_CONTROLLER,
    STATION_COORDINATOR,
)


def endpoint(*roles):
    """Validation ladder steps 1 and 2: authentication then role authorisation."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in ALL_ROLES:
                fail("ERR_UNAUTHENTICATED",
                     "X-User-ID and a recognised X-User-Role header are required.")
            if user_role not in roles:
                fail("ERR_FORBIDDEN_ROLE",
                     "Role %s is not authorised for this endpoint." % user_role)
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def init_request_state():
    g._touched = set()
    g._created = set()


def new_row(extra_common=True):
    """Allocate a fresh row skeleton with its system audit fields."""
    row = {"id": new_id(), "_seq": next_seq(), "created_at": now_iso()}
    if extra_common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    try:
        g._created.add(row["id"])
    except Exception:
        pass
    return row


def touch(row):
    """PRD 2.4/2.8: one version increment per affected row per request."""
    if row is None:
        return
    rid = row.get("id")
    created = getattr(g, "_created", None)
    touched = getattr(g, "_touched", None)
    if created is not None and rid in created:
        return
    if touched is not None:
        if rid in touched:
            return
        touched.add(rid)
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now_iso()
