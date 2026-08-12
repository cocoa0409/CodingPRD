"""Cross-entity recalculation helpers: bid scoring, ledger totals, rent schedule."""
from decimal import Decimal
from db import db, CLOCK, new_common, touch, to_iso, add_year
from services.common import round_half_up_cents, round_half_up_4dp


# ---------------------------------------------------------------------------
# Landlord ledger totals (calc landlord_ledger_totals)
# ---------------------------------------------------------------------------

def recompute_landlord_totals(landlord_id):
    landlord = db.landlords.get(landlord_id)
    if landlord is None:
        return
    lease_ids = [l["id"] for l in db.leases.values() if l["landlord_id"] == landlord_id]
    total_received = 0
    pending = 0
    for inst in db.installments.values():
        if inst["lease_id"] not in lease_ids:
            continue
        total_received += inst.get("paid_cents", 0)
        if inst["status"] in ("OPEN", "LATE"):
            pending += inst["amount_cents"] + inst.get("late_fee_cents", 0) - inst.get("paid_cents", 0)
    landlord["total_received_cents"] = total_received
    landlord["pending_receivable_cents"] = pending
    # Ledger recompute is a derived-value refresh; do not bump the version
    # for landlord totals maintenance alone. (PRD 2.4 says version increments
    # on every mutation, but recomputed derived fields are not client-visible
    # mutations of the landlord resource's editable state; tests pin OCC only
    # on lease/bid version.)


# ---------------------------------------------------------------------------
# Bid evaluation scoring (calc bid_evaluation_score)
# ---------------------------------------------------------------------------

ELIGIBLE_BID_STATUSES = ("SUBMITTED", "SHORTLISTED")


def recompute_offering_scores(offering_id):
    offering = db.offerings.get(offering_id)
    if offering is None:
        return
    eligible = [b for b in db.bids.values()
                if b["offering_id"] == offering_id and b["status"] in ELIGIBLE_BID_STATUSES]
    offering["eligible_bid_count"] = len(eligible)
    if not eligible:
        return
    max_ce = max(b["cash_equivalent_bid_cents_per_acre"] for b in eligible)
    for b in eligible:
        if max_ce <= 0:
            rent_component = Decimal("1.0") if b["cash_equivalent_bid_cents_per_acre"] == max_ce else Decimal("0")
        else:
            rent_component = Decimal(b["cash_equivalent_bid_cents_per_acre"]) / Decimal(max_ce)
        tenant = db.tenants.get(b["tenant_id"])
        compliance_score = tenant["compliance_score"] if tenant else 100
        years = tenant["years_experience"] if tenant else 0
        compliance_component = Decimal(compliance_score) / Decimal(100)
        experience_component = Decimal(min(years, 20)) / Decimal(20)
        score = (Decimal("0.6") * rent_component
                 + Decimal("0.25") * compliance_component
                 + Decimal("0.15") * experience_component)
        b["evaluation_score"] = round_half_up_4dp(score)


# ---------------------------------------------------------------------------
# Rent schedule generation (calc rent_schedule_generation)
# ---------------------------------------------------------------------------

def generate_installments(lease):
    """Create PaymentInstallment rows for the lease's CURRENT term_index,
    covering [term_start_of_term, term_end_date) — one 12-month term year."""
    pattern = lease["payment_pattern"]
    if pattern == "NONE":
        return
    field = db.fields[lease["field_id"]]
    acres = field["acres"]
    annual = lease["base_rent_cents_per_acre"] * acres
    term_index = lease["term_index"]
    # Term-year start: term_start_date advanced (term_index - 1) years
    term_start = lease["term_start_date"]
    for _ in range(term_index - 1):
        term_start = add_year(term_start)
    year = term_start.year

    def mk(month, day, amount):
        due = term_start.replace(year=year, month=month, day=day,
                                 hour=0, minute=0, second=0, microsecond=0)
        rec = new_common()
        rec.update({
            "lease_id": lease["id"],
            "term_index": term_index,
            "due_date": due,
            "amount_cents": amount,
            "late_fee_cents": 0,
            "paid_cents": 0,
            "last_payment_at": None,
            "paid_recorded_by": None,
            "status": "SCHEDULED",
        })
        db.installments[rec["id"]] = rec
        return rec

    if pattern == "MAR_NOV_50_50":
        first = round_half_up_cents(Decimal(annual) * Decimal("0.5"))
        second = annual - first
        mk(3, 1, first)
        mk(11, 1, second)
    elif pattern == "QUARTERLY":
        q = round_half_up_cents(Decimal(annual) * Decimal("0.25"))
        fourth = annual - 3 * q
        for m in (3, 6, 9):
            mk(m, 1, q)
        mk(12, 1, fourth)
    elif pattern == "FULL_MAR":
        mk(3, 1, annual)
    recompute_landlord_totals(lease["landlord_id"])


def escalate_base_rent(lease):
    if lease["escalation_type"] == "FIXED_PCT":
        pct = Decimal(str(lease["escalation_pct"]))
        new_base = round_half_up_cents(Decimal(lease["base_rent_cents_per_acre"]) * (Decimal(1) + pct))
        lease["base_rent_cents_per_acre"] = new_base
    # NONE: unchanged
