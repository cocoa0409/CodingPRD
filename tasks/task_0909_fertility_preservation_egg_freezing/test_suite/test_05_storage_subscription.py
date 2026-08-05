"""Storage subscription lifecycle: renewal cycle (ACTIVE<->PAST_DUE), per-specimen renewal
fee rounding, early-renew guard, and the single-active-subscription constraint.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_subscription_payload,
)
from test_helpers import fixtures as fx

BILLING = TEST_USERS["billing_admin_headers"]


# --------------------------------------------------------------- Difficulty: renewal cycle
def test_renew_moves_active_to_past_due_after_period_elapsed(api):
    """PRD §3.5: "From ACTIVE, a renewal is permitted only once the period has elapsed — the
    current clock must be at or after current_period_end ... A permitted renewal recomputes
    annual_fee_cents over the current specimen_count and moves the subscription to PAST_DUE,
    awaiting the renewal payment."

    Design: Difficulty/non_linear_state_machine/subscription_active_pastdue_active_cycle
    """
    fx.set_clock(fx.CLOCK_DEFAULT_UTC)
    b = fx.setup_active_subscription()
    fx.set_clock("2027-05-02T00:00:00Z")  # past current_period_end (2027-05-01)
    data = validate_success(api.renew_subscription(b["subscription_id"], BILLING), 200)
    assert data["status"] == "PAST_DUE", f"renew after period end must yield PAST_DUE, got {data['status']}"


def test_payment_within_grace_returns_past_due_to_active(api):
    """PRD §3.5: "From PAST_DUE, recording a payment is permitted only while the current clock
    is before current_period_end plus a 30-day grace window; it returns the subscription to
    ACTIVE, advancing current_period_start to the previous current_period_end, extending
    current_period_end by a further 365 days, and setting last_paid_at to the current clock."

    Design: Difficulty/non_linear_state_machine/subscription_active_pastdue_active_cycle
    """
    fx.set_clock(fx.CLOCK_DEFAULT_UTC)
    b = fx.setup_active_subscription()
    fx.set_clock("2027-05-02T00:00:00Z")
    validate_success(api.renew_subscription(b["subscription_id"], BILLING), 200)
    fx.set_clock("2027-05-10T00:00:00Z")  # within the 30-day grace after 2027-05-01
    data = validate_success(api.record_subscription_payment(b["subscription_id"], BILLING), 200)
    assert data["status"] == "ACTIVE", f"payment within grace must return to ACTIVE, got {data['status']}"


# --------------------------------------------------------------- Difficulty: per-specimen fee rounding
def test_renewal_fee_rounds_per_specimen_before_summing(api):
    """PRD §3.5: "Each specimen's net annual fee is the base annual rate of 4,000 cents per
    specimen reduced by a loyalty discount of 3.33 percent (a factor of 0.0333), with that
    single per-specimen figure rounded half-up to a whole cent first. The subscription's
    annual_fee_cents is then that rounded per-specimen fee multiplied by the specimen_count."

    Design: Difficulty/combinatorial_formula/storage_renewal_fee_per_specimen_rounding
    """
    fx.set_clock(fx.CLOCK_DEFAULT_UTC)
    b = fx.setup_retrieved_cycle(mature_oocyte_count=10, tank_capacity=20, with_subscription=True)
    fx.set_clock("2027-05-02T00:00:00Z")
    data = validate_success(api.renew_subscription(b["subscription_id"], BILLING), 200)
    # round_half_up(4000 * (1 - 0.0333)) = round_half_up(3866.8) = 3867; * 10 = 38670.
    assert data["annual_fee_cents"] == 38670, \
        f"per-specimen rounding must give 38670, got {data['annual_fee_cents']}"


def test_renewal_recomputes_fee_over_current_specimen_count(api):
    """PRD §3.5: "A permitted renewal recomputes `annual_fee_cents` over the current
    `specimen_count` and moves the subscription to `PAST_DUE`, awaiting the renewal payment."
    PRD §2.7: "A `StorageSubscription`'s `specimen_count` is the count of that patient's
    `CryoSpecimen` in `STORED` or `RESERVED` status."

    Design: Difficulty/combinatorial_formula/storage_renewal_fee_per_specimen_rounding
    """
    fx.set_clock(fx.CLOCK_DEFAULT_UTC)
    b = fx.setup_retrieved_cycle(mature_oocyte_count=10, tank_capacity=20, with_subscription=True)
    fx.set_clock("2027-05-02T00:00:00Z")
    data = validate_success(api.renew_subscription(b["subscription_id"], BILLING), 200)
    assert data["specimen_count"] == 10, f"specimen_count must be 10, got {data['specimen_count']}"
    assert data["status"] == "PAST_DUE", "renewal moves the subscription to PAST_DUE"


# --------------------------------------------------------------- Corner: guards
def test_renew_before_period_end_rejected(api):
    """PRD §3.5: "From ACTIVE, a renewal is permitted only once the period has elapsed — the
    current clock must be at or after current_period_end; renewing earlier is rejected with
    ERR_PERIOD_NOT_ELAPSED."

    Design: Corner/validations/early_renew_before_period_end_returns_period_not_elapsed
    """
    fx.set_clock(fx.CLOCK_DEFAULT_UTC)
    b = fx.setup_active_subscription()
    resp = api.renew_subscription(b["subscription_id"], BILLING)  # clock still 2026-05-01
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ELAPSED.value, 409)


def test_second_active_subscription_rejected(api):
    """PRD §3.5: "A patient may hold only one non-terminal subscription; an attempt to open a
    second while one is still active is rejected with ERR_DUPLICATE_ACTIVE_RESOURCE."

    Design: Corner/validations/duplicate_active_subscription_returns_duplicate
    """
    patient = fx.create_patient()
    validate_success(
        api.create_storage_subscription(create_subscription_payload(patient["id"]), BILLING), 201)
    resp = api.create_storage_subscription(create_subscription_payload(patient["id"]), BILLING)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_RESOURCE.value, 409)
