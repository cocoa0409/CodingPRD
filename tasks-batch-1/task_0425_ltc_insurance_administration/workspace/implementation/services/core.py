"""Core domain logic: cascades, payout, repricing, premium clock transitions."""
from db import STORE, new_id, common_fields, touch
from services import calc, serialize

NON_TERMINAL_CLAIM = {"SUBMITTED", "UNDER_REVIEW", "PENDING_REASSESSMENT"}


# --- Ledger ------------------------------------------------------------------

def append_ledger(policy_id, claim_id, source_kind, amount_cents):
    eid = new_id()
    entry = {
        "id": eid,
        "policy_id": policy_id,
        "claim_id": claim_id,
        "source_kind": source_kind,
        "amount_cents": amount_cents,
        "created_at": serialize_now(),
        "_seq": STORE.next_seq(),
    }
    STORE.ledger_entries[eid] = entry
    return entry


def serialize_now():
    from response import now_iso
    return now_iso()


# --- Pool / partnership recompute -------------------------------------------

def pool_for_policy(policy_id):
    for pool in STORE.benefit_pools.values():
        if pool["policy_id"] == policy_id:
            return pool
    return None


def partnership_for_policy(policy_id):
    for pd in STORE.partnership_disregards.values():
        if pd["policy_id"] == policy_id:
            return pd
    return None


def recompute_partnership(policy):
    """While ACCRUING, protected_asset_cents == lifetime_paid_cents (PRD §3.9)."""
    if not policy["is_partnership_policy"]:
        return
    pd = partnership_for_policy(policy["id"])
    if pd is None or pd["disregard_status"] != "ACCRUING":
        return
    lifetime = serialize.pool_lifetime_paid_cents(policy["id"])
    if pd["protected_asset_cents"] != lifetime:
        pd["protected_asset_cents"] = lifetime
        touch(pd)


# --- Coverage transition helpers --------------------------------------------

def has_other_non_terminal_claim(policy_id, exclude_claim_id):
    for c in STORE.claims.values():
        if c["policy_id"] != policy_id:
            continue
        if c["id"] == exclude_claim_id:
            continue
        if c["status"] in NON_TERMINAL_CLAIM:
            return True
    return False


# --- Claim payout (PRD §3.7) -------------------------------------------------

def run_claim_payout(policy, claim):
    """Compute per-line benefit, set claim.month_paid_cents. Returns total."""
    pool = pool_for_policy(policy["id"])
    inflated_daily = serialize.policy_inflated_daily(policy)
    inflated_monthly = serialize.policy_inflated_monthly(policy)
    elim_satisfied = serialize.policy_elimination_days_satisfied(policy)
    remaining_elim = max(0, int(policy["elimination_period_days"]) - elim_satisfied)

    # amount already paid this service_month on prior APPROVED claims
    month_running = 0
    for c in STORE.claims.values():
        if (c["policy_id"] == policy["id"] and c["status"] == "APPROVED"
                and c["service_month"] == claim["service_month"] and c["id"] != claim["id"]):
            for line in STORE.claim_lines.values():
                if line["claim_id"] == c["id"]:
                    month_running += line["benefit_paid_cents"]

    pool_remaining = serialize.benefit_pool(pool)["remaining_pool_cents"]

    lines = [l for l in STORE.claim_lines.values() if l["claim_id"] == claim["id"]]
    lines.sort(key=lambda l: (l["service_date"], l["_seq"]))

    total = 0
    for line in lines:
        if not line["is_qualifying_day"]:
            line["benefit_paid_cents"] = 0
            line["elimination_applied"] = False
            touch(line)
            continue
        if remaining_elim > 0:
            line["elimination_applied"] = True
            line["benefit_paid_cents"] = 0
            remaining_elim -= 1
            touch(line)
            continue
        line["elimination_applied"] = False
        if policy["product_mode"] == "INDEMNITY":
            raw_day = inflated_daily
        else:  # REIMBURSEMENT
            raw_day = min(line["billed_charge_cents"], inflated_daily)
        monthly_headroom = max(0, inflated_monthly - month_running)
        day_pay = min(raw_day, monthly_headroom, pool_remaining)
        if day_pay < 0:
            day_pay = 0
        line["benefit_paid_cents"] = day_pay
        line["elimination_applied"] = False
        month_running += day_pay
        pool_remaining -= day_pay
        total += day_pay
        touch(line)

    claim["month_paid_cents"] = total
    return total


# --- Premium repricing (PRD §3.11) ------------------------------------------

