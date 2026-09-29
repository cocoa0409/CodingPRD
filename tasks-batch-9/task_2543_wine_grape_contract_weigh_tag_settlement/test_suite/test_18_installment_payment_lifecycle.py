"""What happens to the money after the vintage closes: nothing is payable before the close,
the statutory lien falls as the protected rows are cleared, the contract bubbles shut on the
last cent, and a row nobody paid on time goes delinquent the instant after it was due.
"""
from test_helpers import (
    CLERK,
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
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"
CLOSED_AT = "2026-08-28T09:00:00Z"
PAYMENT_DAY = "2026-08-29T10:00:00Z"

FIRST_DUE_AT = "2026-09-27T09:00:00Z"
SECOND_DUE_AT = "2026-10-27T09:00:00Z"
ONE_SECOND_PAST_THE_DUE_INSTANT = "2026-09-27T09:00:01Z"

GROSS_LBS = 57000
TARE_LBS = 17000
LOAD_TONS = 20.000
CLEAN_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

# One clean 20.000-ton load at 450000 cents a ton, unadjusted.
SETTLED_GROSS_CENTS = 9000000
PROMPT_PAY_CREDIT_CENTS = 45000
LIEN_HOLDBACK_CENTS = 450000
NET_PAYABLE_CENTS = 8595000
HALF_OF_THE_NET_PAYABLE = 4297500
FIRST_PART_PAYMENT = 2000000
REST_OF_THE_HALF = HALF_OF_THE_NET_PAYABLE - FIRST_PART_PAYMENT

# Half protected by the statutory lien and half not, so the lien balance and the
# contract's own closure are driven by different rows.
HALF_PROTECTED_HALF_NOT = [
    {
        "installment_no": 1,
        "pct_of_settlement": 50.0,
        "due_offset_days": 30,
        "lien_protected": True,
    },
    {
        "installment_no": 2,
        "pct_of_settlement": 50.0,
        "due_offset_days": 60,
        "lien_protected": False,
    },
]

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
LANE = {
    "lane_code": "L1",
    "daily_capacity_tons": 80.000,
    "turnaround_buffer_minutes": 30,
    "max_load_tons": 40.0,
}
TONNAGE_TERMS = {
    "contract_basis": "TONNAGE",
    "base_price_per_ton_cents": 450000,
    "committed_tons": 40.000,
    "over_delivery_policy": "ACCEPT_AT_CONTRACT",
    "term_start_vintage": 2026,
    "term_end_vintage": 2026,
}


def _an_active_contract_with_no_fruit_delivered(contract_code: str) -> dict:
    """An ACTIVE TONNAGE contract on a single 100-percent lien-protected installment, with
    no weigh tags and no close."""
    move_clock(CLOCK_PINNED_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code=contract_code,
        installment_plan=single_installment_plan(),
        **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])
    ctx["installments"] = list_installments(contract_id=contract["id"])
    return ctx


