"""Business logic: calculations (SCAFFOLD table 3), cascades, and clock sweeps.

Constants:
  ATTESTATION_CYCLE_DAYS = 120, DUE_WARNING_DAYS = 30   (caqh_attestation_cycle)
  RETRO_DAYS = 90                                        (enrollment_effective_date)
  REVALIDATION_WINDOW_DAYS = 60                          (revalidation_schedule)
  RECOUPMENT_FEE_PCT = 0.02, round_half_up per claim     (recoupment_fee)
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import base_fields, store, touch
from util import fmt_ts, last_day_of_month, parse_date, parse_timestamp

ATTESTATION_CYCLE_DAYS = 120
DUE_WARNING_DAYS = 30
RETRO_DAYS = 90
REVALIDATION_WINDOW_DAYS = 60
RECOUPMENT_FEE_PCT = Decimal("0.02")

ACTIVE_RECORD_STATES = ("ACTIVE", "PENDING_REVALIDATION")
IN_FLIGHT_APP_STATES = ("DRAFT", "SUBMITTED", "PENDING_INFO")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def claims_of(provider_id, payer_id=None):
    return [
        c for c in store.claims.values()
        if c["provider_id"] == provider_id
        and (payer_id is None or c["payer_id"] == payer_id)
    ]


def claim_order(c):
    """service_date ASC, tie-break created_at ASC (then insertion seq)."""
    return (c["service_date"], c["created_at"], c["_seq"])


def records_of(provider_id, payer_id=None):
    return [
        r for r in store.records.values()
        if r["provider_id"] == provider_id
        and (payer_id is None or r["payer_id"] == payer_id)
    ]


def profile_of(provider_id):
    for p in store.caqh_profiles.values():
        if p["provider_id"] == provider_id:
            return p
    return None


def recoup_fee(amount_cents):
    """Per-claim recovery fee: round_half_up(amount_cents * 0.02) to whole cents.
    Pinned order: fee per claim first, sum later — never round the aggregate."""
    return int(
        (Decimal(amount_cents) * RECOUPMENT_FEE_PCT).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def provider_balance_cents(provider_id):
    """Outstanding recoupment = sum(amount_cents + recoupment_fee_cents) over the
    provider's claims currently in RECOUPED."""
    return sum(
        c["amount_cents"] + c["recoupment_fee_cents"]
        for c in store.claims.values()
        if c["provider_id"] == provider_id and c["status"] == "RECOUPED"
    )


# ---------------------------------------------------------------------------
# Calculation: enrollment_effective_date (application path)
# ---------------------------------------------------------------------------

def compute_effective_date(app, payer, approved_day):
    """APPROVAL_DATE: approval day (requested date ignored).
    RETRO_90: max(requested_effective_date, approval_day - 90 days)."""
    if payer["effective_date_policy"] == "APPROVAL_DATE":
        return approved_day.isoformat()
    floor = (approved_day - timedelta(days=RETRO_DAYS)).isoformat()
    return max(app["requested_effective_date"], floor)


# ---------------------------------------------------------------------------
# Calculation: revalidation_schedule
# ---------------------------------------------------------------------------

def compute_revalidation_schedule(rec, payer):
    """base = date(last_revalidation_completed_at) + interval days.
    Medicare payers snap the due date to the last calendar day of base's month.
    window_start = due_date - 60 days."""
    base = parse_date(rec["last_revalidation_completed_at"][:10]) + timedelta(
        days=payer["revalidation_interval_days"]
    )
    due = last_day_of_month(base) if payer["is_medicare"] else base
    rec["revalidation_due_date"] = due.isoformat()
    rec["revalidation_window_start"] = (
        due - timedelta(days=REVALIDATION_WINDOW_DAYS)
    ).isoformat()


# ---------------------------------------------------------------------------
# Overlap / coverage
# ---------------------------------------------------------------------------

