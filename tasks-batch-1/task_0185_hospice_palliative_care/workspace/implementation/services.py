"""Business logic: calculations, derived-field reconciliation, serialization.

Every rule traces to a PRD sentence (§1.3 / §3).
"""
from datetime import timedelta

import db

# --- Calculation constants (scaffold §1.3) ---------------------------------
ROUTINE_HIGH_DAYS = 60
ROUTINE_HIGH_CENTS = 21000      # $210.00/day, first 60 days
ROUTINE_BASE_CENTS = 16500      # $165.00/day, day 61+
RESPITE_CENTS = 47000           # $470.00/day inpatient respite
GIP_CENTS = 110000              # $1,100.00/day general inpatient
RESPITE_MAX_CONSECUTIVE = 5
CAP_WINDOW_DAYS = 365
PERIOD_1_2_LENGTH = 90
PERIOD_3_PLUS_LENGTH = 60


# --- 90/90/60 period sequencing (PRD §3.3, scaffold §1.3 period_sequencing) -
def length_days(sequence):
    """Nominal length = 90 when sequence in {1,2}, else 60."""
    return PERIOD_1_2_LENGTH if sequence in (1, 2) else PERIOD_3_PLUS_LENGTH


def start_offset_days(sequence):
    """Sum of nominal lengths of all earlier periods.
    seq1->0, seq2->90, seq3->180, seq4->240, seq5->300, ..."""
    off = 0
    for s in range(1, sequence):
        off += length_days(s)
    return off


def requires_face_to_face(sequence):
    """True for sequence >= 3 (PRD §3.3)."""
    return sequence >= 3


# --- Elapsed-day cursor ------------------------------------------------------
def elapsed_days(election, when):
    """Days from election_date to `when` (a tz-aware UTC datetime)."""
    delta = when - election["_election_date_dt"]
    return delta.days


# --- per-diem (PRD §3.6, scaffold §1.3 day_per_diem) ------------------------
def day_payment_cents(level, elapsed_day_index):
    if level == "ROUTINE":
        if elapsed_day_index < ROUTINE_HIGH_DAYS:
            return ROUTINE_HIGH_CENTS
        return ROUTINE_BASE_CENTS
    if level == "RESPITE":
        return RESPITE_CENTS
    if level == "GIP":
        return GIP_CENTS
    return 0


# --- benefit period resolution by service_date ------------------------------
def period_for_offset(election, offset_days):
    """Return the materialized BenefitPeriod whose nominal window
    [start_offset, start_offset+length) contains offset_days, or None."""
    best = None
    for bp in db.benefit_periods.values():
        if bp["election_id"] != election["id"]:
            continue
        so = bp["start_offset_days"]
        if so <= offset_days < so + bp["length_days"]:
            best = bp
    return best


def highest_materialized_sequence(election):
    seqs = [bp["sequence"] for bp in db.benefit_periods.values()
            if bp["election_id"] == election["id"]]
    return max(seqs) if seqs else 0


def period_by_sequence(election, sequence):
    for bp in db.benefit_periods.values():
        if bp["election_id"] == election["id"] and bp["sequence"] == sequence:
            return bp
    return None


def lowest_pending_cert_period(election):
    """The election's lowest BenefitPeriod with cert_status == PENDING_CERT."""
    pending = [bp for bp in db.benefit_periods.values()
               if bp["election_id"] == election["id"] and bp["cert_status"] == "PENDING_CERT"]
    if not pending:
        return None
    return min(pending, key=lambda bp: bp["sequence"])


# --- current_period_number (PRD §3.3, scaffold §1.3 elapsed_cursor) ---------
def current_period_number(election):
    highest = highest_materialized_sequence(election)
    if highest == 0:
        return 1
    cursor = elapsed_days(election, db.get_clock())
    seq = 1
    while seq < highest and cursor >= start_offset_days(seq + 1):
        seq += 1
    return seq


# --- days_used_in_period reconciliation (PRD §2.5, §1.3) --------------------
def latest_care_day(election):
    days = [cd for cd in db.care_days.values() if cd["election_id"] == election["id"]]
    if not days:
        return None
    # ordered by service_date asc, created_at (_seq) asc; latest = last
    days.sort(key=lambda cd: (cd["_service_date_dt"], cd["_seq"]))
    return days[-1]


