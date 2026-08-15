"""Core derived-state machinery: borrowing base, interest accrual, posture bands,
margin deficiency, borrower standing, and the periodic review (PRD 2.4, 2.8, 3.x)."""
from db import STORE, get_clock

TERMINAL_LOAN_STATES = ("PAID_OFF", "CHARGED_OFF", "FORECLOSED")
ADVANCE_RATE_BP = {"CHATTEL_CROP": 7500, "EQUIPMENT": 7000, "REAL_ESTATE": 8000}
CROP_ADVANCE_BP = 6000
DAY_COUNT_DENOMINATOR = 360  # ACT/360


# ---------------------------------------------------------------------------
# Mutation stamping: updated_at refresh + version increment
# ---------------------------------------------------------------------------

def touch(entity):
    entity["updated_at"] = get_clock()
    entity["version"] += 1


def stamp_new(entity):
    now = get_clock()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = STORE.next_seq()
    return entity


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def loans_of_borrower(borrower_id):
    return [l for l in STORE.loans.values() if l["borrower_id"] == borrower_id]


def loans_of_association(association_id):
    return [l for l in STORE.loans.values() if l["association_id"] == association_id]


def budgets_of_loan(loan_id):
    return [b for b in STORE.budgets.values() if b["loan_account_id"] == loan_id]


def collaterals_of_loan(loan_id):
    return [c for c in STORE.collaterals.values() if c["loan_account_id"] == loan_id]


def filings_of_collateral(collateral_id):
    return [f for f in STORE.filings.values() if f["collateral_id"] == collateral_id]


def policies_of_borrower(borrower_id):
    return [p for p in STORE.policies.values() if p["borrower_id"] == borrower_id]


def policies_assigned_to_loan(loan_id):
    return [p for p in STORE.policies.values() if p["assigned_loan_id"] == loan_id]


def claims_of_policy(policy_id):
    return [c for c in STORE.claims.values() if c["policy_id"] == policy_id]


def draws_of_loan(loan_id):
    return [d for d in STORE.draws.values() if d["loan_account_id"] == loan_id]


def plans_of_loan(loan_id):
    return [p for p in STORE.plans.values() if p["loan_account_id"] == loan_id]


def deferrals_of_loan(loan_id):
    return [d for d in STORE.deferrals.values() if d["loan_account_id"] == loan_id]


def notices_of_loan(loan_id):
    return [n for n in STORE.notices.values() if n["loan_account_id"] == loan_id]


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def perfection_state(collateral):
    """PERFECTED iff any UCC filing of this collateral is FILED or CONTINUED."""
    for f in filings_of_collateral(collateral["id"]):
        if f["status"] in ("FILED", "CONTINUED"):
            return "PERFECTED"
    return "UNPERFECTED"


def pending_draw_cents(loan):
    """Sum of amount_cents over this loan's draws in status APPROVED exactly."""
    return sum(d["amount_cents"] for d in draws_of_loan(loan["id"])
               if d["status"] == "APPROVED")


def feeding_budget(loan):
    """The newest (by creation order) APPROVED or ACTUALIZED budget of the loan."""
    cands = [b for b in budgets_of_loan(loan["id"])
             if b["status"] in ("APPROVED", "ACTUALIZED")]
    if not cands:
        return None
    return max(cands, key=lambda b: b["_seq"])


def compute_borrowing_base(loan, exclude_collateral_id=None):
    """PRD 3.3: per-collateral floors first, then sum, commitment cap last."""
    collateral_component = 0
    for c in collaterals_of_loan(loan["id"]):
        if c["id"] == exclude_collateral_id:
            continue
        if c["status"] == "PLEDGED" and perfection_state(c) == "PERFECTED":
            line = (c["appraised_value_cents"] * ADVANCE_RATE_BP[c["collateral_type"]]) // 10000
            collateral_component += max(0, line - c["prior_lien_cents"])
    crop_component = 0
    b = feeding_budget(loan)
    if b is not None:
        if b["status"] == "ACTUALIZED":
            crop_component = (b["actual_revenue_cents"] * CROP_ADVANCE_BP) // 10000
        else:  # APPROVED (provisional)
            crop_component = (b["projected_revenue_cents"] * CROP_ADVANCE_BP) // 10000
    raw = collateral_component + crop_component
    cap = loan["approved_commitment_cents"]
    return raw if cap is None else min(cap, raw)


def recompute_borrowing_base(loan):
    loan["borrowing_base_cents"] = compute_borrowing_base(loan)


