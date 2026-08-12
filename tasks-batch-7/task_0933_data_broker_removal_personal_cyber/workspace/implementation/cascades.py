"""Multi-row side-effect chains. Hop ordering is normative (PRD §2.11)."""

import calc
import constants as K
import derive
import ledger
import rows
from clock import CLOCK, plus_days, whole_days_between
from store import DB


# --- scans ------------------------------------------------------------------

def cancel_scan(scan, reason_code, account_id):
    """QUEUED|FAILED -> CANCELLED, releasing the held SCAN unit."""
    scan["status"] = "CANCELLED"
    if scan["entitlement_units_held"] == 1:
        scan["entitlement_units_held"] = 0
        profile = DB.profiles.get(scan["profile_id"])
        member_id = profile["member_id"] if profile else None
        ledger.append(
            account_id=account_id,
            member_id=member_id,
            resource_type="SCAN",
            entry_type="RELEASE",
            amount=1,
            reason_code=reason_code,
            source_reference=scan["id"],
        )
    rows.touch(scan)


def cancel_queued_scans(profile, account_id):
    for scan in derive.profile_scans(profile["id"]):
        if scan["status"] == "QUEUED":
            cancel_scan(scan, "SCAN_CANCELLED", account_id)


# --- monitored profiles -----------------------------------------------------

def pause_profile(profile, account_id):
    profile["status"] = "PAUSED"
    cancel_queued_scans(profile, account_id)
    rows.touch(profile)


def retire_profile(profile, account_id):
    """DRAFT|ACTIVE|PAUSED -> RETIRED. DRAFT releases nothing."""
    origin = profile["status"]
    profile["status"] = "RETIRED"
    profile["retired_at"] = CLOCK.now
    if origin == "ACTIVE":
        cancel_queued_scans(profile, account_id)
    if origin in ("ACTIVE", "PAUSED"):
        ledger.append(
            account_id=account_id,
            member_id=profile["member_id"],
            resource_type="PROFILE",
            entry_type="RELEASE",
            amount=1,
            reason_code="PROFILE_RETIRED",
            source_reference=profile["id"],
        )
    rows.touch(profile)


# --- device seats / add-ons -------------------------------------------------

def void_bound_seats(addon):
    for seat in derive.addon_seats(addon["id"]):
        if seat["status"] == "BOUND":
            seat["status"] = "VOIDED"
            seat["voided_at"] = CLOCK.now
            # bind_count is preserved so binding history survives.
            rows.touch(seat)


def restore_voided_seats(addon):
    for seat in derive.addon_seats(addon["id"]):
        if seat["status"] != "VOIDED":
            continue
        member = DB.members.get(seat["member_id"])
        if member is None or member["status"] != "ACTIVE":
            continue
        seat["status"] = "BOUND"
        seat["bound_at"] = CLOCK.now
        seat["voided_at"] = None
        seat["bind_count"] = seat["bind_count"] + 1
        rows.touch(seat)


def addon_inclusive_remaining_days(cycle):
    """Add-ons prorate on the INCLUSIVE remaining-day count (PRD §3.8)."""
    if cycle is None:
        return 0
    return max(0, whole_days_between(CLOCK.now, cycle["ends_at"])) + 1


def suspend_addon(addon):
    """ACTIVE -> SUSPENDED. Books the SEAT_RELEASED credit onto the OPEN cycle.

    The SEAT_RELEASED variant is keyed on the TRANSITION (SCAFFOLD
    calculations.addon_proration_amount trigger, PRD §3.8 "used when an add-on
    moves ACTIVE -> SUSPENDED"), so it books on the account-suspension cascade
    too, not only on POST /addons/{id}/suspend.
    """
    addon["status"] = "SUSPENDED"
    addon["suspended_at"] = CLOCK.now
    cycle = derive.open_cycle(addon["account_id"])
    if cycle is not None:
        days = addon_inclusive_remaining_days(cycle)
        credit = calc.addon_credit(
            int(addon["per_seat_fee_cents"]), int(addon["seats_total"]), days
        )
        cycle["addon_credit_cents"] = int(cycle["addon_credit_cents"]) + credit
        rows.touch(cycle)
    void_bound_seats(addon)
    rows.touch(addon)


def resume_addon(addon):
    addon["status"] = "ACTIVE"
    addon["suspended_at"] = None
    restore_voided_seats(addon)
    rows.touch(addon)


def cancel_addon(addon):
    origin = addon["status"]
    addon["status"] = "CANCELLED"
    if origin == "ACTIVE":
        void_bound_seats(addon)
    rows.touch(addon)


# --- billing cycles ---------------------------------------------------------

