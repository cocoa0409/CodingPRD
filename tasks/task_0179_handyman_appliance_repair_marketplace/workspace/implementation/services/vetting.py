"""Pro vetting + assignability (PRD §3.2, §3.5).

Assignability gates, evaluated background-first, then license, then skill tags
(SCAFFOLD validations priorities 8/9/10):
  - background gate: background_check_status == CLEARED  -> ERR_PRO_NOT_CLEARED
  - license gate: when category.requires_license, license_status == VERIFIED and
    license_expires_on in the future -> ERR_LICENSE_REQUIRED
  - skill gate: pro.skill_tags superset of category.skill_tags -> ERR_SKILL_TAG_MISMATCH

Background-check posture recompute (PRD §3.2 / SCAFFOLD Pro state machine):
  - PENDING->CLEARED when every CRIMINAL/IDENTITY check has decision PASS.
  - any CRIMINAL/IDENTITY FAIL -> FLAGGED (from PENDING or CLEARED). The
    CLEARED->FLAGGED edge cancels the Pro's SCHEDULED jobs and releases their
    windows.
  - LICENSE PASS -> license_status VERIFIED (+ license_expires_on); past expiry
    at decision time -> EXPIRED.
"""
from db import store
from errors import ApiError
from models import touch
from services import pricing


def assert_assignable(pro, category):
    """Run the three assignability gates in pinned order. Raises the first
    failing gate's ApiError."""
    if pro["background_check_status"] != "CLEARED":
        raise ApiError("ERR_PRO_NOT_CLEARED",
                       "Pro is not background-cleared")
    if category["requires_license"]:
        if pro["license_status"] != "VERIFIED":
            raise ApiError("ERR_LICENSE_REQUIRED",
                           "Pro license is not verified")
        exp = pro.get("license_expires_on")
        if exp is None or exp <= store.now():
            raise ApiError("ERR_LICENSE_REQUIRED",
                           "Pro license is missing or expired")
    required = set(category.get("skill_tags") or [])
    carried = set(pro.get("skill_tags") or [])
    if not required.issubset(carried):
        raise ApiError("ERR_SKILL_TAG_MISMATCH",
                       "Pro does not carry every required skill tag")


def _pro_checks(pro_id):
    return [c for c in store.background_checks.values() if c["pro_id"] == pro_id]


def recompute_background_status(pro):
    """Recompute background_check_status from this Pro's CRIMINAL/IDENTITY
    checks and fire the CLEARED->FLAGGED cancellation cascade when applicable.

    Returns True if status changed (so the caller can touch() the Pro)."""
    checks = _pro_checks(pro["id"])
    required = [c for c in checks if c["check_type"] in ("CRIMINAL", "IDENTITY")]
    any_fail = any(c["decision"] == "FAIL" for c in required)
    all_pass = len(required) > 0 and all(c["decision"] == "PASS" for c in required)

    old = pro["background_check_status"]
    new = old
    if any_fail:
        new = "FLAGGED"
    elif old == "PENDING" and all_pass:
        new = "CLEARED"

    if new == old:
        return False

    pro["background_check_status"] = new
    if old == "CLEARED" and new == "FLAGGED":
        _cancel_scheduled_jobs(pro)
    return True


def apply_license_decision(pro, check):
    """A LICENSE check PASS sets license_status VERIFIED and copies its expiry
    onto the Pro; a past-or-equal expiry at decision time -> EXPIRED. Returns
    True when the Pro's license posture changed."""
    if check["check_type"] != "LICENSE":
        return False
    if check["decision"] != "PASS":
        return False
    expiry = check.get("license_expires_on")
    pro["license_expires_on"] = expiry
    if expiry is not None and expiry > store.now():
        pro["license_status"] = "VERIFIED"
    else:
        pro["license_status"] = "EXPIRED"
    return True


def _cancel_scheduled_jobs(pro):
    """Cancel every SCHEDULED job assigned to this Pro and release the windows
    those jobs had booked (PRD §3.2)."""
    for job in list(store.jobs.values()):
        if job["pro_id"] == pro["id"] and job["status"] == "SCHEDULED":
            job["status"] = "CANCELLED"
            # release the window booked for this job, clearing booked_job_id.
            for win in store.dispatch_windows.values():
                if win.get("booked_job_id") == job["id"] and win["hold_state"] == "BOOKED":
                    win["hold_state"] = "RELEASED"
                    win["booked_job_id"] = None
                    touch(win)
            job["pro_id"] = None
            touch(job)