def available_credit_cents(loan):
    cap = loan["approved_commitment_cents"]
    base = loan["borrowing_base_cents"]
    headroom = base if cap is None else min(cap, base)
    return headroom - loan["outstanding_principal_cents"] - pending_draw_cents(loan)


def coverage_cents(loan):
    cap = loan["approved_commitment_cents"]
    base = loan["borrowing_base_cents"]
    headroom = base if cap is None else min(cap, base)
    return headroom - loan["outstanding_principal_cents"]


# ---------------------------------------------------------------------------
# Interest accrual (PRD 3.6): segment accrual, daily charge rounded half-up
# to whole cents FIRST, then multiplied by whole UTC days.
# ---------------------------------------------------------------------------

def accrue_interest(loan):
    if loan["status"] not in ("ACTIVE", "RESTRUCTURING"):
        return
    lad = loan["last_accrual_date"]  # a datetime.date or None
    if lad is None:
        return
    clock = get_clock()
    d = (clock.date() - lad).days
    if d < 0:
        return
    if d > 0 and loan["outstanding_principal_cents"] > 0:
        p = loan["outstanding_principal_cents"] * loan["rate_bps"]
        # round_half_up(p / 3_600_000) for non-negative p
        daily = (2 * p + 3_600_000) // (2 * 3_600_000)
        loan["accrued_interest_cents"] += daily * d
    loan["last_accrual_date"] = clock.date()


def projected_accrued(loan):
    """Accrued interest as if accrual ran to the clock now, without mutating."""
    accrued = loan["accrued_interest_cents"]
    if loan["status"] in ("ACTIVE", "RESTRUCTURING") and loan["last_accrual_date"] is not None:
        d = (get_clock().date() - loan["last_accrual_date"]).days
        if d > 0 and loan["outstanding_principal_cents"] > 0:
            p = loan["outstanding_principal_cents"] * loan["rate_bps"]
            daily = (2 * p + 3_600_000) // (2 * 3_600_000)
            accrued += daily * d
    return accrued


# ---------------------------------------------------------------------------
# Coverage-band posture (PRD 3.6/3.8). DEFAULT is sticky; never band-derived.
# ---------------------------------------------------------------------------

def recompute_posture(loan):
    # DEFAULT is sticky: only restructure execute or terminal payoff exits it.
    # Terminal status does NOT exempt a loan here — a payoff that zeroes the
    # balances must be able to recompute DELINQUENT -> WATCH/CURRENT so the
    # borrower's standing recovers (PRD 3.1, 3.6).
    if loan["approved_commitment_cents"] is None:
        return
    if loan["payment_posture"] == "DEFAULT":
        return
    cov = coverage_cents(loan)
    commitment = loan["approved_commitment_cents"]
    if cov * 10 >= commitment:
        band = "CURRENT"
    elif cov >= 0:
        band = "WATCH"
    else:
        band = "DELINQUENT"
    loan["payment_posture"] = band
    if band != "DELINQUENT":
        loan["consecutive_delinquent_reviews"] = 0


# ---------------------------------------------------------------------------
# Margin deficiency check (PRD 3.8)
# ---------------------------------------------------------------------------

def margin_deficiency_check(loan):
    if loan["approved_commitment_cents"] is None:
        return
    deficiency = (loan["outstanding_principal_cents"]
                  - min(loan["approved_commitment_cents"], loan["borrowing_base_cents"]))
    issued = None
    for n in notices_of_loan(loan["id"]):
        if n["status"] == "ISSUED":
            issued = n
            break
    if deficiency > 0 and issued is None:
        from util import new_id
        notice = {
            "id": new_id(),
            "loan_account_id": loan["id"],
            "deficiency_cents": deficiency,
            "status": "ISSUED",
        }
        stamp_new(notice)
        STORE.notices[notice["id"]] = notice
    elif deficiency <= 0 and issued is not None:
        issued["status"] = "CURED"
        touch(issued)
        reevaluate_borrower(loan["borrower_id"])


# ---------------------------------------------------------------------------
# Borrower standing (PRD 3.1): derived ACTIVE <-> SUSPENDED
# ---------------------------------------------------------------------------

