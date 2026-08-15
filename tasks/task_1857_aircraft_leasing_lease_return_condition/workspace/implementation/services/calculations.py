"""Calculation rules (scaffold section 1.3). All money is integer cents;
decimal products are rounded half-up at the pinned rounding points."""
from decimal import Decimal, ROUND_HALF_UP

from db import STORE

UPLIFT = {
    "CRITICAL": Decimal("1.50"),
    "MAJOR": Decimal("1.25"),
    "MINOR": Decimal("1.10"),
}

REQUIRED_DOC_TYPES = ("BIRTH_RECORD", "AIRWORTHINESS_CERT", "ENGINE_LOG", "LLP_STATUS")

TIER1_LIMIT_HOURS = 50
TIER1_RATE_CENTS = 5000
TIER2_RATE_CENTS = 7500
CYCLE_RATIO_NUM = 1
CYCLE_RATIO_DEN = 2
CYCLE_SURCHARGE_CENTS = 25000

MAX_REINSPECTIONS = 1
TRANSITION_BUFFER_DAYS = 2

CHECKLIST_TEMPLATE = (
    ("AIRFRAME", "CRITICAL"),
    ("ENGINE", "MAJOR"),
    ("INTERIOR", "MINOR"),
    ("PAINT", "MINOR"),
)


def D(v):
    return Decimal(str(v))


def round_half_up_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_balance(lease):
    lease["reserve_balance_cents"] = (
        lease["reserve_accrued_cents"]
        - lease["reserve_reimbursed_cents"]
        - lease["reserve_forfeited_cents"]
    )


def compute_accrual(lease, report):
    """maintenance_reserve_accrual: rounding applied once to the FH term;
    the cycle term is exact integer arithmetic."""
    hours = D(report["flight_hours"])
    if lease["accrual_basis"] == "MINIMUM_GUARANTEE":
        hours = max(hours, D(lease["minimum_monthly_hours"]))
    fh_term = round_half_up_cents(hours * lease["reserve_rate_per_fh_cents"])
    fc_term = int(report["flight_cycles"]) * lease["reserve_rate_per_fc_cents"]
    return fh_term + fc_term


def recompute_aircraft_totals(aircraft_id):
    """aircraft_utilization_totals: SUM over ACCEPTED reports across every
    lease of the airframe."""
    lease_ids = {
        l["id"] for l in STORE["leases"].values() if l["aircraft_id"] == aircraft_id
    }
    hours = Decimal("0")
    cycles = 0
    for r in STORE["utilization_reports"].values():
        if r["lease_id"] in lease_ids and r["status"] == "ACCEPTED":
            hours += D(r["flight_hours"])
            cycles += int(r["flight_cycles"])
    aircraft = STORE["aircraft"].get(aircraft_id)
    if aircraft is not None:
        aircraft["total_flight_hours"] = float(hours)
        aircraft["total_flight_cycles"] = cycles


def monthly_charge(lease, month, report):
    """monthly_lease_charge: per-tier round-half-up before summation."""
    hours_v = report["flight_hours"] if report is not None else 0
    cycles = int(report["flight_cycles"]) if report is not None else 0
    hours = D(hours_v)
    overage = max(Decimal("0"), hours - D(lease["monthly_hour_cap"]))
    tier1 = min(overage, D(TIER1_LIMIT_HOURS))
    tier2 = max(Decimal("0"), overage - D(TIER1_LIMIT_HOURS))
    overage_cents = round_half_up_cents(tier1 * TIER1_RATE_CENTS) + round_half_up_cents(
        tier2 * TIER2_RATE_CENTS
    )
    surcharge = (
        CYCLE_SURCHARGE_CENTS
        if cycles * CYCLE_RATIO_DEN > hours * CYCLE_RATIO_NUM
        else 0
    )
    total = lease["monthly_rent_cents"] + overage_cents + surcharge
    return {
        "month": month,
        "hours": hours_v,
        "cycles": cycles,
        "base_rent_cents": lease["monthly_rent_cents"],
        "overage_cents": overage_cents,
        "cycle_surcharge_cents": surcharge,
        "total_cents": total,
    }


def provisional_estimate(items):
    """return_compensation provisional variant: per-item round-half-up, then sum."""
    total = 0
    for it in items:
        if it["status"] == "NON_COMPLIANT":
            total += round_half_up_cents(
                D(it["rectification_cost_estimate_cents"]) * UPLIFT[it["severity"]]
            )
    return total


def records_completeness(aircraft_id):
    """records_completeness_score: count of required doc types with at least
    one VERIFIED document, over 4."""
    verified_types = {
        d["doc_type"]
        for d in STORE["aircraft_documents"].values()
        if d["aircraft_id"] == aircraft_id and d["status"] == "VERIFIED"
    }
    count = sum(1 for t in REQUIRED_DOC_TYPES if t in verified_types)
    return count, count / 4.0
