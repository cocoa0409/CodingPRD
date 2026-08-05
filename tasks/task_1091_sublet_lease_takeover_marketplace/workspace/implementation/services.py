"""Business logic: calculations (PRD §2.7, §3.3, §3.4), settlement financials,
agreement execution, and the withdraw / void / dispute cascades (PRD §3.2/§3.5/§3.8)."""

from datetime import date, timedelta
from decimal import Decimal

from core import (
    STORE, touch, now_iso,
    round_half_up_int, round_half_up_rate, round4,
    days_in_month, days_remaining_inclusive, months_between,
)

# Constants (SCAFFOLD §1.3)
DEPOSIT_CAP_MULTIPLE = 2
SERVICE_RATE = "0.10"      # on prorated first-period rent
PROCESSING_RATE = "0.03"   # on deposit
MAX_RENT_INCOME_RATIO = Decimal("0.35")
INCOME_MULTIPLE = Decimal("40")
HANDOFF_BUFFER_MINUTES = 120

NON_TERMINAL_APP = {"SUBMITTED", "SCREENING", "INFO_REQUESTED", "SCREENED"}


def _parse_ymd(s):
    return date(*[int(x) for x in s.split("-")])


# ---------------------------------------------------------------------------
# Derived counters
# ---------------------------------------------------------------------------
def applicant_active_count(applicant_id):
    return sum(
        1 for a in STORE["applications"].values()
        if a["applicant_id"] == applicant_id and a["status"] in NON_TERMINAL_APP
    )


def lease_occupancy_count(lease_id):
    return sum(
        1 for ag in STORE["agreements"].values()
        if ag["lease_id"] == lease_id and ag["status"] in ("EXECUTED", "ACTIVE")
    )


# ---------------------------------------------------------------------------
# Proration (PRD §3.4 / §3.6, SCAFFOLD prorated_first_period_rent)
# ---------------------------------------------------------------------------
def prorate(base_monthly_rent_cents, d):
    dim = days_in_month(d)
    rem = days_remaining_inclusive(d)
    return round_half_up_int(base_monthly_rent_cents * rem, dim)


# ---------------------------------------------------------------------------
# Income qualification (PRD §3.3)
# ---------------------------------------------------------------------------
def compute_qualification(annual_income_cents, eff_rent_cents, policy):
    if annual_income_cents <= 0:
        affordability = Decimal("9999.9999")
        multiple = Decimal("0")
    else:
        affordability = (Decimal(12) * Decimal(eff_rent_cents) / Decimal(annual_income_cents))
        multiple = (Decimal(annual_income_cents) / Decimal(eff_rent_cents))
    if policy == "STANDARD":
        result = "PASS" if affordability <= MAX_RENT_INCOME_RATIO else "FAIL"
    else:  # STRICT
        result = "PASS" if multiple >= INCOME_MULTIPLE else "FAIL"
    return round4(affordability), round4(multiple), result


# ---------------------------------------------------------------------------
# Settlement financials (PRD §3.4)
# ---------------------------------------------------------------------------
def compute_settlement_financials(settlement, agreement, listing, lease):
    agreement_type = agreement["agreement_type"]
    if agreement_type == "SUBLET":
        base = listing["asking_rent_cents"]
    else:
        base = lease["monthly_rent_cents"]

    deposit = min(lease["security_deposit_cents"], DEPOSIT_CAP_MULTIPLE * base)
    last_month = base if agreement_type == "TAKEOVER" else 0

    occ_start = _parse_ymd(agreement["occupancy_start_date"])
    prorated = prorate(base, occ_start)

    service_component = round_half_up_rate(SERVICE_RATE, prorated)
    processing_component = round_half_up_rate(PROCESSING_RATE, deposit)
    platform_fee = service_component + processing_component

    total_move_in = prorated + deposit + last_month + platform_fee

    settlement["base_monthly_rent_cents"] = base
    settlement["deposit_amount_cents"] = deposit
    settlement["last_month_rent_cents"] = last_month
    settlement["prorated_first_rent_cents"] = prorated
    settlement["final_prorated_first_rent_cents"] = 0
    settlement["platform_fee_cents"] = platform_fee
    settlement["total_move_in_cents"] = total_move_in


