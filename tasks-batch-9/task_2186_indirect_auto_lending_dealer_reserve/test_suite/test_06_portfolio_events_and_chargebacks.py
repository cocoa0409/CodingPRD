"""Portfolio events, the reserve chargeback, and the early-payoff cascade."""
from test_helpers import (
    ADMIN, ApiErrorId, CLOCK_START, api_client, assert_chargeback_event,
    post_reserve_adjustment, read_application, read_contract, read_dealer,
    record_chargeback_event, set_clock, setup_funded_contract, setup_program,
    submit_application, validate_error, validate_paginated, validate_success,
)


def test_earned_to_date_variant_prorates_over_elapsed_seasoning(api):
    """PRD 3.5: "The **earned-to-date** variant, which runs on every portfolio event
    in §3.6, uses that event's `months_seasoned` instead; it values participation over
    elapsed seasoning only and is written to `earned_to_date_reserve_cents` on the
    event record as a disclosure figure."
    PRD 3.5: "It is never posted to the ledger, and for the same contract it is
    deliberately **not** equal to `reserve_accrued_cents` less
    `participation_chargeback_cents`, because the chargeback prorates over the
    agreement's chargeback window while this variant prorates over the contract's
    term."
    PRD 3.6: "The event's `months_seasoned` is the number of whole days between the
    contract's `funded_at` and the `event_date`, divided by 30 and rounded down to a
    whole number."

    Design: Difficulty/dual_variant_calc/reserve_scheduled_yield_vs_earned_to_date_on_contract
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-k1")
    contract_id = funded["contract"]["id"]
    assert funded["contract"]["reserve_accrued_cents"] == 154055
    assert funded["contract"]["incentive_accrued_cents"] == 7003

    set_clock("2027-02-01T00:00:00Z")
    response = api.create_chargeback_event(
        contract_id,
        {"event_type": "EARLY_PAYOFF", "event_date": "2027-02-01T00:00:00Z"},
        ADMIN,
    )
    event = validate_success(response, 201)
    assert_chargeback_event(event)

    assert event["months_seasoned"] == 6
    assert event["window_months"] == 12
    assert event["participation_chargeback_cents"] == 77028
    assert event["earned_to_date_reserve_cents"] == 15406
    assert event["earned_to_date_reserve_cents"] != (
        154055 - event["participation_chargeback_cents"]
    ), "the two figures prorate over different denominators"


def test_each_accrual_entry_is_rounded_before_the_two_are_summed(api):
    """PRD 3.6: "That fraction is then applied to each of the contract's two
    positive accrual entries **separately**, and each product is rounded half up to
    whole cents **on its own, before the two are added together** — summing first and
    rounding once produces a different and wrong figure."
    PRD 3.6: "`participation_chargeback_cents` is the rounded product of the
    contract's `PARTICIPATION_ACCRUAL` entry's `amount_cents` and the unearned
    fraction; `incentive_chargeback_cents` is the rounded product of the contract's
    `INCENTIVE_ACCRUAL` entry's `amount_cents` and the same fraction; and the two are
    processed in that fixed order."

    Design: Difficulty/combinatorial_formula/chargeback_per_entry_rounding_before_sum
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-cb")
    set_clock("2027-02-01T00:00:00Z")

    event = record_chargeback_event(
        funded["contract"]["id"], "EARLY_PAYOFF", "2027-02-01T00:00:00Z"
    )
    assert event["participation_chargeback_cents"] == 77028
    assert event["incentive_chargeback_cents"] == 3502
    assert event["chargeback_total_cents"] == 80530
    assert event["chargeback_total_cents"] != 80529, (
        "summing the two accruals before rounding would give 80529"
    )


