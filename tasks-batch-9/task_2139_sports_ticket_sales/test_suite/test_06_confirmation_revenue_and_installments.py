"""Order confirmation: the hospitality and revenue cascade, and instalment billing."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_installment_schedule,
    book_package,
    confirm_order,
    create_approved_order,
    create_order,
    read_account,
    read_order,
    read_package,
    read_season,
    read_seat,
    run_ops,
    set_clock,
    setup_four_seat_zone_c_world,
    setup_hospitality_world,
    setup_selling_world,
    setup_zone_d_world,
    submit_order,
    validate_error,
    validate_success,
)


def _cascade_world():
    """A four-seat order plus a HELD suite package big enough to cross the goal."""
    world = setup_hospitality_world(
        season={"revenue_goal_cents": 500000, "total_home_games": 1},
        seat_ranges=[
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 4}
        ],
        plan={"min_seats": 1, "max_seats": 8},
    )
    world["package"] = book_package(
        world["game"]["id"], world["account_id"], world["rep_headers"],
        suite_code="SUITE-1", headcount=21,
        service_window_start_utc="2026-10-10T18:00:00Z",
        service_window_end_utc="2026-10-10T21:00:00Z",
    )
    order = create_approved_order(
        world["account_id"], world["plan_id"], world["seat_ids"], world["rep_headers"]
    )
    world["order"] = order
    return world


def test_confirmation_cascades_a_held_package_into_the_revenue_ledger():
    """PRD 3.6: "- **Cascade link 1.** Every hospitality package belonging to the same account whose `package_status` is `HELD` and whose `game_id` appears in the plan's `game_ids` becomes `CONFIRMED`, processed in `service_window_start_utc` ascending order with ties broken by `created_at` ascending."
    PRD 3.6: "- **Cascade link 2.** Because each of those packages became `CONFIRMED`, the season's `contracted_revenue_cents` increases by that package's `total_due_cents`, once per cascaded package."

    Design: Difficulty/transitive_cascade/order_confirm_cascade_package_then_revenue_then_pricing_mode
    """
    world = _cascade_world()

    confirmed = confirm_order(
        world["order"]["id"], world["rep_headers"], installment_count=1
    )

    assert confirmed["final_total_cents"] == 38430
    assert read_package(world["package"]["id"])["package_status"] == "CONFIRMED"
    assert read_season(world["season_id"])["contracted_revenue_cents"] == 548730


def test_cascaded_package_total_flips_the_pricing_regime_to_balanced():
    """PRD 3.6: "- **Cascade link 3.** Because the ledger grew, the revenue-goal check runs once, after every addition above has landed: if `contracted_revenue_cents` has reached or passed `revenue_goal_cents`, then `revenue_goal_met` becomes true and `dynamic_pricing_mode` flips from `AGGRESSIVE` to `BALANCED`."
    PRD 3.6: "`lifetime_value_cents` is the sum of `final_total_cents` over the account's `CONFIRMED` orders plus the sum of `total_due_cents` over the account's `CONFIRMED` or `SETTLED` hospitality packages."
    PRD 3.6: "Each seat in `seat_ids` receives `assigned_account_id` set to the order's `account_id` and `seat_status` `ASSIGNED`; the four season seat counters are recomputed."

    Design: Difficulty/transitive_cascade/order_confirm_cascade_package_then_revenue_then_pricing_mode
    """
    world = _cascade_world()

    confirm_order(world["order"]["id"], world["rep_headers"], installment_count=1)

    season = read_season(world["season_id"])
    assert season["revenue_goal_met"] is True
    assert season["dynamic_pricing_mode"] == "BALANCED"
    assert season["assigned_seat_count"] == 4
    account = read_account(world["account_id"])
    assert account["lifetime_value_cents"] == 548730
    assert account["service_status"] == "ACTIVE"


def test_confirmation_is_refused_once_the_season_reaches_in_season():
    """PRD 2.9: "**Season status gate,** HTTP 409. Game creation and seat minting require the season to be in `PLANNING`, with seat minting additionally permitted in `RENEWAL_OPEN`; plan construction and plan publication require `PLANNING` or `RENEWAL_OPEN`; order creation, submission, confirmation, relocation and hold creation require `RENEWAL_OPEN` or `GENERAL_ONSALE`; hospitality booking requires `RENEWAL_OPEN`, `GENERAL_ONSALE` or `IN_SEASON`."
    PRD 2.9: "A selling operation attempted outside `RENEWAL_OPEN` or `GENERAL_ONSALE` is `ERR_SEASON_NOT_SELLING`; a setup operation attempted in the wrong status — including opening renewal from a status other than `PLANNING`, and hospitality booking while `PLANNING` or `ARCHIVED` — is `ERR_SEASON_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_once_the_season_reaches_in_season
    """
    world = setup_selling_world()
    order = create_approved_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )
    set_clock("2026-10-11T00:00:00Z")
    run_ops(world["season_id"])
    assert read_season(world["season_id"])["season_status"] == "IN_SEASON"

    response = api_client.confirm_plan_order(
        order["id"], {"installment_count": 1}, world["rep_headers"]
    )

    validate_error(response, ApiErrorId.ERR_SEASON_NOT_SELLING.value, 409)


def test_confirmation_refused_by_the_season_gate_leaves_the_order_approved():
    """PRD 3.6: "Five preconditions must hold: the order is `APPROVED`; the season is `RENEWAL_OPEN` or `GENERAL_ONSALE`; the plan's `plan_status` is `PUBLISHED`; the account's `billing_status` is neither `LAPSED` nor `WRITTEN_OFF`; and every seat in `seat_ids` has a null `assigned_account_id` and is either `AVAILABLE` or covered by an `ACTIVE` hold that belongs to the confirming order's own account."
    PRD 2.10: "The ledger obeys a standing invariant: at all times it equals the sum of `final_total_cents` over every plan order whose `order_status` is `CONFIRMED`, plus the sum of `total_due_cents` over every hospitality package whose `package_status` is either `CONFIRMED` or `SETTLED`."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_once_the_season_reaches_in_season
    """
    world = setup_selling_world()
    order = create_approved_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )
    set_clock("2026-10-11T00:00:00Z")
    run_ops(world["season_id"])

    api_client.confirm_plan_order(
        order["id"], {"installment_count": 1}, world["rep_headers"]
    )

    unchanged = read_order(order["id"])
    assert unchanged["order_status"] == "APPROVED"
    assert unchanged["final_total_cents"] == 0
    season = read_season(world["season_id"])
    assert season["season_status"] == "IN_SEASON"
    assert season["contracted_revenue_cents"] == 0


def test_installment_schedule_puts_the_remainder_in_the_first_instalment():
    """PRD 3.6: "The base amount is `final_total_cents` divided by that count, discarding any fraction; the remainder is `final_total_cents` minus the base amount multiplied by the count. The **first** instalment carries the base amount plus the entire remainder, and every subsequent instalment carries exactly the base amount."
    PRD 3.6: "The instalment at index *i* falls due 30 days after the instalment before it, with index 0 due at the confirming instant itself — equivalently, the due date of index *i* is the confirmation instant advanced by *i* times thirty days."

    Design: Corner/calculations/calc_installment_schedule_puts_the_remainder_in_the_first_installment
    """
    world = setup_zone_d_world()
    order = create_approved_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )

    confirmed = confirm_order(order["id"], world["rep_headers"], installment_count=3)

    assert confirmed["final_total_cents"] == 5942
    assert_installment_schedule(confirmed)
    installments = confirmed["installments"]
    assert len(installments) == 3
    assert installments[0]["amount_cents"] == 1982
    assert installments[0]["due_date_utc"] == "2026-08-01T00:00:00.000Z"
    assert installments[1]["amount_cents"] == 1980
    assert installments[1]["due_date_utc"] == "2026-08-31T00:00:00.000Z"
    assert installments[2]["amount_cents"] == 1980
    assert installments[2]["due_date_utc"] == "2026-09-30T00:00:00.000Z"
    assert confirmed["payment_status"] == "SCHEDULED"


def test_account_holder_may_confirm_its_own_order():
    """PRD 3.6: "A `SalesRep` who owns the account, or the `AccountHolder` acting for itself, confirms an `APPROVED` order by supplying an `installment_count` of 1, 3 or 6."
    PRD 3.6: "`payment_status` moves from `NOT_STARTED` to `SCHEDULED` and the `installments` array is generated as described below."

    Design: Corner/rbac/rbac_account_holder_may_confirm_its_own_order
    """
    world = setup_selling_world()
    order = create_approved_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )

    confirmed = validate_success(
        api_client.confirm_plan_order(
            order["id"], {"installment_count": 1}, world["account_headers"]
        ),
        200,
    )

    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["final_total_cents"] == 9905
    assert confirmed["payment_status"] == "SCHEDULED"
    seat = read_seat(world["seat_ids"][0])
    assert seat["seat_status"] == "ASSIGNED"
    assert seat["assigned_account_id"] == world["account_id"]
    assert read_account(world["account_id"])["service_status"] == "ACTIVE"


def test_confirm_response_already_carries_every_cascaded_value():
    """PRD 1: "First, the system is **immediately consistent**: every cascade, every derived counter and every recomputed score lands inside the request that triggered it, so a read taken immediately after a write never observes a half-applied state."
    PRD 3.6: "`payment_status` moves from `NOT_STARTED` to `SCHEDULED` and the `installments` array is generated as described below."
    PRD 2.10: "The ledger obeys a standing invariant: at all times it equals the sum of `final_total_cents` over every plan order whose `order_status` is `CONFIRMED`, plus the sum of `total_due_cents` over every hospitality package whose `package_status` is either `CONFIRMED` or `SETTLED`."

    Design: Corner/consistency_model/cons_confirm_response_already_carries_every_cascaded_value
    """
    world = setup_selling_world()
    order = create_approved_order(
        world["account_id"], world["plan_id"], [world["seat_ids"][0]], world["rep_headers"]
    )

    confirmed = validate_success(
        api_client.confirm_plan_order(
            order["id"], {"installment_count": 1}, world["rep_headers"]
        ),
        200,
    )

    assert confirmed["final_total_cents"] == 9905
    assert confirmed["payment_status"] == "SCHEDULED"
    assert len(confirmed["installments"]) == 1
    assert confirmed["installments"][0]["amount_cents"] == 9905

    season = read_season(world["season_id"])
    assert season["contracted_revenue_cents"] == 9905
    assert season["assigned_seat_count"] == 1
    assert season["available_seat_count"] == 1