# ---------------------------------------------------------------------------
# Agreement execution (final signature landed) (PRD §3.5)
# ---------------------------------------------------------------------------
def execute_agreement(agreement):
    agreement["status"] = "EXECUTED"
    listing = STORE["listings"].get(agreement["listing_id"])
    if listing is not None and listing["status"] == "OPEN":
        listing["status"] = "MATCHED"
        touch(listing)
    lease = STORE["leases"].get(agreement["lease_id"])
    if lease is not None:
        lease["active_occupancy_count"] = lease_occupancy_count(lease["id"])
        touch(lease)


# ---------------------------------------------------------------------------
# Void an agreement with its cascade (PRD §3.5 / §2.8)
# ---------------------------------------------------------------------------
def void_agreement(agreement):
    prior_status = agreement["status"]
    agreement["status"] = "VOID"
    touch(agreement)
    # Settlement: if FUNDED -> REFUNDED (deposit leaves escrow)
    for s in STORE["settlements"].values():
        if s["agreement_id"] == agreement["id"]:
            if s["status"] == "FUNDED":
                s["status"] = "REFUNDED"
                s["deposit_held_cents"] = 0
                touch(s)
    # Occupancy release if it had been EXECUTED
    if prior_status == "EXECUTED":
        lease = STORE["leases"].get(agreement["lease_id"])
        if lease is not None:
            lease["active_occupancy_count"] = lease_occupancy_count(lease["id"])
            touch(lease)
    # Cancel any SCHEDULED handoff appointment
    for ap in STORE["appointments"].values():
        if ap["agreement_id"] == agreement["id"] and ap["status"] == "SCHEDULED":
            ap["status"] = "CANCELLED"
            touch(ap)


# ---------------------------------------------------------------------------
# Listing withdrawal cascade (PRD §3.2)
# ---------------------------------------------------------------------------
def withdraw_listing_cascade(listing):
    # depth1: applications on this listing in active screening/match states -> DECLINED
    cascade_app_states = {"SUBMITTED", "SCREENING", "INFO_REQUESTED", "SCREENED", "MATCHED"}
    for app in STORE["applications"].values():
        if app["listing_id"] != listing["id"]:
            continue
        if app["status"] not in cascade_app_states:
            continue
        app["status"] = "DECLINED"
        touch(app)
        applicant = STORE["applicants"].get(app["applicant_id"])
        if applicant is not None:
            touch(applicant)
        # depth2: each such application's non-terminal agreement -> VOID (cascade)
        for ag in STORE["agreements"].values():
            if ag["application_id"] == app["id"] and ag["status"] in ("DRAFT", "PENDING_SIGNATURES", "EXECUTED"):
                void_agreement(ag)


# ---------------------------------------------------------------------------
# Dispute resolution cascades (PRD §3.8)
# ---------------------------------------------------------------------------
def terminate_agreement(agreement):
    """RESOLVED_APPLICANT: agreement -> TERMINATED; settlement refunded; occupancy--; listing CLOSED."""
    agreement["status"] = "TERMINATED"
    touch(agreement)
    for s in STORE["settlements"].values():
        if s["agreement_id"] == agreement["id"] and s["status"] in ("FUNDED", "HANDED_OFF"):
            s["status"] = "REFUNDED"
            s["deposit_held_cents"] = 0
            touch(s)
    lease = STORE["leases"].get(agreement["lease_id"])
    if lease is not None:
        lease["active_occupancy_count"] = lease_occupancy_count(lease["id"])
        touch(lease)
    listing = STORE["listings"].get(agreement["listing_id"])
    if listing is not None and listing["status"] in ("OPEN", "MATCHED"):
        listing["status"] = "CLOSED"
        touch(listing)
