"""Common-element warranty claims (PRD 3.9).

The remediation window is a CLOSED interval [start, end] with a 259200-second
cooldown on both sides of the pairwise same-component test, plus a separate
project-wide depth cap with no cooldown.  This geometry is deliberately unlike
the half-open closing-batch window in services/sales.py and shares no helper
with it.
"""

from fractions import Fraction

import clock
import store
from rounding import half_up_frac

SECONDS_PER_MONTH = 2592000
STRUCTURAL_WARRANTY_SECONDS = 60 * SECONDS_PER_MONTH
NON_STRUCTURAL_WARRANTY_SECONDS = 24 * SECONDS_PER_MONTH
REMEDIATION_COOLDOWN_SECONDS = 259200
COMPONENT_CAP_BP = 6000
REOPEN_UPLIFT_BP = 2500
TOTAL_BP = 10000
MAX_REOPENS = 2

OCCUPYING_CLAIM_STATUSES = ("REMEDIATION_SCHEDULED", "REMEDIATED")


def warranty_expiry(project, component):
    """Pinned at filing from the project's `warranty_start_at`, with the window
    selected entirely by the component's `is_structural` flag."""
    seconds = (STRUCTURAL_WARRANTY_SECONDS if component["is_structural"]
               else NON_STRUCTURAL_WARRANTY_SECONDS)
    return clock.plus_seconds(project["warranty_start_at"], seconds)


def component_cap_cents(component):
    return half_up_frac(
        Fraction(component["replacement_cost_cents"] * COMPONENT_CAP_BP,
                 TOTAL_BP))


def admission_charge_cents(claim, component):
    """First admission: the lesser of the claimed cost and the component cap."""
    return min(claim["claimed_cost_cents"], component_cap_cents(component))


def reopen_charge_cents(claim, component):
    """Reopen admission applies the uplift *before* the cap and returns the new
    total, so only the delta reaches the project's charge ledger."""
    uplift = half_up_frac(
        Fraction(claim["accrued_charge_cents"] * REOPEN_UPLIFT_BP, TOTAL_BP))
    return min(claim["accrued_charge_cents"] + uplift,
               component_cap_cents(component))


def component_window_conflict(claim, start_at, end_at):
    """Pairwise, same component, both comparisons inclusive and each existing
    window's tail extended by the cooldown."""
    for other in store.warranty_claims.values():
        if other["id"] == claim["id"]:
            continue
        if other["major_component_id"] != claim["major_component_id"]:
            continue
        if other["status"] not in OCCUPYING_CLAIM_STATUSES:
            continue
        if other["remediation_start_at"] is None:
            continue
        other_end = clock.plus_seconds(other["remediation_end_at"],
                                       REMEDIATION_COOLDOWN_SECONDS)
        requested_end = clock.plus_seconds(end_at,
                                           REMEDIATION_COOLDOWN_SECONDS)
        if start_at <= other_end and other["remediation_start_at"] <= requested_end:
            return other
    return None


def _project_windows(project_id, exclude_claim_id=None):
    windows = []
    for other in store.project_claims(project_id):
        if other["id"] == exclude_claim_id:
            continue
        if other["status"] not in OCCUPYING_CLAIM_STATUSES:
            continue
        if (other["remediation_start_at"] is None
                or other["remediation_end_at"] is None):
            continue
        windows.append((other["remediation_start_at"],
                        other["remediation_end_at"]))
    return windows


def max_overlap_depth(project_id, start_at, end_at, exclude_claim_id=None,
                      include_requested=True):
    """Sweep the endpoint events with starts placed before ends at the same
    instant, so an instant shared by one window's end and another's start
    counts both windows.  Returns the greatest depth reached at any instant
    inside the closed window [start_at, end_at]."""
    windows = _project_windows(project_id, exclude_claim_id)
    if include_requested:
        windows = windows + [(start_at, end_at)]

    # Depth can only rise at a window start, so the candidate instants are the
    # window starts lying inside the requested closed window, plus its own
    # opening instant for windows that were already open when it begins.
    candidates = [start_at]
    for window_start, _window_end in windows:
        if start_at <= window_start <= end_at:
            candidates.append(window_start)

    deepest = 0
    for instant in candidates:
        depth = len([1 for window_start, window_end in windows
                     if window_start <= instant <= window_end])
        if depth > deepest:
            deepest = depth
    return deepest