def reevaluate_borrower(borrower_id):
    b = STORE.borrowers.get(borrower_id)
    if b is None or b["status"] == "TERMINATED":
        return
    suspended = False
    if b["active_covenant_breach_count"] >= 2:
        suspended = True
    if not suspended:
        for loan in loans_of_borrower(borrower_id):
            if loan["payment_posture"] in ("DELINQUENT", "DEFAULT"):
                suspended = True
                break
    if not suspended:
        loan_ids = {l["id"] for l in loans_of_borrower(borrower_id)}
        for n in STORE.notices.values():
            if n["loan_account_id"] in loan_ids and n["status"] == "ESCALATED":
                suspended = True
                break
    new_status = "SUSPENDED" if suspended else "ACTIVE"
    if b["status"] != new_status:
        b["status"] = new_status
        touch(b)


def standard_cascade(loan, skip_posture=False):
    """PRD 2.8: posture recompute, margin deficiency check, borrower re-eval."""
    if not skip_posture:
        recompute_posture(loan)
    margin_deficiency_check(loan)
    reevaluate_borrower(loan["borrower_id"])


# ---------------------------------------------------------------------------
# Insurance helpers
# ---------------------------------------------------------------------------

def has_assigned_active_policy(loan):
    for p in STORE.policies.values():
        if (p["assigned_loan_id"] == loan["id"]
                and p["status"] == "ACTIVE"
                and p["assignment_status"] == "ASSIGNED"):
            return True
    return False


def has_perfected_pledged_collateral(loan):
    for c in collaterals_of_loan(loan["id"]):
        if c["status"] == "PLEDGED" and perfection_state(c) == "PERFECTED":
            return True
    return False


def coverage_remaining_cents(policy):
    used = sum(c["indemnity_to_lender_cents"] or 0
               for c in claims_of_policy(policy["id"]) if c["status"] == "PAID")
    return policy["coverage_amount_cents"] - used


def active_disaster_declaration(association, county, ref=None):
    """A declaration whose ref matches (when given), covering county, end >= clock."""
    clock = get_clock()
    for d in association["active_disaster_declarations"]:
        if ref is not None and d["disaster_ref"] != ref:
            continue
        if county not in d["counties"]:
            continue
        if d["end_date"] >= clock:
            return d
    return None


# ---------------------------------------------------------------------------
# Periodic review (PRD 2.4)
# ---------------------------------------------------------------------------

def run_periodic_review(association):
    clock = get_clock()
    association["review_index"] += 1
    touch(association)

    assoc_loans = loans_of_association(association["id"])

    # 1. Interest accrual sweep for ACTIVE / RESTRUCTURING loans.
    for loan in assoc_loans:
        if loan["status"] in ("ACTIVE", "RESTRUCTURING"):
            accrue_interest(loan)

    # 2. Lapse FILED / CONTINUED filings whose lapse_date <= clock.
    loan_by_id = {l["id"]: l for l in assoc_loans}
    affected_loan_ids = set()
    for f in list(STORE.filings.values()):
        if f["status"] not in ("FILED", "CONTINUED"):
            continue
        collateral = STORE.collaterals.get(f["collateral_id"])
        if collateral is None:
            continue
        loan = loan_by_id.get(collateral["loan_account_id"])
        if loan is None:
            continue
        if f["lapse_date"] <= clock:
            f["status"] = "LAPSED"
            touch(f)
            affected_loan_ids.add(loan["id"])
    for loan_id in affected_loan_ids:
        loan = loan_by_id[loan_id]
        recompute_borrowing_base(loan)
        standard_cascade(loan)

    # 3. Deferral lifecycle.
    for d in list(STORE.deferrals.values()):
        if d["loan_account_id"] not in loan_by_id:
            continue
        if d["status"] in ("APPROVED", "IN_EFFECT") and d["requested_end"] <= clock:
            d["status"] = "EXPIRED"
            touch(d)
        elif d["status"] == "APPROVED" and d["requested_start"] <= clock < d["requested_end"]:
            d["status"] = "IN_EFFECT"
            touch(d)

    # 4. Coverage-band posture recompute + consecutive-delinquency escalation.
    for loan in assoc_loans:
        if loan["status"] in TERMINAL_LOAN_STATES:
            continue
        if loan["approved_commitment_cents"] is None:
            continue
        if loan["payment_posture"] == "DEFAULT":
            continue  # sticky
        recompute_posture(loan)
        if loan["payment_posture"] == "DELINQUENT":
            loan["consecutive_delinquent_reviews"] += 1
            if loan["consecutive_delinquent_reviews"] >= 2:
                loan["payment_posture"] = "DEFAULT"
        reevaluate_borrower(loan["borrower_id"])

    # 5. Margin deficiency sweep.
    for loan in assoc_loans:
        if loan["status"] in TERMINAL_LOAN_STATES:
            continue
        margin_deficiency_check(loan)

    return association