def _a_settled_vintage(contract_code: str, installment_plan: list) -> dict:
    """One clean 20.000-ton load delivered, graded and settled at 2026-08-28T09:00:00Z."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["lane"] = create_lane(**LANE)
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code=contract_code,
        installment_plan=installment_plan,
        **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], SAMPLING_WINDOW[0], SAMPLING_WINDOW[1]
    )
    record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    call = issue_pick_call(contract["id"], ctx["block"]["id"], TARGET_PICK_AT, LOAD_TONS)
    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    appointment = book_appointment(call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], LOAD_TONS)

    move_clock(TRUCK_ARRIVES_AT)
    tag = capture_gross(
        appointment["id"], ctx["block"]["id"], GROSS_LBS, appointment_version(appointment["id"])
    )
    capture_tare(tag["id"], TARE_LBS)
    record_grading(tag["id"], **CLEAN_READING)

    move_clock(CLOSED_AT)
    ctx["contract"] = close_settlement(contract["id"])
    ctx["installments"] = list_installments(contract_id=contract["id"])
    return ctx


# --- Nothing is payable before the vintage closes ----------------------------------


def test_acceptance_creates_the_installment_as_an_empty_shell(api):
    """The plan became a row the moment the producer accepted, but it carries no money and
    no due date until a close fills it in.

    PRD: "one installment row is created for each element of `installment_plan`, copying
    `installment_no`, `pct_of_settlement`, `due_offset_days` and `lien_protected` verbatim,
    each starting in status `PENDING_SETTLEMENT` with `planned_amount_cents` 0 and
    `paid_amount_cents` 0."

    Design: Corner/state_machines/paying_an_installment_before_settlement_close_is_rejected_409
    """
    ctx = _an_active_contract_with_no_fruit_delivered("GC-EARLYPAY")

    assert len(ctx["installments"]) == 1
    installment = ctx["installments"][0]
    assert installment["status"] == "PENDING_SETTLEMENT"
    assert installment["planned_amount_cents"] == 0
    assert installment["paid_amount_cents"] == 0
    assert installment["lien_protected"] is True


def test_a_payment_against_that_shell_is_refused(api):
    """The clerk cannot pay ahead of the close: only the three post-close statuses admit a
    payment, and this row is in none of them.

    PRD: "The installment must be payable — its status must be `SCHEDULED`, `PARTIALLY_PAID`
    or `DELINQUENT`; an installment still in `PENDING_SETTLEMENT`, or already `PAID`, yields
    `ERR_INSTALLMENT_NOT_PAYABLE` with HTTP 409."

    Design: Corner/state_machines/paying_an_installment_before_settlement_close_is_rejected_409
    """
    ctx = _an_active_contract_with_no_fruit_delivered("GC-EARLYPAY")

    validate_error(
        api.create_payment(ctx["installments"][0]["id"], {"amount_cents": 1000}, CLERK),
        ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value,
        409,
    )


def test_the_refused_payment_left_the_row_and_the_lien_alone(api):
    """The refusal wrote nothing: the row is still an empty shell, and the producer is owed
    nothing yet even though the row is lien-protected.

    PRD: "Every payment against a `lien_protected` installment recomputes the producer's
    `outstanding_lien_balance_cents`, which is the sum, over every installment of every
    contract of that producer whose `lien_protected` flag is true and whose status is
    `SCHEDULED`, `PARTIALLY_PAID` or `DELINQUENT`, of `planned_amount_cents` less
    `paid_amount_cents`."

    Design: Corner/state_machines/paying_an_installment_before_settlement_close_is_rejected_409
    """
    ctx = _an_active_contract_with_no_fruit_delivered("GC-EARLYPAY")
    api.create_payment(ctx["installments"][0]["id"], {"amount_cents": 1000}, CLERK)

    installment = read_installment(ctx["installments"][0]["id"])
    assert installment["status"] == "PENDING_SETTLEMENT"
    assert installment["paid_amount_cents"] == 0
    assert installment["planned_amount_cents"] == 0
    assert installment["due_at"] is None
    assert read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == 0


# --- The last cent of the last installment closes the contract ---------------------


def _a_settled_vintage_split_in_two_halves() -> dict:
    """The 50/50 plan settled and the clock moved to the day payments start."""
    ctx = _a_settled_vintage("GC-BUBBLE", HALF_PROTECTED_HALF_NOT)
    move_clock(PAYMENT_DAY)
    ctx["first"], ctx["second"] = ctx["installments"][0], ctx["installments"][1]
    return ctx


def test_the_close_prices_the_vintage_through_the_whole_money_pipeline(api):
    """The settled gross lands in the 0.5-percent prompt-payment band, and both the credit
    and the statutory holdback are struck on that pre-credit figure.

    PRD: "Step two looks up a prompt-payment tier **on that pre-credit total**: below
    5,000,000 cents the rate is 0.0 percent; from 5,000,000 up to but not including 10,000,000
    cents it is 0.5 percent; from 10,000,000 up to but not including 15,000,000 cents it is 1.0
    percent; and at or above 15,000,000 cents it is 1.5 percent."

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()

    assert ctx["contract"]["final_settlement_cents"] == SETTLED_GROSS_CENTS
    assert ctx["contract"]["prompt_pay_credit_cents"] == PROMPT_PAY_CREDIT_CENTS
    assert ctx["contract"]["lien_holdback_cents"] == LIEN_HOLDBACK_CENTS
    assert ctx["contract"]["net_payable_cents"] == NET_PAYABLE_CENTS


