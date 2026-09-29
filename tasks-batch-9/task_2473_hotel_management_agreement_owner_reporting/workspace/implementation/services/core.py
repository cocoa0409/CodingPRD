"""Shared lookups, cascades and side-effect helpers."""

from db import by_seq, new_row, store, touch
from errors import ApiError
from money import as_json_number
from services import calc
from timeutil import add_days_iso, cmp_iso, month_start_iso

APPROVED_EQUIVALENT = ("APPROVED", "DEEMED_APPROVED", "DEADLOCK_CARRYFORWARD")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def find_agreement(agreement_id):
    row = store.agreements.get(agreement_id)
    if row is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return row


def find_budget(budget_id):
    row = store.budgets.get(budget_id)
    if row is None:
        raise ApiError("ERR_BUDGET_NOT_FOUND")
    return row


def find_package(package_id):
    row = store.report_packages.get(package_id)
    if row is None:
        raise ApiError("ERR_PACKAGE_NOT_FOUND")
    return row


def find_variance(variance_id):
    row = store.variance_requests.get(variance_id)
    if row is None:
        raise ApiError("ERR_VARIANCE_NOT_FOUND")
    return row


def find_charge(charge_id):
    row = store.charges.get(charge_id)
    if row is None:
        raise ApiError("ERR_CHARGE_NOT_FOUND")
    return row


def find_distribution(distribution_id):
    row = store.distributions.get(distribution_id)
    if row is None:
        raise ApiError("ERR_DISTRIBUTION_NOT_FOUND")
    return row


def find_call(call_id):
    row = store.working_capital_calls.get(call_id)
    if row is None:
        raise ApiError("ERR_CALL_NOT_FOUND")
    return row


def find_test(test_id):
    row = store.performance_tests.get(test_id)
    if row is None:
        raise ApiError("ERR_TEST_NOT_FOUND")
    return row


def find_dispute(dispute_id):
    row = store.brand_disputes.get(dispute_id)
    if row is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND")
    return row


def find_claim(claim_id):
    row = store.employment_claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return row


def agreement_of_package(package):
    return store.agreements.get(package["agreement_id"])


def require_active(agreement):
    """Precedence rule 18."""
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")


def require_active_or_cure(agreement):
    if agreement["status"] not in ("ACTIVE", "CURE_PERIOD"):
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")


def charges_of(package_id):
    return by_seq([c for c in store.charges.values() if c["report_package_id"] == package_id])


def accruals_of(package_id):
    return by_seq([a for a in store.fee_accruals.values() if a["report_package_id"] == package_id])


def benchmarks_of(package_id):
    return by_seq([b for b in store.benchmarks.values() if b["report_package_id"] == package_id])


def distributions_of(package_id):
    return by_seq([d for d in store.distributions.values() if d["report_package_id"] == package_id])


def packages_of(agreement_id):
    return by_seq([p for p in store.report_packages.values() if p["agreement_id"] == agreement_id])


def budgets_of(agreement_id):
    return by_seq([b for b in store.budgets.values() if b["agreement_id"] == agreement_id])


def calls_of(agreement_id):
    return by_seq(
        [c for c in store.working_capital_calls.values() if c["agreement_id"] == agreement_id]
    )


def reserve_entries_of(agreement_id):
    return by_seq([e for e in store.reserve_entries.values() if e["agreement_id"] == agreement_id])


def distributions_of_agreement(agreement_id):
    rows = []
    package_ids = {p["id"] for p in store.report_packages.values() if p["agreement_id"] == agreement_id}
    for dist in store.distributions.values():
        if dist["report_package_id"] in package_ids:
            rows.append(dist)
    return by_seq(rows)


def approved_equivalent_budget_exists(agreement_id, fiscal_year, exclude_id=None):
    for budget in store.budgets.values():
        if budget["agreement_id"] != agreement_id:
            continue
        if budget["fiscal_year"] != fiscal_year:
            continue
        if exclude_id is not None and budget["id"] == exclude_id:
            continue
        if budget["status"] in APPROVED_EQUIVALENT:
            return budget
    return None


