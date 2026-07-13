"""Business logic: denormalization, ranking, rent calculations, and the atomic
state cascades (offer accept/refuse, certification finalize, interim, eviction)."""
from decimal import Decimal, ROUND_HALF_UP

import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PREFERENCE_POINTS = {
    "VETERAN": 50,
    "ELDERLY": 30,
    "DISABLED": 30,
    "INVOLUNTARY_DISPLACEMENT": 40,
    "LOCAL_RESIDENT": 20,
    "WORKING_FAMILY": 10,
}
DEPENDENT_DEDUCTION_ANNUAL_CENTS = 48000
ELDERLY_DISABLED_DEDUCTION_ANNUAL_CENTS = 40000
MEDICAL_THRESHOLD_RATE = Decimal("0.03")
TTP_ADJ_RATE = Decimal("0.30")
TTP_GROSS_RATE = Decimal("0.10")
MINIMUM_RENT_CENTS = 5000
REFUSAL_LIMIT = 3
PURGE_STALE_DAYS = 90
MAKE_READY_DAYS = 14


def _rhu(value):
    """Round a Decimal half-up to whole cents (integer)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Household lookups & applicant denormalization
# ---------------------------------------------------------------------------
def household_members(applicant_id):
    return [m for m in db.members.values() if m["applicant_id"] == applicant_id]


def recompute_applicant_denorm(applicant):
    mem = household_members(applicant["id"])
    db.touch(
        applicant,
        household_size=len(mem),
        annual_gross_income_cents=sum(m["annual_income_cents"] for m in mem),
    )


# ---------------------------------------------------------------------------
# Preference points -> waitlist entry total_points
# ---------------------------------------------------------------------------
def applicant_total_points(applicant_id):
    return sum(
        PREFERENCE_POINTS[c["preference_type"]]
        for c in db.preference_claims.values()
        if c["applicant_id"] == applicant_id and c["status"] == "VERIFIED"
    )


def recompute_total_points(applicant_id):
    total = applicant_total_points(applicant_id)
    for e in db.waitlist_entries.values():
        if e["applicant_id"] == applicant_id:
            db.touch(e, total_points=total)


# ---------------------------------------------------------------------------
# Waitlist effective_rank
# ---------------------------------------------------------------------------
def recompute_ranks(waitlist):
    wid = waitlist["id"]
    entries = [e for e in db.waitlist_entries.values() if e["waitlist_id"] == wid]
    if waitlist["lottery_drawn"]:
        pool = [e for e in entries if e["status"] == "ACTIVE"]
        pool.sort(key=lambda e: (-e["total_points"], e["lottery_number"], e["_seq"]))
    else:
        pool = [e for e in entries if e["status"] == "PENDING"]
        pool.sort(key=lambda e: (_application_date(e), e["_seq"]))
    ranked = {e["id"]: i + 1 for i, e in enumerate(pool)}
    for e in entries:
        db.touch(e, effective_rank=ranked.get(e["id"]))


def _application_date(entry):
    applicant = db.applicants[entry["applicant_id"]]
    return applicant["application_date"]


# ---------------------------------------------------------------------------
# Rent calculations
# ---------------------------------------------------------------------------
def compute_gross(applicant_id, cert_type):
    mem = household_members(applicant_id)
    if cert_type == "INTERIM":  # ACTUAL variant: recurring only
        return sum(m["annual_income_cents"] for m in mem)
    # ANTICIPATED variant: recurring + non-recurring
    return sum(m["annual_income_cents"] + m["nonrecurring_income_cents"] for m in mem)


def compute_adjusted(applicant_id, gross, childcare_cents, medical_cents):
    mem = household_members(applicant_id)
    dependents = sum(1 for m in mem if m["is_dependent"])
    dependent_deduction = dependents * DEPENDENT_DEDUCTION_ANNUAL_CENTS
    ed_household = any(m["is_elderly"] or m["is_disabled"] for m in mem)
    ed_deduction = ELDERLY_DISABLED_DEDUCTION_ANNUAL_CENTS if ed_household else 0
    childcare_deduction = childcare_cents
    if ed_household:
        threshold = _rhu(MEDICAL_THRESHOLD_RATE * gross)
        medical_deduction = max(0, medical_cents - threshold)
    else:
        medical_deduction = 0
    total = dependent_deduction + ed_deduction + childcare_deduction + medical_deduction
    return max(0, gross - total)


def compute_ttp(gross, adjusted):
    comp_adjusted = _rhu(TTP_ADJ_RATE * Decimal(adjusted) / Decimal(12))
    comp_gross = _rhu(TTP_GROSS_RATE * Decimal(gross) / Decimal(12))
    return max(comp_adjusted, comp_gross, MINIMUM_RENT_CENTS)


def current_effective_cert(tenancy_id):
    effs = [
        c
        for c in db.certifications.values()
        if c["tenancy_id"] == tenancy_id and c["status"] == "EFFECTIVE"
    ]
    if not effs:
        return None
    effs.sort(key=lambda c: (c["effective_date"], c["created_at"]), reverse=True)
    return effs[0]


def recompute_tenancy_rent(tenancy):
    unit = db.units[tenancy["unit_id"]]
    ua = unit["utility_allowance_cents"]
    eff = current_effective_cert(tenancy["id"])
    ttp = eff["ttp_cents"] if eff else 0
    db.touch(
        tenancy,
        monthly_tenant_rent_cents=max(0, ttp - ua),
        utility_reimbursement_cents=max(0, ua - ttp),
    )


def finalize_certification(cert):
    """Run rent calcs, snapshot, transition DRAFT->EFFECTIVE, supersede prior,
    recompute tenancy rent, bump tenancy version."""
    tenancy = db.tenancies[cert["tenancy_id"]]
    applicant_id = tenancy["applicant_id"]
    gross = compute_gross(applicant_id, cert["cert_type"])
    adjusted = compute_adjusted(
        applicant_id,
        gross,
        cert["childcare_expenses_annual_cents"],
        cert["medical_expenses_annual_cents"],
    )
    ttp = compute_ttp(gross, adjusted)
    # Supersede prior effective cert first, then promote this one.
    prior = current_effective_cert(tenancy["id"])
    if prior and prior["id"] != cert["id"]:
        db.touch(prior, status="SUPERSEDED")
    db.touch(
        cert,
        annual_gross_income_cents=gross,
        annual_adjusted_income_cents=adjusted,
        ttp_cents=ttp,
        status="EFFECTIVE",
    )
    recompute_tenancy_rent(tenancy)


# ---------------------------------------------------------------------------
# Applicant / waitlist housing & withdrawal cascades
# ---------------------------------------------------------------------------
def _touch_waitlist_for(entry_id_or_entry):
    entry = entry_id_or_entry
    wl = db.waitlists.get(entry["waitlist_id"])
    if wl:
        recompute_ranks(wl)


def house_applicant(applicant, housed_entry):
    """Applicant becomes HOUSED; sibling in-play entries are WITHDRAWN."""
    db.touch(applicant, status="HOUSED")
    affected_waitlists = set()
    for e in db.waitlist_entries.values():
        if e["applicant_id"] != applicant["id"]:
            continue
        if e["id"] == housed_entry["id"]:
            continue
        if e["status"] in ("PENDING", "ACTIVE", "OFFERED"):
            db.touch(e, status="WITHDRAWN")
            affected_waitlists.add(e["waitlist_id"])
    for wid in affected_waitlists:
        wl = db.waitlists.get(wid)
        if wl:
            recompute_ranks(wl)


def maybe_withdraw_applicant(applicant_id):
    """Applicant WAITLISTED -> WITHDRAWN when no entry remains in play/housed."""
    applicant = db.applicants.get(applicant_id)
    if not applicant or applicant["status"] != "WAITLISTED":
        return
    live = any(
        e["applicant_id"] == applicant_id
        and e["status"] in ("PENDING", "ACTIVE", "OFFERED", "HOUSED")
        for e in db.waitlist_entries.values()
    )
    if not live:
        db.touch(applicant, status="WITHDRAWN")


# ---------------------------------------------------------------------------
# Offer accept / refuse
# ---------------------------------------------------------------------------
def accept_offer(offer):
    entry = db.waitlist_entries[offer["waitlist_entry_id"]]
    unit = db.units[offer["unit_id"]]
    applicant = db.applicants[entry["applicant_id"]]
    now = db.now()

    db.touch(offer, status="ACCEPTED")
    tenancy = db.create(
        db.tenancies,
        applicant_id=applicant["id"],
        unit_id=unit["id"],
        status="ACTIVE",
        lease_start_date=now,
        lease_end_date=None,
        monthly_tenant_rent_cents=0,
        utility_reimbursement_cents=0,
    )
    db.create(
        db.certifications,
        tenancy_id=tenancy["id"],
        source_interim_change_id=None,
        cert_type="INITIAL",
        status="DRAFT",
        hud_status="NOT_SUBMITTED",
        effective_date=tenancy["lease_start_date"],
        childcare_expenses_annual_cents=0,
        medical_expenses_annual_cents=0,
        annual_gross_income_cents=0,
        annual_adjusted_income_cents=0,
        ttp_cents=0,
    )
    db.touch(unit, status="OCCUPIED")
    db.touch(entry, status="HOUSED")
    house_applicant(applicant, entry)
    # ranks of the accepting waitlist (entry left the ACTIVE/PENDING pool)
    wl = db.waitlists.get(entry["waitlist_id"])
    if wl:
        recompute_ranks(wl)
    return tenancy


def refuse_offer(offer):
    entry = db.waitlist_entries[offer["waitlist_entry_id"]]
    unit = db.units[offer["unit_id"]]
    now = db.now()

    db.touch(offer, status="REFUSED")
    db.touch(unit, status="AVAILABLE")
    new_count = entry["refusal_count"] + 1
    if new_count >= REFUSAL_LIMIT:
        db.touch(entry, refusal_count=new_count, status="PURGED")
    else:
        db.touch(entry, refusal_count=new_count, status="ACTIVE", last_contact_at=now)
    wl = db.waitlists.get(entry["waitlist_id"])
    if wl:
        recompute_ranks(wl)
    if entry["status"] == "PURGED":
        maybe_withdraw_applicant(entry["applicant_id"])


# ---------------------------------------------------------------------------
# Eviction cascade
# ---------------------------------------------------------------------------
def terminate_tenancy(tenancy):
    now = db.now()
    db.touch(tenancy, status="TERMINATED", lease_end_date=now)
    unit = db.units.get(tenancy["unit_id"])
    if unit and unit["status"] == "OCCUPIED":
        db.touch(unit, status="AVAILABLE", last_lease_end_date=tenancy["lease_end_date"])