def enrollment_overlap_exists(provider_id, payer_id, new_effective_date):
    """Half-open [effective_date, termination_date) semantics; touching allowed.
    Blocks when a record is ACTIVE/PENDING_REVALIDATION, or when the new
    effective date falls strictly inside a TERMINATED record's interval."""
    for r in records_of(provider_id, payer_id):
        if r["status"] in ACTIVE_RECORD_STATES:
            return True
        if r["status"] == "TERMINATED" and r["termination_date"] is not None:
            if r["effective_date"] <= new_effective_date < r["termination_date"]:
                return True
    return False


def covering_record(provider_id, payer_id, service_date):
    """claim_hold_evaluation coverage test (at most one match per invariant)."""
    for r in records_of(provider_id, payer_id):
        if (
            r["status"] in ACTIVE_RECORD_STATES
            and r["effective_date"] <= service_date
            and (r["termination_date"] is None or service_date < r["termination_date"])
        ):
            return r
    return None


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def release_held_claims(provider_id, payer_id, effective_date):
    """Record activation: HELD claims with service_date >= effective_date ->
    RELEASED, in service_date ASC / created_at ASC order. Earlier claims stay HELD."""
    held = sorted(
        (
            c
            for c in claims_of(provider_id, payer_id)
            if c["status"] == "HELD" and c["service_date"] >= effective_date
        ),
        key=claim_order,
    )
    for c in held:
        c["status"] = "RELEASED"
        touch(c)


def terminate_record(rec, termination_date):
    """Record-termination cascade (retro_recoupment):
      held_set    -> DENIED / ENROLLMENT_TERMINATED
      recoup_set  (RELEASED with service_date >= termination_date) -> RECOUPED
                   with per-claim fee round_half_up(amount * 0.02)
      gross_impacted_cents = principal over both sets (fees excluded)
      net_recouped_cents   = principal + fee over recouped claims only
    Both sets processed in service_date ASC / created_at ASC order."""
    rec["status"] = "TERMINATED"
    rec["termination_date"] = termination_date
    touch(rec)
    pair = claims_of(rec["provider_id"], rec["payer_id"])
    held = sorted((c for c in pair if c["status"] == "HELD"), key=claim_order)
    recoup = sorted(
        (
            c
            for c in pair
            if c["status"] == "RELEASED" and c["service_date"] >= termination_date
        ),
        key=claim_order,
    )
    gross = 0
    net = 0
    for c in held:
        c["status"] = "DENIED"
        c["denial_reason"] = "ENROLLMENT_TERMINATED"
        touch(c)
        gross += c["amount_cents"]
    for c in recoup:
        fee = recoup_fee(c["amount_cents"])
        c["status"] = "RECOUPED"
        c["recoupment_fee_cents"] = fee
        touch(c)
        gross += c["amount_cents"]
        net += c["amount_cents"] + fee
    rec["gross_impacted_cents"] += gross
    rec["net_recouped_cents"] += net


def deny_held_claims(provider_id, payer_id, denial_reason):
    """Deactivation cascade / provider-termination leftover denial."""
    held = sorted(
        (c for c in claims_of(provider_id, payer_id) if c["status"] == "HELD"),
        key=claim_order,
    )
    for c in held:
        c["status"] = "DENIED"
        c["denial_reason"] = denial_reason
        touch(c)


def create_enrollment_record(
    provider_id,
    payer_id,
    enrollment_scope,
    benefit_assignment,
    effective_date,
    payer,
    source_application_id=None,
    source_roster_line_id=None,
):
    rec = base_fields()
    rec.update(
        {
            "provider_id": provider_id,
            "payer_id": payer_id,
            "source_application_id": source_application_id,
            "source_roster_line_id": source_roster_line_id,
            "enrollment_scope": enrollment_scope,
            "benefit_assignment": benefit_assignment,
            "effective_date": effective_date,
            "termination_date": None,
            "last_revalidation_completed_at": fmt_ts(store.clock),
            "revalidation_due_date": None,
            "revalidation_window_start": None,
            "gross_impacted_cents": 0,
            "net_recouped_cents": 0,
            "status": "ACTIVE",
        }
    )
    compute_revalidation_schedule(rec, payer)
    store.records[rec["id"]] = rec
    # Claim-release cascade on activation.
    release_held_claims(provider_id, payer_id, effective_date)
    return rec


