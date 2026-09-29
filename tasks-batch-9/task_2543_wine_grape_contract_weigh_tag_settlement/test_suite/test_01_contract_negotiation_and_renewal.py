"""Contract negotiation as a genuine cycle, its round ceiling, and the renewal
dimension that advances independently of the lifecycle."""
from test_helpers import (
    MANAGER,
    ApiErrorId,
    accept_contract,
    counter_contract,
    create_allocation,
    create_contract,
    move_clock,
    offer_contract,
    read_contract,
    setup_reference_book,
    single_installment_plan,
    validate_error,
)

NEGOTIATION_START = "2026-08-20T08:00:00Z"
RENEWAL_WINDOW_OPENS_AT = "2027-08-03T00:00:00Z"
RENEWAL_WINDOW_CLOSES_AT = "2027-11-01T00:00:00Z"


def _two_negotiations() -> dict:
    """One producer with two contracts on the same block: `negotiated` walks the
    offer/counter cycle three times and is then accepted, while `stuck` exhausts its
    three rounds and stays on the table."""
    move_clock(NEGOTIATION_START)
    ctx = setup_reference_book()
    grower_id, block_id, spec_id = ctx["grower"]["id"], ctx["block"]["id"], ctx["spec"]["id"]

    negotiated = create_contract(
        grower_id,
        spec_id,
        contract_basis="TONNAGE",
        base_price_per_ton_cents=450000,
        committed_tons=40.000,
        over_delivery_policy="ACCEPT_AT_SPOT",
        term_start_vintage=2026,
        term_end_vintage=2027,
        termination_notice_days=90,
        evergreen_flag=False,
        installment_plan=single_installment_plan(),
    )
    create_allocation(negotiated["id"], block_id)
    stuck = create_contract(
        grower_id,
        spec_id,
        contract_basis="TONNAGE",
        base_price_per_ton_cents=450000,
        committed_tons=10.000,
        over_delivery_policy="REJECT",
        term_start_vintage=2026,
        term_end_vintage=2027,
        installment_plan=single_installment_plan(),
    )
    create_allocation(stuck["id"], block_id)

    for counter_price in (460000, 470000):
        offer_contract(negotiated["id"])
        counter_contract(negotiated["id"], grower_id, counter_price)
    offer_contract(negotiated["id"])

    for counter_price in (455000, 456000, 457000):
        offer_contract(stuck["id"])
        counter_contract(stuck["id"], grower_id, counter_price)

    ctx["negotiated"] = read_contract(negotiated["id"])
    ctx["stuck"] = read_contract(stuck["id"])
    return ctx


def test_offer_counter_cycle_revisits_offered_and_records_the_latest_counter():
    """Three offers separated by two counters leave the contract back in `OFFERED`
    with `offer_round` 3 and the producer's last price on the row.

    PRD: "Countering drives `OFFERED → COUNTERED`, is permitted only to the `Grower`
    whose identifier matches the contract's `grower_id`, and requires a
    `counter_base_price_per_ton_cents` in the body, which is stored on the contract as
    `countered_price_per_ton_cents`."

    Design: Difficulty/non_linear_state_machine/grape_contract_cyclic_negotiation_with_independent_renewal_dimension
    """
    ctx = _two_negotiations()

    assert ctx["negotiated"]["lifecycle_status"] == "OFFERED"
    assert ctx["negotiated"]["offer_round"] == 3
    assert ctx["negotiated"]["countered_price_per_ton_cents"] == 470000


def test_accepting_the_third_offer_activates_the_contract_and_derives_its_caps():
    """Acceptance ends the cycle and derives the tonnage envelope from the committed
    40.000 tons and the default 10.0 percent over-delivery tolerance.

    PRD: "In every case, `hard_cap_tons` is `contract_cap_tons` multiplied by one plus
    `over_delivery_tolerance_pct` divided by 100, rounded half up to 3 decimals."

    Design: Difficulty/non_linear_state_machine/grape_contract_cyclic_negotiation_with_independent_renewal_dimension
    """
    ctx = _two_negotiations()
    contract = accept_contract(ctx["negotiated"]["id"], ctx["grower"]["id"])

    assert contract["lifecycle_status"] == "ACTIVE"
    assert float(contract["contract_cap_tons"]) == 40.000
    assert float(contract["hard_cap_tons"]) == 44.000
    assert contract["cap_scope"] == "PER_CONTRACT"


