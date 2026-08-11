"""Charging a cycle, the payment axis, and the four-bucket credit ledger."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit,
    assert_credit_conserved,
    assert_same_instant,
    issue_goodwill_credit,
    read_account,
    read_cycle,
    read_subscription,
    register_and_verify_account,
    set_clock,
    setup_allocated_cycle,
    setup_household,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import allocate_cycle, generate_cycle, make_account_holder_headers

OPS = TEST_USERS["ops_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


# ==========================================================================
# The charge gate on the parent account
# ==========================================================================
def test_a_suspended_household_cannot_have_its_cycle_charged(api):
    """PRD §3.1: "While suspended, no cycle of that household may be charged."
    PRD §3.1: "Any operation that requires a live household — creating a subscription,
    activating one, charging a cycle, creating a registry, creating a gift order — checks
    that the owning account's `status` is `ACTIVE` and otherwise returns
    `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/cycle_charge_requires_account_status_active
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="susp")
    validate_success(
        api.suspend_account(ctx["account_id"], "Payment dispute under review", SUPPORT)
    )

    resp = api.charge_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, 409)

    after = read_cycle(api, cycle["id"])
    assert after["payment_status"] == "UNCHARGED"
    assert after["charged_cash_cents"] == 0
    assert read_account(api, ctx["account_id"])["status"] == "SUSPENDED"


def test_the_cycles_own_axis_was_chargeable_all_along(api):
    """PRD §3.7: "An `OpsAdmin` charges a cycle whose `payment_status` is `UNCHARGED` and
    whose `status` is `ALLOCATED` or `CUTOFF_LOCKED`; the owning account must be `ACTIVE`."
    PRD §3.1: "Reinstatement requires the account to be `SUSPENDED`, moves it
    `SUSPENDED → ACTIVE`, and clears `suspended_reason` back to null."

    Design: Difficulty/cross_entity_state_dependency/cycle_charge_requires_account_status_active
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="susp2")
    validate_success(api.suspend_account(ctx["account_id"], "Payment dispute", SUPPORT))
    validate_error(
        api.charge_cycle(cycle["id"], OPS), ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value, 409
    )

    blocked = read_cycle(api, cycle["id"])
    assert blocked["status"] == "ALLOCATED", "the cycle's fulfilment axis never moved"
    assert blocked["payment_status"] == "UNCHARGED"

    validate_success(api.reinstate_account(ctx["account_id"], SUPPORT))
    charged = validate_success(api.charge_cycle(cycle["id"], OPS))
    assert charged["payment_status"] == "CHARGED"
    assert charged["charged_cash_cents"] == 2999


def test_charging_a_cycle_twice_is_refused_on_the_payment_axis(api):
    """PRD §3.7: "A cycle already charged is refused with
    `ERR_CYCLE_PAYMENT_STATE_INVALID` (HTTP 409)."
    PRD §3.7: "When it evaluates above 0, the cycle moves `UNCHARGED → CHARGED` with
    `charged_cash_cents` and `retained_cash_cents` both set to that amount — and the account
    must have `payment_method_on_file` true."

    Design: Corner/state_machines/corner_charge_twice_rejected_on_payment_axis
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="chg")
    validate_success(api.charge_cycle(cycle["id"], OPS))

    resp = api.charge_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_CYCLE_PAYMENT_STATE_INVALID.value, 409)

    after = read_cycle(api, cycle["id"])
    assert after["payment_status"] == "CHARGED"
    assert after["charged_cash_cents"] == 2999
    assert after["retained_cash_cents"] == 2999


def test_a_charge_without_a_payment_method_moves_the_billing_axis_then_rejects(api):
    """PRD §3.7: "That last requirement is the single declared exception to the rule that a
    rejected request leaves no trace. When `total_due_cents` is above 0 and the account has
    no payment method on file, the request fails with `ERR_NO_PAYMENT_METHOD` (HTTP 402) —
    *and* the subscription's `billing_state` moves `CURRENT → PAST_DUE`, incrementing the
    subscription's `version`, before the rejection is emitted. Nothing else moves: the cycle
    stays `UNCHARGED`, no credit is consumed and no points are touched."

    Design: Corner/validations/corner_charge_without_payment_method_mutates_billing_then_rejects
    """
    ctx, cycle = setup_allocated_cycle(
        api, email_prefix="nocard", account_overrides={"payment_method_on_file": False}
    )
    resp = api.charge_cycle(cycle["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_NO_PAYMENT_METHOD.value, 402)

    subscription = read_subscription(api, ctx["subscription"]["id"])
    assert subscription["billing_state"] == "PAST_DUE", (
        "this is the one rung that mutates before rejecting"
    )
    assert subscription["lifecycle_state"] == "ACTIVE"

    after = read_cycle(api, cycle["id"])
    assert after["payment_status"] == "UNCHARGED"
    assert after["charged_cash_cents"] == 0


def test_a_named_expired_credit_is_refused_at_charge_time(api):
    """PRD §3.7: "When it *is* supplied, the server consumes exactly the named credits in
    the declared stack order and validates them: a named credit whose `expires_at` is at or
    before the logical clock is refused with `ERR_CREDIT_EXPIRED` (HTTP 409), and a named
    credit whose `status` is neither `AVAILABLE` nor `PARTIALLY_CONSUMED` is refused with
    `ERR_CREDIT_NOT_AVAILABLE` (HTTP 409)."
    PRD §3.7: "such a credit is `refundable` and expires in 365 days"

    Design: Corner/validations/corner_named_expired_credit_rejected_at_charge
    """
    ctx, cycle = setup_allocated_cycle(api, email_prefix="expcred")
    credit = issue_goodwill_credit(api, ctx["account_id"], 5000)
    assert_same_instant(credit["expires_at"], "2027-06-01T00:00:00Z", "Credit.expires_at")

    set_clock(api, "2027-06-02T00:00:00Z")
    resp = api.charge_cycle(cycle["id"], OPS, {"credit_ids": [credit["id"]]})
    validate_error(resp, ApiErrorId.ERR_CREDIT_EXPIRED.value, 409)

    assert read_cycle(api, cycle["id"])["payment_status"] == "UNCHARGED"
    after = validate_success(api.get_credit(credit["id"], ctx["headers"]))
    assert after["consumed_cents"] == 0


def test_the_charge_response_and_the_credit_read_agree_immediately(api):
    """PRD §3.7: "`consumed_cents` is what has been spent against cycles; `remaining_cents`
    is what is still spendable"
    PRD §3.1: "`available_credit_cents` is the sum of `remaining_cents` over the account's
    credits whose `status` is `AVAILABLE` or `PARTIALLY_CONSUMED` *and* whose `expires_at`
    is strictly after the logical clock — a credit whose expiry instant equals the clock
    exactly is excluded. It is recomputed on every credit status change and reported on every
    account read."

    Design: Corner/consistency_model/corner_charge_response_reflects_credit_consumption_immediately
    """
    ctx = setup_household(api, email_prefix="chgnow")
    credit = issue_goodwill_credit(api, ctx["account_id"], 5000)
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    allocate_cycle(api, cycle["id"])

    charged = validate_success(api.charge_cycle(cycle["id"], OPS))
    assert charged["referral_credit_applied_cents"] == 1500
    assert charged["total_due_cents"] == 1499
    assert charged["charged_cash_cents"] == 1499

    after = validate_success(api.get_credit(credit["id"], ctx["headers"]))
    assert after["consumed_cents"] == 1500
    assert after["remaining_cents"] == 3500
    assert after["status"] == "PARTIALLY_CONSUMED"
    assert_credit_conserved(after)
    assert read_account(api, ctx["account_id"])["available_credit_cents"] == 3500


# ==========================================================================
# The credit ledger on its own
# ==========================================================================
def test_a_goodwill_credit_starts_fully_spendable(api):
    """PRD §3.7: "A support operator may issue a credit directly by naming `account_id` and
    `issued_cents`, which must be greater than zero, with an optional `credit_type` that
    defaults to `GOODWILL`; such a credit is `refundable` and expires in 365 days, and
    issuing it recomputes the household's `available_credit_cents`."
    PRD §2.9: "for every `Credit` row, `issued_cents` always equals `consumed_cents` plus
    `remaining_cents` plus `forfeited_cents`."

    Design: Corner/entities/corner_goodwill_credit_remaining_equals_issued_at_creation
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("goodwill"))
    data = validate_success(
        api.issue_credit({"account_id": account["id"], "issued_cents": 2500}, SUPPORT), 201
    )
    assert_credit(data)
    assert data["credit_type"] == "GOODWILL"
    assert data["remaining_cents"] == 2500
    assert data["consumed_cents"] == 0
    assert data["forfeited_cents"] == 0
    assert data["refundable"] is True
    assert data["status"] == "AVAILABLE"
    assert read_account(api, account["id"])["available_credit_cents"] == 2500


def test_revoking_a_credit_recomputes_the_household_position(api):
    """PRD §3.7: "A support operator may instead revoke a credit in either of those two
    states, with the identical money movement and a final `status` of `REVOKED`"
    PRD §2.9: "revoking or expiring a credit moves whatever remains into `forfeited_cents`."

    Design: Corner/cross_cutting_layers/corner_available_credit_recomputed_after_revoke
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("derive"))
    headers = make_account_holder_headers(account["id"])
    big = issue_goodwill_credit(api, account["id"], 2500)
    small = issue_goodwill_credit(api, account["id"], 1500)
    assert read_account(api, account["id"])["available_credit_cents"] == 4000

    validate_success(api.revoke_credit(big["id"], SUPPORT))

    assert read_account(api, account["id"])["available_credit_cents"] == 1500
    revoked = validate_success(api.get_credit(big["id"], headers))
    assert revoked["forfeited_cents"] == 2500
    assert_credit_conserved(revoked)
    assert validate_success(api.get_credit(small["id"], headers))["remaining_cents"] == 1500


def test_revoking_an_already_revoked_credit_is_refused(api):
    """PRD §3.7: "Attempting to revoke, expire or apply a credit that is in none of the two
    spendable states is refused with `ERR_CREDIT_NOT_AVAILABLE`"

    Design: Corner/state_machines/corner_revoke_an_already_revoked_credit_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("revoke"))
    headers = make_account_holder_headers(account["id"])
    credit = issue_goodwill_credit(api, account["id"], 2500)
    validate_success(api.revoke_credit(credit["id"], SUPPORT))

    resp = api.revoke_credit(credit["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_AVAILABLE.value, 409)

    after = validate_success(api.get_credit(credit["id"], headers))
    assert after["status"] == "REVOKED"
    assert after["forfeited_cents"] == 2500
    assert after["remaining_cents"] == 0
    assert read_account(api, account["id"])["available_credit_cents"] == 0


def test_expiring_a_credit_whose_expiry_is_still_ahead_is_refused(api):
    """PRD §3.7: "attempting the operator-driven expiry on a credit whose `expires_at` is
    still strictly in the future is refused with `ERR_CREDIT_NOT_YET_EXPIRED` (HTTP 409)."
    PRD §3.7: "Expiry is type-dependent: a `GIFT` credit's `expires_at` sits 730 days after
    issuance, while every other type expires 365 days after issuance."

    Design: Corner/state_machines/corner_expire_credit_before_its_expiry_rejected
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    account = register_and_verify_account(api, email=unique_email("notexp"))
    headers = make_account_holder_headers(account["id"])
    credit = issue_goodwill_credit(api, account["id"], 2500)

    resp = api.expire_credit(credit["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_YET_EXPIRED.value, 409)

    after = validate_success(api.get_credit(credit["id"], headers))
    assert after["status"] == "AVAILABLE"
    assert after["remaining_cents"] == 2500
    assert_same_instant(after["expires_at"], "2027-06-01T00:00:00Z", "Credit.expires_at")
