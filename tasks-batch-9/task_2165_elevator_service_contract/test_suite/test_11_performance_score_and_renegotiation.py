"""Performance scoring and the renegotiation cycle."""
from test_helpers import (
    ApiErrorId,
    assert_renegotiation_round,
    counter_round,
    create_renegotiation_payload,
    open_renegotiation,
    read_contract,
    read_round,
    read_visit,
    setup_contract_scoring_fifty,
    setup_contract_scoring_seventy_five,
    setup_contract_scoring_sixty_two_fifty,
    setup_penalty_drag_world,
    setup_renegotiation_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_countering_cycles_the_negotiation_back_to_an_open_round(api):
    """PRD §3.9: "The countered round moves `OPEN → COUNTERED` with
    `countered_by_user_id` stamped, and in the same operation a **successor round is
    created** in `OPEN`, carrying the counterparty's own `proposed_monthly_fee_cents`,
    `proposed_callback_response_minutes` and `proposed_scope_type`, with
    `opened_by_user_id` set to the countering user, with `trigger_performance_score`
    copied unchanged from the round being countered rather than re-evaluated, and
    with `round_number` equal to the contract's `renegotiation_round_count` after
    that count is incremented by 1."
    PRD §3.9: "Because each counter both closes one round and opens another, the
    negotiation loops — open, countered, open again — until somebody accepts,
    somebody closes it out, or the fourth round is reached and no further round may
    be appended."

    Design: Difficulty/non_linear_state_machine/renegotiation_round_cycles_open_countered_open_countered_open
    """
    world = setup_contract_scoring_sixty_two_fifty(
        building_name="Theta Arms", building_address="8 Theta Blvd"
    )
    program = world["program"]

    round_one = open_renegotiation(
        program,
        proposed_monthly_fee_cents=360_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    round_two = counter_round(
        program,
        round_one["id"],
        as_contractor=True,
        proposed_monthly_fee_cents=430_000,
        proposed_callback_response_minutes=60,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    round_three = counter_round(
        program,
        round_two["id"],
        as_contractor=False,
        proposed_monthly_fee_cents=390_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    assert_renegotiation_round(round_three)

    assert read_round(round_one["id"])["status"] == "COUNTERED"
    assert read_round(round_one["id"])["round_number"] == 1
    assert read_round(round_two["id"])["status"] == "COUNTERED"
    assert read_round(round_two["id"])["round_number"] == 2
    assert round_three["status"] == "OPEN"
    assert round_three["round_number"] == 3

    contract = read_contract(program.contract_id)
    assert contract["renegotiation_round_count"] == 3
    assert contract["status"] == "UNDER_RENEGOTIATION"


def test_successor_rounds_carry_the_original_trigger_score(api):
    """PRD §3.9: "with `trigger_performance_score` copied unchanged from the round
    being countered rather than re-evaluated"
    PRD §3.9: "The raw score is then the uptime component weighted at 0.50, plus the
    response component weighted at 0.25, plus the visit component weighted at 0.25,
    less the penalty drag. That raw figure is rounded half up to 2 decimal places
    exactly once, and the result is then clamped into the range from 0.00 to 100.00
    inclusive. The clamped value is stored on the contract as `performance_score`,
    which stays null until the first evaluation ever runs."
    PRD §3.2: "When the logical clock reaches or passes the first instant of the
    month *after* a visit's `period_month`, the epoch sweep turns any visit still
    `SCHEDULED` into `MISSED` and any visit still `DISPUTED` into `REJECTED`."

    Design: Difficulty/non_linear_state_machine/renegotiation_round_cycles_open_countered_open_countered_open
    """
    world = setup_contract_scoring_sixty_two_fifty(
        building_name="Theta Arms", building_address="8 Theta Blvd"
    )
    program = world["program"]
    assert world["sweep"]["missed_visits_marked"] == 1
    assert read_visit(world["visit"]["id"])["status"] == "MISSED"

    round_one = open_renegotiation(
        program,
        proposed_monthly_fee_cents=360_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    assert round_one["trigger_performance_score"] == 62.50, (
        "0.50*100.00 uptime + 0.25*50.00 response + 0.25*0.00 visit - 0.00 drag"
    )
    assert read_contract(program.contract_id)["performance_score"] == 62.50

    round_two = counter_round(
        program,
        round_one["id"],
        as_contractor=True,
        proposed_monthly_fee_cents=430_000,
        proposed_callback_response_minutes=60,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    round_three = counter_round(
        program,
        round_two["id"],
        as_contractor=False,
        proposed_monthly_fee_cents=390_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    assert round_three["trigger_performance_score"] == 62.50


def test_a_score_of_exactly_seventy_five_is_not_low_enough(api):
    """PRD §3.9: "The score is evaluated and stored first, and the request proceeds
    only if it is **strictly below 75.00**; a score of exactly 75.00 is not low
    enough and the request is refused with `ERR_RENEGOTIATION_NOT_WARRANTED`."
    PRD §3.9: "The **response component** is 100.00 when no callback on those cars
    reached `CLEARED` with a `reported_at` inside the scoring month; otherwise it is
    100 multiplied by the number of those cleared callbacks whose `sla_breached` is
    false, divided by the total number of them, rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/performance_score_exactly_at_trigger_threshold_blocks_renegotiation
    """
    world = setup_contract_scoring_seventy_five(
        building_name="Nu Terrace", building_address="13 Nu Rd"
    )
    program = world["program"]

    assert world["callback"]["response_minutes"] == 30
    assert world["callback"]["sla_breached"] is False
    assert read_visit(world["visit"]["id"])["status"] == "MISSED"

    validate_error(
        api.create_renegotiation(
            create_renegotiation_payload(
                program.contract_id,
                proposed_monthly_fee_cents=350_000,
                proposed_callback_response_minutes=45,
                proposed_scope_type="FULL_MAINTENANCE",
            ),
            program.manager_headers,
        ),
        ApiErrorId.ERR_RENEGOTIATION_NOT_WARRANTED.value,
    )


def test_the_refused_renegotiation_appends_no_round(api, admin_headers):
    """PRD §3.9: "The score is evaluated and stored first, and the request proceeds
    only if it is **strictly below 75.00**; a score of exactly 75.00 is not low
    enough and the request is refused with `ERR_RENEGOTIATION_NOT_WARRANTED`."
    PRD §3.9: "When it succeeds, a round is created in `status` `OPEN` with
    `opened_by_user_id` stamped from the acting `X-User-ID` and
    `trigger_performance_score` set to the score just evaluated; the contract's
    `renegotiation_round_count` is incremented by 1 and the round's `round_number`
    is that resulting count, so the first round of a contract's life is round 1; the
    contract moves `ACTIVE → UNDER_RENEGOTIATION`; and the contract's `version` is
    incremented by 1."

    Design: Difficulty/boundary_precision_check/performance_score_exactly_at_trigger_threshold_blocks_renegotiation
    """
    world = setup_contract_scoring_seventy_five(
        building_name="Nu Terrace", building_address="13 Nu Rd"
    )
    program = world["program"]

    validate_error(
        api.create_renegotiation(
            create_renegotiation_payload(
                program.contract_id,
                proposed_monthly_fee_cents=350_000,
                proposed_callback_response_minutes=45,
                proposed_scope_type="FULL_MAINTENANCE",
            ),
            program.manager_headers,
        ),
        ApiErrorId.ERR_RENEGOTIATION_NOT_WARRANTED.value,
    )

    contract = read_contract(program.contract_id)
    assert contract["status"] == "ACTIVE", "a refused request must not park the contract"
    assert contract["renegotiation_round_count"] == 0

    rows, meta = validate_paginated(
        api.list_renegotiations(admin_headers, {"contract_id": program.contract_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_the_penalty_drag_subtracts_points_from_the_score(api):
    """PRD §3.9: "A fourth term drags the score down in proportion to money owed. The
    penalty drag in points is the contract's `penalty_balance_cents` divided by
    100,000 — one point of drag per 1,000 dollars of outstanding balance — rounded
    half up to 2 decimal places, and then capped at **15.00 points** however large
    the balance grows."
    PRD §3.9: "The score looks at exactly one month of history: the most recent
    calendar month that lies entirely in the past relative to the logical clock —
    that is, the month before the clock's current month."

    Design: Corner/calculations/performance_score_penalty_drag_subtracts_points_from_the_score
    """
    world = setup_penalty_drag_world(
        building_name="Calc Six", building_address="6 Calc St"
    )
    program = world["program"]

    assert world["penalty"]["amount_cents"] == 25_000
    assert read_contract(program.contract_id)["penalty_balance_cents"] == 25_000
    assert read_visit(world["visit"]["id"])["status"] == "MISSED"

    opened = open_renegotiation(
        program,
        proposed_monthly_fee_cents=420_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    assert opened["trigger_performance_score"] == 49.75, (
        "50.00 less a 0.25-point drag from the 25,000-cent balance"
    )
    contract = read_contract(program.contract_id)
    assert contract["performance_score"] == 49.75
    assert opened["status"] == "OPEN"
    assert opened["round_number"] == 1
    assert contract["status"] == "UNDER_RENEGOTIATION"


def test_accepting_a_countered_round_rewrites_the_contract_terms(api):
    """PRD §3.9: "The round moves `OPEN → ACCEPTED` with `accepted_by_user_id`
    stamped, and the contract is rewritten from the proposal:
    `monthly_base_fee_cents` takes `proposed_monthly_fee_cents`,
    `callback_response_minutes` takes `proposed_callback_response_minutes`, and
    `scope_type` takes `proposed_scope_type`."
    PRD §3.9: "Every *other* round on the contract still sitting in `OPEN` is driven
    to `WITHDRAWN`, the contract returns `UNDER_RENEGOTIATION → ACTIVE`, and the
    contract's `version` is incremented by 1."

    Design: Corner/state_machines/accepting_a_renegotiation_rewrites_terms_and_withdraws_sibling_rounds
    """
    program = setup_contract_scoring_fifty(
        car_code="CAR-SC",
        manager_user_id="bm-sc",
        contractor_user_id="sc-sc",
        building_name="SM Twelve",
        building_address="12 SM St",
    )
    round_one = open_renegotiation(
        program,
        proposed_monthly_fee_cents=340_000,
        proposed_callback_response_minutes=45,
        proposed_scope_type="FULL_MAINTENANCE",
    )
    round_two = counter_round(
        program,
        round_one["id"],
        as_contractor=True,
        proposed_monthly_fee_cents=380_000,
        proposed_callback_response_minutes=50,
        proposed_scope_type="OIL_AND_GREASE",
    )

    accepted = validate_success(
        api.accept_renegotiation(round_two["id"], program.manager_headers)
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == "bm-sc"
    assert read_round(round_one["id"])["status"] == "COUNTERED"

    contract = read_contract(program.contract_id)
    assert contract["status"] == "ACTIVE"
    assert contract["monthly_base_fee_cents"] == 380_000
    assert contract["callback_response_minutes"] == 50
    assert contract["scope_type"] == "OIL_AND_GREASE"
    assert contract["renegotiation_round_count"] == 2


def test_a_fifth_round_is_refused_by_the_round_limit(api, admin_headers):
    """PRD §3.9: "The contract's `renegotiation_round_count` must also still be below
    **four**, or the request is refused with `ERR_RENEGOTIATION_ROUND_LIMIT`."
    PRD §3.9: "Countering is what makes this a cycle. Either a `ServiceContractor` or
    a `BuildingManager` may counter an `OPEN` round, provided the contract is
    `UNDER_RENEGOTIATION`, the contract's `renegotiation_round_count` is still below
    four, and the acting `X-User-ID` differs from that round's `opened_by_user_id`."

    Design: Corner/validations/renegotiation_round_limit_reached_blocks_a_fifth_round
    """
    world = setup_renegotiation_in_progress(
        counters=3,
        car_code="CAR-VD",
        manager_user_id="bm-vd",
        contractor_user_id="sc-vd",
        building_name="Val Thirteen",
        building_address="13 Val St",
    )
    program = world["program"]
    rounds = world["rounds"]
    assert len(rounds) == 4
    assert read_contract(program.contract_id)["renegotiation_round_count"] == 4

    validate_error(
        api.counter_renegotiation(
            rounds[3]["id"],
            {
                "proposed_monthly_fee_cents": 365_000,
                "proposed_callback_response_minutes": 50,
                "proposed_scope_type": "FULL_MAINTENANCE",
            },
            program.manager_headers,
        ),
        ApiErrorId.ERR_RENEGOTIATION_ROUND_LIMIT.value,
    )

    assert read_contract(program.contract_id)["renegotiation_round_count"] == 4
    last = read_round(rounds[3]["id"])
    assert last["status"] == "OPEN"
    assert last["round_number"] == 4

    listed, meta = validate_paginated(
        api.list_renegotiations(admin_headers, {"contract_id": program.contract_id})
    )
    assert meta["total_count"] == 4
    assert len(listed) == 4