def reconcile_days_used(election):
    """days_used_in_period = count of CareDays bound to the current benefit period.

    The current benefit period is the materialized period whose nominal window
    contains the latest care day (scaffold §1.3 days_used_reconciliation). When
    there is no care day yet, falls back to the current_period_number window.
    """
    latest = latest_care_day(election)
    if latest is not None:
        bp = db.benefit_periods.get(latest["benefit_period_id"])
    else:
        bp = period_by_sequence(election, current_period_number(election))
    if bp is None:
        return 0
    count = sum(1 for cd in db.care_days.values()
                if cd["benefit_period_id"] == bp["id"])
    return count


def refresh_election_derived(election, bump_version=False):
    """Recompute current_period_number and days_used_in_period (PRD §2.5).

    Per §2.5 the server recomputes these derived values 'Whenever an election is
    mutated or read back through its detail endpoint.' The version-incrementing
    reconciliation is scoped (§2.5) to 'every care-day posting and again on revoke
    and discharge'; on those calls pass bump_version=True. On plain reads — and on
    the certify / care-plan writes, which §3.4/§3.5 say increment the version by
    exactly one through their own db.touch — we refresh the displayed values
    without an extra bump, so OCC's expected_election_version stays coherent.
    """
    new_cpn = current_period_number(election)
    new_dui = reconcile_days_used(election)
    changed = (new_cpn != election["current_period_number"]
               or new_dui != election["days_used_in_period"])
    election["current_period_number"] = new_cpn
    election["days_used_in_period"] = new_dui
    if changed and bump_version:
        db.touch(election)


# --- respite run length (PRD §3.7, scaffold §1.3 respite_run_length) --------
def respite_run_length(election, service_date_dt, exclude_id=None):
    """Count of consecutive RESPITE days ending on service_date_dt, counting it
    as 1 and walking backward one calendar day so long as the immediately
    preceding day also has a RESPITE care day for the election."""
    run = 1
    cursor = service_date_dt - timedelta(days=1)
    while True:
        found = False
        for cd in db.care_days.values():
            if cd["id"] == exclude_id:
                continue
            if cd["election_id"] != election["id"]:
                continue
            if cd["level_of_care"] != "RESPITE":
                continue
            if cd["_service_date_dt"] == cursor:
                found = True
                break
        if not found:
            break
        run += 1
        cursor -= timedelta(days=1)
    return run


# --- provisional cap liability (PRD §3.11, scaffold §1.3) -------------------
def _in_window(provider, service_date_dt):
    start = provider["_cap_year_start_dt"]
    end = start + timedelta(days=CAP_WINDOW_DAYS)
    return start <= service_date_dt < end


def provider_window_caredays(provider):
    """All CareDays of all Elections under the provider whose service_date is
    inside the cap window [cap_year_start, +365d)."""
    election_ids = {e["id"] for e in db.elections.values()
                    if e["provider_id"] == provider["id"]}
    result = []
    for cd in db.care_days.values():
        if cd["election_id"] in election_ids and _in_window(provider, cd["_service_date_dt"]):
            result.append(cd)
    return result


def compute_provisional_cap(provider):
    """Provisional variant — raw year-to-date sum, no per-beneficiary min."""
    caredays = provider_window_caredays(provider)
    total_paid = sum(cd["payment_cents"] for cd in caredays)
    beneficiary_ids = {cd["election_id"] for cd in caredays}
    counted = len(beneficiary_ids)
    allowance = provider["per_beneficiary_cap_cents"] * counted
    liability = max(0, total_paid - allowance)
    return total_paid, counted, liability


def recompute_provider_ledger(provider):
    """Recompute and store provisional ledger fields (called on each posting and
    on cap-summary read). Skips when the cap year is already settled (frozen)."""
    if provider.get("cap_settled"):
        return
    total_paid, counted, liability = compute_provisional_cap(provider)
    provider["total_paid_cents"] = total_paid
    provider["counted_beneficiaries"] = counted
    provider["cap_liability_cents"] = liability


