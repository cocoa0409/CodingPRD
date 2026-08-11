"""Derived / computed field evaluation, all at read time (PRD §2.11)."""

import calc
import constants as K
from clock import CLOCK, plus_hours
from store import DB


# --- billing cycles ---------------------------------------------------------

def open_cycle(account_id):
    for c in DB.cycles.values():
        if c["account_id"] == account_id and c["status"] == "OPEN":
            return c
    return None


def account_cycles(account_id):
    return [c for c in DB.cycles.values() if c["account_id"] == account_id]


# --- entitlement ledger -----------------------------------------------------

def ledger_of_cycle(account_id, cycle_id):
    if cycle_id is None:
        return []
    return [
        e
        for e in DB.ledger.values()
        if e["account_id"] == account_id and e["cycle_id"] == cycle_id
    ]


def pool_figures(account_id):
    """Invariant 1 -- pool arithmetic, restricted to the single OPEN cycle."""
    cycle = open_cycle(account_id)
    entries = ledger_of_cycle(account_id, cycle["id"] if cycle else None)
    out = {}
    for resource in K.LEDGER_RESOURCE_TYPES:
        granted = sum(
            e["amount"] for e in entries
            if e["resource_type"] == resource and e["entry_type"] == "GRANT"
        )
        consumed = sum(
            e["amount"] for e in entries
            if e["resource_type"] == resource and e["entry_type"] == "CONSUME"
        )
        released = sum(
            e["amount"] for e in entries
            if e["resource_type"] == resource and e["entry_type"] == "RELEASE"
        )
        key = resource.lower()
        out[key] = {
            "granted": granted,
            "consumed": consumed,
            "released": released,
            "remaining": granted - consumed + released,
        }
    return out


def member_removal_net(member):
    """Member.removal_units_consumed_this_cycle: CONSUME minus RELEASE."""
    cycle = open_cycle(member["account_id"])
    if cycle is None:
        return 0
    consumed = 0
    released = 0
    for e in DB.ledger.values():
        if (
            e["member_id"] == member["id"]
            and e["cycle_id"] == cycle["id"]
            and e["resource_type"] == "REMOVAL"
        ):
            if e["entry_type"] == "CONSUME":
                consumed += e["amount"]
            elif e["entry_type"] == "RELEASE":
                released += e["amount"]
    return consumed - released


def member_subcap_remaining(member):
    account = DB.accounts.get(member["account_id"])
    plan = DB.plans.get(account["plan_id"]) if account else None
    if plan is None:
        return 0
    return int(plan["per_member_removal_subcap"]) - member_removal_net(member)


# --- household graph --------------------------------------------------------

def account_members(account_id):
    return [m for m in DB.members.values() if m["account_id"] == account_id]


def occupied_seat_count(account_id):
    return len(
        [m for m in account_members(account_id) if m["status"] in ("INVITED", "ACTIVE")]
    )


def member_profiles(member_id):
    return [p for p in DB.profiles.values() if p["member_id"] == member_id]


def account_profiles(account_id):
    member_ids = {m["id"] for m in account_members(account_id)}
    return [p for p in DB.profiles.values() if p["member_id"] in member_ids]


def account_of_profile(profile):
    member = DB.members.get(profile["member_id"])
    return DB.accounts.get(member["account_id"]) if member else None


def account_addons(account_id):
    return [a for a in DB.addons.values() if a["account_id"] == account_id]


def addon_seats(addon_id):
    return [s for s in DB.seats.values() if s["addon_id"] == addon_id]


def profile_identifiers(profile_id):
    return [i for i in DB.identifiers.values() if i["profile_id"] == profile_id]


def profile_findings(profile_id):
    return [f for f in DB.findings.values() if f["profile_id"] == profile_id]


def profile_exposures(profile_id):
    return [e for e in DB.exposures.values() if e["profile_id"] == profile_id]


def profile_scans(profile_id):
    return [s for s in DB.scans.values() if s["profile_id"] == profile_id]


def exposure_requests(exposure_id):
    return [r for r in DB.removal_requests.values() if r["exposure_id"] == exposure_id]


def broker_exposures(broker_id):
    return [e for e in DB.exposures.values() if e["broker_id"] == broker_id]


def broker_requests(broker_id):
    return [r for r in DB.removal_requests.values() if r["broker_id"] == broker_id]


# --- per-entity derived values ---------------------------------------------

def profile_hygiene(profile):
    open_findings = [f for f in profile_findings(profile["id"]) if f["status"] == "OPEN"]
    return calc.hygiene(open_findings, bool(profile["two_factor_attested"]))


def request_on_time(request):
    if request["status"] != "COMPLETED":
        return None
    if request["closed_at"] is None or request["sla_deadline_at"] is None:
        return None
    return request["closed_at"] <= request["sla_deadline_at"]


def document_effective_status(document):
    if document["status"] == "VERIFIED" and CLOCK.now < document["expires_at_dt"]:
        return "VALID"
    return "INVALID"


def seat_rebind_eligible_at(seat):
    if seat["released_at"] is None:
        return None
    return plus_hours(seat["released_at"], K.SEAT_REBIND_COOLOFF_HOURS)


def addon_seat_counts(addon):
    bound = len([s for s in addon_seats(addon["id"]) if s["status"] == "BOUND"])
    return bound, int(addon["seats_total"]) - bound


def broker_counts_lifetime(broker_id):
    reappearances = sum(e["reappearance_count"] for e in broker_exposures(broker_id))
    requests = broker_requests(broker_id)
    expired = len([r for r in requests if r["status"] == "EXPIRED"])
    rejected = len([r for r in requests if r["status"] == "REJECTED"])
    on_time = len(
        [r for r in requests if r["status"] == "COMPLETED" and request_on_time(r) is True]
    )
    return reappearances, expired, rejected, on_time


def broker_counts_current_window(broker_id):
    cutoff = CLOCK.now.timestamp() - K.COMPLIANCE_WINDOW_DAYS * K.SECONDS_PER_DAY

    def at_or_after(dt):
        return dt is not None and dt.timestamp() >= cutoff

    reappearances = len(
        [
            e
            for e in broker_exposures(broker_id)
            if e["status"] == "REAPPEARED" and at_or_after(e["last_seen_at"])
        ]
    )
    requests = broker_requests(broker_id)
    expired = len(
        [r for r in requests if r["status"] == "EXPIRED" and at_or_after(r["closed_at"])]
    )
    rejected = len(
        [r for r in requests if r["status"] == "REJECTED" and at_or_after(r["closed_at"])]
    )
    on_time = len(
        [
            r
            for r in requests
            if r["status"] == "COMPLETED"
            and request_on_time(r) is True
            and at_or_after(r["closed_at"])
        ]
    )
    return reappearances, expired, rejected, on_time


def cycle_money(cycle):
    """Derived money. Frozen once the cycle is CLOSED (PRD §2.11)."""
    if cycle["status"] == "CLOSED" and cycle["frozen_totals"] is not None:
        return cycle["frozen_totals"]
    return calc.cycle_totals(cycle)
