"""TenantStatement parallel dimensions, payments, disputes, credit/payment
compensation, transitive cascades, and the payment OCC guard.

Covers queue-A non_linear_state_machine (parallel dims), transitive_cascade,
compensating_invariant; plus queue-B payment/dispute/OCC corner instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    make_tenant_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["property_manager_headers"]


# --------------------------------------------------------------------------- #
# non_linear_state_machine / tenant_statement_parallel_delivery_payment_dimensions
# --------------------------------------------------------------------------- #
def test_mark_delivered_leaves_payment_status_untouched(api):
    """PRD §3.8: "A `PropertyManager` may mark an `ISSUED` statement as
    `DELIVERED`; this delivery action touches only the delivery dimension and
    never the payment dimension."

    Design: Difficulty/non_linear_state_machine/tenant_statement_parallel_delivery_payment_dimensions
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=20000, tenant_user_id="tPP")
    stmt = bundle["statement"]
    data = validate_success(api.mark_delivered(stmt["id"], PM))
    assert data["delivery_status"] == "DELIVERED"
    assert data["payment_status"] == "UNPAID"


def test_partial_payment_leaves_delivery_status_untouched(api):
    """PRD §3.9: "a partial payment (a positive amount strictly less than the
    balance) takes an `UNPAID` statement to `PARTIALLY_PAID`"
    PRD §3.8: "the two never interfere with each other."

    Design: Difficulty/non_linear_state_machine/tenant_statement_parallel_delivery_payment_dimensions
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=20000, tenant_user_id="tPP")
    stmt = bundle["statement"]
    tenant = make_tenant_headers("tPP")
    validate_success(api.mark_delivered(stmt["id"], PM))
    after_deliver = get_success_data(api.get_statement(stmt["id"], PM))
    data = validate_success(
        api.post_payment(
            stmt["id"],
            {"amount_cents": 5000, "expected_statement_version": after_deliver["version"]},
            tenant,
        ),
        expected_status=201,
    )
    refreshed = get_success_data(api.get_statement(stmt["id"], PM))
    assert refreshed["payment_status"] == "PARTIALLY_PAID"
    assert refreshed["delivery_status"] == "DELIVERED"  # delivery axis untouched


# --------------------------------------------------------------------------- #
# transitive_cascade / dispute_resolve_credit_balance_to_paid_depth3
# --------------------------------------------------------------------------- #
def test_resolve_full_credit_cascades_to_paid(api):
    """PRD §3.11: "On resolution the granted credit is added to the statement's
    `credit_cents`, the `total_due_cents` and `balance_due_cents` are recomputed,
    and if the resulting balance is zero or below the statement's payment status
    is set to `PAID`; the statement's `version` advances."

    Design: Difficulty/transitive_cascade/dispute_resolve_credit_balance_to_paid_depth3
    """
    bundle = fx.setup_dispute_under_review(
        credit_amount_cents=6000, reason="RATIO_ERROR", total_cost_cents=7059, tenant_user_id="tD"
    )
    dispute = bundle["dispute"]
    data = validate_success(api.resolve_dispute(dispute["id"], {"credit_amount_cents": 6000}, PM))
    assert data["status"] == "RESOLVED"
    stmt = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert stmt["credit_cents"] == 6000           # hop 1
    assert stmt["total_due_cents"] == 0           # hop 2
    assert stmt["balance_due_cents"] == 0         # hop 2
    assert stmt["payment_status"] == "PAID"       # hop 3 caused by balance reaching 0


def test_resolve_credit_recomputes_statement_totals(api):
    """PRD §3.8: "the `total_due_cents` equals the utility charge plus the admin
    fee plus the late fee minus the credits, and the `balance_due_cents` equals
    the `total_due_cents` minus the amount paid."

    Design: Difficulty/transitive_cascade/dispute_resolve_credit_balance_to_paid_depth3
    """
    bundle = fx.setup_dispute_under_review(
        credit_amount_cents=6000, reason="RATIO_ERROR", total_cost_cents=7059, tenant_user_id="tD2"
    )
    validate_success(api.resolve_dispute(bundle["dispute"]["id"], {"credit_amount_cents": 2000}, PM))
    stmt = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    # utility 6000, admin 0, late 0, credit 2000 -> total 4000, balance 4000
    assert stmt["total_due_cents"] == 4000
    assert stmt["balance_due_cents"] == 4000


# --------------------------------------------------------------------------- #
# transitive_cascade / payment_reverse_amount_paid_status_recompute_depth2
# --------------------------------------------------------------------------- #
def test_reverse_full_payment_recomputes_amount_paid_and_status(api):
    """PRD §3.9: "Reversing a payment moves it to `REVERSED`, subtracts its
    `amount_cents` from the statement's `amount_paid_cents`, recomputes the
    `balance_due_cents`, recomputes the `payment_status` (for instance back from
    `PAID` to `PARTIALLY_PAID` or `UNPAID` as the restored balance dictates), and
    advances the statement's `version` as a compensating mutation."

    Design: Difficulty/transitive_cascade/payment_reverse_amount_paid_status_recompute_depth2
    """
    bundle = fx.setup_statement_with_payment(amount_cents=6000, total_cost_cents=7059, tenant_user_id="tRV")
    payment = bundle["payment"]
    data = validate_success(api.reverse_payment(payment["id"], PM))
    assert data["status"] == "REVERSED"
    stmt = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert stmt["amount_paid_cents"] == 0          # hop 1
    assert stmt["balance_due_cents"] == 6000       # hop 2
    assert stmt["payment_status"] == "UNPAID"      # hop 2


def test_full_payment_clears_balance_to_paid(api):
    """PRD §3.9: "a payment exactly equal to the balance clears it, driving the
    balance to zero and the payment status to `PAID` — this applies whether the
    statement was `UNPAID`, `PARTIALLY_PAID`, or `DELINQUENT` at the time the
    balance is cleared in full."

    Design: Difficulty/transitive_cascade/payment_reverse_amount_paid_status_recompute_depth2
    """
    bundle = fx.setup_statement_with_payment(amount_cents=6000, total_cost_cents=7059, tenant_user_id="tRV2")
    stmt = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert stmt["payment_status"] == "PAID"
    assert stmt["balance_due_cents"] == 0
    assert stmt["amount_paid_cents"] == 6000


# --------------------------------------------------------------------------- #
# compensating_invariant / dispute_reopen_reverses_credit_total_due_conserved
# --------------------------------------------------------------------------- #
def test_reopen_reverses_credit_and_conserves_total_due(api):
    """PRD §3.11: "On reopen the `reopen_count` increments by one and the
    previously granted credit is reversed — the prior `credit_amount_cents` is
    subtracted back out of the statement's `credit_cents`, the balances are
    recomputed, and the statement's `version` advances as a compensating
    mutation, keeping the statement's money conserved across the reopen cycle."

    Design: Difficulty/compensating_invariant/dispute_reopen_reverses_credit_total_due_conserved
    """
    bundle = fx.setup_dispute_under_review(
        credit_amount_cents=2000, reason="HIGH_READING", total_cost_cents=7059, tenant_user_id="tCI"
    )
    validate_success(api.resolve_dispute(bundle["dispute"]["id"], {"credit_amount_cents": 2000}, PM))
    after_resolve = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert after_resolve["credit_cents"] == 2000
    assert after_resolve["total_due_cents"] == 4000

    reopened = validate_success(api.reopen_dispute(bundle["dispute"]["id"], PM))
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["reopen_count"] == 1
    after_reopen = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert after_reopen["credit_cents"] == 0          # prior credit reversed
    assert after_reopen["total_due_cents"] == 6000    # conserved == pre-resolve value


def test_reopen_balance_due_conserved_to_pre_resolve(api):
    """PRD §3.11: "the prior `credit_amount_cents` is subtracted back out of the
    statement's `credit_cents`, the balances are recomputed, and the statement's
    `version` advances as a compensating mutation, keeping the statement's money
    conserved across the reopen cycle."
    PRD §3.8: "the `balance_due_cents` equals the `total_due_cents` minus the
    amount paid."

    Design: Difficulty/compensating_invariant/dispute_reopen_reverses_credit_total_due_conserved
    """
    bundle = fx.setup_dispute_under_review(
        credit_amount_cents=2000, reason="HIGH_READING", total_cost_cents=7059, tenant_user_id="tCI2"
    )
    before_resolve = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert before_resolve["balance_due_cents"] == 6000
    validate_success(api.resolve_dispute(bundle["dispute"]["id"], {"credit_amount_cents": 2000}, PM))
    mid = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert mid["balance_due_cents"] == 4000  # credit dropped balance
    validate_success(api.reopen_dispute(bundle["dispute"]["id"], PM))
    after = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    # balance restored to its pre-resolve value (no payment, no credit)
    assert after["balance_due_cents"] == 6000


# --------------------------------------------------------------------------- #
# compensating_invariant / payment_reverse_restores_balance_amount_paid_conserved
# --------------------------------------------------------------------------- #
def test_reverse_partial_payment_conserves_balance(api):
    """PRD §3.9: "Posting adds the `amount_cents` to the statement's
    `amount_paid_cents`, recomputes `balance_due_cents`, and advances the
    statement's `version`."
    PRD §3.9: "Reversing a payment moves it to `REVERSED`, subtracts its
    `amount_cents` from the statement's `amount_paid_cents`, recomputes the
    `balance_due_cents`, recomputes the `payment_status`"

    Design: Difficulty/compensating_invariant/payment_reverse_restores_balance_amount_paid_conserved
    """
    bundle = fx.setup_statement_with_payment(amount_cents=4000, total_cost_cents=7059, tenant_user_id="tCP")
    after_pay = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert after_pay["amount_paid_cents"] == 4000
    assert after_pay["balance_due_cents"] == 2000
    assert after_pay["payment_status"] == "PARTIALLY_PAID"

    validate_success(api.reverse_payment(bundle["payment"]["id"], PM))
    after_rev = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    assert after_rev["amount_paid_cents"] == 0           # restored
    assert after_rev["balance_due_cents"] == 6000        # conserved == pre-payment value
    assert after_rev["payment_status"] == "UNPAID"


def test_reverse_payment_marks_payment_reversed_and_advances_version(api):
    """PRD §3.9: "A successful payment creates a `Payment` resource against a
    `statement_id` and `property_id` with its `tenant_user_id` stamped from the
    caller; the payment begins `POSTED` and may later become `REVERSED`."
    PRD §3.9: "Reversing a payment moves it to `REVERSED`, subtracts its
    `amount_cents` from the statement's `amount_paid_cents`, recomputes the
    `balance_due_cents`, recomputes the `payment_status` (for instance back from
    `PAID` to `PARTIALLY_PAID` or `UNPAID` as the restored balance dictates), and
    advances the statement's `version` as a compensating mutation."

    Design: Difficulty/compensating_invariant/payment_reverse_restores_balance_amount_paid_conserved
    """
    bundle = fx.setup_statement_with_payment(amount_cents=4000, total_cost_cents=7059, tenant_user_id="tCP2")
    after_pay = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    data = validate_success(api.reverse_payment(bundle["payment"]["id"], PM))
    assert data["status"] == "REVERSED"
    after_rev = get_success_data(api.get_statement(bundle["statement"]["id"], PM))
    # the compensating mutation advances the statement version
    assert after_rev["version"] == after_pay["version"] + 1


# --------------------------------------------------------------------------- #
# Corner: cross_cutting_complexity_layers / occ_stale_statement_version_on_payment_returns_stale_version
# --------------------------------------------------------------------------- #
def test_payment_with_stale_statement_version_rejected(api):
    """PRD §2.10: "If that value does not equal the statement's current
    `version` at the time the payment is processed, the create is rejected with
    `ERR_STALE_VERSION` and HTTP status 412, preventing the client from paying
    against a balance it has not actually seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_statement_version_on_payment_returns_stale_version
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=7059, tenant_user_id="tOCC")
    stmt = bundle["statement"]
    stale_version = stmt["version"]
    tenant = make_tenant_headers("tOCC")
    # a dispute-resolution credit advances the statement version
    dispute = get_success_data(
        api.open_dispute(stmt["id"], {"reason": "HIGH_READING", "credit_amount_cents": 1000}, tenant)
    )
    get_success_data(api.start_review(dispute["id"], PM))
    get_success_data(api.resolve_dispute(dispute["id"], {"credit_amount_cents": 1000}, PM))
    validate_error(
        api.post_payment(
            stmt["id"], {"amount_cents": 5000, "expected_statement_version": stale_version}, tenant
        ),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


# --------------------------------------------------------------------------- #
# Corner: cross_cutting_complexity_layers / payment_increments_statement_version_derived_balance_reconciled
# --------------------------------------------------------------------------- #
def test_partial_payment_increments_version_and_reconciles_balance(api):
    """PRD §3.9: "a partial payment (a positive amount strictly less than the
    balance) takes an `UNPAID` statement to `PARTIALLY_PAID`"
    PRD §3.9: "Posting adds the `amount_cents` to the statement's
    `amount_paid_cents`, recomputes `balance_due_cents`, and advances the
    statement's `version`."

    Design: Corner/cross_cutting_complexity_layers/payment_increments_statement_version_derived_balance_reconciled
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=7059, tenant_user_id="tDF")
    stmt = bundle["statement"]
    tenant = make_tenant_headers("tDF")
    validate_success(
        api.post_payment(
            stmt["id"], {"amount_cents": 2000, "expected_statement_version": stmt["version"]}, tenant
        ),
        expected_status=201,
    )
    refreshed = get_success_data(api.get_statement(stmt["id"], PM))
    assert refreshed["amount_paid_cents"] == 2000
    assert refreshed["balance_due_cents"] == 4000  # 6000 - 2000
    assert refreshed["payment_status"] == "PARTIALLY_PAID"
    assert refreshed["version"] == stmt["version"] + 1


# --------------------------------------------------------------------------- #
# Corner: cross_cutting_complexity_layers / issue_statements_cascades_one_statement_per_eligible_lease
# --------------------------------------------------------------------------- #
def test_issue_statements_creates_one_per_eligible_lease(api):
    """PRD §3.6: "On success the system creates exactly one `TenantStatement` per
    eligible lease, each born with `delivery_status` of `ISSUED` and
    `payment_status` of `UNPAID`"

    Design: Corner/cross_cutting_complexity_layers/issue_statements_cascades_one_statement_per_eligible_lease
    """
    bundle = fx.setup_two_unit_rubs_cycle(occupant_a=1, occupant_b=1, total_cost_cents=30000)
    cycle_id = bundle["cycle"]["id"]
    statements = get_success_data(api.list_statements(PM, params={"billing_cycle_id": cycle_id}))
    assert len(statements) == 2
    for s in statements:
        assert s["delivery_status"] == "ISSUED"
        assert s["payment_status"] == "UNPAID"


# --------------------------------------------------------------------------- #
# Corner: endpoints / get_statement_returns_computed_total_and_balance
# --------------------------------------------------------------------------- #
def test_get_statement_returns_computed_totals(api):
    """PRD §3.8: "the `total_due_cents` equals the utility charge plus the admin
    fee plus the late fee minus the credits, and the `balance_due_cents` equals
    the `total_due_cents` minus the amount paid."

    Design: Corner/endpoints/get_statement_returns_computed_total_and_balance
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=7059, tenant_user_id="tGET")
    data = validate_success(api.get_statement(bundle["statement"]["id"], PM))
    assert data["utility_charge_cents"] == 6000
    assert data["admin_fee_cents"] == 0
    assert data["credit_cents"] == 0
    assert data["total_due_cents"] == 6000
    assert data["balance_due_cents"] == 6000


# --------------------------------------------------------------------------- #
# Corner: validations / payment_amount_exceeds_balance_returns_payment_exceeds_balance
# --------------------------------------------------------------------------- #
def test_payment_exceeding_balance_rejected(api):
    """PRD §3.9: "The amount must be strictly greater than zero and at most the
    statement's current `balance_due_cents`; an amount exceeding the balance is
    rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/payment_amount_exceeds_balance_returns_payment_exceeds_balance
    """
    bundle = fx.setup_single_rubs_statement(total_cost_cents=7059, tenant_user_id="tPE")
    stmt = bundle["statement"]
    tenant = make_tenant_headers("tPE")
    validate_error(
        api.post_payment(
            stmt["id"], {"amount_cents": 7000, "expected_statement_version": stmt["version"]}, tenant
        ),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value,
    )