def compute_final_cap(provider):
    """Final settlement variant (PRD §3.11): allowance and demand remain on the
    aggregate raw total, but the per-beneficiary streamlined min is part of the
    domain twist. The PRD prose: 'the demand recorded as the frozen
    cap_liability_cents is the in-window total less the allowance'. We follow the
    scaffold final_cap_settlement note: raw_total = sum of all window payments,
    allowance = per_beneficiary_cap_cents * counted_beneficiaries, and the frozen
    total_paid_cents is the per-beneficiary-capped sum (the streamlined cap)."""
    caredays = provider_window_caredays(provider)
    beneficiary_ids = {cd["election_id"] for cd in caredays}
    counted = len(beneficiary_ids)

    # Per-beneficiary streamlined cap applied before summing -> frozen total.
    capped_total = 0
    raw_total = 0
    for eid in beneficiary_ids:
        ben_paid = sum(cd["payment_cents"] for cd in caredays if cd["election_id"] == eid)
        raw_total += ben_paid
        capped_total += min(ben_paid, provider["per_beneficiary_cap_cents"])

    allowance = provider["per_beneficiary_cap_cents"] * counted
    liability = max(0, raw_total - allowance)
    return capped_total, counted, liability


# ===========================================================================
# Serialization — emit declared fields in a stable shape
# ===========================================================================
def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def serialize_provider(p):
    out = _common(p)
    out.update({
        "name": p["name"],
        "cap_year_start": p["cap_year_start"],
        "per_beneficiary_cap_cents": p["per_beneficiary_cap_cents"],
        "cap_liability_cents": p["cap_liability_cents"],
        "total_paid_cents": p["total_paid_cents"],
        "counted_beneficiaries": p["counted_beneficiaries"],
        "cap_settled": p["cap_settled"],
    })
    return out


def serialize_election(e):
    out = _common(e)
    out.update({
        "provider_id": e["provider_id"],
        "patient_name": e["patient_name"],
        "election_date": e["election_date"],
        "attending_physician_id": e["attending_physician_id"],
        "status": e["status"],
        "current_period_number": e["current_period_number"],
        "days_used_in_period": e["days_used_in_period"],
        "revocation_date": e["revocation_date"],
        "bereavement_required": e["bereavement_required"],
    })
    return out


def serialize_benefit_period(bp):
    out = _common(bp)
    out.update({
        "election_id": bp["election_id"],
        "sequence": bp["sequence"],
        "length_days": bp["length_days"],
        "start_offset_days": bp["start_offset_days"],
        "requires_face_to_face": bp["requires_face_to_face"],
        "certification_id": bp["certification_id"],
        "cert_status": bp["cert_status"],
    })
    return out


def serialize_certification(c):
    out = _common(c)
    out.update({
        "election_id": c["election_id"],
        "period_sequence": c["period_sequence"],
        "certifying_physician_id": c["certifying_physician_id"],
        "face_to_face_physician_id": c["face_to_face_physician_id"],
        "face_to_face_date": c["face_to_face_date"],
        "narrative_present": c["narrative_present"],
        "expected_election_version": c["expected_election_version"],
        "status": c["status"],
        "rejection_reason": c["rejection_reason"],
    })
    return out


def serialize_care_plan(cp):
    out = _common(cp)
    out.update({
        "election_id": cp["election_id"],
        "supersedes_plan_id": cp["supersedes_plan_id"],
        "revision_number": cp["revision_number"],
        "idg_members": cp["idg_members"],
        "review_due_offset_days": cp["review_due_offset_days"],
        "status": cp["status"],
    })
    return out


def serialize_care_day(cd):
    out = _common(cd)
    out.update({
        "election_id": cd["election_id"],
        "benefit_period_id": cd["benefit_period_id"],
        "service_date": cd["service_date"],
        "level_of_care": cd["level_of_care"],
        "high_intensity": cd["high_intensity"],
        "payment_cents": cd["payment_cents"],
        "respite_run_length": cd["respite_run_length"],
    })
    return out


def serialize_coverage_item(ci):
    out = _common(ci)
    out.update({
        "election_id": ci["election_id"],
        "care_plan_id": ci["care_plan_id"],
        "item_type": ci["item_type"],
        "related_to_terminal_dx": ci["related_to_terminal_dx"],
        "coverage_status": ci["coverage_status"],
    })
    return out


def serialize_physician(ph):
    out = _common(ph)
    out.update({
        "full_name": ph["full_name"],
        "is_medical_director": ph["is_medical_director"],
    })
    return out


def serialize_bereavement_case(bc):
    out = _common(bc)
    out.update({
        "election_id": bc["election_id"],
        "enrolled_date": bc["enrolled_date"],
        "service_window_days": bc["service_window_days"],
        "status": bc["status"],
    })
    return out
