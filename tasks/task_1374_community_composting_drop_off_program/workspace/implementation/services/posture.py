"""Site posture computation (calculation `site_posture`, PRD §2.7)."""

import math
from datetime import timedelta

import db

COMPLAINT_WINDOW_DAYS = 14


def compute_posture(site):
    """Evaluate the pinned tier sequence and return the posture string.

    Tiers (first match wins):
      1. site.status != OPERATIONAL or program.status != ACTIVE -> CLOSED
      2. host_agreement_id is null -> CLOSED
      3. (stored_kg - pending_pickup_kg) >= capacity_kg -> SUSPENDED
      4. open MAJOR/CRITICAL contam count >= 2 * posture_contam_threshold -> SUSPENDED
      5. available >= ceil(0.8 * capacity) OR open contam >= threshold
         OR unresolved complaints 14d >= complaint threshold -> WATCH
      6. else OPEN
    """
    program = db.programs.get(site["program_id"])
    now = db.clock_now()

    if site["status"] != "OPERATIONAL" or (program and program["status"] != "ACTIVE"):
        return "CLOSED"

    if not site.get("host_agreement_id"):
        return "CLOSED"

    stored = float(site.get("stored_kg", 0))
    pending = float(site.get("pending_pickup_kg", 0))
    available = stored - pending
    capacity = site["capacity_kg"]

    if available >= capacity:
        return "SUSPENDED"

    contam_threshold = program["posture_contam_threshold"] if program else 3
    complaint_threshold = program["posture_complaint_threshold"] if program else 2

    open_reports = [
        r for r in db.contamination_reports.values()
        if r["site_id"] == site["id"] and r["status"] in ("OPEN", "FEEDBACK_SENT")
    ]
    open_count = len(open_reports)
    severe_count = sum(1 for r in open_reports if r["severity"] in ("MAJOR", "CRITICAL"))

    if severe_count >= 2 * contam_threshold:
        return "SUSPENDED"

    cap_watch = math.ceil(0.8 * capacity)
    window_start = now - timedelta(days=COMPLAINT_WINDOW_DAYS)
    unresolved_complaints = sum(
        1
        for c in db.complaints.values()
        if c["site_id"] == site["id"]
        and c["status"] in ("OPEN", "ACKNOWLEDGED", "REOPENED")
        and window_start <= c["reported_at"] <= now
    )

    if (
        available >= cap_watch
        or open_count >= contam_threshold
        or unresolved_complaints >= complaint_threshold
    ):
        return "WATCH"

    return "OPEN"


def recompute_site_posture(site):
    """Recompute and store a site's posture (does not bump version by itself)."""
    site["posture"] = compute_posture(site)
    return site["posture"]