def test_the_chargeback_entry_moves_the_dealer_ledger_by_the_rounded_total(api):
    """PRD 3.6: "The contract's `reserve_status` advances `ACCRUED → CHARGED_BACK`,
    and a single ledger entry of `entry_type` `CHARGEBACK` is posted for the negative
    of `chargeback_total_cents`, with the dealership's `chargeback_count` increasing
    by one, `reserve_balance_cents` recomputed, and `scorecard_stale` set to true —
    the dealership's published grade no longer reflects its ledger."

    Design: Difficulty/combinatorial_formula/chargeback_per_entry_rounding_before_sum
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-cb2")
    set_clock("2027-02-01T00:00:00Z")

    record_chargeback_event(
        funded["contract"]["id"], "EARLY_PAYOFF", "2027-02-01T00:00:00Z"
    )

    entries, meta = validate_paginated(
        api.list_reserve_entries(
            ADMIN,
            params={"dealer_id": program["dealer_id"], "entry_type": "CHARGEBACK"},
        )
    )
    assert meta["total_count"] == 1
    assert entries[0]["amount_cents"] == -80530

    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 80528
    assert dealer["chargeback_count"] == 1
    assert dealer["scorecard_stale"] is True
    assert read_contract(funded["contract"]["id"])["reserve_status"] == "CHARGED_BACK"


def test_a_payoff_at_exactly_the_window_length_earns_the_reserve(api):
    """PRD 3.6: "`within_window` is true when `months_seasoned` is **strictly less
    than** `window_months`, and false otherwise — a contract that seasons to exactly
    the window length has escaped it."
    PRD 3.6: "When `within_window` is false, nothing is clawed back:
    `participation_chargeback_cents`, `incentive_chargeback_cents`, and
    `chargeback_total_cents` are all zero, no ledger entry of any kind is created, and
    the contract's `reserve_status` advances `ACCRUED → EARNED`."
    PRD 3.6: "When `payoff_months_seasoned` is **strictly less than** twelve months,
    the dealership's `early_payoff_count` increases by one — a payoff at exactly twelve
    months of seasoning is not early and does not count."

    Design: Corner/state_machines/payoff_outside_chargeback_window_marks_reserve_earned
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-ew")
    set_clock("2027-08-05T00:00:00Z")

    event = record_chargeback_event(
        funded["contract"]["id"], "EARLY_PAYOFF", "2027-08-05T00:00:00Z"
    )
    assert event["months_seasoned"] == 12
    assert event["window_months"] == 12
    assert event["within_window"] is False
    assert event["participation_chargeback_cents"] == 0
    assert event["incentive_chargeback_cents"] == 0
    assert event["chargeback_total_cents"] == 0

    contract = read_contract(funded["contract"]["id"])
    assert contract["reserve_status"] == "EARNED"
    assert contract["funding_status"] == "PAID_OFF"

    dealer = read_dealer(program["dealer_id"])
    assert dealer["reserve_balance_cents"] == 161058
    assert dealer["chargeback_count"] == 0
    assert dealer["early_payoff_count"] == 0
    assert dealer["status"] == "ACTIVE"


