"""Derived (computed) fields, always recalculated from source data.

StaffMember.weighted_open_units / open_case_count, ReferralPanelMember.
active_referral_count and the GrantProgram ledger buckets are pure functions
of the underlying cases/referrals, so every cascade (assign, hold, resume,
close, grant freeze, sweep auto-close) stays consistent by construction.
"""
from db import db
from services.calc import EXTENDED_WEIGHT


# ---- caseload (attorney only; paralegal assignments never add load) ----

def attorney_load_count(staff_id):
    """(weighted_open_units, open_case_count) over OPEN cases only."""
    weight = 0
    count = 0
    for c in db.cases.values():
        if c["assigned_attorney_id"] == staff_id and c["status"] == "OPEN":
            weight += c["case_weight"]
            count += 1
    return weight, count


def available_units(member):
    weight, _ = attorney_load_count(member["id"])
    return member["max_units"] - weight


def active_attorney_pool():
    """Sum of available_units over ACTIVE attorneys (others contribute 0)."""
    total = 0
    for m in db.staff.values():
        if m["staff_type"] == "ATTORNEY" and m["status"] == "ACTIVE":
            total += available_units(m)
    return total


def any_active_attorney_with(min_units):
    for m in db.staff.values():
        if (m["staff_type"] == "ATTORNEY" and m["status"] == "ACTIVE"
                and available_units(m) >= min_units):
            return True
    return False


# ---- referral panel ----

def panel_active_count(panel_member_id):
    return sum(1 for r in db.referrals.values()
               if r["panel_member_id"] == panel_member_id
               and r["status"] == "ACCEPTED")


# ---- grant ledger ----

def grant_reserved_cents(program_id):
    return sum(c["reserved_cents"] for c in db.cases.values()
               if c["grant_program_id"] == program_id
               and c["funding_status"] in ("GRANT_RESERVED", "GRANT_FROZEN"))


def grant_spent_cents(program_id):
    return sum(c["reserved_cents"] for c in db.cases.values()
               if c["grant_program_id"] == program_id
               and c["funding_status"] == "GRANT_SPENT")


# ---- lookups ----

def find_venue_rule(county, case_type):
    for r in db.venue_rules.values():
        if r["county"] == county and r["case_type"] == case_type:
            return r
    return None


def latest_conflict_check(application_id):
    checks = [c for c in db.conflict_checks.values()
              if c["application_id"] == application_id]
    if not checks:
        return None
    return max(checks, key=lambda c: (c["created_at"], c["_seq"]))


def application_of(case):
    return db.applications.get(case["application_id"])
