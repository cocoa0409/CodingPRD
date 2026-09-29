"""Ledger entries, the payment waterfall, balance/aging arithmetic and the
delinquency ladder (PRD 3.1)."""
import clock
import db
import money

ENTRY_TYPES = (
    "ASSESSMENT",
    "SPECIAL_ASSESSMENT_INSTALLMENT",
    "LATE_FEE",
    "INTEREST",
    "FINE",
    "COLLECTION_COST",
    "INSURANCE_DEDUCTIBLE_CHARGEBACK",
    "RESALE_FEE",
    "PAYMENT",
    "CREDIT_REFUND",
    "REVERSAL",
)

BUCKETS = (
    "INTEREST",
    "LATE_FEE",
    "COLLECTION_COST",
    "FINE",
    "ASSESSMENT",
    "SPECIAL_ASSESSMENT",
    "NONE",
)

BUCKET_OF_TYPE = {
    "ASSESSMENT": "ASSESSMENT",
    "SPECIAL_ASSESSMENT_INSTALLMENT": "SPECIAL_ASSESSMENT",
    "LATE_FEE": "LATE_FEE",
    "INTEREST": "INTEREST",
    "FINE": "FINE",
    "COLLECTION_COST": "COLLECTION_COST",
    "INSURANCE_DEDUCTIBLE_CHARGEBACK": "ASSESSMENT",
    "RESALE_FEE": "COLLECTION_COST",
    "PAYMENT": "NONE",
    "CREDIT_REFUND": "NONE",
    "REVERSAL": "NONE",
}

# Manual charge types a CommunityManager / BoardTreasurer may post directly.
MANUAL_CHARGE_TYPES = ("COLLECTION_COST", "INTEREST", "ASSESSMENT")

BUCKET_ORDER = ("INTEREST", "LATE_FEE", "COLLECTION_COST", "FINE", "ASSESSMENT",
                "SPECIAL_ASSESSMENT")

STAGES = ("CURRENT", "REMINDER", "LATE_NOTICE", "LIEN_FILED", "FORECLOSURE_REFERRAL")
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}
LIEN_STAGES = ("LIEN_FILED", "FORECLOSURE_REFERRAL")


def post_entry(unit, entry_type, amount_cents, effective_period, due_on=None,
               memo=None, billing_run_id=None, source_case_id=None,
               special_assessment_id=None, source_claim_id=None,
               reverses_entry_id=None, status="POSTED"):
    """Insert a LedgerEntry.  Ledger entries are deliberately UNVERSIONED: they
    carry only id and created_at, never updated_at nor version (PRD 2.4)."""
    row = db.base_fields(versioned=False)
    row.update({
        "unit_id": unit["id"],
        "billing_run_id": billing_run_id,
        "source_case_id": source_case_id,
        "special_assessment_id": special_assessment_id,
        "source_claim_id": source_claim_id,
        "reverses_entry_id": reverses_entry_id,
        "entry_type": entry_type,
        "bucket": BUCKET_OF_TYPE[entry_type],
        "amount_cents": int(amount_cents),
        "due_on": due_on,
        "posted_at": clock.now(),
        "effective_period": effective_period,
        "applied_allocations": [],
        "unapplied_cents": 0,
        "applied_cents": 0,
        "status": status,
        "memo": memo,
    })
    return db.insert("ledger_entries", row)


def entries_of(unit_id):
    return db.sorted_rows("ledger_entries", lambda e: e["unit_id"] == unit_id)


def open_charges(unit_id, bucket=None):
    """POSTED positive-amount rows with remaining capacity, in waterfall order."""
    rows = [
        e for e in db.store["ledger_entries"].values()
        if e["unit_id"] == unit_id
        and e["status"] == "POSTED"
        and e["amount_cents"] > 0
        and (e["amount_cents"] - e["applied_cents"]) > 0
        and (bucket is None or e["bucket"] == bucket)
    ]
    rows.sort(key=lambda e: (
        e["due_on"] or clock.DEFAULT_NOW, e["posted_at"], e["created_at"], e["_seq"]))
    return rows


# ------------------------------------------------------------------ recompute


def balance_of(unit_id):
    """Invariant L: signed sum of amount_cents over EVERY row, whatever the status."""
    return sum(e["amount_cents"] for e in db.store["ledger_entries"].values()
               if e["unit_id"] == unit_id)


def aging_of(unit_id):
    rows = [
        e for e in db.store["ledger_entries"].values()
        if e["unit_id"] == unit_id and e["status"] == "POSTED"
        and e["amount_cents"] > 0 and (e["amount_cents"] - e["applied_cents"]) > 0
    ]
    if not rows:
        return 0
    now = clock.now()
    ages = []
    for e in rows:
        if e["due_on"] is None:
            continue
        ages.append(clock.floor_days(now, e["due_on"]))
    if not ages:
        return 0
    return max(ages)


