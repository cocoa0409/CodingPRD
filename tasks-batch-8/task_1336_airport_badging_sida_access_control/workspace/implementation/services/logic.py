"""Business logic: training currency, badge expiry, cascades, points, audits,
access decisions, and the logical-clock sweep (PRD §3, scaffold §1.2/§1.3)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

BADGE_CLASSES = {"SIDA", "STERILE", "AOA"}

REQUIRED_COURSES = {
    "SIDA": ("SIDA_INITIAL", "AOA_SAFETY"),
    "STERILE": ("STERILE_INITIAL",),
    "AOA": ("SIDA_INITIAL", "AOA_DRIVING"),
}

VALIDITY_MONTHS = {
    "SIDA_INITIAL": 12,
    "AOA_SAFETY": 24,
    "AOA_DRIVING": 12,
    "STERILE_INITIAL": 12,
}

COURSE_CODES = set(VALIDITY_MONTHS)

POINTS = {
    "FAILURE_TO_DISPLAY": 3,
    "ESCORT_VIOLATION": 6,
    "UNAUTHORIZED_AREA": 6,
    "SECURITY_BREACH": 12,
}

SUSPEND_THRESHOLD = 12
REVOKE_THRESHOLD = 24
TIER_LOW_DAYS = 7
TIER_HIGH_DAYS = 30
WINDOW_MONTHS = 24

RENEWAL_GRACE_DAYS = 30
BADGE_VALIDITY_MONTHS = 24
APPLICATION_WINDOW_DAYS = 90
RETURN_WINDOW_DAYS = 30
RECOVERY_THRESHOLD_PCT = Decimal("95.00")

# zone_code -> (allowed_badge_classes, escorted_entry_allowed)
ZONES = {
    "PUBLIC_TERMINAL": (frozenset(), True),
    "STERILE_CONCOURSE": (frozenset({"SIDA", "STERILE"}), True),
    "AOA_MOVEMENT": (frozenset({"SIDA", "AOA"}), True),
    "SECURE_ID_AREA": (frozenset({"SIDA"}), False),
}

NON_TERMINAL_APP_STATUSES = ("SUBMITTED", "STA_PENDING", "PENDING_REQUIREMENTS", "READY")

# Badge statuses that count against the sponsor's active badge quota.
ACTIVE_COUNT_STATUSES = ("ACTIVE", "SUSPENDED")
# Badge statuses that make a sponsor delinquent when overdue and unreturned.
DELINQUENT_STATUSES = ("LOST", "STOLEN", "EXPIRED", "REVOKED")
# Statuses from which a badge may be marked returned.
RETURNABLE_STATUSES = ("LOST", "STOLEN", "EXPIRED", "REVOKED")


# ---------------------------------------------------------------------------
# Training currency (training_currency_check)
# ---------------------------------------------------------------------------

def _completions(applicant_id: str, course_code: str) -> list:
    return [
        t
        for t in db.STORES["training_completions"].values()
        if t["applicant_id"] == applicant_id and t["course_code"] == course_code
    ]


def course_strict_current(applicant_id: str, course_code: str, now) -> bool:
    """A completion is STRICT-current at T iff completion.expires_at > T."""
    return any(t["_expires_dt"] > now for t in _completions(applicant_id, course_code))


def course_grace_current(applicant_id: str, course_code: str, now) -> bool:
    """GRACE-current at T iff completion.expires_at + 30 days > T."""
    return any(
        t["_expires_dt"] + timedelta(days=RENEWAL_GRACE_DAYS) > now
        for t in _completions(applicant_id, course_code)
    )


def all_courses_current(applicant_id: str, badge_class: str, now, grace: bool = False) -> bool:
    check = course_grace_current if grace else course_strict_current
    return all(
        check(applicant_id, course, now) for course in REQUIRED_COURSES[badge_class]
    )


def ready_evaluate(app: dict, now) -> bool:
    """PENDING_REQUIREMENTS <-> READY evaluation. Touches and returns True on change."""
    if app["status"] == "PENDING_REQUIREMENTS":
        if all_courses_current(app["applicant_id"], app["badge_class"], now, grace=False):
            app["status"] = "READY"
            db.touch(app)
            return True
    elif app["status"] == "READY":
        if not all_courses_current(app["applicant_id"], app["badge_class"], now, grace=False):
            app["status"] = "PENDING_REQUIREMENTS"
            db.touch(app)
            return True
    return False


# ---------------------------------------------------------------------------
# Badge expiry (badge_expiry_computation)
# ---------------------------------------------------------------------------

def compute_badge_expiry(applicant_id: str, badge_class: str, issued_dt, grace: bool):
    """expires_at = min(issued_at + 24 months, min over required courses of horizon).

    horizon(c) = course's latest completion.expires_at            (initial issuance)
               = course's latest completion.expires_at + 30 days  (renewal / replace)
    Returns None when some required course has no completion at all.
    """
    horizons = []
    for course in REQUIRED_COURSES[badge_class]:
        comps = _completions(applicant_id, course)
        if not comps:
            return None
        best = max(t["_expires_dt"] for t in comps)
        if grace:
            best = best + timedelta(days=RENEWAL_GRACE_DAYS)
        horizons.append(best)
    cap = db.add_months(issued_dt, BADGE_VALIDITY_MONTHS)
    return min([cap] + horizons)


# ---------------------------------------------------------------------------
# Sponsor standing (sponsor_active_badge_count, sponsor_delinquency_check)
# ---------------------------------------------------------------------------

def sponsor_active_badge_count(sponsor_id: str) -> int:
    return sum(
        1
        for b in db.STORES["badges"].values()
        if b["sponsor_id"] == sponsor_id and b["status"] in ACTIVE_COUNT_STATUSES
    )


def sponsor_delinquent(sponsor_id: str, now) -> bool:
    """Overdue comparison is inclusive: due exactly at return_deadline counts."""
    for b in db.STORES["badges"].values():
        if (
            b["sponsor_id"] == sponsor_id
            and b["status"] in DELINQUENT_STATUSES
            and b.get("_return_deadline_dt") is not None
            and b["_return_deadline_dt"] <= now
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Badge lifecycle helpers (escort chains, suspension, deactivation)
# ---------------------------------------------------------------------------

def granted_privilege(badge_id: str):
    for p in db.STORES["escort_privileges"].values():
        if p["badge_id"] == badge_id and p["status"] == "GRANTED":
            return p
    return None


def revoke_granted_privilege(badge_id: str, reason: str) -> None:
    p = granted_privilege(badge_id)
    if p is not None:
        p["status"] = "REVOKED"
        p["revoked_reason"] = reason
        db.touch(p)


def suspend_badge(badge: dict, by: str, reason: str, until_dt) -> None:
    """ACTIVE -> SUSPENDED with the escort-revocation chain."""
    badge["status"] = "SUSPENDED"
    badge["suspended_by"] = by
    badge["suspension_reason"] = reason
    if until_dt is not None:
        badge["suspended_until"] = db.fmt_clock(until_dt)
        badge["_suspended_until_dt"] = until_dt
    else:
        badge["suspended_until"] = None
        badge["_suspended_until_dt"] = None
    revoke_granted_privilege(badge["id"], "BADGE_SUSPENDED")
    db.touch(badge)


def deactivate_badge(badge: dict, new_status: str, deactivated_dt) -> None:
    """Shared bookkeeping for LOST / STOLEN / EXPIRED / REVOKED transitions."""
    badge["status"] = new_status
    badge["deactivated_at"] = db.fmt_clock(deactivated_dt)
    badge["_deactivated_dt"] = deactivated_dt
    deadline = deactivated_dt + timedelta(days=RETURN_WINDOW_DAYS)
    badge["return_deadline"] = db.fmt_clock(deadline)
    badge["_return_deadline_dt"] = deadline
    revoke_granted_privilege(badge["id"], "BADGE_DEACTIVATED")
    db.touch(badge)


# ---------------------------------------------------------------------------
# Violation points (violation_points_and_suspension)
# ---------------------------------------------------------------------------

def holder_windowed_points(applicant_id: str, now) -> int:
    """Sum of points over SUSTAINED violations of the same applicant's badges
    with occurred_at strictly within the trailing 24 months."""
    cutoff = db.add_months(now, -WINDOW_MONTHS)
    total = 0
    for v in db.STORES["violations"].values():
        if v["status"] != "SUSTAINED":
            continue
        badge = db.STORES["badges"].get(v["badge_id"])
        if badge is None or badge["applicant_id"] != applicant_id:
            continue
        if v["_occurred_dt"] > cutoff:
            total += v["points"]
    return total


def apply_threshold_cascade(badge: dict, manager_id: str, now) -> None:
    """Threshold cascade against the badge a sustained violation was recorded on."""
    pts = holder_windowed_points(badge["applicant_id"], now)
    if pts >= REVOKE_THRESHOLD and badge["status"] in ("ACTIVE", "SUSPENDED"):
        deactivate_badge(badge, "REVOKED", now)
    elif pts >= SUSPEND_THRESHOLD and badge["status"] == "ACTIVE":
        days = TIER_LOW_DAYS if pts <= 17 else TIER_HIGH_DAYS
        suspend_badge(badge, by=manager_id, reason="VIOLATION_POINTS", until_dt=now + timedelta(days=days))


# ---------------------------------------------------------------------------
# Access decision (access_decision)
# ---------------------------------------------------------------------------

def access_decide(badge, zone_code: str, escortee_count: int):
    """Returns (decision, denial_reason). Denial is a logged outcome, not an error."""
    if badge is None:
        return "DENIED", "DENIED_NO_BADGE"
    if badge["status"] != "ACTIVE":
        return "DENIED", "DENIED_BADGE_INACTIVE"
    allowed_classes, escorted_allowed = ZONES[zone_code]
    if badge["badge_class"] not in allowed_classes:
        return "DENIED", "DENIED_ZONE_CLASS"
    if escortee_count > 0:
        if not escorted_allowed:
            return "DENIED", "DENIED_ESCORT_NOT_PERMITTED"
        priv = granted_privilege(badge["id"])
        if priv is None:
            return "DENIED", "DENIED_ESCORT_NOT_PERMITTED"
        if escortee_count > priv["max_escortees"]:
            return "DENIED", "DENIED_ESCORT_CAPACITY"
    return "ALLOWED", None


# ---------------------------------------------------------------------------
# Audit recovery rates (audit_recovery_rate)
# ---------------------------------------------------------------------------

def _round2(accounted: int, scoped: int) -> Decimal:
    return (Decimal(100) * Decimal(accounted) / Decimal(scoped)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def audit_scope(cycle: dict) -> list:
    """Badges whose deactivated_at falls in [window_start, window_end) — half-open."""
    start = cycle["_window_start_dt"]
    end = cycle["_window_end_dt"]
    return [
        b
        for b in db.STORES["badges"].values()
        if b.get("_deactivated_dt") is not None and start <= b["_deactivated_dt"] < end
    ]


def _is_accounted(badge: dict) -> bool:
    return badge["status"] in ("RETURNED", "VOIDED")


def audit_provisional(cycle: dict, now):
    """Live provisional figures while OPEN: due scope = past-due return deadlines."""
    scope = audit_scope(cycle)
    due = [
        b
        for b in scope
        if b.get("_return_deadline_dt") is not None and b["_return_deadline_dt"] <= now
    ]
    due_scoped = len(due)
    due_accounted = sum(1 for b in due if _is_accounted(b))
    rate = None if due_scoped == 0 else float(_round2(due_accounted, due_scoped))
    return due_scoped, due_accounted, rate


def close_audit_cycle(cycle: dict) -> None:
    """Freeze final figures (aggregate-then-round) and close the cycle."""
    scope = audit_scope(cycle)
    scoped = len(scope)
    accounted = sum(1 for b in scope if _is_accounted(b))
    if scoped == 0:
        rate_dec = Decimal("100.00")
    else:
        rate_dec = _round2(accounted, scoped)

    per_class = []
    for cls in sorted({b["badge_class"] for b in scope}):
        sub = [b for b in scope if b["badge_class"] == cls]
        sub_scoped = len(sub)
        sub_accounted = sum(1 for b in sub if _is_accounted(b))
        per_class.append(
            {
                "badge_class": cls,
                "scoped": sub_scoped,
                "accounted": sub_accounted,
                "rate_pct": float(_round2(sub_accounted, sub_scoped)),
            }
        )

    cycle["scoped_count"] = scoped
    cycle["accounted_count"] = accounted
    cycle["recovery_rate_pct"] = float(rate_dec)
    cycle["per_class_rates"] = per_class
    cycle["outcome"] = "COMPLIANT" if rate_dec >= RECOVERY_THRESHOLD_PCT else "DEFICIENT"
    cycle["due_scoped_count"] = None
    cycle["due_accounted_count"] = None
    cycle["recovery_rate_provisional_pct"] = None
    cycle["status"] = "CLOSED"
    db.touch(cycle)


# ---------------------------------------------------------------------------
# Logical clock sweep (PRD §2.5)
# ---------------------------------------------------------------------------

def sweep_clock(now) -> None:
    """Atomically apply every time-driven transition for a clock set."""
    # Badges in ACTIVE/SUSPENDED whose expires_at has been reached -> EXPIRED.
    for badge in list(db.STORES["badges"].values()):
        if badge["status"] in ("ACTIVE", "SUSPENDED") and badge["_expires_dt"] <= now:
            deactivate_badge(badge, "EXPIRED", badge["_expires_dt"])

    # Non-terminal applications past application_expires_at -> EXPIRED (inclusive).
    for app in list(db.STORES["applications"].values()):
        if app["status"] in NON_TERMINAL_APP_STATUSES and app["_app_expires_dt"] <= now:
            app["status"] = "EXPIRED"
            db.touch(app)

    # Readiness cycle: READY regression and PENDING_REQUIREMENTS promotion.
    for app in list(db.STORES["applications"].values()):
        if app["status"] in ("READY", "PENDING_REQUIREMENTS"):
            ready_evaluate(app, now)