def test_the_two_halves_split_the_net_payable_exactly(api):
    """Two 50-percent rows on an even net payable leave no residual to absorb, and each row
    is dated from the close by its own offset.

    PRD: "After every close, the sum of the installments' `planned_amount_cents` equals
    `net_payable_cents` exactly."

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()

    assert [row["planned_amount_cents"] for row in ctx["installments"]] == [
        HALF_OF_THE_NET_PAYABLE,
        HALF_OF_THE_NET_PAYABLE,
    ]
    assert sum(row["planned_amount_cents"] for row in ctx["installments"]) == NET_PAYABLE_CENTS
    assert [row["due_at"] for row in ctx["installments"]] == [FIRST_DUE_AT, SECOND_DUE_AT]
    assert [row["status"] for row in ctx["installments"]] == ["SCHEDULED", "SCHEDULED"]


def test_only_the_protected_half_stands_behind_the_statutory_lien(api):
    """Half the money is lien-protected and half is not, so the producer's lien balance is
    one installment's worth rather than the whole net payable.

    PRD: "The close also stamps `settlement_closed_at` from the logical clock, flips every
    `PROVISIONAL` line to `FINAL`, transitions every installment `PENDING_SETTLEMENT →
    SCHEDULED`, recomputes the producer's `outstanding_lien_balance_cents`, and withdraws the
    harvest"

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()

    assert ctx["first"]["lien_protected"] is True
    assert ctx["second"]["lien_protected"] is False
    assert (
        read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"]
        == HALF_OF_THE_NET_PAYABLE
    )


def test_a_part_payment_leaves_the_row_partly_paid_and_lowers_the_lien(api):
    """Two million against a 4,297,500 balance is short of it, so the row stays open and the
    lien falls by exactly what was paid.

    PRD: "When the payment leaves a balance still owing — that is, when `amount_cents` is
    strictly less than the remaining balance — the installment lands in `PARTIALLY_PAID`."

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()

    paid = pay_installment(ctx["first"]["id"], FIRST_PART_PAYMENT)
    assert paid["status"] == "PARTIALLY_PAID"
    assert paid["paid_amount_cents"] == FIRST_PART_PAYMENT
    assert (
        read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == REST_OF_THE_HALF
    )
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "SETTLED"


def test_clearing_the_protected_row_releases_the_lien_without_closing_the_contract(api):
    """The last protected installment is paid, so the lien is stamped released — but the
    unprotected half is still outstanding and the contract stays settled.

    PRD: "When the last outstanding `lien_protected` installment of a contract reaches
    `PAID`, the contract's `lien_released_at` is stamped from the logical clock — and it is
    stamped only when still null."

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()
    pay_installment(ctx["first"]["id"], FIRST_PART_PAYMENT)

    cleared = pay_installment(ctx["first"]["id"], REST_OF_THE_HALF)
    assert cleared["status"] == "PAID"
    assert cleared["paid_amount_cents"] == HALF_OF_THE_NET_PAYABLE

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "SETTLED"
    assert contract["lien_released_at"] == PAYMENT_DAY
    assert read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == 0