def select_budget_for_year(agreement_id, fiscal_year):
    """Eligibility filter, then rank by (revision_round DESC, created_at DESC)."""
    candidates = [
        b
        for b in store.budgets.values()
        if b["agreement_id"] == agreement_id
        and b["fiscal_year"] == fiscal_year
        and b["status"] in APPROVED_EQUIVALENT
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b["revision_round"], b["_seq"]), reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# package derived fields and rollup
# ---------------------------------------------------------------------------

def refresh_package_status(package):
    package["package_status"] = calc.package_status_rollup(
        package["financial_status"], package["benchmark_status"]
    )


def recompute_centralized_allocation(package, agreement):
    """Full recompute over every charge of the package (never incremental)."""
    cap = calc.centralized_cap_cents(
        package["gross_revenue_cents"], agreement["centralized_services_cap_pct"]
    )
    charges = sorted(charges_of(package["id"]), key=calc.charge_sort_key)
    remaining = cap
    for charge in charges:
        requested = calc.charge_requested_amount(
            charge["pool_amount_cents"], charge["hotel_basis_share"]
        )
        if charge["disclosure_status"] == "ADJUSTED":
            allocated = charge["adjusted_amount_cents"] or 0
        else:
            allocated = min(requested, max(0, remaining))
        deferred = requested - allocated
        changed = (
            charge["requested_amount_cents"] != requested
            or charge["allocated_amount_cents"] != allocated
            or charge["deferred_amount_cents"] != deferred
        )
        charge["requested_amount_cents"] = requested
        charge["allocated_amount_cents"] = allocated
        charge["deferred_amount_cents"] = deferred
        remaining = remaining - allocated
        if changed:
            touch(charge)
    package["allocated_centralized_cents"] = sum(
        c["allocated_amount_cents"] for c in charges
    )
    return charges


def freeze_package_financials(package, agreement):
    """The pinned five-step evaluation order of agop_and_provisional_incentive."""
    # 1. centralized allocation (cap keyed on gross revenue)
    recompute_centralized_allocation(package, agreement)
    # 2. base management fee (per revenue line, then summed)
    package["base_fee_cents"] = calc.base_management_fee_per_line(
        package["rooms_revenue_cents"],
        package["fnb_revenue_cents"],
        package["other_revenue_cents"],
        agreement["base_fee_pct"],
    )
    # 3. AGOP
    package["agop_cents"] = calc.agop_cents(
        package["gross_revenue_cents"],
        package["operating_expenses_cents"],
        package["base_fee_cents"],
        package["allocated_centralized_cents"],
    )
    # 4. monthly owner priority
    monthly_priority = calc.monthly_priority_cents(agreement["owner_priority_cents"])
    # 5. provisional incentive fee
    package["incentive_fee_provisional_cents"] = calc.provisional_incentive_cents(
        package["agop_cents"], monthly_priority, agreement["incentive_fee_pct"]
    )


def create_accrual_set(package):
    """A fresh ACCRUED set is raised at every financial submit."""
    created = []
    created.append(
        _new_accrual(package, "BASE", "PROVISIONAL", package["base_fee_cents"])
    )
    if package["allocated_centralized_cents"] != 0:
        created.append(
            _new_accrual(
                package,
                "CENTRALIZED_SERVICES",
                "PROVISIONAL",
                package["allocated_centralized_cents"],
            )
        )
    if package["incentive_fee_provisional_cents"] != 0:
        created.append(
            _new_accrual(
                package,
                "INCENTIVE",
                "PROVISIONAL",
                package["incentive_fee_provisional_cents"],
            )
        )
    return created


def _new_accrual(package, fee_type, variant, amount_cents):
    accrual = new_row(
        {
            "report_package_id": package["id"],
            "fee_type": fee_type,
            "variant": variant,
            "fiscal_year": package["fiscal_year"],
            "period_month": package["period_month"],
            "amount_cents": amount_cents,
            "status": "ACCRUED",
            "paid_amount_cents": 0,
        }
    )
    store.fee_accruals[accrual["id"]] = accrual
    return accrual


# ---------------------------------------------------------------------------
# working capital calls
# ---------------------------------------------------------------------------

