"""The statutory lien attaches to the producer and not to the agreement that generated it, so an
unpaid lien-protected installment on one contract blocks a termination notice on an entirely
different contract of the same producer. Alongside it, the payment guard: a single cent of
overpayment is refused outright rather than clamped or carried, and a partial payment leaves the
lien standing.
"""
from test_helpers import (
    CLERK,
    MANAGER,
    ApiErrorId,
    accept_contract,
    acknowledge_pick_call,
    appointment_version,
    book_appointment,
    book_sampling_visit,
    capture_gross,
    capture_tare,
    close_settlement,
    create_allocation,
    create_contract,
    create_crew,
    create_lane,
    issue_pick_call,
    list_installments,
    move_clock,
    offer_contract,
    pay_installment,
    read_contract,
    read_grower,
    read_installment,
    record_grading,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_error,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
FIELD_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"
CLOSED_AT = "2026-08-28T09:00:00Z"

# One 20.000-net-ton load at 450000 cents a ton with a neutral grading: 9,000,000 cents of
# settled gross, a 0.5 % prompt-pay credit of 45,000 and a 5 % lien holdback of 450,000.
DELIVERED_TONS = 20.000
GROSS_WEIGHT_LBS = 57000
TARE_WEIGHT_LBS = 17000
SETTLED_GROSS_CENTS = 9_000_000
NET_PAYABLE_CENTS = 8_595_000
ONE_CENT_TOO_MUCH = NET_PAYABLE_CENTS + 1
A_PART_PAYMENT_CENTS = 4_000_000
THE_REMAINING_BALANCE_CENTS = NET_PAYABLE_CENTS - A_PART_PAYMENT_CENTS
DUE_AT = "2026-09-27T09:00:00Z"

# 2026-11-26T09:00:00Z is exactly the contract's 90 notice days after the close instant, so the
# notice length never competes with the lien for the refusal.
NINETY_DAYS_OUT = "2026-11-26T09:00:00Z"

NEUTRAL_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SPEC = {
    "spec_code": "CAB-STD-2026",
    "min_brix_accept": 20.0,
    "brix_bonus_start": 24.0,
    "brix_penalty_start": 22.0,
    "rot_rejection_pct": 8.0,
    "min_brix_pick_call": 21.0,
}
RIPE_SAMPLE = {
    "measured_brix": 24.5,
    "measured_ta_gl": 6.5,
    "measured_ph": 3.40,
    "measured_rot_pct": 1.0,
}


def _one_settled_contract_and_one_untouched_one() -> dict:
    """One producer with two ACTIVE agreements over the same block. The first takes a single
    clean load and is closed, leaving one lien-protected installment owing; the second has never
    seen a truck."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides=dict(SPEC),
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)
    ctx["lane"] = create_lane(
        lane_code="L1",
        daily_capacity_tons=80.000,
        turnaround_buffer_minutes=30,
        max_load_tons=40.000,
    )

    for key, code, end_vintage in (
        ("delivering", "GC-LIEN-C1", 2027),
        ("untouched", "GC-LIEN-C2", 2028),
    ):
        contract = create_contract(
            ctx["grower"]["id"],
            ctx["spec"]["id"],
            contract_code=code,
            contract_basis="TONNAGE",
            committed_tons=40.000,
            base_price_per_ton_cents=450000,
            over_delivery_policy="ACCEPT_AT_CONTRACT",
            term_start_vintage=2026,
            term_end_vintage=end_vintage,
            installment_plan=single_installment_plan(),
        )
        create_allocation(contract["id"], ctx["block"]["id"])
        offer_contract(contract["id"])
        ctx[key] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        ctx["delivering"]["id"],
        ctx["block"]["id"],
        ctx["crew"]["id"],
        FIELD_WINDOW[0],
        FIELD_WINDOW[1],
    )
    record_sampling_visit(visit["id"], **RIPE_SAMPLE)

    call = issue_pick_call(
        ctx["delivering"]["id"], ctx["block"]["id"], TARGET_PICK_AT, DELIVERED_TONS
    )
    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    appointment = book_appointment(
        call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], DELIVERED_TONS
    )

    move_clock(TRUCK_ARRIVES_AT)
    tag = capture_gross(
        appointment["id"],
        ctx["block"]["id"],
        GROSS_WEIGHT_LBS,
        appointment_version(appointment["id"]),
    )
    capture_tare(tag["id"], TARE_WEIGHT_LBS)
    record_grading(tag["id"], **NEUTRAL_READING)

    move_clock(CLOSED_AT)
    ctx["delivering"] = close_settlement(ctx["delivering"]["id"])
    ctx["installment"] = list_installments(contract_id=ctx["delivering"]["id"])[0]
    return ctx


def _serve_notice(api, contract_id: str, reason: str):
    return api.serve_termination_notice(
        contract_id, {"effective_at": NINETY_DAYS_OUT, "reason": reason}, MANAGER
    )


def test_the_close_leaves_the_producer_carrying_the_whole_net_payable(api):
    """The lien balance is the unpaid part of every lien-protected installment the producer has
    anywhere, and immediately after a close that is the entire net payable.

    PRD: "Every payment against a `lien_protected` installment recomputes the producer's
    `outstanding_lien_balance_cents`, which is the sum, over every installment of every contract
    of that producer whose `lien_protected` flag is true and whose status is `SCHEDULED`,
    `PARTIALLY_PAID` or `DELINQUENT`, of `planned_amount_cents` less `paid_amount_cents`."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()

    assert ctx["delivering"]["final_settlement_cents"] == SETTLED_GROSS_CENTS
    assert ctx["delivering"]["net_payable_cents"] == NET_PAYABLE_CENTS
    assert read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == NET_PAYABLE_CENTS


def test_the_single_installment_is_scheduled_for_the_whole_amount(api):
    """The one hundred per cent element takes the whole net payable, and its due date is counted
    from the close rather than from anything the plan was written against.

    PRD: "Each receives a `planned_amount_cents` of `net_payable_cents` multiplied by its own
    `pct_of_settlement` divided by 100, rounded half up to whole cents, and a `due_at` of
    `settlement_closed_at` plus its own `due_offset_days` days."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()

    installment = read_installment(ctx["installment"]["id"])
    assert installment["status"] == "SCHEDULED"
    assert installment["planned_amount_cents"] == NET_PAYABLE_CENTS
    assert installment["due_at"] == DUE_AT
    assert installment["lien_protected"] is True


def test_the_lien_blocks_a_termination_on_a_contract_that_never_took_a_load(api):
    """The second agreement has no delivery, no settlement and no installment of its own owing,
    and its termination is refused all the same — the balance consulted is the producer's.

    PRD: "That balance is producer-wide, so an unpaid lien-protected installment on a
    *different* contract of the same producer blocks the termination of this one."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()
    assert ctx["untouched"]["final_settlement_cents"] == 0

    validate_error(
        _serve_notice(api, ctx["untouched"]["id"], "Blocked by the lien on the other contract"),
        ApiErrorId.ERR_LIEN_OUTSTANDING.value,
        409,
    )


def test_a_single_cent_of_overpayment_is_refused_rather_than_clamped(api):
    """One cent past the balance is refused outright: the clerk is not allowed to overshoot and
    have the surplus quietly absorbed or spilled forward.

    PRD: "And the payment may not exceed what is still owed: `amount_cents` must be at most
    `planned_amount_cents` less `paid_amount_cents`, because an overpayment is refused outright
    rather than spilled into the next installment — the refusal is `ERR_PAYMENT_EXCEEDS_BALANCE`
    with HTTP 409."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()

    validate_error(
        api.create_payment(
            ctx["installment"]["id"], {"amount_cents": ONE_CENT_TOO_MUCH}, CLERK
        ),
        ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value,
        409,
    )
    assert read_installment(ctx["installment"]["id"])["paid_amount_cents"] == 0


def test_a_payment_that_leaves_a_balance_lands_in_the_partial_state(api):
    """Strictly less than the remaining balance means the installment is not finished with, and
    the lien on the contract has not been released.

    PRD: "When the payment leaves a balance still owing — that is, when `amount_cents` is
    strictly less than the remaining balance — the installment lands in `PARTIALLY_PAID`."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()

    paid = pay_installment(ctx["installment"]["id"], A_PART_PAYMENT_CENTS)
    assert paid["status"] == "PARTIALLY_PAID"
    assert paid["paid_amount_cents"] == A_PART_PAYMENT_CENTS
    assert read_contract(ctx["delivering"]["id"])["lien_released_at"] is None


def test_a_partial_payment_does_not_unlock_the_termination(api):
    """The gate is a zero balance and not a good-faith effort, so the remainder keeps the other
    agreement locked exactly as before.

    PRD: "and the producer's statutory lien must already be clear: `outstanding_lien_balance_cents`
    must be exactly 0, else `ERR_LIEN_OUTSTANDING` with HTTP 409."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()
    pay_installment(ctx["installment"]["id"], A_PART_PAYMENT_CENTS)
    assert (
        read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"]
        == THE_REMAINING_BALANCE_CENTS
    )

    validate_error(
        _serve_notice(api, ctx["untouched"]["id"], "Still blocked"),
        ApiErrorId.ERR_LIEN_OUTSTANDING.value,
        409,
    )


def test_settling_the_balance_releases_the_lien_and_closes_the_paid_contract(api):
    """The payment that clears the last cent stamps the release from the clock and carries the
    agreement out of the settled state, both cascades riding on the one call.

    PRD: "When the last outstanding `lien_protected` installment of a contract reaches `PAID`,
    the contract's `lien_released_at` is stamped from the logical clock — and it is stamped only
    when still null. When every installment of the contract has reached `PAID`, the contract
    itself transitions `SETTLED → CLOSED`, which is terminal."

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()
    pay_installment(ctx["installment"]["id"], A_PART_PAYMENT_CENTS)

    settled = pay_installment(ctx["installment"]["id"], THE_REMAINING_BALANCE_CENTS)
    assert settled["status"] == "PAID"
    assert settled["paid_amount_cents"] == NET_PAYABLE_CENTS

    contract = read_contract(ctx["delivering"]["id"])
    assert contract["lifecycle_status"] == "CLOSED"
    assert contract["lien_released_at"] == CLOSED_AT
    assert read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == 0


def test_with_the_lien_clear_the_other_contract_may_finally_be_terminated(api):
    """Nothing about the second agreement changed across the whole sequence; only the producer's
    balance did, and that is what was standing in the way.

    PRD: "The notice stores `termination_effective_at` from the `effective_at` input, sets
    `renewal_status` to `NOT_RENEWING`, and clears the harvest"

    Design: Corner/validations/producer_lien_is_grower_wide_and_overpayment_is_refused
    """
    ctx = _one_settled_contract_and_one_untouched_one()
    pay_installment(ctx["installment"]["id"], A_PART_PAYMENT_CENTS)
    pay_installment(ctx["installment"]["id"], THE_REMAINING_BALANCE_CENTS)

    served = validate_success(_serve_notice(api, ctx["untouched"]["id"], "Lien cleared"))
    assert served["lifecycle_status"] == "TERMINATION_PENDING"
    assert served["termination_effective_at"] == NINETY_DAYS_OUT
