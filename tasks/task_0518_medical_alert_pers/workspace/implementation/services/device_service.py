"""Device timing helpers (PRD 3.5)."""
from datetime import timedelta

from clock import clock
from models import touch


def recompute_next_test_due(device, plan):
    """next_test_due_at = last_test_at + plan.included_test_interval_days (PRD 3.5)."""
    last = device.get("last_test_at_dt")
    if last is None or plan is None:
        device["next_test_due_at_dt"] = None
        return
    device["next_test_due_at_dt"] = last + timedelta(days=plan["included_test_interval_days"])


def maybe_flag_needs_test(device):
    """PRD 3.5: an ACTIVE device whose clock.now >= next_test_due_at auto-flags
    NEEDS_TEST (on next alarm-create or test-submit). Returns True if flagged."""
    if device["status"] != "ACTIVE":
        return False
    due = device.get("next_test_due_at_dt")
    if due is not None and clock.now() >= due:
        device["status"] = "NEEDS_TEST"
        touch(device)
        return True
    return False