def create_working_capital_call(agreement, amount_cents, reason, auto_created):
    call = new_row(
        {
            "agreement_id": agreement["id"],
            "amount_cents": amount_cents,
            "reason": reason,
            "status": "REQUESTED",
            "due_date_utc": add_days_iso(store.now_iso, agreement["funding_due_days"]),
            "funded_amount_cents": 0,
            "late_funded": False,
            "auto_created": auto_created,
        }
    )
    store.working_capital_calls[call["id"]] = call
    return call


# ---------------------------------------------------------------------------
# reserve ledger
# ---------------------------------------------------------------------------

def append_reserve_entry(agreement, entry_type, amount_cents, source_kind, memo):
    running = sum(e["amount_cents"] for e in reserve_entries_of(agreement["id"]))
    entry = new_row(
        {
            "agreement_id": agreement["id"],
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "balance_after_cents": running + amount_cents,
            "source_kind": source_kind,
            "memo": memo,
        },
        common=False,
    )
    store.reserve_entries[entry["id"]] = entry
    agreement["ffe_reserve_balance_cents"] = agreement["ffe_reserve_balance_cents"] + amount_cents
    touch(agreement)
    return entry


# ---------------------------------------------------------------------------
# the distribution hold cascade (PRD §2.7)
# ---------------------------------------------------------------------------

def raise_distribution_hold(agreement):
    agreement["distribution_hold"] = True
    touch(agreement)
    for dist in distributions_of_agreement(agreement["id"]):
        if dist["status"] == "CALCULATED":
            dist["status"] = "HELD"
            touch(dist)


def release_distribution_hold(agreement):
    agreement["distribution_hold"] = False
    touch(agreement)
    for dist in distributions_of_agreement(agreement["id"]):
        if dist["status"] == "HELD":
            dist["status"] = "CALCULATED"
            touch(dist)


def deny_pending_variances(agreement):
    rows = []
    budget_ids = {b["id"] for b in store.budgets.values() if b["agreement_id"] == agreement["id"]}
    for variance in store.variance_requests.values():
        if variance["budget_id"] in budget_ids and variance["status"] == "PENDING":
            rows.append(variance)
    for variance in by_seq(rows):
        variance["status"] = "DENIED"
        variance["denied_by_cascade"] = True
        touch(variance)


def supersede_submitted_budgets(agreement):
    for budget in budgets_of(agreement["id"]):
        if budget["status"] == "SUBMITTED":
            budget["status"] = "SUPERSEDED"
            touch(budget)


# ---------------------------------------------------------------------------
# cash distribution
# ---------------------------------------------------------------------------

def create_distribution(package, agreement):
    accruals = accruals_of(package["id"])
    available = package["closing_cash_available_cents"]
    wc_gap = max(
        0, agreement["working_capital_floor_cents"] - agreement["working_capital_balance_cents"]
    )
    base_due = sum(
        a["amount_cents"]
        for a in accruals
        if a["fee_type"] == "BASE" and a["status"] == "INVOICED"
    )
    reserve_due = calc.reserve_due_cents(
        package["gross_revenue_cents"], agreement["ffe_reserve_pct"]
    )
    priority_due = calc.monthly_priority_cents(agreement["owner_priority_cents"])
    incent_due = sum(
        a["amount_cents"]
        for a in accruals
        if a["fee_type"] == "INCENTIVE"
        and a["variant"] == "PROVISIONAL"
        and a["status"] == "INVOICED"
    )
    buckets = calc.waterfall(available, wc_gap, base_due, reserve_due, priority_due, incent_due)
    fields = {
        "report_package_id": package["id"],
        "available_cash_cents": available,
    }
    fields.update(buckets)
    fields["status"] = "CALCULATED"
    distribution = new_row(fields)
    store.distributions[distribution["id"]] = distribution
    return distribution


def datetime_at_or_before(clock_iso, deadline_iso):
    """True when the clock is at or before the deadline."""
    if deadline_iso is None:
        return False
    return cmp_iso(clock_iso, deadline_iso) <= 0


def package_due_date(fiscal_year, period_month):
    year, month, day = calc.due_date_parts(fiscal_year, period_month)
    return month_start_iso(year, month, day)


def number_out(value):
    return as_json_number(value) if value is not None else None