def close_cycle(cycle, account):
    """OPEN -> CLOSED, freezing the derived money and minting the successor."""
    pre, discount, total = calc.cycle_totals(cycle)
    cycle["frozen_totals"] = (pre, discount, total)
    cycle["closed_at"] = CLOCK.now
    cycle["status"] = "CLOSED"
    rows.touch(cycle)
    # When AND ONLY WHEN the owning account's status is ACTIVE (PRD §3.9).
    if account["status"] != "ACTIVE":
        return None
    plan = DB.plans.get(account["plan_id"])
    successor = rows.new_row(
        "cycles",
        {
            "account_id": account["id"],
            "cycle_seq": int(cycle["cycle_seq"]) + 1,
            "starts_at": CLOCK.now,
            "ends_at": plus_days(CLOCK.now, K.CYCLE_LENGTH_DAYS),
            "status": "OPEN",
            "base_charge_cents": int(plan["monthly_fee_cents"]),
            "proration_charge_cents": 0,
            "proration_credit_cents": 0,
            "addon_charge_cents": 0,
            "addon_credit_cents": 0,
            "closed_at": None,
            "frozen_totals": None,
        },
    )
    ledger.grant_cycle(account, successor, plan)
    return successor


# --- accounts ---------------------------------------------------------------

def suspend_account(account):
    """The depth-5 cascade. Ordering is normative."""
    # Hop 1
    account["status"] = "SUSPENDED"
    account["suspended_at"] = CLOCK.now
    # Hop 2: ACTIVE profiles -> PAUSED
    newly_paused = []
    for profile in derive.account_profiles(account["id"]):
        if profile["status"] == "ACTIVE":
            profile["status"] = "PAUSED"
            rows.touch(profile)
            newly_paused.append(profile)
    # Hops 3, 4 and 5: their QUEUED scans -> CANCELLED, then the ledger, then
    # the derived pool figures (which are read-time aggregates).
    for profile in newly_paused:
        for scan in derive.profile_scans(profile["id"]):
            if scan["status"] == "QUEUED":
                cancel_scan(scan, "SCAN_CANCELLED", account["id"])
    # Separate branch: ACTIVE add-ons -> SUSPENDED, voiding their bound seats.
    for addon in derive.account_addons(account["id"]):
        if addon["status"] == "ACTIVE":
            suspend_addon(addon)
    rows.touch(account)


def resume_account(account):
    account["status"] = "ACTIVE"
    account["suspended_at"] = None
    for addon in derive.account_addons(account["id"]):
        if addon["status"] == "SUSPENDED":
            resume_addon(addon)
    # Monitoring deliberately does NOT come back; paused profiles stay PAUSED.
    rows.touch(account)


def cancel_account(account):
    account["status"] = "CANCELLED"
    account["cancelled_at"] = CLOCK.now
    for addon in derive.account_addons(account["id"]):
        if addon["status"] in ("ACTIVE", "SUSPENDED"):
            cancel_addon(addon)
    for profile in derive.account_profiles(account["id"]):
        if profile["status"] in ("DRAFT", "ACTIVE", "PAUSED"):
            retire_profile(profile, account["id"])
    cycle = derive.open_cycle(account["id"])
    if cycle is not None:
        close_cycle(cycle, account)
    rows.touch(account)


# --- members ----------------------------------------------------------------

def remove_member(member):
    origin = member["status"]
    member["status"] = "REMOVED"
    if origin == "ACTIVE":
        for profile in derive.member_profiles(member["id"]):
            if profile["status"] in ("DRAFT", "ACTIVE", "PAUSED"):
                retire_profile(profile, member["account_id"])
        for seat in DB.seats.values():
            if seat["member_id"] == member["id"] and seat["status"] == "BOUND":
                seat["status"] = "RELEASED"
                seat["released_at"] = CLOCK.now
                rows.touch(seat)
    rows.touch(member)


def revoke_authorization(member):
    """The depth-4 void-and-refund cascade (PRD §3.2)."""
    # Hop 1
    member["authorization_status"] = "REVOKED"
    member["authorization_revoked_at"] = CLOCK.now
    # Hop 2: DRAFTED removal requests of this member -> VOIDED
    for request in DB.removal_requests.values():
        if request["member_id"] != member["id"] or request["status"] != "DRAFTED":
            continue
        request["status"] = "VOIDED"
        request["closed_at"] = CLOCK.now
        # Hop 3: refund the consumed unit
        if request["entitlement_units_consumed"] == 1 and request["entitlement_units_released"] == 0:
            request["entitlement_units_released"] = 1
            ledger.append(
                account_id=member["account_id"],
                member_id=member["id"],
                resource_type="REMOVAL",
                entry_type="RELEASE",
                amount=1,
                reason_code="AUTHORIZATION_REVOKED",
                source_reference=request["id"],
            )
        rows.touch(request)
    # Hop 4 is arithmetic on read-time aggregates.
    rows.touch(member)


# --- removal requests -------------------------------------------------------

def complete_removal(request, agent_id):
    # Hop 1
    request["status"] = "COMPLETED"
    request["closed_at"] = CLOCK.now
    request["completed_by_agent_id"] = agent_id
    rows.touch(request)
    # Hop 2: the linked exposure is suppressed
    exposure = DB.exposures.get(request["exposure_id"])
    if exposure is not None:
        if exposure["status"] == "FOUND":
            exposure["status"] = "SUPPRESSED"
        elif exposure["status"] == "REAPPEARED":
            exposure["status"] = "RE_SUPPRESSED"
        else:
            return
        exposure["suppression_count"] = exposure["suppression_count"] + 1
        exposure["last_suppressed_at"] = CLOCK.now
        rows.touch(exposure)
    # Hop 3 (profile counters) and the broker re-derivation are read-time
    # aggregates; nothing is stored.
