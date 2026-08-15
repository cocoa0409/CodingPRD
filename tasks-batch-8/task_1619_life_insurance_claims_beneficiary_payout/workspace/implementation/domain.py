"""Business logic: calculations, state-machine cascades, and the clock sweep."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from helpers import (
    add_years,
    complete_months_between,
    fmt_clock,
    fmt_dt3,
    new_record,
    round_half_up_cents,
    touch,
)
from store import db

TERMINAL_CLAIM_STATES = {"PAID", "DENIED", "RESCINDED", "INTERPLEADED", "ESCHEATED"}

REQUIRED_DOC_BASE = {"CERTIFIED_DEATH_CERTIFICATE"}
REQUIRED_DOC_CONTESTABLE_EXTRA = {"ATTENDING_PHYSICIAN_STATEMENT"}

DUE_DILIGENCE_LEAD_DAYS = 120
ELECTION_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def bcs_of_claim(claim_id):
    return [b for b in db.beneficiary_claims.values() if b["claim_id"] == claim_id]


def docs_of_claim(claim_id):
    return [d for d in db.documents.values() if d["claim_id"] == claim_id]


def elections_of_claim(claim_id):
    bc_ids = {b["id"] for b in bcs_of_claim(claim_id)}
    return [e for e in db.elections.values() if e["beneficiary_claim_id"] in bc_ids]


def designation_of(bc):
    if bc.get("designation_id"):
        return db.designations.get(bc["designation_id"])
    return None


def claim_of_bc(bc):
    return db.claims.get(bc["claim_id"])


def statute_for_claim(claim):
    return db.statutes.get(claim["state_code"])


def has_non_terminal_claim(policy_id):
    return any(
        c["policy_id"] == policy_id and c["status"] not in TERMINAL_CLAIM_STATES
        for c in db.claims.values()
    )


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD Table 3 / PRD §3)
# ---------------------------------------------------------------------------

def contestability_flag(policy, date_of_death):
    """Strict: death exactly on the boundary date is NOT contestable."""
    boundary = _add_months_date(policy["issue_date"], policy["contestability_months"])
    return date_of_death < boundary


def _add_months_date(d, months):
    from helpers import add_months

    return add_months(d, months)


def statutory_interest(claim, as_of_date):
    """Statutory delay interest: face * rate_bp/10000 * accrual_days/365, half-up.

    accrual_days = max(0, days_elapsed - grace_days); at days_elapsed == grace_days
    accrual is exactly zero. PROOF_OF_LOSS_COMPLETE basis with incomplete proof
    means accrual cannot start (interest 0).
    """
    statute = statute_for_claim(claim)
    if statute is None:
        return 0
    if statute["interest_basis"] == "DATE_OF_DEATH":
        basis = claim["date_of_death"]
    else:  # PROOF_OF_LOSS_COMPLETE
        basis = claim.get("proof_complete_date")
        if basis is None:
            return 0
    days_elapsed = (as_of_date - basis).days
    accrual_days = max(0, days_elapsed - statute["grace_days"])
    raw = (
        Decimal(claim["face_amount_cents"])
        * Decimal(statute["annual_interest_rate_bp"])
        * Decimal(accrual_days)
        / (Decimal(10000) * Decimal(365))
    )
    return round_half_up_cents(raw)


def required_doc_types(claim):
    types = set(REQUIRED_DOC_BASE)
    if claim["contestability_flag"]:
        types |= REQUIRED_DOC_CONTESTABLE_EXTRA
    return types


def docs_complete(claim):
    docs = docs_of_claim(claim["id"])
    for t in required_doc_types(claim):
        if not any(d["doc_type"] == t and d["review_result"] == "VERIFIED" for d in docs):
            return False
    return True


def share_of(bc):
    d = designation_of(bc)
    if d is not None:
        return Decimal(str(d["share_percent"]))
    return Decimal(100)  # ESTATE claimant


def select_pool(candidates):
    """Rank-based pool selection over the given beneficiary claims."""
    prim = [b for b in candidates if (designation_of(b) or {}).get("beneficiary_type") == "PRIMARY"]
    if prim:
        return prim
    cont = [b for b in candidates if (designation_of(b) or {}).get("beneficiary_type") == "CONTINGENT"]
    if cont:
        return cont
    return [b for b in candidates if b["claimant_type"] == "ESTATE"]


def assign_amounts(total, pool):
    """Round each beneficiary share first (half-up), then assign the remainder
    (positive or negative) to the highest share; ties break to earliest
    designation effective_date, then earliest designation created_at."""
    amounts = {}
    for b in pool:
        amounts[b["id"]] = round_half_up_cents(Decimal(total) * share_of(b) / Decimal(100))
    if not pool:
        return amounts
    remainder = total - sum(amounts.values())

    def tiekey(b):
        d = designation_of(b)
        eff = d["effective_date"] if d else date.max
        cre = d["created_at"] if d else datetime.max.replace(tzinfo=timezone.utc)
        return (-share_of(b), eff, cre)

    recipient = sorted(pool, key=tiekey)[0]
    amounts[recipient["id"]] += remainder
    return amounts


def run_allocation(claim, candidate_statuses, promote_validated):
    """Run the allocation waterfall.

    candidate_statuses: which BC statuses participate in pool selection.
    promote_validated: when true, VALIDATED pool members move to PAYABLE.
    Returns the pool (list of BeneficiaryClaim records).
    """
    cands = [b for b in bcs_of_claim(claim["id"]) if b["status"] in candidate_statuses]
    pool = select_pool(cands)
    amounts = assign_amounts(claim["total_payable_cents"], pool)
    for b in pool:
        b["allocated_amount_cents"] = amounts[b["id"]]
        if promote_validated and b["status"] == "VALIDATED":
            b["status"] = "PAYABLE"
            touch(b)
    return pool


def dmf_match_score(policy, rec):
    ssn_rec = rec.get("deceased_ssn_last4")
    ssn_pol = policy.get("insured_ssn_last4")
    if ssn_rec and ssn_pol and ssn_rec == ssn_pol:
        return 100  # SSN exact match short-circuits
    score = 0
    if rec["deceased_name"] == policy["insured_name"]:
        score += 45
    if rec["deceased_dob"] == policy["insured_dob"]:
        score += 25
    zip_rec = rec.get("deceased_zip")
    zip_pol = policy.get("insured_zip")
    if zip_rec and zip_pol and zip_rec == zip_pol:
        score += 15
    # The +15 SSN term is unreachable in the weighted path (an exact SSN match
    # already short-circuited to 100); retained for spec symmetry.
    if ssn_rec and ssn_pol and ssn_rec == ssn_pol:
        score += 15
    return score


def raa_provisional_interest(acc):
    """Simple-yield statement estimate, recomputed on every read."""
    claim = db.claims.get(acc["claim_id"])
    statute = db.statutes.get(claim["state_code"]) if claim else None
    if statute is None:
        return 0
    days_open = (db.now.date() - acc["created_at"].date()).days
    raw = (
        Decimal(acc["balance_cents"])
        * Decimal(statute["raa_annual_interest_rate_bp"])
        * Decimal(days_open)
        / (Decimal(10000) * Decimal(365))
    )
    return round_half_up_cents(raw)


def raa_final_yield(acc, closing_balance, on_date):
    """Monthly-compounded yield over complete calendar months on the closing balance."""
    claim = db.claims.get(acc["claim_id"])
    statute = db.statutes.get(claim["state_code"]) if claim else None
    if statute is None:
        return 0
    months = complete_months_between(acc["created_at"].date(), on_date)
    monthly = Decimal(statute["raa_annual_interest_rate_bp"]) / Decimal(10000) / Decimal(12)
    factor = (Decimal(1) + monthly) ** months - Decimal(1)
    return round_half_up_cents(Decimal(closing_balance) * factor)


# ---------------------------------------------------------------------------
# Escheatment cases and the clock sweep (PRD §2.4, §3.9)
# ---------------------------------------------------------------------------

def create_escheatment_case(claim, subject_type, trigger_date, amount_cents, account_id=None):
    statute = db.statutes.get(claim["state_code"])
    dormancy_years = statute["dormancy_years"] if statute else 0
    due = add_years(trigger_date, dormancy_years)
    diligence = due - timedelta(days=DUE_DILIGENCE_LEAD_DAYS)
    case = new_record()
    case.update(
        {
            "claim_id": claim["id"],
            "account_id": account_id,
            "subject_type": subject_type,
            "state_code": claim["state_code"],
            "amount_cents": amount_cents,
            "trigger_date": trigger_date,
            "escheat_due_date": due,
            "due_diligence_start_date": diligence,
            "resolution_note": None,
            "status": "MONITORING",
        }
    )
    db.cases[case["id"]] = case
    return case


def run_sweep():
    """Time-based sweep, fixed order: (1) RAA dormancy flips + case creation,
    (2) escheatment-case MONITORING -> DUE_DILIGENCE progression."""
    today = db.now.date()
    # Phase 1: dormancy
    for acc in list(db.accounts.values()):
        if acc["status"] != "OPEN":
            continue
        claim = db.claims.get(acc["claim_id"])
        statute = db.statutes.get(claim["state_code"]) if claim else None
        if statute is None:
            continue
        anniversary = add_years(acc["last_activity_at"].date(), statute["dormancy_years"])
        if today > anniversary:  # strict: exactly equal stays OPEN
            acc["status"] = "DORMANT"
            touch(acc)
            create_escheatment_case(
                claim,
                "RETAINED_ASSET_ACCOUNT",
                acc["last_activity_at"].date(),
                acc["balance_cents"],
                account_id=acc["id"],
            )
    # Phase 2: due-diligence progression (includes cases just spawned above)
    for case in list(db.cases.values()):
        if case["status"] == "MONITORING" and today >= case["due_diligence_start_date"]:
            case["status"] = "DUE_DILIGENCE"
            touch(case)


# ---------------------------------------------------------------------------
# Legal hold enter / release (PRD §3.7)
# ---------------------------------------------------------------------------

def enter_legal_hold(claim):
    claim["hold_return_state"] = claim["status"]
    claim["status"] = "LEGAL_HOLD"
    for e in elections_of_claim(claim["id"]):
        if e["status"] in ("ELECTED", "CONFIRMED"):
            e["status"] = "SUSPENDED"
            touch(e)
    touch(claim)


def release_hold_if_clear(claim):
    """Automatic release: when no BeneficiaryClaim of the claim remains DISPUTED."""
    if claim["status"] != "LEGAL_HOLD":
        return
    if any(b["status"] == "DISPUTED" for b in bcs_of_claim(claim["id"])):
        return
    ret = claim["hold_return_state"] or "UNDER_REVIEW"
    claim["status"] = ret
    claim["hold_return_state"] = None
    for e in elections_of_claim(claim["id"]):
        if e["status"] == "SUSPENDED":
            e["status"] = "ELECTED"  # must be re-confirmed
            touch(e)
    touch(claim)
    if ret == "APPROVED":
        # Re-run allocation; total_payable_cents was untouched by the hold, so
        # allocations are restored exactly.
        run_allocation(claim, {"VALIDATED", "PAYABLE"}, promote_validated=True)


def reject_open_beneficiary_claims(claim, reason):
    for b in bcs_of_claim(claim["id"]):
        if b["status"] in ("SUBMITTED", "VALIDATED", "DISPUTED"):
            b["status"] = "REJECTED"
            b["rejection_reason"] = reason
            touch(b)


# ---------------------------------------------------------------------------
# Serializers (exact field sets per SCAFFOLD entities table)
# ---------------------------------------------------------------------------

def _iso_date(d):
    return d.isoformat() if d is not None else None


def ser_statute(s):
    return {
        "id": s["id"],
        "state_code": s["state_code"],
        "annual_interest_rate_bp": s["annual_interest_rate_bp"],
        "interest_basis": s["interest_basis"],
        "grace_days": s["grace_days"],
        "payment_deadline_days": s["payment_deadline_days"],
        "dormancy_years": s["dormancy_years"],
        "raa_minimum_cents": s["raa_minimum_cents"],
        "raa_annual_interest_rate_bp": s["raa_annual_interest_rate_bp"],
        "created_at": fmt_dt3(s["created_at"]),
    }


def ser_policy(p):
    return {
        "id": p["id"],
        "policy_number": p["policy_number"],
        "insured_name": p["insured_name"],
        "insured_dob": _iso_date(p["insured_dob"]),
        "insured_ssn_last4": p["insured_ssn_last4"],
        "insured_zip": p["insured_zip"],
        "state_code": p["state_code"],
        "face_amount_cents": p["face_amount_cents"],
        "issue_date": _iso_date(p["issue_date"]),
        "contestability_months": p["contestability_months"],
        "lapse_date": _iso_date(p["lapse_date"]),
        "status": p["status"],
        "created_at": fmt_dt3(p["created_at"]),
        "updated_at": fmt_dt3(p["updated_at"]),
        "version": p["version"],
    }


def ser_designation(d):
    return {
        "id": d["id"],
        "policy_id": d["policy_id"],
        "beneficiary_name": d["beneficiary_name"],
        "beneficiary_type": d["beneficiary_type"],
        "share_percent": d["share_percent"],
        "effective_date": _iso_date(d["effective_date"]),
        "revoked_at": fmt_clock(d["revoked_at"]) if d["revoked_at"] else None,
        "status": d["status"],
        "created_at": fmt_dt3(d["created_at"]),
        "updated_at": fmt_dt3(d["updated_at"]),
        "version": d["version"],
    }


def ser_claim(c):
    return {
        "id": c["id"],
        "policy_id": c["policy_id"],
        "state_code": c["state_code"],
        "date_of_death": _iso_date(c["date_of_death"]),
        "cause_of_death": c["cause_of_death"],
        "notification_date": _iso_date(c["notification_date"]),
        "assigned_examiner_id": c["assigned_examiner_id"],
        "contestability_flag": c["contestability_flag"],
        "proof_complete_date": _iso_date(c["proof_complete_date"]),
        "face_amount_cents": c["face_amount_cents"],
        "accrued_interest_cents": c["accrued_interest_cents"],
        "total_payable_cents": c["total_payable_cents"],
        "hold_return_state": c["hold_return_state"],
        "approved_at": _iso_date(c["approved_at"]),
        "paid_at": _iso_date(c["paid_at"]),
        "denial_reason": c["denial_reason"],
        "rescission_reason": c["rescission_reason"],
        "court_reference": c["court_reference"],
        "status": c["status"],
        "created_at": fmt_dt3(c["created_at"]),
        "updated_at": fmt_dt3(c["updated_at"]),
        "version": c["version"],
    }


def ser_document(d):
    return {
        "id": d["id"],
        "claim_id": d["claim_id"],
        "doc_type": d["doc_type"],
        "uploaded_by_id": d["uploaded_by_id"],
        "review_result": d["review_result"],
        "reviewed_by_id": d["reviewed_by_id"],
        "rejection_reason": d["rejection_reason"],
        "created_at": fmt_dt3(d["created_at"]),
        "updated_at": fmt_dt3(d["updated_at"]),
        "version": d["version"],
    }


def ser_beneficiary_claim(b):
    return {
        "id": b["id"],
        "claim_id": b["claim_id"],
        "designation_id": b["designation_id"],
        "claimant_name": b["claimant_name"],
        "claimant_type": b["claimant_type"],
        "allocated_amount_cents": b["allocated_amount_cents"],
        "paid_amount_cents": b["paid_amount_cents"],
        "rejection_reason": b["rejection_reason"],
        "status": b["status"],
        "created_at": fmt_dt3(b["created_at"]),
        "updated_at": fmt_dt3(b["updated_at"]),
        "version": b["version"],
    }


def ser_election(e):
    return {
        "id": e["id"],
        "beneficiary_claim_id": e["beneficiary_claim_id"],
        "option": e["option"],
        "status": e["status"],
        "elected_at": fmt_clock(e["elected_at"]) if e["elected_at"] else None,
        "confirmed_at": fmt_clock(e["confirmed_at"]) if e["confirmed_at"] else None,
        "created_at": fmt_dt3(e["created_at"]),
        "updated_at": fmt_dt3(e["updated_at"]),
        "version": e["version"],
    }


def ser_account(a):
    return {
        "id": a["id"],
        "claim_id": a["claim_id"],
        "beneficiary_claim_id": a["beneficiary_claim_id"],
        "deposited_cents": a["deposited_cents"],
        "balance_cents": a["balance_cents"],
        "withdrawn_total_cents": a["withdrawn_total_cents"],
        "provisional_interest_cents": raa_provisional_interest(a),
        "interest_paid_cents": a["interest_paid_cents"],
        "last_activity_at": fmt_clock(a["last_activity_at"]) if a["last_activity_at"] else None,
        "status": a["status"],
        "created_at": fmt_dt3(a["created_at"]),
        "updated_at": fmt_dt3(a["updated_at"]),
        "version": a["version"],
    }


def ser_match(m):
    return {
        "id": m["id"],
        "policy_id": m["policy_id"],
        "deceased_name": m["deceased_name"],
        "deceased_dob": _iso_date(m["deceased_dob"]),
        "deceased_death_date": _iso_date(m["deceased_death_date"]),
        "deceased_ssn_last4": m["deceased_ssn_last4"],
        "deceased_zip": m["deceased_zip"],
        "match_score": m["match_score"],
        "generated_claim_id": m["generated_claim_id"],
        "status": m["status"],
        "created_at": fmt_dt3(m["created_at"]),
        "updated_at": fmt_dt3(m["updated_at"]),
        "version": m["version"],
    }


def ser_case(c):
    return {
        "id": c["id"],
        "claim_id": c["claim_id"],
        "account_id": c["account_id"],
        "subject_type": c["subject_type"],
        "state_code": c["state_code"],
        "amount_cents": c["amount_cents"],
        "trigger_date": _iso_date(c["trigger_date"]),
        "escheat_due_date": _iso_date(c["escheat_due_date"]),
        "due_diligence_start_date": _iso_date(c["due_diligence_start_date"]),
        "resolution_note": c["resolution_note"],
        "status": c["status"],
        "created_at": fmt_dt3(c["created_at"]),
        "updated_at": fmt_dt3(c["updated_at"]),
        "version": c["version"],
    }
