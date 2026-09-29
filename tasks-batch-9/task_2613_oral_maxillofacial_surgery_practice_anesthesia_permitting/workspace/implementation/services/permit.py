"""AnesthesiaPermit status transitions and their enforcement side effects."""
from datetime import timedelta

from db import clock_dt, clock_str, touch
from services.cascade import probation_cascade, suspension_cascade, sweep_cascade
from services.domain import (PERMIT_TERM_MONTHS, REMEDIATION_WINDOW_DAYS,
                             REQUIRED_DRILL_TYPES, get_practice)
from services.practice import recompute_privilege, touch_practice
from timeutil import add_months, fmt_dt, parse_date


def required_drill_types(permit_level):
    return list(REQUIRED_DRILL_TYPES.get(permit_level, []))


def stamp_issuance(permit):
    """First issuance stamps the term; a later re-issue never extends it."""
    if not permit.get("issued_at"):
        permit["issued_at"] = clock_str()
    if not permit.get("expires_at"):
        issued = parse_date(permit["issued_at"])
        permit["expires_at"] = fmt_dt(add_months(issued, PERMIT_TERM_MONTHS))


def remediation_deadline():
    return fmt_dt(clock_dt() + timedelta(days=REMEDIATION_WINDOW_DAYS))


def to_active(permit, practice, stamp=True):
    permit["status"] = "ACTIVE"
    if stamp:
        stamp_issuance(permit)
    permit["last_enforcement_reason"] = None
    permit["remediation_deadline_at"] = None
    touch(permit)
    recompute_privilege(practice)
    return permit


def to_probation(permit, practice, reason, stamp=False):
    permit["status"] = "PROBATION"
    if stamp:
        stamp_issuance(permit)
    permit["last_enforcement_reason"] = reason
    permit["probation_count"] = int(permit.get("probation_count") or 0) + 1
    permit["remediation_deadline_at"] = remediation_deadline()
    touch(permit)
    recompute_privilege(practice)
    probation_cascade(practice)
    return permit


def to_suspended(permit, practice, reason):
    permit["status"] = "SUSPENDED"
    permit["last_enforcement_reason"] = reason
    touch(permit)
    recompute_privilege(practice)
    released = suspension_cascade(practice)
    return released


def to_applied(permit, practice, reason):
    permit["status"] = "APPLIED"
    permit["last_enforcement_reason"] = reason
    touch(permit)
    recompute_privilege(practice)
    return permit


def to_revoked(permit, practice, reason):
    permit["status"] = "REVOKED"
    permit["last_enforcement_reason"] = reason
    touch(permit)
    recompute_privilege(practice)
    return permit


def sweep_suspend(permit, practice, reason):
    permit["status"] = "SUSPENDED"
    permit["last_enforcement_reason"] = reason
    touch(permit)
    recompute_privilege(practice)
    return sweep_cascade(practice)


def sweep_expire(permit, practice):
    permit["status"] = "EXPIRED"
    permit["last_enforcement_reason"] = "PERMIT_EXPIRY"
    touch(permit)
    recompute_privilege(practice)
    return sweep_cascade(practice)


def sentinel_enforcement(practice, permit):
    """A SENTINEL adverse event escalates ACTIVE -> PROBATION, PROBATION -> SUSPENDED."""
    if permit is None:
        return
    if permit["status"] == "ACTIVE":
        to_probation(permit, practice, "SENTINEL_EVENT")
        touch_practice(practice)
    elif permit["status"] == "PROBATION":
        to_suspended(permit, practice, "SENTINEL_EVENT")
        touch_practice(practice)
