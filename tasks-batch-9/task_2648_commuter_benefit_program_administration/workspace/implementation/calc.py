"""Calculations: the exclusion waterfall, ledger conservation, invoice pricing,
the payroll rollup, month close, the ordinance ladder and the fulfillment rollup.

All monetary values are whole-cent integers.  Every percentage application goes
through round_half_up at a pinned rounding point (PRD 2.8); the pre-tax ratio cap
is the single place a fraction is discarded by truncation instead.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from errors import fail
from store import bump, sorted_rows, stamp_new, store
from validate import parse_iso8601, parse_month

# ------------------------------------------------------------------ constants
REGION_SURCHARGE_PCT = {
    "US-CA-SFO": Decimal("7.5"),
    "US-NY-NYC": Decimal("6.25"),
    "US-IL-CHI": Decimal("5.0"),
    "US-WA-SEA": Decimal("4.0"),
    "US-TX-AUS": Decimal("2.5"),
}
BULK_DISCOUNT_TIER_1_MAX_LINES = 4
BULK_DISCOUNT_TIER_1_PCT = Decimal("0.0")
BULK_DISCOUNT_TIER_2_MAX_LINES = 9
BULK_DISCOUNT_TIER_2_PCT = Decimal("1.5")
BULK_DISCOUNT_TIER_3_PCT = Decimal("3.0")

ADMIN_FEE_PER_PARTICIPANT_CENTS = 425
ADMIN_FEE_MINIMUM_CENTS = 5000
FEE_WAIVER_TIER_2_MIN_CENTS = 50000
FEE_WAIVER_TIER_3_MIN_CENTS = 200000

SECONDS_PER_DAY = 86400

COVERED_REGION_CODES = ["US-CA-SFO", "US-NY-NYC", "US-WA-SEA"]
ORDINANCE_EMPLOYEE_THRESHOLD = 20
ORDINANCE_MINIMUM_TRANSIT_LIMIT_CENTS = 30000

TRANSIT_MCC_SET = [4111, 4112, 4131, 4789]
PARKING_MCC_SET = [7523]
AUTO_SUBSTANTIATION_CEILING_CENTS = 2500

REISSUE_FEE_ESCALATION_MULTIPLIER = 2
MEDIA_REISSUE_LIMIT = 2
WAIVABLE_UNDELIVERED_REASONS = ["NEVER_ARRIVED"]
MAX_SUBSTANTIATION_REOPENS = 2
MID_MONTH_CHANGE_LIMIT = 1

TRANSIT_CATEGORY_TYPES = ("TRANSIT_PASS", "VANPOOL")


def round_half_up(amount_cents, pct):
    """cents * pct / 100, converted back to whole cents with round half up."""
    value = (Decimal(int(amount_cents)) * pct) / Decimal(100)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def limit_group_for(category_type):
    return "TRANSIT" if category_type in TRANSIT_CATEGORY_TYPES else "PARKING"


# ------------------------------------------------------------ ledger + balance
def recompute_available(account):
    account["available_balance_cents"] = (
        account["rollover_in_cents"]
        + account["contributed_cents"]
        - account["spent_cents"]
        - account["forfeited_cents"]
        - account["refunded_cents"]
        - account["reversed_cents"]
        - account["fee_charged_cents"]
    )
    return account["available_balance_cents"]


def post_entry(account, entry_type, amount_cents, source_entity, source_id, reason):
    """Recompute the conserved balance, then append the immutable ledger row."""
    balance_after = recompute_available(account)
    entry = {
        "benefit_account_id": account["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": balance_after,
        "source_entity": source_entity,
        "source_id": source_id,
        "reason": reason,
    }
    stamp_new(entry, versioned=False)
    store.ledger_entries[entry["id"]] = entry
    return entry


def account_ledger(account_id):
    rows = [e for e in store.ledger_entries.values()
            if e["benefit_account_id"] == account_id]
    return sorted_rows(rows)


# ------------------------------------------------------- exclusion split (3.4)
ELECTED_INCLUSION = ("PENDING", "HELD", "FUNDED")
FUNDED_INCLUSION = ("FUNDED",)


def exclusion_split(employer, category, employee_id, window_id, pretax_cents,
                    posttax_cents, basis, enforce_spill_policy=True,
                    exclude_election_id=None):
    """The four-ceiling waterfall.  Returns the computed allocation fields.

    Raises ERR_EXCLUSION_LIMIT_EXCEEDED when the employer's spill_policy is
    REJECT_OVERAGE and the pre-tax request would spill.
    """
    group = category["limit_group"]
    if group == "TRANSIT":
        group_limit = employer["transit_group_limit_cents"]
    else:
        group_limit = employer["parking_group_limit_cents"]

    inclusion = ELECTED_INCLUSION if basis == "ELECTED_BASIS" else FUNDED_INCLUSION
    prior = 0
    for sibling in store.elections.values():
        if sibling["employee_id"] != employee_id:
            continue
        if exclude_election_id is not None and sibling["id"] == exclude_election_id:
            continue
        if sibling["election_window_id"] != window_id:
            continue
        if sibling["benefit_category_id"] == category["id"]:
            continue
        sibling_category = store.benefit_categories.get(sibling["benefit_category_id"])
        if sibling_category is None or sibling_category["limit_group"] != group:
            continue
        if sibling["funding_status"] not in inclusion:
            continue
        prior += sibling["excluded_amount_cents"]

    group_headroom = group_limit - prior
    if group_headroom < 0:
        group_headroom = 0

    category_cap = category["monthly_exclusion_limit_cents"]
    total_amount = pretax_cents + posttax_cents
    ratio_cap = (total_amount * employer["pretax_ratio_cap_pct"]) // 100

    excluded = min(pretax_cents, group_headroom, category_cap, ratio_cap)
    spill = pretax_cents - excluded
    if spill > 0 and enforce_spill_policy and employer["spill_policy"] == "REJECT_OVERAGE":
        fail("ERR_EXCLUSION_LIMIT_EXCEEDED",
             "The requested pre-tax amount exceeds the available exclusion headroom "
             "and the employer's spill policy rejects any overage.")
    return {
        "total_amount_cents": total_amount,
        "excluded_amount_cents": excluded,
        "posttax_spill_cents": spill,
        "posttax_effective_cents": posttax_cents + spill,
        "exclusion_basis": basis,
    }


# ------------------------------------------------- fulfillment rollup (3.6)
def election_orders(election_id, include_cancelled=False):
    rows = [o for o in store.media_orders.values() if o["election_id"] == election_id]
    if not include_cancelled:
        rows = [o for o in rows if o["status"] != "CANCELLED"]
    return sorted_rows(rows)


def fulfillment_rollup(election):
    """Top-down precedence; the first matching clause wins."""
    if election["funding_status"] == "CANCELLED":
        return "CANCELLED"
    if election["entitled_media_units"] == 0:
        return "NOT_REQUIRED"
    orders = election_orders(election["id"])
    if not orders:
        return "AWAITING_ORDER"
    if any(o["status"] == "UNDELIVERED" for o in orders):
        return "REPLACEMENT_PENDING"
    if all(o["status"] == "DELIVERED" for o in orders) and \
            sum(o["quantity"] for o in orders) >= election["entitled_media_units"]:
        return "DELIVERED"
    if any(o["status"] == "SHIPPED" for o in orders):
        return "IN_TRANSIT"
    return "ORDERED"


def rederive_fulfillment(election):
    election["fulfillment_status"] = fulfillment_rollup(election)
    return election["fulfillment_status"]


# ------------------------------------------- employer rollups and auto-suspend
def employer_of_window(window):
    return store.employers.get(window["employer_id"])


def employer_of_election(election):
    window = store.election_windows.get(election["election_window_id"])
    if window is None:
        return None
    return store.employers.get(window["employer_id"])


def employer_of_category(category):
    return store.employers.get(category["employer_id"])


def recompute_commitment(employer):
    """employer_pretax_commitment: recompute the funded total and test the cap.

    Returns True when the employer row was actually mutated (total moved and/or
    the program was driven ACTIVE -> SUSPENDED).
    """
    total = 0
    for election in store.elections.values():
        if election["funding_status"] != "FUNDED":
            continue
        window = store.election_windows.get(election["election_window_id"])
        if window is None or window["employer_id"] != employer["id"]:
            continue
        total += election["excluded_amount_cents"]
    changed = total != employer["total_pretax_committed_cents"]
    employer["total_pretax_committed_cents"] = total
    suspended = False
    if employer["program_status"] == "ACTIVE" and total > employer["program_cap_cents"]:
        employer["program_status"] = "SUSPENDED"
        suspended = True
    return changed or suspended


def recompute_enrolled(employer):
    count = 0
    for employee in store.employees.values():
        if employee["employer_id"] == employer["id"] and employee["status"] == "ACTIVE":
            count += 1
    changed = count != employer["enrolled_employee_count"]
    employer["enrolled_employee_count"] = count
    return changed


# ------------------------------------------------ order batch invoice (3.5)
def batch_pending_lines(batch_id):
    rows = [o for o in store.media_orders.values()
            if o["order_batch_id"] == batch_id and o["status"] == "PENDING"]
    return sorted_rows(rows)


def price_batch(batch):
    """Per-line surcharge rounding first, then one rounding on the bulk discount."""
    lines = batch_pending_lines(batch["id"])
    pct = REGION_SURCHARGE_PCT[batch["region_code"]]
    subtotal = 0
    for line in lines:
        line["line_gross_cents"] = line["unit_price_cents_snapshot"] * line["quantity"]
        line["line_surcharge_cents"] = round_half_up(line["line_gross_cents"], pct)
        line["line_total_cents"] = line["line_gross_cents"] + line["line_surcharge_cents"]
        subtotal += line["line_total_cents"]
        bump(line)
    batch["line_count"] = len(lines)
    batch["subtotal_cents"] = subtotal
    if len(lines) <= BULK_DISCOUNT_TIER_1_MAX_LINES:
        discount_pct = BULK_DISCOUNT_TIER_1_PCT
    elif len(lines) <= BULK_DISCOUNT_TIER_2_MAX_LINES:
        discount_pct = BULK_DISCOUNT_TIER_2_PCT
    else:
        discount_pct = BULK_DISCOUNT_TIER_3_PCT
    batch["discount_cents"] = round_half_up(subtotal, discount_pct)
    batch["total_cents"] = batch["subtotal_cents"] - batch["discount_cents"]
    return lines


def batch_live_lines(batch_id):
    """Every line of the batch that has not been cancelled."""
    rows = [o for o in store.media_orders.values()
            if o["order_batch_id"] == batch_id and o["status"] != "CANCELLED"]
    return sorted_rows(rows)


def recompute_line_count(batch):
    """batch_line_count rollup (PRD 2.12): correct at response emission."""
    if batch is None:
        return
    batch["line_count"] = len(batch_live_lines(batch["id"]))


def maybe_reconcile_batch(batch):
    """RELEASED -> RECONCILED bubble-up; returns True when it fired."""
    if batch is None or batch["status"] != "RELEASED":
        return False
    if batch["line_count"] < 1:
        return False
    rows = [o for o in store.media_orders.values() if o["order_batch_id"] == batch["id"]]
    if not rows:
        return False
    if all(o["status"] in ("DELIVERED", "CANCELLED") for o in rows):
        batch["status"] = "RECONCILED"
        return True
    return False


# ----------------------------------------------- payroll charge rollup (3.9)
def payroll_rollup(payroll_file):
    scope = []
    for election in store.elections.values():
        if election["funding_status"] not in ("FUNDED", "SETTLED"):
            continue
        window = store.election_windows.get(election["election_window_id"])
        if window is None:
            continue
        if window["employer_id"] != payroll_file["employer_id"]:
            continue
        if window["benefit_month"] != payroll_file["period_month"]:
            continue
        scope.append(election)

    participants = set(e["employee_id"] for e in scope)
    participant_count = len(participants)
    total_pretax = sum(e["excluded_amount_cents"] for e in scope)
    total_posttax = sum(e["posttax_effective_cents"] for e in scope)

    admin_fee = max(ADMIN_FEE_MINIMUM_CENTS,
                    participant_count * ADMIN_FEE_PER_PARTICIPANT_CENTS)
    pre_waiver = total_pretax + total_posttax + admin_fee
    if pre_waiver < FEE_WAIVER_TIER_2_MIN_CENTS:
        waiver_pct = Decimal(0)
    elif pre_waiver < FEE_WAIVER_TIER_3_MIN_CENTS:
        waiver_pct = Decimal(25)
    else:
        waiver_pct = Decimal(50)
    fee_waiver = round_half_up(admin_fee, waiver_pct)

    payroll_file["participant_count"] = participant_count
    payroll_file["total_pretax_cents"] = total_pretax
    payroll_file["total_posttax_cents"] = total_posttax
    payroll_file["admin_fee_cents"] = admin_fee
    payroll_file["pre_waiver_charge_cents"] = pre_waiver
    payroll_file["fee_waiver_cents"] = fee_waiver
    payroll_file["employer_charge_cents"] = pre_waiver - fee_waiver


# --------------------------------------------- ordinance assessment (3.9)
def month_end_instant(month_string):
    year, month = parse_month(month_string)
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return nxt - timedelta(milliseconds=1)


def assess_ordinance(employer, assessment_month):
    boundary = month_end_instant(assessment_month)
    covered = 0
    for employee in store.employees.values():
        if employee["employer_id"] != employer["id"]:
            continue
        if employee["status"] != "ACTIVE":
            continue
        if employee["work_region_code"] != employer["region_code"]:
            continue
        hired = employee["_hire_date"]
        if hired is not None and hired <= boundary:
            covered += 1

    qualifying = 0
    for category in store.benefit_categories.values():
        if category["employer_id"] != employer["id"]:
            continue
        if category["status"] != "ACTIVE":
            continue
        if not category["pretax_allowed"]:
            continue
        if category["category_type"] in TRANSIT_CATEGORY_TYPES:
            qualifying += 1

    if employer["region_code"] not in COVERED_REGION_CODES:
        mandate_status = "EXEMPT"
        finding = "EXEMPT_REGION_NOT_COVERED"
    elif covered < ORDINANCE_EMPLOYEE_THRESHOLD:
        mandate_status = "EXEMPT"
        finding = "EXEMPT_BELOW_THRESHOLD"
    elif qualifying == 0:
        mandate_status = "MANDATED_NONCOMPLIANT"
        finding = "DEFICIENT_NO_QUALIFYING_TRANSIT_OFFERING"
    elif employer["transit_group_limit_cents"] < ORDINANCE_MINIMUM_TRANSIT_LIMIT_CENTS:
        mandate_status = "MANDATED_NONCOMPLIANT"
        finding = "DEFICIENT_LIMIT_BELOW_MINIMUM"
    else:
        mandate_status = "MANDATED_COMPLIANT"
        finding = "COMPLIANT"

    return {
        "covered_employee_count": covered,
        "qualifying_transit_offering_count": qualifying,
        "assessed_transit_group_limit_cents": employer["transit_group_limit_cents"],
        "mandate_status": mandate_status,
        "finding": finding,
    }


# ------------------------------------------ card transaction posture (3.7)
def allowed_mcc_set(category):
    if category["limit_group"] == "TRANSIT":
        return TRANSIT_MCC_SET
    return PARKING_MCC_SET


def substantiation_posture(category, amount_cents, merchant_category_code):
    """Returns (substantiation_status, posted_spend_cents)."""
    if merchant_category_code not in allowed_mcc_set(category):
        return "INELIGIBLE", 0
    if amount_cents <= AUTO_SUBSTANTIATION_CEILING_CENTS:
        return "AUTO_SUBSTANTIATED", amount_cents
    return "PENDING_DOCS", amount_cents


# ------------------------------------------------- media replacement fee (3.6)
def replacement_fee(media_order, transit_media, waive):
    if waive:
        return 0
    if media_order["replacement_count"] == 0:
        return transit_media["replacement_fee_cents"]
    return transit_media["replacement_fee_cents"] * REISSUE_FEE_ESCALATION_MULTIPLIER


# ------------------------------------------------------- month close (3.8)
def close_account(account, employer, employee):
    """Compute and apply the close deltas for one account.

    Returns True when the account row was actually mutated.
    """
    unused = account["available_balance_cents"]
    if employee is not None and employee["status"] == "TERMINATED":
        rollover_out = 0
        terminated_at = employee["_termination_date"]
        if terminated_at is None:
            days = 0
        else:
            delta = store.clock_now() - terminated_at
            days = int(delta.total_seconds() // SECONDS_PER_DAY)
        if days <= employer["forfeiture_grace_days"]:
            refunded_delta = unused
            forfeited_delta = 0
        else:
            refunded_delta = 0
            forfeited_delta = unused
    else:
        policy = employer["rollover_policy"]
        if policy == "NO_ROLLOVER":
            rollover_out = 0
        elif policy == "FULL_ROLLOVER":
            rollover_out = unused
        else:
            rollover_out = min(unused, employer["rollover_cap_cents"])
        forfeited_delta = unused - rollover_out
        refunded_delta = 0

    if forfeited_delta <= 0 and refunded_delta <= 0:
        return False

    if forfeited_delta > 0:
        account["forfeited_cents"] += forfeited_delta
        post_entry(account, "FORFEITURE", -forfeited_delta, "BenefitAccount",
                   account["id"], "Unused benefit dollars forfeited at month close.")
    if refunded_delta > 0:
        account["refunded_cents"] += refunded_delta
        post_entry(account, "REFUND", -refunded_delta, "BenefitAccount",
                   account["id"],
                   "Unused benefit dollars refunded to the employer under the "
                   "termination grace rule.")
    recompute_available(account)
    return True


def accounts_of_employer(employer_id):
    rows = []
    for account in store.benefit_accounts.values():
        category = store.benefit_categories.get(account["benefit_category_id"])
        if category is not None and category["employer_id"] == employer_id:
            rows.append(account)
    return sorted_rows(rows)


def resolve_account_for(employee_id, benefit_category_id):
    for account in store.benefit_accounts.values():
        if account["employee_id"] == employee_id and \
                account["benefit_category_id"] == benefit_category_id:
            return account
    return None


def parse_clock_iso(value):
    return parse_iso8601(value)
