"""Domain helpers: entity stamping, accrual ledger, offering totals, lazy defaults."""
from db import db, next_seq
from services.calculations import preferred_return_accrual_cents
from util import CLOCK, fmt_dt, new_id, parse_dt

# Subscription states that count toward offering.total_committed_cents.
COMMITTED_STATES = ("SUITABILITY_APPROVED", "AWAITING_FUNDING", "FUNDED")
# Terminal subscription states (SCAFFOLD §1.2).
TERMINAL_SUB_STATES = ("FUNDED", "WITHDRAWN")
# "ACCREDITATION_VERIFIED-or-later" set for transfer-buyer onboarding.
ONBOARDED_STATES = ("ACCREDITATION_VERIFIED", "SUITABILITY_APPROVED", "AWAITING_FUNDING", "FUNDED")


def stamp_new(obj):
    """Full lifecycle resource: id + created_at/updated_at + version=1."""
    obj["id"] = new_id()
    ts = CLOCK.now_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def stamp_new_light(obj):
    """Light resource (SubscriptionDocument / DistributionLine / portal session):
    id + created_at only on the wire; _seq stays internal for stable ordering."""
    obj["id"] = new_id()
    obj["created_at"] = CLOCK.now_iso()
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    """PRD 2.4: version increments by one on every mutation of the resource."""
    obj["updated_at"] = CLOCK.now_iso()
    obj["version"] = obj.get("version", 1) + 1


def sorted_items(records):
    return sorted(records, key=lambda o: (o["created_at"], o.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Preferred-return accrual (lazy, PRD 3.8)
# ---------------------------------------------------------------------------
#
# Internal per-subscription accrual ledger:
#   _pref_ledger     — net debits: preferred return paid out or transferred away
#                      (credits for pref transferred in are negative debits)
#   _accrued_frozen  — True while not FUNDED; the accrual then reads as the
#                      frozen snapshot instead of a live computation
#   _frozen_accrued  — value frozen when the subscription leaves FUNDED


def lifetime_accrual(sub, offering, as_of):
    return preferred_return_accrual_cents(
        sub["funded_cents"],
        offering.get("preferred_return_pct_annual"),
        offering.get("carried_interest_pct"),
        sub.get("funded_at"),
        as_of,
    )


def current_accrued_pref(sub, offering=None, as_of=None):
    """accrued_pref_cents as of `as_of` (default: logical now), net of the ledger."""
    if sub.get("_accrued_frozen", True):
        return sub.get("_frozen_accrued", 0)
    if offering is None:
        offering = db["offerings"].get(sub["offering_id"])
    if offering is None:
        return 0
    as_of = as_of or CLOCK.now()
    return lifetime_accrual(sub, offering, as_of) - sub.get("_pref_ledger", 0)


def freeze_accrual(sub, offering=None):
    """Snapshot the accrual when a subscription leaves FUNDED (withdraw/dissolve)."""
    sub["_frozen_accrued"] = current_accrued_pref(sub, offering)
    sub["_accrued_frozen"] = True


def unfreeze_accrual(sub):
    sub["_accrued_frozen"] = False


# ---------------------------------------------------------------------------
# Offering aggregates (computed fields per SCAFFOLD §1.1)
# ---------------------------------------------------------------------------

def offering_subscriptions(offering_id):
    return [s for s in db["subscriptions"].values() if s["offering_id"] == offering_id]


def offering_total_committed(offering_id):
    return sum(
        s["committed_cents"]
        for s in offering_subscriptions(offering_id)
        if s["status"] in COMMITTED_STATES
    )


def offering_total_funded(offering_id):
    return sum(
        s["funded_cents"]
        for s in offering_subscriptions(offering_id)
        if s["status"] == "FUNDED"
    )


def offering_unreturned_capital(offering_id):
    return sum(
        s["unreturned_capital_cents"]
        for s in offering_subscriptions(offering_id)
        if s["status"] == "FUNDED"
    )


def funded_subscriptions(offering_id):
    """FUNDED subscriptions in waterfall order: funded_at ASC, created_at ASC."""
    subs = [s for s in offering_subscriptions(offering_id) if s["status"] == "FUNDED"]
    return sorted(subs, key=lambda s: (s.get("funded_at") or "", s["created_at"], s.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Lazy contribution defaulting (PRD 2.8 / 3.4)
# ---------------------------------------------------------------------------

def sweep_defaults():
    """Default past-due, under-funded contributions; suspend their investors.

    Runs before every request (lazy observation on any read/write) and again
    eagerly inside the clock-advance endpoint.
    """
    now = CLOCK.now()
    for c in db["contributions"].values():
        if c["status"] not in ("PENDING", "ESCROW_RECEIVED"):
            continue
        call = db["capital_calls"].get(c["capital_call_id"])
        if call is None or call["status"] not in ("ISSUED", "PARTIALLY_FUNDED"):
            continue
        if now > parse_dt(call["due_date"]) and c["amount_received_cents"] < c["amount_due_cents"]:
            c["status"] = "DEFAULTED"
            touch(c)
            sub = db["subscriptions"].get(c["subscription_id"])
            if sub is None:
                continue
            inv = db["investors"].get(sub["investor_id"])
            if inv is not None and inv["portal_access_status"] != "SUSPENDED":
                inv["portal_access_status"] = "SUSPENDED"
                touch(inv)


def call_contributions(capital_call_id):
    return [c for c in db["contributions"].values() if c["capital_call_id"] == capital_call_id]


def check_not_future_period(report_year, report_quarter):
    """ERR_FUTURE_REPORT_PERIOD when the report period lies ahead of the clock."""
    from errors import raise_error
    from util import current_quarter

    cy, cq = current_quarter(CLOCK.now())
    if (report_year, report_quarter) > (cy, cq):
        raise_error(
            "ERR_FUTURE_REPORT_PERIOD",
            f"report period {report_year} Q{report_quarter} is in the future",
        )
