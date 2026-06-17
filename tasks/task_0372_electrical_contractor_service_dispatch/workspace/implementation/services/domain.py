"""Shared domain constants and helpers (PRD §3).

Calculation constants are taken verbatim from PRD §3.3, §3.7, §3.8 and
SCAFFOLD calculations[].constants.
"""

# Forward-looking quote default rate when no technician is dispatched (PRD §3.3).
DEFAULT_HOURLY_RATE_CENTS = 12000

# Invoice constants (PRD §3.7).
DISPATCH_FEE_CENTS = 8900
EMERGENCY_SURCHARGE_CENTS = 15000
TAX_RATE = "0.0825"  # kept as string for Decimal precision

# Warranty window (PRD §3.7): 30 days.
WARRANTY_DAYS = 30

# Scopes that require a permit and a MASTER technician (PRD §3.1, §3.3, §3.6).
PERMIT_SCOPES = {"PANEL", "EV_CHARGER"}

JOB_SCOPES = {"OUTLET", "PANEL", "EV_CHARGER"}
JOB_CLASSES = {"SERVICE", "INSTALL"}
JOB_PRIORITIES = {"STANDARD", "EMERGENCY"}


def job_zone(customer):
    """The zone a job routes to is derived from the customer's service_zip
    prefix (PRD §3.4). The zone is the leading ZIP-prefix of the service_zip;
    a technician matches when its service_zone equals this prefix."""
    return customer["service_zip"][:3]


def active_membership_for_customer(db, customer_id):
    """The customer's currently ACTIVE membership, or None (PRD §3.3).

    If multiple ACTIVE memberships somehow exist, the earliest-created one is
    used for a deterministic snapshot (stable created_at order)."""
    actives = [
        m for m in db.memberships.values()
        if m["customer_id"] == customer_id and m["status"] == "ACTIVE"
    ]
    if not actives:
        return None
    actives.sort(key=lambda m: (m["created_at"], m["_seq"]))
    return actives[0]


def plan_for_job(db, job):
    """Return the MembershipPlan referenced by the job's snapshotted membership,
    or None when the job has no membership."""
    if job.get("membership_id") is None:
        return None
    membership = db.memberships.get(job["membership_id"])
    if membership is None:
        return None
    return db.membership_plans.get(membership["plan_id"])
