"""Loan servicing: payoff accrual, extension self-loop, renewal re-term,
the lifetime period cap, optimistic-concurrency stale-version, and void-after-serviced."""
from test_helpers import (
    validate_success, validate_error,
    constants,
    factories as f,
    fixtures as fx,
    make_officer_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _ledger(api, loan_id):
    res = api.list_loan_transactions(loan_id, OFFICER)
    return res.json()["data"]


# ── Difficulty: combinatorial payoff — round per period then multiply ──

def test_payoff_round_per_period_then_multiply_per_period_charge(api):
    """PRD §3.4: "The charge for a single period is computed by taking the loan's
    `principal_cents`, multiplying by the schedule's `monthly_interest_bps`, dividing
    by 10000, rounding that interest portion half-up to whole cents, and then adding
    the flat `monthly_storage_fee_cents`."

    Design: Difficulty/combinatorial_formula/payoff_round_per_period_then_multiply_mode_b
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_59)  # 59 days -> ceil(59/30) = 2 live periods
    payoff = validate_success(api.get_loan_payoff(ctx["loan"]["id"], OFFICER), 200)
    # round(20000 * 0.10) = 2000, + 500 storage = 2500 per period.
    assert payoff["per_period_charge_cents"] == 2500
    assert payoff["total_periods"] == 2


def test_payoff_round_per_period_then_multiply_total(api):
    """PRD §3.4: "The payoff is then the loan's `principal_cents` plus the loan's
    snapshotted `setup_fee_cents` plus the total period count multiplied by that
    per-period charge."
    PRD §3.4: "the interest portion is rounded half-up **per period first**, the flat
    storage fee is then added to form the per-period charge, and only then is that
    charge multiplied by the period count and summed with principal and setup fee."

    Design: Difficulty/combinatorial_formula/payoff_round_per_period_then_multiply_mode_b
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_59)
    payoff = validate_success(api.get_loan_payoff(ctx["loan"]["id"], OFFICER), 200)
    # 20000 principal + 200 setup + 2*2500 = 25200.
    assert payoff["payoff_cents"] == 25200


# ── Difficulty: extension self-loop keeps the loan ACTIVE while periods climb ──

def test_extension_self_loop_keeps_loan_active(api):
    """PRD §3.5: "An **extension** keeps the loan `ACTIVE` by buying exactly one more
    finance period."
    PRD §3.5: "Extensions may repeat across many rounds."

    Design: Difficulty/non_linear_state_machine/loan_extension_self_loop_cycle
    """
    ctx = fx.setup_active_loan()
    loan = ctx["loan"]
    after1 = validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(loan["version"]),
        make_officer_headers("officer-1")), 200)
    after2 = validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(after1["version"]),
        make_officer_headers("officer-1")), 200)
    assert after2["status"] == "ACTIVE"


def test_extension_self_loop_increments_periods_charged(api):
    """PRD §3.5: "On success the system appends a `FinanceTransaction` of kind
    `EXTENSION_FEE` with a positive `amount_cents` equal to that one-period fee and
    `periods_in_charge` of 1, increases the drawer's `balance_cents` by the fee,
    increments the loan's `periods_charged` by one".

    Design: Difficulty/non_linear_state_machine/loan_extension_self_loop_cycle
    """
    ctx = fx.setup_active_loan()
    loan = ctx["loan"]
    after1 = validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(loan["version"]),
        make_officer_headers("officer-1")), 200)
    assert after1["periods_charged"] == 1
    after2 = validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(after1["version"]),
        make_officer_headers("officer-1")), 200)
    assert after2["periods_charged"] == 2


# ── Difficulty: extension fee diverges from the full payoff on the same loan ──

def test_payoff_before_extension_at_term_end(api):
    """PRD §3.4: "The payoff is then the loan's `principal_cents` plus the loan's
    snapshotted `setup_fee_cents` plus the total period count multiplied by that
    per-period charge."

    Design: Difficulty/dual_variant_calc/extension_fee_vs_full_payoff_diverge_on_loan
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_30)  # day 30 -> ceil(30/30) = 1 live period
    payoff = validate_success(api.get_loan_payoff(ctx["loan"]["id"], OFFICER), 200)
    # 20000 + 200 + 1*2500 = 22700.
    assert payoff["payoff_cents"] == 22700


def test_extension_fee_is_one_period_charge_not_full_payoff(api):
    """PRD §3.5: "The fee charged is exactly one per-period charge — computed as in §3.4
    (the rounded interest portion plus the flat storage fee) — regardless of how many
    days have actually elapsed, and it does not include principal or setup fee."

    Design: Difficulty/dual_variant_calc/extension_fee_vs_full_payoff_diverge_on_loan
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_30)
    loan = ctx["loan"]
    validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(loan["version"]),
        make_officer_headers("officer-1")), 200)
    ledger = _ledger(api, loan["id"])
    ext = next(t for t in ledger if t["kind"] == "EXTENSION_FEE")
    assert ext["amount_cents"] == 2500          # one live period only
    assert ext["amount_cents"] != 22700         # diverges from the full payoff