def test_an_event_dated_before_funding_is_refused(api):
    """PRD 3.6: "the `event_date` must be at or after the contract's `funded_at`.
    Equality is accepted and simply yields a seasoning of zero; an earlier date is
    refused with `ERR_INVALID_EVENT_DATE` (HTTP 422)."

    Design: Corner/validations/chargeback_event_dated_before_funding_returns_invalid_event_date
    """
    program = setup_program()
    funded = setup_funded_contract(program, doc_prefix="IMG-ed")

    response = api.create_chargeback_event(
        funded["contract"]["id"],
        {"event_type": "DEFAULT", "event_date": "2026-07-15T00:00:00Z"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_EVENT_DATE.value, 422)

    _, meta = validate_paginated(
        api.list_chargeback_events(funded["contract"]["id"], ADMIN)
    )
    assert meta["total_count"] == 0
    contract = read_contract(funded["contract"]["id"])
    assert contract["funding_status"] == "FUNDED"
    assert contract["reserve_status"] == "ACCRUED"


def _setup_two_funded_contracts_and_an_open_file(program):
    """Two funded contracts plus one application left in SUBMITTED."""
    first = setup_funded_contract(
        program,
        application_overrides={"applicant_reference": "APP-c1"},
        doc_prefix="IMG-c1",
    )
    second = setup_funded_contract(
        program,
        application_overrides={
            "applicant_reference": "APP-c2", "monthly_debt_cents": 180000,
            "amount_financed_cents": 1000000, "collateral_value_cents": 1000000,
        },
        doc_prefix="IMG-c2",
    )
    open_file = submit_application(
        program["dealer_id"], applicant_reference="APP-hold",
        monthly_debt_cents=180000, amount_financed_cents=1000000,
        collateral_value_cents=1000000,
    )
    return first, second, open_file


def test_early_payoff_claws_back_reserve_and_counts_the_payoff(api):
    """PRD 3.6: "An `EARLY_PAYOFF` event advances the contract `FUNDED → PAID_OFF`.
    Its `months_seasoned` and its `payoff_months_seasoned` are both set to the
    seasoning computed above."
    PRD 3.6: "When `payoff_months_seasoned` is **strictly less than** twelve months,
    the dealership's `early_payoff_count` increases by one — a payoff at exactly twelve
    months of seasoning is not early and does not count."

    Design: Difficulty/transitive_cascade/early_payoff_cascade_to_dealer_suspension_and_application_hold
    """
    program = setup_program()
    first, second, _ = _setup_two_funded_contracts_and_an_open_file(program)
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 218558
    set_clock("2027-02-01T00:00:00Z")

    event = record_chargeback_event(first["contract"]["id"], "EARLY_PAYOFF",
                                    "2027-02-01T00:00:00Z")
    assert event["chargeback_total_cents"] == 80530

    contract = read_contract(first["contract"]["id"])
    assert contract["funding_status"] == "PAID_OFF"
    assert contract["payoff_months_seasoned"] == 6
    assert contract["reserve_status"] == "CHARGED_BACK"

    dealer = read_dealer(program["dealer_id"])
    assert dealer["early_payoff_count"] == 1
    assert dealer["chargeback_count"] == 1
    assert dealer["reserve_balance_cents"] == 138028
    assert read_contract(second["contract"]["id"])["funding_status"] == "FUNDED"


def test_the_early_payoff_rate_breach_suspends_and_holds_open_files(api):
    """PRD 3.6: "when the dealership is `ACTIVE`, its `total_funded_ever_count` is
    at least 2, and its recomputed `early_payoff_rate_bps` is at or above 3000 — thirty
    percent of everything it has ever funded having paid off inside the first year —
    the dealership advances `ACTIVE → SUSPENDED` with `suspension_reason` set to the
    sentinel `AUTO_EARLY_PAYOFF_RATE`, and every one of its applications in
    `SUBMITTED`, `CONDITIONED`, `RESUBMITTED`, or `APPROVED` captures its current
    status into `held_from_status` and moves to `ON_HOLD`."
    PRD 2.8: "when `total_funded_ever_count` is greater than zero, it is ten thousand
    multiplied by `early_payoff_count`, divided by `total_funded_ever_count`, rounded
    half up to a whole number of basis points"

    Design: Difficulty/transitive_cascade/early_payoff_cascade_to_dealer_suspension_and_application_hold
    """
    program = setup_program()
    first, second, open_file = _setup_two_funded_contracts_and_an_open_file(program)
    set_clock("2027-02-01T00:00:00Z")

    record_chargeback_event(first["contract"]["id"], "EARLY_PAYOFF",
                            "2027-02-01T00:00:00Z")

    dealer = read_dealer(program["dealer_id"])
    assert dealer["early_payoff_rate_bps"] == 5000
    assert dealer["status"] == "SUSPENDED"
    assert dealer["suspension_reason"] == "AUTO_EARLY_PAYOFF_RATE"
    assert dealer["outstanding_principal_cents"] == 1000000
    assert dealer["funded_contract_count"] == 1

    held = read_application(open_file["id"])
    assert held["status"] == "ON_HOLD"
    assert held["held_from_status"] == "SUBMITTED"
    assert read_contract(second["contract"]["id"])["funding_status"] == "FUNDED"


def test_an_immediate_payoff_returns_the_ledger_to_its_pre_funding_balance(api):
    """PRD 3.6: "When `within_window` is true, the unearned fraction is
    `window_months` less `months_seasoned`, divided by `window_months`, and it is
    carried as an exact ratio rather than being rounded."
    PRD 2.8: "`reserve_balance_cents` is the signed sum of `amount_cents` across
    every ledger entry whose `dealer_id` is this dealership's, taken over all entry
    types, and it is recomputed on every ledger posting."

    Design: Difficulty/compensating_invariant/fund_then_immediate_chargeback_conserves_reserve_balance
    """
    program = setup_program()
    opening = post_reserve_adjustment(program["dealer_id"], 50000)
    assert opening["balance_after_cents"] == 50000

    funded = setup_funded_contract(program, doc_prefix="IMG-inv")
    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 211058

    event = record_chargeback_event(
        funded["contract"]["id"], "EARLY_PAYOFF", CLOCK_START
    )
    assert event["months_seasoned"] == 0
    assert event["within_window"] is True
    assert event["participation_chargeback_cents"] == 154055
    assert event["incentive_chargeback_cents"] == 7003
    assert event["chargeback_total_cents"] == 161058

    assert read_dealer(program["dealer_id"])["reserve_balance_cents"] == 50000, (
        "exactly the pre-funding value"
    )


def test_the_contract_own_ledger_entries_sum_to_zero_after_full_clawback(api):
    """PRD 2.11: "Each `ReserveEntry` names the `dealer_id` whose ledger it moves
    and, for contract-attributable movements, the `contract_id` it belongs to."
    PRD 3.6: "The contract's `reserve_status` advances `ACCRUED → CHARGED_BACK`, and
    a single ledger entry of `entry_type` `CHARGEBACK` is posted for the negative of
    `chargeback_total_cents`"
    PRD 3.6: "An `EARLY_PAYOFF` event advances the contract `FUNDED → PAID_OFF`."

    Design: Difficulty/compensating_invariant/fund_then_immediate_chargeback_conserves_reserve_balance
    """
    program = setup_program()
    post_reserve_adjustment(program["dealer_id"], 50000)
    funded = setup_funded_contract(program, doc_prefix="IMG-inv2")
    contract_id = funded["contract"]["id"]

    record_chargeback_event(contract_id, "EARLY_PAYOFF", CLOCK_START)

    entries, _ = validate_paginated(
        api.list_reserve_entries(ADMIN, params={"contract_id": contract_id})
    )
    assert sum(entry["amount_cents"] for entry in entries) == 0

    contract = read_contract(contract_id)
    assert contract["reserve_status"] == "CHARGED_BACK"
    assert contract["funding_status"] == "PAID_OFF"
