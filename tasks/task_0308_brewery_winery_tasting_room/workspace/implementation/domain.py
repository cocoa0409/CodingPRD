"""Derived-field reconciliation and shared domain helpers.

Recompute helpers centralise the "every derived field stays reconciled"
contract (PRD §2.5). When a recompute mutates a primary resource, callers are
responsible for calling db.touch() on that resource per PRD §2.4 (version +
updated_at bump). These helpers only set the derived values.
"""
from datetime import timedelta

import constants as C
from db import db
from clock import now as clock_now
from util import parse_datetime


# ---------------------------------------------------------------------------
# Winery derived balances (PRD §3.1)
# ---------------------------------------------------------------------------
def recompute_winery_bulk(winery):
    """bulk_volume_gallons = SUM over non-terminal batches of available bulk."""
    total = 0.0
    for b in db.batches.values():
        if b["winery_id"] != winery["id"]:
            continue
        if b["status"] in ("FERMENTING", "AGING", "BOTTLING"):
            total += b["volume_in_gallons"] - b["loss_gallons"] - b["bottled_volume_gallons"]
    winery["bulk_volume_gallons"] = total


def recompute_winery_loyalty_liability(winery):
    """loyalty_point_liability = SUM of loyalty_points over this winery's memberships."""
    total = 0
    for m in db.memberships.values():
        if m["winery_id"] == winery["id"]:
            total += m["loyalty_points"]
    winery["loyalty_point_liability"] = total


# ---------------------------------------------------------------------------
# Product derived balances (PRD §3.4)
# ---------------------------------------------------------------------------
def recompute_product_free(product):
    """free_bottles = on_hand_bottles - allocated_bottles (never negative semantics
    arise from invariants, not clamping)."""
    product["free_bottles"] = product["on_hand_bottles"] - product["allocated_bottles"]


# ---------------------------------------------------------------------------
# Batch derived bulk (PRD §3.2)
# ---------------------------------------------------------------------------
def recompute_batch_available(batch):
    """available_bulk_gallons = volume_in_gallons - loss_gallons - bottled_volume_gallons;
    never negative."""
    val = batch["volume_in_gallons"] - batch["loss_gallons"] - batch["bottled_volume_gallons"]
    batch["available_bulk_gallons"] = val if val > 0 else 0.0


# ---------------------------------------------------------------------------
# AllocationRelease derived available (PRD §3.5)
# ---------------------------------------------------------------------------
def recompute_release_available(release):
    val = release["pool_bottles"] - release["reserved_bottles"] - release["committed_bottles"]
    release["available_bottles"] = val if val > 0 else 0


# ---------------------------------------------------------------------------
# Age gate (PRD §2.8, §3.6) — DOB-based, evaluated at the current clock
# ---------------------------------------------------------------------------
def age_years_at_now(date_of_birth_iso):
    dob = parse_datetime(date_of_birth_iso, "date_of_birth")
    now = clock_now()
    years = now.year - dob.year
    # subtract a year if the birthday hasn't occurred yet this year
    if (now.month, now.day) < (dob.month, dob.day):
        years -= 1
    return years


def is_of_age(date_of_birth_iso):
    return age_years_at_now(date_of_birth_iso) >= C.AGE_MINIMUM_YEARS
