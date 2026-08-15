"""Rental billing: dual-variant charges, demurrage tiers, billing runs, credit
limits, credit-hold cascades, and ledger conservation (PRD §3.5, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_test_billing_run,
    create_test_customer,
    create_test_cylinder,
    create_test_installation,
    create_test_rental,
    finalize_test_billing_run,
    get_customer,
    get_installation,
    get_rental,
    post_test_billing_run,
    post_test_payment,
    return_test_rental,
    set_installation_status,
    set_logical_clock,
    setup_released_lot,
    validate_error,
    validate_success,
)

BC = TEST_USERS["billing_clerk_headers"]
PM = TEST_USERS["plant_manager_headers"]


def _two_variant_customers():
    cal = create_test_customer(
        account_name="C-CAL", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=100000,
    )
    grp = create_test_customer(
        account_name="C-GRP", billing_variant="GRACE_PERIOD", free_days=3,
        credit_limit_cents=100000,
    )
    return cal, grp


def _rent_and_return(customer, cylinder, rate=1000, planned=5, clock_to=None):
    rental = create_test_rental(
        customer["id"], cylinder["id"], daily_rate_cents=rate, planned_days=planned
    )
    if clock_to:
        set_logical_clock(clock_to)
    returned = return_test_rental(rental["id"])
    return rental, returned


# --- Difficulty: dual_variant_calc / rental_charge_calendar_vs_grace_divergence ---

def test_return_charge_calendar_day_variant(api):
    """PRD §3.5: "Under `CALENDAR_DAY` the base is the daily rate multiplied by
    the days out — every out day bills."
    PRD §3.5: "The final charge closes the rental out: the billing-variant base
    over the days out, plus demurrage accrued through the return date, minus the
    `demurrage_billed_cents` already charged by billing runs, floored at zero,
    and stored in `final_charge_cents`."

    Design: Difficulty/dual_variant_calc/rental_charge_calendar_vs_grace_divergence
    """
    ctx = setup_released_lot(num_cylinders=2)
    cal, grp = _two_variant_customers()
    rental, returned = _rent_and_return(cal, ctx["cylinders"][0], clock_to="2026-08-10T00:00:00Z")
    assert returned["status"] == "RETURNED"
    assert returned["final_charge_cents"] == 13000, (
        "9 days out x 1000 base + 4 overdue days x 1000 tier-1 demurrage"
    )
    assert get_customer(cal["id"])["outstanding_balance_cents"] == 13000


def test_return_charge_grace_period_variant(api):
    """PRD §3.5: "Under `GRACE_PERIOD` the base is the daily rate multiplied by
    the days out minus `free_days`, floored at zero — nine days out with three
    free days bills six days, not nine."

    Design: Difficulty/dual_variant_calc/rental_charge_calendar_vs_grace_divergence
    """
    ctx = setup_released_lot(num_cylinders=2)
    cal, grp = _two_variant_customers()
    rental, returned = _rent_and_return(grp, ctx["cylinders"][1], clock_to="2026-08-10T00:00:00Z")
    assert returned["final_charge_cents"] == 10000, (
        "max(0, 9 - 3) x 1000 base + 4000 demurrage = 10000, diverging by "
        "exactly 3000 cents from the CALENDAR_DAY twin"
    )
    assert get_customer(grp["id"])["outstanding_balance_cents"] == 10000


# --- Difficulty: combinatorial_formula / demurrage_tier_straddle_marginal_rates ---

def test_demurrage_nine_days_straddles_tier_boundary(api):
    """PRD §3.6: "Each overdue day bills by tier: indices 1 through 7 at one
    times the daily rate, indices 8 through 30 at one and a half times, and index
    31 onward at twice the daily rate. Each tier segment is rounded half-up to
    whole cents on its own — segment days times daily rate times multiplier — and
    a rental's charge line is the sum of its already-rounded segments, never
    rounded again."

    Design: Difficulty/combinatorial_formula/demurrage_tier_straddle_marginal_rates
    """
    ctx = setup_released_lot(num_cylinders=1)
    customer = create_test_customer(account_name="C-CF1", credit_limit_cents=100000)
    rental = create_test_rental(
        customer["id"], ctx["cylinders"][0]["id"], daily_rate_cents=1000,
        planned_days=2,
    )
    set_logical_clock("2026-08-12T00:00:00Z")
    returned = return_test_rental(rental["id"])
    # 11 days out (base 11000) + 9 overdue days: 7*1000*1.0 + 2*1000*1.5 = 10000.
    assert returned["final_charge_cents"] == 21000


def test_demurrage_marginal_tier_not_applied_retroactively(api):
    """PRD §3.6: "Each overdue day bills by tier: indices 1 through 7 at one
    times the daily rate, indices 8 through 30 at one and a half times, and index
    31 onward at twice the daily rate."
    The marginal tier applies only to days 8..9; a flat retroactive reading of
    9 x 1500 would bill 13500 demurrage and a 24500 total, which the tiered rule
    forbids.

    Design: Difficulty/combinatorial_formula/demurrage_tier_straddle_marginal_rates
    """
    ctx = setup_released_lot(num_cylinders=1)
    customer = create_test_customer(account_name="C-CF1B", credit_limit_cents=100000)
    rental = create_test_rental(
        customer["id"], ctx["cylinders"][0]["id"], daily_rate_cents=1000,
        planned_days=2,
    )
    set_logical_clock("2026-08-12T00:00:00Z")
    returned = return_test_rental(rental["id"])
    base = 11 * 1000
    demurrage = returned["final_charge_cents"] - base
    assert demurrage == 10000, "demurrage portion proves the 7x1.0 + 2x1.5 split"
    assert returned["final_charge_cents"] != 24500, (
        "a retroactive 1.5x reading of all 9 days is not the PRD rule"
    )


# --- Difficulty: combinatorial_formula / billing_run_per_line_rounding_order ---

def _setup_two_333_rentals():
    ctx = setup_released_lot(num_cylinders=2)
    customer = create_test_customer(
        account_name="C-CF2", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=500000,
    )
    r1 = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=333, planned_days=1)
    r2 = create_test_rental(customer["id"], ctx["cylinders"][1]["id"],
                            daily_rate_cents=333, planned_days=1)
    set_logical_clock("2026-08-10T00:00:00Z")
    run = create_test_billing_run(period_start="2026-08-01", period_end="2026-08-10")
    return ctx, customer, r1, r2, run


def test_billing_run_rounds_per_line_then_sums(api):
    """PRD §3.6: "`total_charges_cents` is the plain sum of the per-line values
    with no further rounding — sum-then-round is forbidden, so two rentals at 333
    cents per day, each eight days overdue, total 2831 plus 2831 equals 5662
    cents, never 5661."

    Design: Difficulty/combinatorial_formula/billing_run_per_line_rounding_order
    """
    ctx, customer, r1, r2, run = _setup_two_333_rentals()
    finalized = finalize_test_billing_run(run["id"])
    assert finalized["status"] == "FINALIZED"
    lines = finalized["charge_lines"]
    assert len(lines) == 2
    for line in lines:
        assert line["demurrage_cents"] == 2831, (
            "7*333 + round_half_up(1*333*1.5) = 2331 + 500 per line"
        )
    assert finalized["total_charges_cents"] == 5662


def test_finalize_sweeps_overdue_and_advances_billed_through(api):
    """PRD §3.6: "First, the overdue checkpoint: every rental still `ACTIVE`
    whose `due_date` is strictly earlier than the logical clock date moves to
    `OVERDUE`. This finalize sweep is the only place rentals go overdue; reads
    never transition them lazily."
    PRD §3.6: "Every accrued rental has its `billed_through_date` advanced to
    `period_end` and its `demurrage_billed_cents` increased by its line amount"

    Design: Difficulty/combinatorial_formula/billing_run_per_line_rounding_order
    """
    ctx, customer, r1, r2, run = _setup_two_333_rentals()
    finalize_test_billing_run(run["id"])
    for rental in (r1, r2):
        after = get_rental(rental["id"])
        assert after["status"] == "OVERDUE", "due 2026-08-02 < clock 2026-08-10"
        assert after["billed_through_date"] == "2026-08-10"
        assert after["demurrage_billed_cents"] == 2831


# --- Difficulty: boundary_precision_check / credit_limit_exact_equality_allowed ---

def _setup_credit_equality():
    """Customer limit 16000 with 8000 outstanding; two FILLED cylinders spare."""
    ctx = setup_released_lot(num_cylinders=3)
    customer = create_test_customer(
        account_name="C-BP2", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=16000,
    )
    r1 = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=1000, planned_days=8)
    set_logical_clock("2026-08-09T00:00:00Z")
    returned = return_test_rental(r1["id"])
    assert returned["final_charge_cents"] == 8000, "8 days out, due today: no overdue"
    assert get_customer(customer["id"])["outstanding_balance_cents"] == 8000
    return ctx, customer


def test_checkout_at_exact_credit_equality_allowed(api):
    """PRD §3.5: "the credit check must pass: the account's
    `outstanding_balance_cents` plus the estimated charge — the customer's
    billing-variant base computed over `planned_days` — must not be strictly
    greater than `credit_limit_cents`, with equality allowed; a breach is
    rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_allowed
    """
    ctx, customer = _setup_credit_equality()
    res = api.create_rental(
        {"customer_id": customer["id"], "cylinder_id": ctx["cylinders"][1]["id"],
         "daily_rate_cents": 1000, "planned_days": 8},
        BC,
    )
    rental = validate_success(res, 201)
    assert rental["status"] == "ACTIVE", "8000 + 8000 == 16000 == limit: allowed"
    assert get_customer(customer["id"])["status"] == "ACTIVE", (
        "an estimate does not move the account onto hold"
    )


def test_checkout_one_day_over_credit_limit_rejected(api):
    """PRD §3.5: "the credit check must pass: the account's
    `outstanding_balance_cents` plus the estimated charge — the customer's
    billing-variant base computed over `planned_days` — must not be strictly
    greater than `credit_limit_cents`, with equality allowed; a breach is
    rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/credit_limit_exact_equality_allowed
    """
    ctx, customer = _setup_credit_equality()
    res = api.create_rental(
        {"customer_id": customer["id"], "cylinder_id": ctx["cylinders"][2]["id"],
         "daily_rate_cents": 1000, "planned_days": 9},
        BC,
    )
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
    after = get_customer(customer["id"])
    assert after["outstanding_balance_cents"] == 8000
    assert after["status"] == "ACTIVE"


# --- Difficulty: priority_pair_validation_conflict / rental_conflict_state_beats_fiscal ---

def _setup_state_vs_fiscal():
    """Customer limit 10000 with 9500 outstanding; one cylinder left IN_STOCK."""
    ctx = setup_released_lot(num_cylinders=1)
    customer = create_test_customer(
        account_name="C-PP3", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=10000,
    )
    r1 = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=500, planned_days=20)
    set_logical_clock("2026-08-20T00:00:00Z")
    returned = return_test_rental(r1["id"])
    assert returned["final_charge_cents"] == 9500, "19 days out, no overdue"
    spare = create_test_cylinder(serial_number="SN-PP3-B")
    assert spare["status"] == "IN_STOCK"
    return customer, spare


def test_checkout_with_unfilled_cylinder_reports_state_error(api):
    """PRD §2.8: "When several checks could reject the same request, the
    rejection reported is the earliest applicable check in the order below — a
    state-gate failure, for instance, masks a hydro-compliance failure that would
    also have fired." (State gates are check 5; the credit limit is check 16.)
    PRD §3.5: "the cylinder must be `FILLED` (else `ERR_CYLINDER_NOT_AVAILABLE`)
    and not hydro-overdue (else `ERR_HYDRO_RETEST_OVERDUE`)"

    Design: Difficulty/priority_pair_validation_conflict/rental_conflict_state_beats_fiscal
    """
    customer, spare = _setup_state_vs_fiscal()
    res = api.create_rental(
        {"customer_id": customer["id"], "cylinder_id": spare["id"],
         "daily_rate_cents": 1000, "planned_days": 10},
        BC,
    )
    # state (check 5) masks the credit breach (check 16): 9500 + 10000 > 10000
    validate_error(res, ApiErrorId.ERR_CYLINDER_NOT_AVAILABLE.value)


def test_rejected_checkout_leaves_outstanding_unchanged(api):
    """PRD §2.8: "When several checks could reject the same request, the
    rejection reported is the earliest applicable check in the order below"
    PRD §3.5: "a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`" — and a
    rejected checkout posts nothing.

    Design: Difficulty/priority_pair_validation_conflict/rental_conflict_state_beats_fiscal
    """
    customer, spare = _setup_state_vs_fiscal()
    res = api.create_rental(
        {"customer_id": customer["id"], "cylinder_id": spare["id"],
         "daily_rate_cents": 1000, "planned_days": 10},
        BC,
    )
    validate_error(res, ApiErrorId.ERR_CYLINDER_NOT_AVAILABLE.value)
    after = get_customer(customer["id"])
    assert after["outstanding_balance_cents"] == 9500, (
        "19 days x 500 from the returned rental, unchanged by the rejection"
    )
    assert after["status"] == "ACTIVE"


# --- Difficulty: cross_entity_state_dependency / rental_requires_customer_active_not_credit_hold ---

def _setup_credit_hold_customer():
    """Customer limit 5000 driven to CREDIT_HOLD by a 14000-cent return charge."""
    ctx = setup_released_lot(num_cylinders=2)
    customer = create_test_customer(
        account_name="C-CE2", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=5000,
    )
    r1 = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=1000, planned_days=4)
    set_logical_clock("2026-08-10T00:00:00Z")
    returned = return_test_rental(r1["id"])
    # 9 days out (9000) + 5 overdue days (5000) = 14000 > 5000 -> CREDIT_HOLD.
    assert returned["final_charge_cents"] == 14000
    assert get_customer(customer["id"])["status"] == "CREDIT_HOLD"
    return ctx, customer


def test_checkout_blocked_on_credit_hold(api):
    """PRD §3.5: "Entering `CREDIT_HOLD` blocks new rentals and new blend orders
    with `ERR_ACCOUNT_NOT_ACTIVE` and cascades to the customer's bulk
    installations, moving every `ACTIVE` one to `PAUSED`; leaving the hold does
    not auto-resume those installations — an operator resumes them explicitly."
    PRD §3.5: "The customer must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/rental_requires_customer_active_not_credit_hold
    """
    ctx, customer = _setup_credit_hold_customer()
    res = api.create_rental(
        {"customer_id": customer["id"], "cylinder_id": ctx["cylinders"][1]["id"],
         "daily_rate_cents": 1000, "planned_days": 1},
        BC,
    )
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_payment_releasing_hold_reenables_checkout(api):
    """PRD §3.5: "A `CREDIT_HOLD` account returns to `ACTIVE` once its balance
    falls to at most 80% of the credit limit, with that release threshold rounded
    half-up to whole cents — equality at the release point does release."
    PRD §3.5: "a payment carries an `amount_cents` greater than zero, subtracts
    it from `outstanding_balance_cents`, and may drive the balance to zero but
    never below it — an amount exceeding the outstanding balance is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Difficulty/cross_entity_state_dependency/rental_requires_customer_active_not_credit_hold
    """
    ctx, customer = _setup_credit_hold_customer()
    post_test_payment(customer["id"], 14000)
    released = get_customer(customer["id"])
    assert released["outstanding_balance_cents"] == 0
    assert released["status"] == "ACTIVE", "0 <= 80% of 5000 releases the hold"

    res = api.create_rental(
        {"customer_id": customer["id"], "cylinder_id": ctx["cylinders"][1]["id"],
         "daily_rate_cents": 1000, "planned_days": 1},
        BC,
    )
    rental = validate_success(res, 201)
    assert rental["status"] == "ACTIVE"


# --- Difficulty: compensating_invariant / ledger_post_then_equal_payment_conserved ---

def _setup_ledger_pair():
    """Customer limit 20000; r1 (1000/day, planned 10) returned for 9000; r2
    (333/day, planned 1) accrues a 2831-cent line on the 08-01..08-10 run."""
    ctx = setup_released_lot(num_cylinders=2)
    customer = create_test_customer(
        account_name="C-CI2", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=20000,
    )
    r1 = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=1000, planned_days=10)
    r2 = create_test_rental(customer["id"], ctx["cylinders"][1]["id"],
                            daily_rate_cents=333, planned_days=1)
    set_logical_clock("2026-08-10T00:00:00Z")
    returned = return_test_rental(r1["id"])
    assert returned["final_charge_cents"] == 9000, "9 days out, due 08-11: no overdue"
    run = create_test_billing_run(period_start="2026-08-01", period_end="2026-08-10")
    finalize_test_billing_run(run["id"])
    return ctx, customer, r1, r2, run


def test_billing_post_adds_lines_to_outstanding(api):
    """PRD §3.6: "Each customer's `outstanding_balance_cents` increases by the
    sum of that customer's lines; any customer thereby pushed strictly over its
    credit limit moves to `CREDIT_HOLD`, and each customer newly on hold has all
    of its `ACTIVE` bulk installations moved to `PAUSED`."

    Design: Difficulty/compensating_invariant/ledger_post_then_equal_payment_conserved
    """
    ctx, customer, r1, r2, run = _setup_ledger_pair()
    pre = get_customer(customer["id"])
    assert pre["outstanding_balance_cents"] == 9000
    posted = post_test_billing_run(run["id"])
    assert posted["status"] == "POSTED"
    after = get_customer(customer["id"])
    assert after["outstanding_balance_cents"] == 11831, "9000 + 2831 posted line"
    assert after["status"] == "ACTIVE", "11831 <= 20000: no hold"


def test_equal_payment_restores_pre_post_balance(api):
    """PRD §3.5: "a payment carries an `amount_cents` greater than zero,
    subtracts it from `outstanding_balance_cents`, and may drive the balance to
    zero but never below it — an amount exceeding the outstanding balance is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Difficulty/compensating_invariant/ledger_post_then_equal_payment_conserved
    """
    ctx, customer, r1, r2, run = _setup_ledger_pair()
    post_test_billing_run(run["id"])
    assert get_customer(customer["id"])["outstanding_balance_cents"] == 11831
    post_test_payment(customer["id"], 2831)
    after = get_customer(customer["id"])
    assert after["outstanding_balance_cents"] == 9000, (
        "post of 2831 paired with a payment of exactly 2831 conserves the balance"
    )
    assert after["status"] == "ACTIVE"


# --- Difficulty: transitive_cascade / billing_post_credit_hold_cascade_depth3 ---

def _setup_billing_cascade():
    """Customer limit 10000: r1 returned for 9000, r2 accrues 2831; an ACTIVE
    bulk installation rides the credit-hold cascade."""
    ctx = setup_released_lot(num_cylinders=2)
    customer = create_test_customer(
        account_name="C-TC3", billing_variant="CALENDAR_DAY", free_days=0,
        credit_limit_cents=10000,
    )
    r1 = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                            daily_rate_cents=1000, planned_days=10)
    r2 = create_test_rental(customer["id"], ctx["cylinders"][1]["id"],
                            daily_rate_cents=333, planned_days=1)
    inst = create_test_installation(customer["id"])
    set_installation_status(inst["id"], "INSTALLED")
    set_installation_status(inst["id"], "ACTIVE")
    set_logical_clock("2026-08-10T00:00:00Z")
    return_test_rental(r1["id"])
    run = create_test_billing_run(period_start="2026-08-01", period_end="2026-08-10")
    finalize_test_billing_run(run["id"])
    return ctx, customer, r1, r2, inst, run


def test_billing_post_pushes_customer_into_credit_hold(api):
    """PRD §3.6: "Each customer's `outstanding_balance_cents` increases by the
    sum of that customer's lines; any customer thereby pushed strictly over its
    credit limit moves to `CREDIT_HOLD`, and each customer newly on hold has all
    of its `ACTIVE` bulk installations moved to `PAUSED`."
    PRD §3.5: "An `ACTIVE` account whose outstanding balance becomes strictly
    greater than its credit limit moves to `CREDIT_HOLD` — equality at the limit
    does not trigger the hold."

    Design: Difficulty/transitive_cascade/billing_post_credit_hold_cascade_depth3
    """
    ctx, customer, r1, r2, inst, run = _setup_billing_cascade()
    posted = post_test_billing_run(run["id"])
    assert posted["status"] == "POSTED"
    after = get_customer(customer["id"])
    assert after["outstanding_balance_cents"] == 11831, "9000 + 2831"
    assert after["status"] == "CREDIT_HOLD", "11831 > 10000 trips the hold"
    assert get_rental(r2["id"])["status"] == "OVERDUE"


def test_credit_hold_cascade_pauses_active_installations(api):
    """PRD §3.6: "each customer newly on hold has all of its `ACTIVE` bulk
    installations moved to `PAUSED`."
    PRD §3.8: "The credit cascade lands here too: when a customer enters
    `CREDIT_HOLD`, every one of its `ACTIVE` installations moves to `PAUSED`, and
    a later release from the hold does not resume them."

    Design: Difficulty/transitive_cascade/billing_post_credit_hold_cascade_depth3
    """
    ctx, customer, r1, r2, inst, run = _setup_billing_cascade()
    assert get_installation(inst["id"])["status"] == "ACTIVE"
    post_test_billing_run(run["id"])
    inst_after = get_installation(inst["id"])
    assert inst_after["status"] == "PAUSED", "link 3 of the billing-post cascade"
    rental_after = get_rental(r2["id"])
    assert rental_after["demurrage_billed_cents"] == 2831
    assert rental_after["billed_through_date"] == "2026-08-10"


# --- Corner: state_machines / rental_double_return_rejected ---

def test_rental_double_return_rejected(api):
    """PRD §3.5: "Returning a cylinder carries a `return_condition` of `OK` or
    `DAMAGED` and is permitted while the rental is `ACTIVE`, `OVERDUE`, or
    `RECALL_HOLD`; any other state is rejected with `ERR_RENTAL_NOT_ACTIVE`."

    Design: Corner/state_machines/rental_double_return_rejected
    """
    ctx = setup_released_lot(num_cylinders=1)
    customer = create_test_customer(account_name="C-SM4", credit_limit_cents=100000)
    rental = create_test_rental(customer["id"], ctx["cylinders"][0]["id"],
                                daily_rate_cents=1000, planned_days=3)
    set_logical_clock("2026-08-04T00:00:00Z")
    returned = return_test_rental(rental["id"])
    assert returned["status"] == "RETURNED"
    assert returned["final_charge_cents"] == 3000, "3 days out, due today: no overdue"

    res = api.return_rental(rental["id"], {"return_condition": "OK"}, BC)
    validate_error(res, ApiErrorId.ERR_RENTAL_NOT_ACTIVE.value)
    assert get_customer(customer["id"])["outstanding_balance_cents"] == 3000, (
        "the rejected second return posts no additional charge"
    )


# --- Corner: state_machines / billing_run_post_before_finalize_rejected ---

def test_billing_run_post_before_finalize_rejected(api):
    """PRD §3.6: "Posting a run — permitted only from `FINALIZED`, else
    `ERR_BILLING_RUN_INVALID_STATE` — lands it in `POSTED`, terminal, and fires
    the financial cascade."

    Design: Corner/state_machines/billing_run_post_before_finalize_rejected
    """
    run = create_test_billing_run(period_start="2026-08-01", period_end="2026-08-10")
    assert run["status"] == "DRAFT"
    res = api.post_billing_run(run["id"], BC)
    validate_error(res, ApiErrorId.ERR_BILLING_RUN_INVALID_STATE.value)
    after = validate_success(api_client.get_billing_run(run["id"], BC), 200)
    assert after["status"] == "DRAFT"
    assert not after.get("charge_lines"), "charge lines are computed at finalize"


# --- Corner: consistency_model / immediate_read_after_write_visibility ---

def test_customer_write_then_read_consistent_and_overpayment_rejected(api):
    """PRD §2.10: "The server performs these reconciliations immediately as part
    of the triggering operation; no lazy transitions occur on later reads."
    PRD §3.5: "A new account is `ACTIVE` with `outstanding_balance_cents` at zero
    and `recall_flag` false."
    PRD §3.5: "an amount exceeding the outstanding balance is rejected with
    `ERR_INVALID_REQUEST`"

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    created = validate_success(
        api.create_customer(
            {"account_name": "C-CM1", "billing_variant": "GRACE_PERIOD",
             "free_days": 3, "credit_limit_cents": 50000},
            BC,
        ),
        201,
    )
    assert created["status"] == "ACTIVE"
    assert created["outstanding_balance_cents"] == 0
    assert created["recall_flag"] is False
    assert created["version"] == 1

    fetched = get_customer(created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["version"] == created["version"] == 1
    assert fetched["outstanding_balance_cents"] == 0

    res = api.post_payment(created["id"], {"amount_cents": 1}, BC)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
    after = get_customer(created["id"])
    assert after["version"] == 1, "a rejected payment mutates nothing"
    assert after["outstanding_balance_cents"] == 0