def credit_of(unit_id):
    return sum(e["unapplied_cents"] for e in db.store["ledger_entries"].values()
               if e["unit_id"] == unit_id and e["status"] == "POSTED"
               and e["entry_type"] == "PAYMENT")


def derive_stage(assoc, balance, age):
    """The delinquency ladder: walk from the top, take the FIRST matching rule."""
    if balance <= 0:
        return "CURRENT"
    if age >= 180 and balance >= 2 * assoc["lien_threshold_cents"]:
        return "FORECLOSURE_REFERRAL"
    if age >= 90 and balance >= assoc["lien_threshold_cents"]:
        return "LIEN_FILED"
    if age >= 30:
        return "LATE_NOTICE"
    if age > assoc["late_fee_grace_days"]:
        return "REMINDER"
    return "CURRENT"


def transfer_blocked_of(unit_id):
    now = clock.now()
    for c in db.store["resale_certificates"].values():
        if c["unit_id"] == unit_id and c["status"] == "ISSUED":
            if c["expires_at"] is not None and c["expires_at"] > now:
                return False
    return True


def recompute_unit(unit, bump=True, run=None):
    """Recompute every derived money/aging figure of a unit, re-derive its
    delinquency posture, run the ladder side effects, and (by default) advance
    Unit.version by exactly 1."""
    assoc = db.get("associations", unit["association_id"])
    unit["balance_due_cents"] = balance_of(unit["id"])
    unit["credit_balance_cents"] = credit_of(unit["id"])
    unit["oldest_unpaid_age_days"] = aging_of(unit["id"])
    unit["transfer_blocked"] = transfer_blocked_of(unit["id"])

    old_stage = unit["delinquency_stage"]
    new_stage = derive_stage(assoc, unit["balance_due_cents"],
                             unit["oldest_unpaid_age_days"])
    if new_stage != old_stage:
        unit["delinquency_stage"] = new_stage
        was_lien = old_stage in LIEN_STAGES
        is_lien = new_stage in LIEN_STAGES
        if is_lien and not was_lien:
            unit["lien_recorded_at"] = clock.now()
        elif was_lien and not is_lien:
            unit["lien_recorded_at"] = None
        old_eligible = unit["voting_eligible"]
        unit["voting_eligible"] = not is_lien
        if unit["voting_eligible"] != old_eligible:
            recompute_balloting_eligibility(unit["association_id"])
        if run is not None and STAGE_RANK[new_stage] > STAGE_RANK[old_stage]:
            run["escalated_unit_count"] += 1
    if bump:
        db.touch(unit)
    return unit


def recompute_balloting_eligibility(association_id):
    """Every SpecialAssessment of the association that is BALLOTING recomputes
    eligible_weight_bp and re-derives `counted` on its votes; each advances its
    own version by 1."""
    from services import assessment
    for sa in db.sorted_rows("special_assessments",
                             lambda s: s["association_id"] == association_id
                             and s["approval_status"] == "BALLOTING"):
        sa["eligible_weight_bp"] = assessment.eligible_weight(association_id)
        assessment.rederive_counted(sa)
        db.touch(sa)


# --------------------------------------------------------- payment waterfall


def apply_payment(unit, payment, amount, application_mode=None, directed_bucket=None,
                  restrict_bucket=None):
    """Run the statutory / owner-directed waterfall.  No rounding anywhere."""
    if restrict_bucket is not None:
        order = (restrict_bucket,)
    else:
        forced = unit["delinquency_stage"] in LIEN_STAGES
        if application_mode == "OWNER_DIRECTED" and directed_bucket and not forced:
            order = (directed_bucket,) + tuple(
                b for b in BUCKET_ORDER if b != directed_bucket)
        else:
            order = BUCKET_ORDER

    remaining = abs(int(amount))
    allocations = []
    for bucket in order:
        if remaining == 0:
            break
        for charge in open_charges(unit["id"], bucket):
            capacity = charge["amount_cents"] - charge["applied_cents"]
            if capacity <= 0:
                continue
            take = min(remaining, capacity)
            charge["applied_cents"] += take
            allocations.append({
                "bucket": bucket,
                "target_entry_id": charge["id"],
                "applied_cents": take,
            })
            remaining -= take
            if remaining == 0:
                break
    payment["applied_allocations"] = allocations
    payment["unapplied_cents"] = remaining
    return allocations


def reverse_entry(unit, original, memo=None):
    """Post the compensating REVERSAL row and close the original."""
    rev = post_entry(
        unit,
        "REVERSAL",
        -original["amount_cents"],
        original["effective_period"],
        due_on=None,
        memo=memo,
        reverses_entry_id=original["id"],
        status="POSTED",
    )
    original["status"] = "REVERSED"
    return rev
