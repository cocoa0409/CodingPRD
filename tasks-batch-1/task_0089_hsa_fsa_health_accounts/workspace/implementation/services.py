"""
Domain logic: serializers, calculations, balance recompute, cascades.

All monetary quantities are integer cents (PRD §2.6) — exact integer arithmetic,
no rounding, no float.
"""
from datetime import datetime, timezone, date

from db import db, now_iso, new_id

CATCHUP_AGE = 55


# ---------------------------------------------------------------------------
# Date / time helpers
# ---------------------------------------------------------------------------
def parse_date(s):
    """Parse an ISO 8601 date (YYYY-MM-DD), tolerating a full datetime prefix."""
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def clock_date():
    """The server's current wall-clock date (PRD §3.9), read from ClockState."""
    cur = db.clock["current_utc"]
    return parse_date(cur)


def years_between(birth_date_str, ref_date_str):
    """Whole number of years between birth_date and ref_date, floored."""
    b = parse_date(birth_date_str)
    r = parse_date(ref_date_str)
    if b is None or r is None:
        return 0
    years = r.year - b.year
    # subtract one if the anniversary has not yet occurred by ref date
    if (r.month, r.day) < (b.month, b.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# Mutation helpers (system fields per PRD §2.4)
# ---------------------------------------------------------------------------
def touch(entity):
    """Refresh updated_at and bump version (a mutation)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_participant(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "email": p["email"],
        "full_name": p["full_name"],
        "birth_date": p["birth_date"],
        "marital_status": p["marital_status"],
        "hdhp_covered": p["hdhp_covered"],
    }


def ser_plan_year(py):
    return {
        "id": py["id"],
        "created_at": py["created_at"],
        "updated_at": py["updated_at"],
        "version": py["version"],
        "label": py["label"],
        "coverage_start": py["coverage_start"],
        "coverage_end": py["coverage_end"],
        "run_out_end": py["run_out_end"],
        "fsa_relief_mode": py["fsa_relief_mode"],
        "grace_period_end": py["grace_period_end"],
        "carryover_cap_cents": py["carryover_cap_cents"],
        "hsa_individual_cap_cents": py["hsa_individual_cap_cents"],
        "hsa_family_cap_cents": py["hsa_family_cap_cents"],
        "hsa_catchup_cents": py["hsa_catchup_cents"],
        "health_fsa_cap_cents": py["health_fsa_cap_cents"],
        "dcfsa_cap_joint_cents": py["dcfsa_cap_joint_cents"],
        "dcfsa_cap_separate_cents": py["dcfsa_cap_separate_cents"],
        "lifecycle": py["lifecycle"],
    }


def ser_account(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "participant_id": a["participant_id"],
        "plan_year_id": a["plan_year_id"],
        "account_type": a["account_type"],
        "coverage_tier": a["coverage_tier"],
        "elected_amount_cents": a["elected_amount_cents"],
        "auto_adjudication_threshold_cents": a["auto_adjudication_threshold_cents"],
        "funding_status": a["funding_status"],
        "compliance_hold": a["compliance_hold"],
        "contributed_cents": a["contributed_cents"],
        "reimbursed_cents": a["reimbursed_cents"],
        "available_balance_cents": a["available_balance_cents"],
        "forfeited_cents": a["forfeited_cents"],
        "carried_in_cents": a["carried_in_cents"],
        "carryover_source_account_id": a["carryover_source_account_id"],
    }


def ser_contribution(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "account_id": c["account_id"],
        "amount_cents": c["amount_cents"],
        "source": c["source"],
        "posted_at": c["posted_at"],
        "status": c["status"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "account_id": c["account_id"],
        "service_date": c["service_date"],
        "expense_category": c["expense_category"],
        "claimed_amount_cents": c["claimed_amount_cents"],
        "substantiated": c["substantiated"],
        "reimbursable_amount_cents": c["reimbursable_amount_cents"],
        "status": c["status"],
        "denial_reason": c["denial_reason"],
        "adjudicated_by": c["adjudicated_by"],
        "reimbursed_by": c["reimbursed_by"],
    }


def ser_batch(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "participant_id": b["participant_id"],
        "claim_ids": list(b["claim_ids"]),
        "total_reimbursed_cents": b["total_reimbursed_cents"],
        "status": b["status"],
    }


def ser_ledger(e):
    # LedgerEntry is immutable: only id + created_at (PRD §2.4).
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "account_id": e["account_id"],
        "claim_id": e["claim_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "memo": e["memo"],
    }


def ser_clock(c):
    return {"current_utc": c["current_utc"]}


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def append_ledger(account_id, entry_type, amount_cents, memo, claim_id=None):
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "account_id": account_id,
        "claim_id": claim_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "memo": memo,
    }
    db.ledger_entries[e["id"]] = e
    return e


# ---------------------------------------------------------------------------
# Available-Balance calculation (scaffold §1.3 / PRD §3.3)
# ---------------------------------------------------------------------------
def recompute_balance(account):
    """
    Recompute contributed_cents, reimbursed_cents and available_balance_cents
    from POSTED contributions and REIMBURSEMENT/REIMBURSEMENT_REVERSAL ledger
    entries. Pure recompute — does NOT mutate version/updated_at.
    """
    acct_id = account["id"]
    contributed = sum(
        c["amount_cents"]
        for c in db.contributions.values()
        if c["account_id"] == acct_id and c["status"] == "POSTED"
    )
    reimb = sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["account_id"] == acct_id and e["entry_type"] == "REIMBURSEMENT"
    )
    reimb_rev = sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["account_id"] == acct_id and e["entry_type"] == "REIMBURSEMENT_REVERSAL"
    )
    reimbursed = reimb - reimb_rev

    account["contributed_cents"] = contributed
    account["reimbursed_cents"] = reimbursed
    if account["account_type"] == "HSA":
        account["available_balance_cents"] = contributed - reimbursed
    else:  # HEALTH_FSA / DCFSA
        account["available_balance_cents"] = (
            account["elected_amount_cents"] + account["carried_in_cents"] - reimbursed
        )


# ---------------------------------------------------------------------------
# Funding-status transition driven by balance (scaffold §1.2)
# ---------------------------------------------------------------------------
def apply_funding_transition(account):
    """
    After a balance recompute, evolve the funding_status dimension:
      ACTIVE  -> DEPLETED when available_balance_cents == 0
      DEPLETED -> ACTIVE   when available_balance_cents > 0
    PENDING and CLOSED are not auto-transitioned here.
    """
    bal = account["available_balance_cents"]
    if account["funding_status"] == "ACTIVE" and bal == 0:
        account["funding_status"] = "DEPLETED"
    elif account["funding_status"] == "DEPLETED" and bal > 0:
        account["funding_status"] = "ACTIVE"


# ---------------------------------------------------------------------------
# Reimbursable-Amount calculation (scaffold §1.3 / PRD §3.5)
# ---------------------------------------------------------------------------
def forward_looking_basis(account):
    """Projected funding basis at APPROVE time."""
    at = account["account_type"]
    if at == "HSA":
        return account["elected_amount_cents"] - account["reimbursed_cents"]
    elif at == "HEALTH_FSA":
        return (
            account["elected_amount_cents"]
            + account["carried_in_cents"]
            - account["reimbursed_cents"]
        )
    else:  # DCFSA pay-as-you-go: only contributed funds
        return account["contributed_cents"] - account["reimbursed_cents"]


def forward_looking_reimbursable(account, claimed_amount_cents):
    basis = forward_looking_basis(account)
    return min(claimed_amount_cents, max(0, basis))


# ---------------------------------------------------------------------------
# HSA-Contribution-Cap (scaffold §1.3 / PRD §3.3)
# ---------------------------------------------------------------------------
def hsa_allowed_cap(account, participant, plan_year):
    if account["coverage_tier"] == "FAMILY":
        base_cap = plan_year["hsa_family_cap_cents"]
    else:
        base_cap = plan_year["hsa_individual_cap_cents"]
    age_at_year_end = years_between(participant["birth_date"], plan_year["coverage_end"])
    catchup = plan_year["hsa_catchup_cents"] if age_at_year_end >= CATCHUP_AGE else 0
    return base_cap + catchup


# ---------------------------------------------------------------------------
# Service-window / filing-window helpers (PRD §3.4)
# ---------------------------------------------------------------------------
def effective_service_end(plan_year):
    """coverage_end, extended to grace_period_end under GRACE_PERIOD."""
    end = parse_date(plan_year["coverage_end"])
    if plan_year["fsa_relief_mode"] == "GRACE_PERIOD" and plan_year["grace_period_end"]:
        ge = parse_date(plan_year["grace_period_end"])
        if ge is not None:
            return ge
    return end


def effective_filing_deadline(plan_year):
    """run_out_end, or grace_period_end when GRACE_PERIOD and that is later."""
    deadline = parse_date(plan_year["run_out_end"])
    if plan_year["fsa_relief_mode"] == "GRACE_PERIOD" and plan_year["grace_period_end"]:
        ge = parse_date(plan_year["grace_period_end"])
        if ge is not None and ge > deadline:
            return ge
    return deadline


def service_date_in_window(plan_year, service_date_str):
    sd = parse_date(service_date_str)
    if sd is None:
        return False
    start = parse_date(plan_year["coverage_start"])
    end = effective_service_end(plan_year)
    return start <= sd <= end


def expense_qualified(account_type, expense_category):
    """
    DEPENDENT_CARE only on DCFSA; MEDICAL/DENTAL/VISION/PRESCRIPTION/OTC only on
    HSA/HEALTH_FSA (PRD §3.4).
    """
    medical = {"MEDICAL", "DENTAL", "VISION", "PRESCRIPTION", "OTC"}
    if account_type == "DCFSA":
        return expense_category == "DEPENDENT_CARE"
    else:  # HSA / HEALTH_FSA
        return expense_category in medical