def test_acceptance_leaves_renewal_not_due_with_a_fully_derived_window():
    """The renewal window is derived at acceptance from the term's final vintage and
    the 90-day termination notice, yet the renewal dimension itself has not moved.

    PRD: "`renewal_window_closes_at` becomes midnight UTC on the first of November of
    the year given by `term_end_vintage` (the year, then `-11-01T00:00:00Z`), and
    `renewal_window_opens_at` becomes that closing instant less
    `termination_notice_days` days."

    Design: Difficulty/non_linear_state_machine/grape_contract_cyclic_negotiation_with_independent_renewal_dimension
    """
    ctx = _two_negotiations()
    contract = accept_contract(ctx["negotiated"]["id"], ctx["grower"]["id"])

    assert contract["renewal_status"] == "NOT_DUE"
    assert contract["renewal_window_opens_at"] == RENEWAL_WINDOW_OPENS_AT
    assert contract["renewal_window_closes_at"] == RENEWAL_WINDOW_CLOSES_AT


def test_fourth_offer_is_refused_and_the_negotiation_stays_countered(api):
    """A contract that has already been offered three times cannot be offered again;
    the refusal leaves both the round counter and the lifecycle exactly where they were.

    PRD: "The fourth attempt is therefore refused with `ERR_MAX_OFFER_ROUNDS_EXCEEDED`
    and HTTP 409, which is what makes the `OFFERED → COUNTERED → OFFERED` loop
    terminate."

    Design: Difficulty/non_linear_state_machine/grape_contract_cyclic_negotiation_with_independent_renewal_dimension
    """
    ctx = _two_negotiations()

    response = api.offer_contract(ctx["stuck"]["id"], MANAGER)
    validate_error(response, ApiErrorId.ERR_MAX_OFFER_ROUNDS_EXCEEDED.value, 409)

    stuck = read_contract(ctx["stuck"]["id"])
    assert stuck["offer_round"] == 3
    assert stuck["lifecycle_status"] == "COUNTERED"


def test_clock_reaching_the_window_opens_renewal_without_moving_the_lifecycle():
    """Advancing the clock to the derived opening instant flips the renewal dimension
    while the contract keeps trading as `ACTIVE`.

    PRD: "All three of those edges are fired by the logical clock, not by a client:
    they require the lifecycle to be `ACTIVE` and the clock to have moved into the
    half-open interval that begins at `renewal_window_opens_at` and ends strictly
    before `renewal_window_closes_at`."

    Design: Difficulty/non_linear_state_machine/grape_contract_cyclic_negotiation_with_independent_renewal_dimension
    """
    ctx = _two_negotiations()
    contract = accept_contract(ctx["negotiated"]["id"], ctx["grower"]["id"])
    move_clock(RENEWAL_WINDOW_OPENS_AT)

    contract = read_contract(contract["id"])
    assert contract["renewal_status"] == "RENEWAL_WINDOW_OPEN"
    assert contract["lifecycle_status"] == "ACTIVE"


def test_a_contract_still_on_the_table_never_opens_its_renewal_window():
    """The same clock advance leaves the `COUNTERED` contract at `NOT_DUE`, because the
    clock-driven renewal edge demands an `ACTIVE` lifecycle.

    PRD: "they require the lifecycle to be `ACTIVE` and the clock to have moved into
    the half-open interval that begins at `renewal_window_opens_at` and ends strictly
    before `renewal_window_closes_at`."

    Design: Difficulty/non_linear_state_machine/grape_contract_cyclic_negotiation_with_independent_renewal_dimension
    """
    ctx = _two_negotiations()
    accept_contract(ctx["negotiated"]["id"], ctx["grower"]["id"])
    move_clock(RENEWAL_WINDOW_OPENS_AT)

    stuck = read_contract(ctx["stuck"]["id"])
    assert stuck["lifecycle_status"] == "COUNTERED"
    assert stuck["renewal_status"] == "NOT_DUE"