# ── Corner: renewal resets baseline and increments renewal_count ──

def test_renewal_resets_baseline_and_increments_count(api):
    """PRD §3.5: "Unlike an extension, a renewal collects **all** the finance charges
    accrued to date — the live-period count times the per-period charge, again excluding
    principal and setup fee — and resets the clock baseline to now."
    PRD §3.5: "increments the loan's `renewal_count` by one ... moves the loan to
    `ACTIVE`, and increments `version` by one."

    Design: Corner/state_machines/renewal_resets_baseline_and_increments_count
    """
    ctx = fx.setup_active_loan()
    fx.set_clock(constants.DAY_45)  # day 45 -> loan IN_GRACE, ceil(45/30)=2 periods
    loan = ctx["loan"]
    renewed = validate_success(api.renew_loan(
        loan["id"], f.renew_loan_payload(loan["version"]),
        make_officer_headers("officer-1")), 200)
    assert renewed["status"] == "ACTIVE"
    assert renewed["renewal_count"] == 1
    ledger = _ledger(api, loan["id"])
    fee = next(t for t in ledger if t["kind"] == "RENEWAL_FEE")
    # 2 periods * 2500 per-period charge = 5000.
    assert fee["amount_cents"] == 5000


# ── Corner: extension past the lifetime period cap is refused ──

def test_extend_past_period_cap_returns_cap_exceeded(api):
    """PRD §3.5: "An extension is refused if charging one more period would push the
    loan's total finance periods past the schedule's `max_periods_total` ... Either
    breach is rejected with `ERR_PERIOD_CAP_EXCEEDED`."

    Design: Corner/state_machines/extend_past_period_cap_returns_cap_exceeded
    """
    base = fx.setup_schedule_and_shop(schedule=constants.CA_SCHEDULE)  # max_periods_total 1
    customer = fx.create_customer()
    item = fx.create_appraised_item(base["shop"]["id"], customer["id"],
                                    appraised_value_cents=600000)
    loan = fx.originate_loan(base["shop"]["id"], item["id"], base["bin"]["id"])
    after1 = validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(loan["version"]),
        make_officer_headers("officer-1")), 200)
    assert after1["periods_charged"] == 1
    res = api.extend_loan(
        loan["id"], f.extend_loan_payload(after1["version"]),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_PERIOD_CAP_EXCEEDED", 409)


# ── Corner: OCC stale-version on extend and renew ──

def test_occ_stale_version_on_extend(api):
    """PRD §2.7: "If another servicing write has advanced the loan's `version` since the
    client read it, the two values disagree and the request is rejected with
    `ERR_STALE_LOAN_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_extend
    """
    ctx = fx.setup_active_loan()
    loan = ctx["loan"]
    stale = loan["version"]
    validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(stale),
        make_officer_headers("officer-1")), 200)  # bumps version
    res = api.extend_loan(
        loan["id"], f.extend_loan_payload(stale),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_STALE_LOAN_VERSION", 412)


def test_occ_stale_version_on_renew(api):
    """PRD §2.7: "Both require the caller to supply `expected_loan_version` in the request
    body, carrying the `version` of the target loan that the client last observed. Before
    the operation proceeds, the server compares `expected_loan_version` against the loan's
    current `version`."
    PRD §2.7: "the request is rejected with `ERR_STALE_LOAN_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_renew
    """
    ctx = fx.setup_active_loan()
    loan = ctx["loan"]
    stale = loan["version"]
    validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(stale),
        make_officer_headers("officer-1")), 200)  # version 1 -> 2
    # The extend pushes term_end out to day 60; advance the clock to that new
    # term_end so the loan re-derives to IN_GRACE (renew is otherwise eligible).
    fx.set_clock(constants.GRACE_END)  # day 60 == post-extend term_end -> IN_GRACE
    res = api.renew_loan(
        loan["id"], f.renew_loan_payload(stale),
        make_officer_headers("officer-1"))
    validate_error(res, "ERR_STALE_LOAN_VERSION", 412)


# ── Corner: void after a chargeable transaction is rejected ──

def test_void_after_extension_returns_already_serviced(api):
    """PRD §3.6: "A void is only permitted while the loan is still `ACTIVE` and no
    chargeable ledger entry — none of kind `EXTENSION_FEE`, `RENEWAL_FEE`, or
    `REDEMPTION_PAYOFF` — yet exists for the loan; a void attempted on a loan that has
    already been serviced is rejected with `ERR_LOAN_ALREADY_SERVICED`."

    Design: Corner/state_machines/void_after_extension_returns_already_serviced
    """
    ctx = fx.setup_active_loan()
    loan = ctx["loan"]
    validate_success(api.extend_loan(
        loan["id"], f.extend_loan_payload(loan["version"]),
        make_officer_headers("officer-1")), 200)
    res = api.void_loan(loan["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_LOAN_ALREADY_SERVICED", 409)