# ---------------------------------------------------------------------------
# Calculation: roster_line_rollup
# ---------------------------------------------------------------------------

def recompute_roster_rollup(roster_file, bump=True):
    """Recompute the five status counts; while the file is SUBMITTED derive its
    status: any PENDING -> SUBMITTED; zero pending and all CONFIRMED -> CONFIRMED;
    zero pending otherwise -> PARTIALLY_CONFIRMED."""
    lines = [
        l for l in store.roster_lines.values()
        if l["roster_file_id"] == roster_file["id"]
    ]
    roster_file["total_lines"] = len(lines)
    roster_file["pending_count"] = sum(1 for l in lines if l["status"] == "PENDING")
    roster_file["confirmed_count"] = sum(1 for l in lines if l["status"] == "CONFIRMED")
    roster_file["rejected_count"] = sum(1 for l in lines if l["status"] == "REJECTED")
    roster_file["discrepancy_count"] = sum(1 for l in lines if l["status"] == "DISCREPANCY")
    roster_file["superseded_count"] = sum(1 for l in lines if l["status"] == "SUPERSEDED")
    if roster_file["status"] == "SUBMITTED":
        if roster_file["pending_count"] > 0:
            roster_file["status"] = "SUBMITTED"
        elif (
            roster_file["confirmed_count"] == roster_file["total_lines"]
            and roster_file["total_lines"] >= 1
        ):
            roster_file["status"] = "CONFIRMED"
        else:
            roster_file["status"] = "PARTIALLY_CONFIRMED"
    if bump:
        touch(roster_file)


# ---------------------------------------------------------------------------
# Clock sweep (POST /api/_clock/set_current_utc)
# ---------------------------------------------------------------------------

def run_clock_sweep():
    """Fires on every logical-clock advance:
      - CAQH profiles: ATTESTED -> DUE at due_at - 30d; -> LAPSED strictly after
        due_at (at exactly due_at the profile is DUE, never LAPSED). Timestamps
        compared at second precision. Only ATTESTED/DUE profiles are touched.
      - Enrollment records: window start -> PENDING_REVALIDATION (from ACTIVE);
        strictly past due date -> DEACTIVATED from either state + HELD-claim
        denial cascade (ENROLLMENT_DEACTIVATED). RELEASED claims untouched.
      - Agreements: ACTIVE -> EXPIRED once the current date passes expiry_date.
    """
    now = store.clock
    today = now.date()
    now_sec = now.replace(microsecond=0)

    for prof in list(store.caqh_profiles.values()):
        if prof["status"] not in ("ATTESTED", "DUE") or not prof["due_at"]:
            continue
        due = parse_timestamp(prof["due_at"]).replace(microsecond=0)
        if now_sec > due:
            prof["status"] = "LAPSED"
            touch(prof)
        elif now_sec >= due - timedelta(days=DUE_WARNING_DAYS):
            if prof["status"] != "DUE":
                prof["status"] = "DUE"
                touch(prof)

    for rec in list(store.records.values()):
        if rec["status"] not in ACTIVE_RECORD_STATES:
            continue
        due = parse_date(rec["revalidation_due_date"])
        if today > due:
            rec["status"] = "DEACTIVATED"
            touch(rec)
            deny_held_claims(
                rec["provider_id"], rec["payer_id"], "ENROLLMENT_DEACTIVATED"
            )
        elif rec["status"] == "ACTIVE" and today >= parse_date(
            rec["revalidation_window_start"]
        ):
            rec["status"] = "PENDING_REVALIDATION"
            touch(rec)

    for ag in list(store.agreements.values()):
        if ag["status"] == "ACTIVE" and today > parse_date(ag["expiry_date"]):
            ag["status"] = "EXPIRED"
            touch(ag)
