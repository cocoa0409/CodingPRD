"""Policy lifecycle engine: ledger posting, billing cycles, clock-driven
transitions (grace/lapse/auto-election), payments, cascades."""
from datetime import timedelta

import domain
import errors
from db import store
from domain import (
    MODE_MONTHS, ENTRY_PREMIUM_CREDIT, ENTRY_COI_DEBIT, ENTRY_SURRENDER_DEBIT,
    ENTRY_LOAN_DISBURSEMENT, ENTRY_LOAN_REPAYMENT_CREDIT, ENTRY_DIVIDEND_CREDIT,
    ENTRY_RIDER_PREMIUM_DEBIT, POLICY_FORM_TERMINAL,
)
from util import add_months
from services import calculations as calc


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def post_ledger(policy, entry_type, amount_cents, change_cents=None):
    """Append a ledger entry. change_cents = how much cash_value_cents moves
    (defaults to amount_cents). For TERM_CONVERTIBLE, PREMIUM_CREDIT posts with
    no cash-value movement (term builds no cash value)."""
    if change_cents is None:
        change_cents = amount_cents
    policy["cash_value_cents"] += change_cents
    entry = domain.stamp_append_only({
        "policy_id": policy["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "posting_date": store.current_date(),
        "resulting_cash_value_cents": policy["cash_value_cents"],
    })
    store.ledger_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Billing cycles
# ---------------------------------------------------------------------------
def create_cycle(policy, index, period_start, status="OPEN"):
    months = MODE_MONTHS[policy["premium_mode"]]
    cycle = domain.stamp_new({
        "policy_id": policy["id"],
        "cycle_index": index,
        "period_start_date": period_start,
        "period_end_date": add_months(period_start, months),
        "due_amount_cents": policy["modal_premium_cents"],
        "paid_amount_cents": 0,
        "status": status,
    })
    store.billing_cycles[cycle["id"]] = cycle
    return cycle


def policy_cycles(policy):
    cycles = [c for c in store.billing_cycles.values() if c["policy_id"] == policy["id"]]
    return sorted(cycles, key=lambda c: c["cycle_index"])


def policy_loans(policy):
    return domain.sorted_by_creation(
        [l for l in store.loans.values() if l["policy_id"] == policy["id"]])


def policy_riders(policy):
    return domain.sorted_by_creation(
        [r for r in store.riders.values() if r["policy_id"] == policy["id"]])


def has_exercised_waiver(policy):
    return any(r["rider_type"] == "WAIVER_OF_PREMIUM" and r["status"] == "EXERCISED"
               for r in policy_riders(policy))


def ensure_cycles(policy):
    """Lazily create billing cycles whose period has already started, for
    in-force, CURRENT policies. New cycles start at the later of the last
    cycle's period end and paid_to_date (post-reinstatement gap)."""
    if policy["form_status"] != "IN_FORCE":
        return []
    if policy["premium_payment_status"] != "CURRENT":
        return []
    today = store.current_date()
    cycles = policy_cycles(policy)
    if not cycles:
        return []
    created = []
    last = cycles[-1]
    start = max(last["period_end_date"], policy["paid_to_date"])
    waived = has_exercised_waiver(policy)
    template = domain.template_of(policy)
    while start <= today:
        cycle = create_cycle(policy, last["cycle_index"] + 1, start,
                             status=("WAIVED" if waived else "OPEN"))
        created.append(cycle)
        # UL cost-of-insurance charged on each cycle anniversary (system)
        if (not waived and template["product_type"] == "UNIVERSAL_LIFE"
                and policy["form_status"] == "IN_FORCE"
                and policy["premium_payment_status"] != "PAID_UP"):
            insured = domain.insured_of(policy)
            coi = calc.monthly_coi(policy["face_amount_cents"],
                                   policy["cash_value_cents"],
                                   insured["date_of_birth"], today,
                                   template.get("coi_rate_table") or [],
                                   policy["underwriting_class"])
            if coi > 0:
                post_ledger(policy, ENTRY_COI_DEBIT, -coi)
                domain.touch_policy(policy)
        last = cycle
        start = max(last["period_end_date"], policy["paid_to_date"])
    return created


# ---------------------------------------------------------------------------
# Clock-driven auto-transitions
# ---------------------------------------------------------------------------
def _grace_cycle(policy, cycle, today):
    """Move an unpaid cycle past its period end into GRACE, and lapse the policy
    the day after the grace period ends (strict > boundary, PRD §3.4)."""
    cycle["status"] = "GRACE"
    domain.touch(cycle)
    policy["premium_payment_status"] = "GRACE"
    policy["grace_period_end_date"] = (
        cycle["period_end_date"] + timedelta(days=domain.GRACE_PERIOD_DAYS))
    domain.touch_policy(policy)
    if today > policy["grace_period_end_date"]:
        lapse_policy(policy, today)


def run_clock_transitions():
    """Fire every auto-transition whose trigger has come due (PRD §2.4).
    Each policy is walked chronologically: the oldest unpaid cycle whose
    period has ended enters grace; lapse fires strictly after the grace end;
    new cycles are created only while the policy remains CURRENT."""
    today = store.current_date()
    for policy in domain.sorted_by_creation(list(store.policies.values())):
        if policy["form_status"] != "IN_FORCE":
            continue
        if policy["premium_payment_status"] == "GRACE":
            gpe = policy.get("grace_period_end_date")
            if gpe is not None and today > gpe:
                lapse_policy(policy, today)
            continue
        if policy["premium_payment_status"] != "CURRENT":
            continue
        # Existing cycles first: only the oldest unpaid past-due cycle enters grace
        for cycle in policy_cycles(policy):
            if cycle["status"] in ("OPEN", "PARTIALLY_PAID") and today > cycle["period_end_date"]:
                _grace_cycle(policy, cycle, today)
                break
        # Then create elapsed cycles one at a time, checking each for grace
        waived = has_exercised_waiver(policy)
        template = domain.template_of(policy)
        while (policy["premium_payment_status"] == "CURRENT"
               and policy["form_status"] == "IN_FORCE"):
            cycles = policy_cycles(policy)
            if not cycles:
                break
            last = cycles[-1]
            start = max(last["period_end_date"], policy["paid_to_date"])
            if start > today:
                break
            cycle = create_cycle(policy, last["cycle_index"] + 1, start,
                                 status=("WAIVED" if waived else "OPEN"))
            # UL cost-of-insurance on each cycle anniversary (system)
            if (not waived and template["product_type"] == "UNIVERSAL_LIFE"
                    and policy["premium_payment_status"] != "PAID_UP"):
                insured = domain.insured_of(policy)
                coi = calc.monthly_coi(policy["face_amount_cents"],
                                       policy["cash_value_cents"],
                                       insured["date_of_birth"], today,
                                       template.get("coi_rate_table") or [],
                                       policy["underwriting_class"])
                if coi > 0:
                    post_ledger(policy, ENTRY_COI_DEBIT, -coi)
                    domain.touch_policy(policy)
            if cycle["status"] in ("OPEN", "PARTIALLY_PAID") and today > cycle["period_end_date"]:
                _grace_cycle(policy, cycle, today)
                break


def lapse_policy(policy, lapse_date):
    """Cycle GRACE->LAPSED, policy GRACE->LAPSED, cascades, auto-election."""
    policy["premium_payment_status"] = "LAPSED"
    policy["_lapsed_date"] = lapse_date
    for cycle in policy_cycles(policy):
        # The unpaid cycle that carried the policy through grace lapses; while
        # in GRACE no newer cycles are created, so any unpaid cycle is it.
        if cycle["status"] in ("OPEN", "PARTIALLY_PAID", "GRACE"):
            cycle["status"] = "LAPSED"
            domain.touch(cycle)
    # Accrue then foreclose outstanding loans
    template = domain.template_of(policy)
    for loan in policy_loans(policy):
        if loan["status"] == "ACTIVE":
            calc.accrue_loan(loan, policy, template, lapse_date)
            loan["status"] = "FORECLOSED"
            domain.touch(loan)
    # Terminate active riders (lapse cascade)
    for rider in policy_riders(policy):
        if rider["status"] == "ACTIVE":
            rider["status"] = "TERMINATED"
            rider["_cascade"] = "lapse"
            domain.touch(rider)
    # Forfeit any unapplied declarations
    for d in store.dividend_declarations.values():
        if d["policy_id"] == policy["id"] and d["status"] == "DECLARED":
            d["status"] = "FORFEITED"
            domain.touch(d)
    domain.touch_policy(policy)
    # Automatic non-forfeiture election when the product holds value
    existing = [e for e in store.nonforfeiture_elections.values()
                if e["policy_id"] == policy["id"]]
    if policy["cash_value_cents"] > 0 and not existing:
        try:
            apply_nonforfeiture(policy, "EXTENDED_TERM", effective_date=lapse_date)
        except errors.ApiError:
            pass  # cannot compute (e.g. net below one month's cost): no election


# ---------------------------------------------------------------------------
# Premium payments
# ---------------------------------------------------------------------------
def record_premium_payment(policy, amount_cents):
    """Allocate chronologically, oldest unpaid cycle first (PRD §3.4)."""
    if policy["form_status"] in POLICY_FORM_TERMINAL:
        raise errors.already_terminal()
    if policy["premium_payment_status"] not in ("CURRENT", "GRACE"):
        raise errors.invalid_state("Policy is not accepting premium payments")
    if policy["form_status"] != "IN_FORCE":
        raise errors.invalid_state("Policy form does not permit premium payments")

    template = domain.template_of(policy)
    insured = domain.insured_of(policy)
    today = store.current_date()

    # UL COI computed on cash value BEFORE this cycle's premium credit
    coi_due = 0
    if (template["product_type"] == "UNIVERSAL_LIFE"
            and policy["form_status"] == "IN_FORCE"
            and policy["premium_payment_status"] != "PAID_UP"):
        coi_due = calc.monthly_coi(policy["face_amount_cents"], policy["cash_value_cents"],
                                   insured["date_of_birth"], today,
                                   template.get("coi_rate_table") or [],
                                   policy["underwriting_class"])

    remaining = amount_cents
    cycles = policy_cycles(policy)

    def fill(cycle):
        nonlocal remaining
        if remaining <= 0:
            return
        need = cycle["due_amount_cents"] - cycle["paid_amount_cents"]
        take = min(need, remaining)
        cycle["paid_amount_cents"] += take
        remaining -= take
        if cycle["paid_amount_cents"] >= cycle["due_amount_cents"]:
            was_grace = cycle["status"] == "GRACE"
            cycle["status"] = "PAID"
            domain.touch(cycle)
            if was_grace and policy["premium_payment_status"] == "GRACE":
                policy["premium_payment_status"] = "CURRENT"
        else:
            if cycle["status"] in ("OPEN", "GRACE"):
                cycle["status"] = "PARTIALLY_PAID"
                domain.touch(cycle)

    for cycle in cycles:
        if cycle["status"] in ("OPEN", "PARTIALLY_PAID", "GRACE"):
            fill(cycle)

    # PRD §3.4: allocation walks existing cycles in ascending cycle_index
    # order. New cycles come into existence through clock progression, not
    # through overpayment; any remainder beyond existing unpaid cycles is
    # still credited in full by the PREMIUM_CREDIT posting below.

    # paid_to_date = max(period_end_date) over PAID cycles
    paid_ends = [c["period_end_date"] for c in policy_cycles(policy)
                 if c["status"] == "PAID"]
    if paid_ends:
        policy["paid_to_date"] = max(paid_ends)

    builds = domain.policy_builds_cash_value(policy)
    post_ledger(policy, ENTRY_PREMIUM_CREDIT, amount_cents,
                change_cents=(amount_cents if builds else 0))
    if coi_due > 0:
        post_ledger(policy, ENTRY_COI_DEBIT, -coi_due)
    domain.touch_policy(policy)
    return policy


# ---------------------------------------------------------------------------
# Non-forfeiture elections
# ---------------------------------------------------------------------------
def compute_surrender_charge(policy):
    template = domain.template_of(policy)
    return calc.surrender_charge(template, policy, domain.policy_year_of(policy))


def apply_nonforfeiture(policy, election_type, effective_date=None):
    """Shared implementation for explicit and automatic elections.
    Caller has already validated eligibility where required."""
    from services import calculations as calcs
    template = domain.template_of(policy)
    insured = domain.insured_of(policy)
    if effective_date is None:
        if policy["premium_payment_status"] == "LAPSED" and policy.get("_lapsed_date"):
            effective_date = policy["_lapsed_date"]
        else:
            effective_date = store.current_date()

    # Accrue outstanding loans to the election date, then snapshot the offset
    for loan in policy_loans(policy):
        if loan["status"] == "ACTIVE":
            calcs.accrue_loan(loan, policy, template, effective_date)

    cash_at = policy["cash_value_cents"]
    loan_offset = (policy["outstanding_loan_principal_cents"]
                   + policy["accrued_loan_interest_cents"])
    charge = compute_surrender_charge(policy)
    net_available = cash_at - loan_offset - charge

    extra_bps = policy.get("_substandard_extra_pct_bps", 0)
    resulting_face = 0
    resulting_term = 0
    payout = 0

    if election_type == "CASH_SURRENDER":
        payout = max(0, net_available)
    elif election_type == "REDUCED_PAID_UP":
        if net_available <= 0:
            raise errors.insufficient_cash_value(
                "Net available value insufficient for reduced paid-up")
        resulting_face = calcs.reduced_paid_up_face(
            net_available, insured["date_of_birth"], effective_date, extra_bps)
    elif election_type == "EXTENDED_TERM":
        resulting_term = calcs.extended_term_months(
            net_available, policy["face_amount_cents"],
            insured["date_of_birth"], effective_date)

    election = domain.stamp_new({
        "policy_id": policy["id"],
        "election_type": election_type,
        "effective_date": effective_date,
        "cash_value_at_election_cents": cash_at,
        "outstanding_loan_offset_cents": loan_offset,
        "surrender_charge_cents": charge,
        "net_available_cents": net_available,
        "resulting_face_amount_cents": resulting_face,
        "resulting_term_months": resulting_term,
        "payout_cents": payout,
    })
    store.nonforfeiture_elections[election["id"]] = election

    # Shared cascade: loans foreclosed, riders terminated, cycles waived
    for loan in policy_loans(policy):
        if loan["status"] == "ACTIVE":
            loan["status"] = "FORECLOSED"
            domain.touch(loan)
    for rider in policy_riders(policy):
        if rider["status"] == "ACTIVE":
            rider["status"] = "TERMINATED"
            domain.touch(rider)
    for cycle in policy_cycles(policy):
        if cycle["status"] in ("OPEN", "PARTIALLY_PAID", "GRACE"):
            cycle["status"] = "WAIVED"
            domain.touch(cycle)

    policy["premium_payment_status"] = "PAID_UP"
    if election_type == "CASH_SURRENDER":
        post_ledger(policy, ENTRY_SURRENDER_DEBIT, -policy["cash_value_cents"])
        policy["form_status"] = "SURRENDERED"
        # Unapplied CASH declarations are forfeited on surrender
        for d in store.dividend_declarations.values():
            if (d["policy_id"] == policy["id"] and d["status"] == "DECLARED"
                    and policy["dividend_option"] == "CASH"):
                d["status"] = "FORFEITED"
                domain.touch(d)
    elif election_type == "REDUCED_PAID_UP":
        policy["face_amount_cents"] = resulting_face
        policy["form_status"] = "REDUCED_PAID_UP"
    elif election_type == "EXTENDED_TERM":
        policy["form_status"] = "EXTENDED_TERM"
    domain.touch_policy(policy)
    return election
