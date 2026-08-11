"""The four write gates and the fiscal ceilings that guard a disbursement."""

from test_helpers import (
    ApiErrorId,
    add_payee,
    block_payee,
    create_account,
    create_active_authorization,
    create_active_client,
    create_budget_category,
    create_client,
    create_payee,
    open_and_close_period,
    payment_request,
    read_account,
    read_bond,
    read_budget_category,
    read_payee,
    read_payment,
    read_period,
    register_bond,
    schedule_payment,
    set_clock,
    set_fraud_posture,
    setup_billpay_world,
    list_payments,
    validate_error,
    validate_success,
)


def test_an_expired_surety_bond_refuses_the_whole_organization():
    """PRD §2.8: "**The bond gate (G1)** refuses on behalf of the whole
    organization. An unbonded fiduciary may lawfully disburse nothing. If no
    `SuretyBond` is currently `IN_FORCE`, or the `IN_FORCE` bond's coverage
    window does not contain the current logical date, the refusal is
    `ERR_BOND_EXPIRED` (HTTP 409)."

    Design: Corner/validations/corner_expired_surety_bond_refuses_every_disbursement
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        bond_overrides={"bond_number": "SB-2025-009", "expiry_date": "2026-05-31"},
    )

    response = payment_request(world, amount_cents=80000, channel="ACH")

    validate_error(response, ApiErrorId.ERR_BOND_EXPIRED.value, 409)
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 0


def test_a_limited_billpay_instrument_refuses_a_discretionary_payee():
    """PRD §3.1: "| Schedule or revise a payment to a `DISCRETIONARY` payee |
    refused | permitted | refused |"
    PRD §2.8: "**The scope gate (G2b)** refuses on behalf of one client's
    instrument. If the scope matrix of §3.1 marks the requested operation as
    not permitted for that instrument's `scope_tier`, the refusal is
    `ERR_SCOPE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/validations/corner_limited_billpay_scope_refuses_a_discretionary_payee
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        scope_tier="LIMITED_BILLPAY",
        payee_type="DISCRETIONARY",
        payee_overrides={"payee_name": "Riverside Casino", "remittance_reference": "RC-8"},
    )

    response = payment_request(world, amount_cents=40000, channel="ACH")

    validate_error(response, ApiErrorId.ERR_SCOPE_NOT_PERMITTED.value, 403)
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 0


def test_the_limited_billpay_ceiling_is_inclusive_at_two_hundred_fifty_thousand():
    """PRD §2.9 rung 33: "**Instrument amount ceiling.** The payment's
    `amount_cents` is at or below the instrument's per-payment ceiling — 250000
    cents under `LIMITED_BILLPAY`, 400000 cents under `REP_PAYEE`, unbounded
    under `FULL_AGENCY`. Both ceilings are inclusive: exactly the ceiling
    passes. Otherwise `ERR_SCOPE_AMOUNT_EXCEEDED` (422)."

    Design: Corner/validations/corner_limited_billpay_per_payment_ceiling_is_inclusive_at_250000
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        scope_tier="LIMITED_BILLPAY",
        allocation_cents=600000,
    )

    over = payment_request(world, amount_cents=250001, channel="ACH")
    validate_error(over, ApiErrorId.ERR_SCOPE_AMOUNT_EXCEEDED.value, 422)
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 0
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 0

    exactly = payment_request(world, amount_cents=250000, channel="ACH")
    accepted = validate_success(exactly, 201)
    assert accepted["amount_cents"] == 250000


def test_the_bond_coverage_ceiling_fires_on_the_organization_wide_aggregate():
    """PRD §3.3: "The committed figure is the only one the ceiling at rung 35
    consults: a payment is refused with `ERR_BOND_COVERAGE_EXCEEDED` when
    `exposure_committed_cents` plus this payment's `amount_cents` would exceed
    `coverage_cents`, and landing exactly on coverage is permitted."
    PRD §3.3: "Because that aggregate spans every client, a small payment for
    one client can be refused because a different client's committed payments
    have consumed the headroom."

    Design: Corner/validations/corner_bond_coverage_ceiling_refuses_on_the_aggregate_not_the_single_request
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        bond_overrides={"bond_number": "SB-2026-THIN", "coverage_cents": 250000},
        allocation_cents=500000,
    )
    second_payee = add_payee(world)

    first = payment_request(world, amount_cents=150000, channel="ACH")
    validate_success(first, 201)

    second = payment_request(world, amount_cents=150000, channel="ACH", payee=second_payee)
    validate_error(second, ApiErrorId.ERR_BOND_COVERAGE_EXCEEDED.value, 409)

    bond = read_bond(world["bond"]["id"])
    assert bond["exposure_committed_cents"] == 150000
    assert bond["headroom_committed_cents"] == 100000
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 150000
    assert len(list_payments(account_id=world["account"]["id"])) == 1


def test_an_account_holding_exactly_the_total_charge_may_schedule_the_payment():
    """PRD §2.9 rung 37: "**Account sufficiency.** The account's
    `available_balance_cents` is at least the payment's `total_charge_cents`;
    an account holding exactly the total charge may schedule the payment.
    Otherwise `ERR_INSUFFICIENT_AVAILABLE` (409)."

    Design: Corner/validations/corner_available_balance_boundary_permits_a_payment_that_lands_exactly_on_zero
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        opening_balance_cents=80500,
        account_overrides={"account_label": "Thin"},
    )

    response = payment_request(world, amount_cents=80000, channel="ACH")
    validate_success(response, 201)

    account = read_account(world["account"]["id"])
    assert account["available_balance_cents"] == 0
    assert account["cleared_balance_cents"] == 80500
    assert account["committed_disbursements_cents"] == 80500

    # A further disbursement against an account with nothing available is
    # refused by the same rung. It names a different payee and a different
    # amount so that the duplicate-payment buffer at rung 19 cannot fire first.
    second_payee = add_payee(world)
    follow_up = payment_request(world, amount_cents=1000, channel="ACH", payee=second_payee)
    validate_error(follow_up, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE.value, 409)


def test_the_account_freeze_gate_pre_empts_the_account_sufficiency_rung():
    """PRD §2.8: "**The account fraud-freeze gate (G3)** refuses on behalf of
    one account."
    PRD §2.8: "When two gates both apply, the earlier one in the list above
    wins."
    PRD §2.9: "When a single request violates several rules at once, exactly
    one error comes back, and which one is fully determined: the rung with the
    lowest number wins."

    Design: Difficulty/priority_pair_validation_conflict/account_freeze_gate_wins_over_insufficient_available_funds
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        opening_balance_cents=60000,
        account_overrides={"account_label": "Thin"},
    )
    set_fraud_posture(
        world["account"]["id"],
        "FROZEN",
        "Confirmed lottery-scam contact reported by the family.",
    )

    # 80000 cents of principal plus a 500-cent fee cannot be covered by the
    # account's 60000 available cents either, so both rungs are in play.
    response = payment_request(world, amount_cents=80000, channel="ACH")

    validate_error(response, ApiErrorId.ERR_ACCOUNT_FROZEN.value, 409)


def test_a_payment_refused_by_the_freeze_gate_commits_nothing():
    """PRD §2.5: "Third, **a rejected request increments nothing**: when any
    rung of §2.9 refuses a request, no version anywhere moves and no field
    anywhere is written, apart from the single audit entry the request
    appends."

    Design: Difficulty/priority_pair_validation_conflict/account_freeze_gate_wins_over_insufficient_available_funds
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        opening_balance_cents=60000,
        account_overrides={"account_label": "Thin"},
    )
    set_fraud_posture(
        world["account"]["id"],
        "FROZEN",
        "Confirmed lottery-scam contact reported by the family.",
    )

    payment_request(world, amount_cents=80000, channel="ACH")

    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
    assert account["available_balance_cents"] == 60000
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 0


def test_the_period_freeze_gate_pre_empts_the_payment_referential_rung():
    """PRD §2.8: "**The reconciliation-freeze gate (G4)** refuses on behalf of
    one account-month. If the `ReconciliationPeriod` that would receive this
    request's ledger effect is `CLOSED` or `LOCKED`, the refusal is
    `ERR_PERIOD_FROZEN` (HTTP 409)."
    PRD §2.8: "All five sit **after** authentication, role authorization,
    existence resolution, request-shape validation and enum-membership
    validation, and **before** every ordinary business rung."

    Design: Difficulty/priority_pair_validation_conflict/period_freeze_gate_wins_over_cross_client_payee_reference
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    open_and_close_period(world["account"]["id"], "2026-06")

    other_client = create_client(
        full_name="Owen Trask", date_of_birth="1938-11-02", intake_reference="INT-9016"
    )
    foreign_payee = create_payee(
        other_client["id"], payee_name="Northside Gas", remittance_reference="NG-31"
    )

    # The payee belongs to a different client, which rung 13 would refuse, but
    # the receiving month's books are already closed.
    response = payment_request(world, amount_cents=80000, channel="ACH", payee=foreign_payee)

    validate_error(response, ApiErrorId.ERR_PERIOD_FROZEN.value, 409)


def test_a_payment_refused_by_the_period_freeze_leaves_the_period_closed():
    """PRD §3.7: "Either way the current logical instant is written to
    `closed_at`, every ledger entry of that period now reads `frozen` as true,
    and the reconciliation-freeze gate at rung 10 begins refusing the
    operations it guards."

    Design: Difficulty/priority_pair_validation_conflict/period_freeze_gate_wins_over_cross_client_payee_reference
    """
    world = setup_billpay_world(clock_iso="2026-06-01T09:00:00Z")
    period = open_and_close_period(world["account"]["id"], "2026-06")

    other_client = create_client(
        full_name="Owen Trask", date_of_birth="1938-11-02", intake_reference="INT-9016"
    )
    foreign_payee = create_payee(
        other_client["id"], payee_name="Northside Gas", remittance_reference="NG-31"
    )

    payment_request(world, amount_cents=80000, channel="ACH", payee=foreign_payee)

    assert read_period(period["id"])["status"] == "CLOSED"
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 0
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 0


def test_scheduling_a_payment_to_a_blocked_payee_is_refused():
    """PRD §3.2: "Once a payee is `BLOCKED`, any attempt to schedule or revise
    a payment to them is refused with `ERR_PAYEE_BLOCKED` at rung 28."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_depends_on_payee_status
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        payee_overrides={"payee_name": "Quick Cash Wire", "remittance_reference": "QCW-4"},
    )
    block_payee(world["payee"]["id"], "Named in an active elder-fraud investigation.")

    response = payment_request(world, amount_cents=80000, channel="ACH")

    validate_error(response, ApiErrorId.ERR_PAYEE_BLOCKED.value, 409)
    assert read_payee(world["payee"]["id"])["status"] == "BLOCKED"
    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
    assert account["available_balance_cents"] == 5000000


def test_the_same_disbursement_succeeds_against_an_active_payee():
    """PRD §3.2: "A new payee is `ACTIVE` with `blocked_reason` null and
    `settled_payment_count` at zero."
    PRD §2.9 rung 28: "**Payee not blocked.** The `Payee` named by the payment
    has status `ACTIVE`. Otherwise `ERR_PAYEE_BLOCKED` (409). Applies to
    scheduling a payment and revising one."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_depends_on_payee_status
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        payee_overrides={"payee_name": "Quick Cash Wire", "remittance_reference": "QCW-4"},
    )
    assert read_payee(world["payee"]["id"])["status"] == "ACTIVE"

    response = payment_request(world, amount_cents=80000, channel="ACH")

    payment = validate_success(response, 201)
    assert payment["settlement_status"] == "SCHEDULED"
    assert read_account(world["account"]["id"])["committed_disbursements_cents"] == 80500


def test_blocking_a_payee_cancels_its_scheduled_payment_and_releases_the_commitments():
    """PRD §3.2: "Blocking also sweeps: every payment to that payee whose
    `settlement_status` is `SCHEDULED` moves to `CANCELLED`, each cancellation
    releasing the account's commitment by `total_charge_cents`, the budget
    line's `committed_cents` by `amount_cents`, and the bond's
    `exposure_committed_cents` by `amount_cents`."

    Design: Difficulty/cross_entity_state_dependency/payment_creation_depends_on_payee_status
    """
    world = setup_billpay_world(
        clock_iso="2026-06-01T09:00:00Z",
        payee_overrides={"payee_name": "Quick Cash Wire", "remittance_reference": "QCW-4"},
    )
    payment = schedule_payment(world, amount_cents=80000, channel="ACH")

    block_payee(world["payee"]["id"], "Named in an active elder-fraud investigation.")

    assert read_payment(payment["id"])["settlement_status"] == "CANCELLED"
    account = read_account(world["account"]["id"])
    assert account["committed_disbursements_cents"] == 0
    assert account["available_balance_cents"] == 5000000
    assert read_budget_category(world["budget_category"]["id"])["committed_cents"] == 0
    assert read_bond(world["bond"]["id"])["exposure_committed_cents"] == 0