def test_part_paying_the_unprotected_row_moves_neither_the_lien_nor_the_contract(api):
    """The second row is not lien-protected and not finished, so the only thing that changes
    is that row.

    PRD: "Each accepted payment increases `paid_amount_cents` by `amount_cents`."

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()
    pay_installment(ctx["first"]["id"], FIRST_PART_PAYMENT)
    pay_installment(ctx["first"]["id"], REST_OF_THE_HALF)

    partly = pay_installment(ctx["second"]["id"], REST_OF_THE_HALF)
    assert partly["status"] == "PARTIALLY_PAID"
    assert read_contract(ctx["contract"]["id"])["lifecycle_status"] == "SETTLED"
    assert read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == 0


def test_the_final_payment_bubbles_the_contract_shut(api):
    """Every installment is paid, so the contract itself reaches its terminal state — and the
    release stamp is not rewritten with the later instant.

    PRD: "When every installment of the contract has reached `PAID`, the contract itself
    transitions `SETTLED → CLOSED`, which is terminal; `lien_released_at` is stamped on that
    transition too if it is still null."

    Design: Corner/state_machines/final_installment_payment_bubbles_the_contract_from_settled_to_closed
    """
    ctx = _a_settled_vintage_split_in_two_halves()
    pay_installment(ctx["first"]["id"], FIRST_PART_PAYMENT)
    pay_installment(ctx["first"]["id"], REST_OF_THE_HALF)
    pay_installment(ctx["second"]["id"], REST_OF_THE_HALF)

    finished = pay_installment(ctx["second"]["id"], FIRST_PART_PAYMENT)
    assert finished["status"] == "PAID"

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "CLOSED"
    assert contract["lien_released_at"] == PAYMENT_DAY

    rows = list_installments(contract_id=ctx["contract"]["id"])
    assert [row["status"] for row in rows] == ["PAID", "PAID"]
    assert sum(row["paid_amount_cents"] for row in rows) == NET_PAYABLE_CENTS


# --- A row nobody paid goes delinquent one second after it was due ------------------


def _a_single_installment_waiting_to_be_paid() -> dict:
    """The whole net payable on one lien-protected row due thirty days after the close."""
    ctx = _a_settled_vintage("GC-DELINQ", single_installment_plan())
    ctx["installment"] = ctx["installments"][0]
    return ctx


def test_the_close_scheduled_the_whole_net_payable_on_one_row(api):
    """A single 100-percent installment takes everything, dated thirty days from the close
    instant.

    PRD: "The contract's installments, all of them still in `PENDING_SETTLEMENT`, are taken in
    ascending `installment_no` — an order materialised from the `installment_plan` array and
    never derived from any identifier."

    Design: Corner/state_machines/scheduled_installment_turns_delinquent_only_after_the_due_instant_passes
    """
    ctx = _a_single_installment_waiting_to_be_paid()

    assert ctx["installment"]["status"] == "SCHEDULED"
    assert ctx["installment"]["planned_amount_cents"] == NET_PAYABLE_CENTS
    assert ctx["installment"]["due_at"] == FIRST_DUE_AT


def test_at_the_due_instant_exactly_the_row_is_still_merely_scheduled(api):
    """Being due is not being late: the delinquency edge needs the clock strictly past the
    due instant, so arriving on it changes nothing.

    PRD: "When the logical clock advances strictly past an installment's `due_at` while its
    `paid_amount_cents` is still below its `planned_amount_cents`, the installment transitions
    to `DELINQUENT` — reachable from both `SCHEDULED` and `PARTIALLY_PAID` — and remains
    payable from there."

    Design: Corner/state_machines/scheduled_installment_turns_delinquent_only_after_the_due_instant_passes
    """
    ctx = _a_single_installment_waiting_to_be_paid()

    move_clock(FIRST_DUE_AT)
    assert read_installment(ctx["installment"]["id"])["status"] == "SCHEDULED"


def test_one_second_later_the_unpaid_row_is_delinquent(api):
    """Nobody called anything; the clock moving past the due instant on an unpaid row is the
    whole trigger, and it does not touch the amounts.

    PRD: "An installment that is not paid on time is not forgiven."

    Design: Corner/state_machines/scheduled_installment_turns_delinquent_only_after_the_due_instant_passes
    """
    ctx = _a_single_installment_waiting_to_be_paid()

    move_clock(ONE_SECOND_PAST_THE_DUE_INSTANT)
    installment = read_installment(ctx["installment"]["id"])
    assert installment["status"] == "DELINQUENT"
    assert installment["paid_amount_cents"] == 0
    assert installment["planned_amount_cents"] == NET_PAYABLE_CENTS


def test_a_late_row_paid_in_full_goes_straight_to_paid(api):
    """The delinquent row is still payable, and one payment for the whole balance skips the
    partly-paid state entirely.

    PRD: "When the payment settles the remaining balance exactly, the installment reaches
    `PAID`, and that same edge is available directly from `SCHEDULED` or `DELINQUENT` when a
    single payment clears the whole remaining balance in one call."

    Design: Corner/state_machines/scheduled_installment_turns_delinquent_only_after_the_due_instant_passes
    """
    ctx = _a_single_installment_waiting_to_be_paid()
    move_clock(ONE_SECOND_PAST_THE_DUE_INSTANT)

    paid = pay_installment(ctx["installment"]["id"], NET_PAYABLE_CENTS)
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == NET_PAYABLE_CENTS


def test_the_late_payment_still_closes_the_contract_and_clears_the_lien(api):
    """Lateness costs the producer nothing structural: the same two cascades ride on the
    payment, stamped from the clock as it now reads.

    PRD: "Two cascades ride on the final payment."

    Design: Corner/state_machines/scheduled_installment_turns_delinquent_only_after_the_due_instant_passes
    """
    ctx = _a_single_installment_waiting_to_be_paid()
    move_clock(ONE_SECOND_PAST_THE_DUE_INSTANT)
    pay_installment(ctx["installment"]["id"], NET_PAYABLE_CENTS)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "CLOSED"
    assert contract["lien_released_at"] == ONE_SECOND_PAST_THE_DUE_INSTANT
    assert read_grower(ctx["grower"]["id"])["outstanding_lien_balance_cents"] == 0