def applicable_increase_pct(policy_id, period_index):
    """Select the single applicable approved increase for an invoice period."""
    candidates = []
    for f in STORE.rate_filings.values():
        if f["policy_id"] != policy_id:
            continue
        if f["status"] not in ("APPROVED", "PARTIALLY_APPROVED"):
            continue
        if f["effective_period_index"] <= period_index:
            candidates.append(f)
    if not candidates:
        return 0
    # largest effective_period_index, tie-break later created_at (then _seq)
    candidates.sort(key=lambda f: (f["effective_period_index"], f["created_at"], f["_seq"]))
    return candidates[-1]["approved_increase_pct"]


def reprice_open_invoices(policy_id, effective_period_index):
    """Recompute amount_cents for OPEN invoices at/after the effective index."""
    for inv in STORE.premium_invoices.values():
        if inv["policy_id"] != policy_id:
            continue
        if inv["status"] != "OPEN":
            continue
        if inv["period_index"] < effective_period_index:
            continue
        pct = applicable_increase_pct(policy_id, inv["period_index"])
        new_amount = calc.premium_amount(inv["base_premium_cents"], pct)
        if inv["amount_cents"] != new_amount:
            inv["amount_cents"] = new_amount
            touch(inv)


# --- Nonforfeiture (PRD §3.10) ----------------------------------------------

def apply_nonforfeiture(policy):
    """Convert to NONFORFEITURE_PAID_UP, compute pool reduction, write ledger."""
    pool = pool_for_policy(policy["id"])
    # pre-reduction inflated pool = grown pool ignoring any prior reduction
    grown = calc.grow(policy["initial_pool_cents"], policy["inflation_rider"],
                      policy["inflation_years_elapsed"])
    pre_reduction = grown - pool["nonforfeiture_reduction_cents"]

    premiums_paid = 0
    for inv in STORE.premium_invoices.values():
        if inv["policy_id"] == policy["id"] and inv["status"] == "PAID":
            premiums_paid += inv["amount_cents"]
    benefits_paid = serialize.pool_lifetime_paid_cents(policy["id"])

    paid_up_pool = min(pre_reduction, max(premiums_paid, benefits_paid))
    reduction = pre_reduction - paid_up_pool
    if reduction < 0:
        reduction = 0

    policy["premium_status"] = "NONFORFEITURE_PAID_UP"
    if reduction > 0:
        pool["nonforfeiture_reduction_cents"] = pool["nonforfeiture_reduction_cents"] + reduction
        touch(pool)
        append_ledger(policy["id"], None, "NONFORFEITURE_REDUCTION", -reduction)
    # PartnershipDisregard stays ACCRUING (no change)


def apply_lapse(policy):
    """Terminal LAPSED; freeze any partnership disregard (PRD §3.10)."""
    policy["premium_status"] = "LAPSED"
    pd = partnership_for_policy(policy["id"])
    if pd is not None and pd["disregard_status"] != "FROZEN":
        pd["disregard_status"] = "FROZEN"
        touch(pd)


def is_nonforfeiture_vested(policy):
    if policy["inflation_rider"] != "NONE":
        return True
    if serialize.pool_lifetime_paid_cents(policy["id"]) > 0:
        return True
    return False


# --- Clock-driven premium transitions (PRD §3.10) ---------------------------

def advance_clock(to_iso):
    """Set the clock and drive premium auto-transitions for all policies."""
    STORE.clock_iso = to_iso
    # Evaluate each OPEN invoice. due_date/grace_deadline are date strings; the
    # clock is an ISO instant. Compare by the date prefix vs the instant: an
    # invoice's due_date is "passed" when clock > end-of-that-date, modelled
    # as clock_date > due_date (string compare on YYYY-MM-DD).
    clock_date = to_iso[:10]

    # Process invoices in deterministic order (creation order).
    invoices = sorted(STORE.premium_invoices.values(), key=lambda i: i["_seq"])
    for inv in invoices:
        if inv["status"] != "OPEN":
            continue
        policy = STORE.policies.get(inv["policy_id"])
        if policy is None:
            continue
        due = inv["due_date"]
        grace = inv["grace_deadline"]
        if clock_date > grace:
            # grace_deadline passed: default + lapse / nonforfeiture branch
            inv["status"] = "DEFAULTED"
            touch(inv)
            if policy["premium_status"] in ("LAPSED", "NONFORFEITURE_PAID_UP", "WAIVED"):
                # already resolved on a terminal premium posture
                continue
            if is_nonforfeiture_vested(policy):
                apply_nonforfeiture(policy)
            else:
                apply_lapse(policy)
        elif clock_date > due:
            # past due but within grace -> GRACE (PAID_CURRENT -> GRACE per §1.2)
            if policy["premium_status"] == "PAID_CURRENT":
                policy["premium_status"] = "GRACE"
