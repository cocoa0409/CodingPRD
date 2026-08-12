"""Cast contracts: negotiation cycle, rehearsal credit, and performer payroll."""
from test_helpers import (
    ApiErrorId,
    assert_cast_contract,
    create_cast_contract_payload,
    get_contract,
    make_accepted_contract,
    make_contract,
    make_open_season,
    make_performer,
    make_season,
    set_clock,
    setup_all_rain_cast_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANY, DIRECTOR
from test_helpers.test_users import make_performer_headers


def test_contract_accept_from_draft_rejected(api):
    """PRD §3.2: "A counter by the owning performer — whose `X-User-ID` must equal
    the contract's `performer_id`, else `ERR_NOT_RESOURCE_OWNER` — moves `OFFERED` →
    `COUNTERED`, stores the payload's `countered_day_rate_cents`, and increments
    `negotiation_round` by 1; from any state other than `OFFERED` a counter fails
    with `ERR_CONTRACT_NOT_OFFERED`. Acceptance by the owning performer moves
    `OFFERED` → `ACCEPTED` under the same state and ownership gates, leaving the
    offered rate as the agreed day rate."

    Design: Corner/state_machines/contract_accept_from_draft_rejected
    """
    season = make_season(name="Skip Revel")
    performer = make_performer(stage_name="Brother Roland", base_day_rate_cents=12000)
    contract = make_contract(
        season["id"], performer["id"],
        offered_day_rate_cents=12000, guaranteed_days=2,
        weather_pay_pct=0.5, required_rehearsal_hours=2,
    )
    res = api.accept_contract(contract["id"], make_performer_headers(performer["id"]))
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_OFFERED, expected_status=409)
    assert get_contract(contract["id"])["status"] == "DRAFT"


def test_contract_create_when_season_open_rejected(api):
    """PRD §3.2: "The season must be `PLANNING` or `BUILD`, else the creation is
    rejected with `ERR_SEASON_INVALID_STATE`."

    Design: Corner/validations/contract_create_when_season_open_rejected
    """
    season = make_open_season(name="LateCast Revel", volunteer_min_hours=0)
    performer = make_performer(stage_name="Late Lute", base_day_rate_cents=10000)
    res = api.create_cast_contract(
        create_cast_contract_payload(
            season["id"], performer["id"],
            offered_day_rate_cents=10000, guaranteed_days=1,
            weather_pay_pct=0.5, required_rehearsal_hours=0,
        ),
        DIRECTOR,
    )
    validate_error(res, ApiErrorId.ERR_SEASON_INVALID_STATE, expected_status=409)


def test_cast_contracts_filtered_by_performer(api, any_headers):
    """PRD §4: "The list endpoints accept the optional filters referenced throughout
    §3 — among them `season_id`, `status`, `performer_id`, `contract_id`,
    `stage_name`, `category`, `vendor_id`, `application_id`, `booth_site`,
    `faire_day_id`, `buyer_email`, `payment_status`, `order_id`, `ticket_id`,
    `issued_for_day_id`, `redeemed_on_day_id`, `volunteer_handle`,
    `linked_order_id`, `linked_permit_id`, `phase`, and `depends_on_task_ids` —
    alongside the `limit` and `offset` pagination parameters of §2.3."

    Design: Corner/endpoints/cast_contracts_filtered_by_performer
    """
    season = make_season(name="Filter Revel")
    p1 = make_performer(stage_name="Troupe One", base_day_rate_cents=10000)
    p2 = make_performer(stage_name="Troupe Two", act_type="COMBAT", base_day_rate_cents=11000)
    c1 = make_contract(season["id"], p1["id"], offered_day_rate_cents=10000,
                       guaranteed_days=1, required_rehearsal_hours=0)
    make_contract(season["id"], p2["id"], offered_day_rate_cents=11000,
                  guaranteed_days=1, required_rehearsal_hours=0)

    data, meta = validate_paginated(
        api.list_cast_contracts(ANY, params={"performer_id": p1["id"]})
    )
    assert len(data) == 1
    assert data[0]["id"] == c1["id"]


def test_negotiation_offer_counter_rounds(api):
    """PRD §3.2: "An offer by the director moves the contract from `DRAFT` or
    `COUNTERED` to `OFFERED` — from any other state it fails with
    `ERR_CONTRACT_NOT_OFFERABLE` — and is permitted only while the season remains
    `PLANNING` or `BUILD` (else `ERR_SEASON_INVALID_STATE`); each offer increments
    `negotiation_round` by 1"
    PRD §3.2: "from any state other than `OFFERED` a counter fails with
    `ERR_CONTRACT_NOT_OFFERED`."

    Design: Difficulty/non_linear_state_machine/cast_contract_counter_offer_cycle
    """
    season = make_season(name="Negotiation Revel", volunteer_min_hours=0)
    performer = make_performer(stage_name="Madame Zara", act_type="COMEDY",
                               base_day_rate_cents=18000)
    contract = make_contract(
        season["id"], performer["id"],
        offered_day_rate_cents=20000, guaranteed_days=2,
        weather_pay_pct=0.5, required_rehearsal_hours=2,
    )

    offered = validate_success(api.offer_contract(contract["id"], {}, DIRECTOR), 200)
    assert offered["status"] == "OFFERED"
    assert offered["negotiation_round"] == 1

    countered = validate_success(
        api.counter_contract(
            contract["id"], {"countered_day_rate_cents": 25000},
            make_performer_headers(performer["id"]),
        ),
        200,
    )
    assert countered["status"] == "COUNTERED"
    assert countered["negotiation_round"] == 2
    assert countered["countered_day_rate_cents"] == 25000

    # A second counter while COUNTERED is not offered-shaped.
    res = api.counter_contract(
        contract["id"], {"countered_day_rate_cents": 26000},
        make_performer_headers(performer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_OFFERED, expected_status=409)


def test_negotiation_reoffer_adopts_countered_rate(api):
    """PRD §3.2: "when the director offers again from `COUNTERED` while omitting
    `offered_day_rate_cents` from the payload, the offer adopts the performer's
    `countered_day_rate_cents` as the new offered rate."
    PRD §3.2: "Acceptance by the owning performer moves `OFFERED` → `ACCEPTED` under
    the same state and ownership gates, leaving the offered rate as the agreed day
    rate."

    Design: Difficulty/non_linear_state_machine/cast_contract_counter_offer_cycle
    """
    season = make_season(name="Negotiation Revel", volunteer_min_hours=0)
    performer = make_performer(stage_name="Madame Zara", act_type="COMEDY",
                               base_day_rate_cents=18000)
    contract = make_contract(
        season["id"], performer["id"],
        offered_day_rate_cents=20000, guaranteed_days=2,
        weather_pay_pct=0.5, required_rehearsal_hours=2,
    )
    validate_success(api.offer_contract(contract["id"], {}, DIRECTOR), 200)
    validate_success(
        api.counter_contract(
            contract["id"], {"countered_day_rate_cents": 25000},
            make_performer_headers(performer["id"]),
        ),
        200,
    )

    reoffered = validate_success(api.offer_contract(contract["id"], {}, DIRECTOR), 200)
    assert reoffered["status"] == "OFFERED"
    assert reoffered["negotiation_round"] == 3
    assert reoffered["offered_day_rate_cents"] == 25000

    accepted = validate_success(
        api.accept_contract(contract["id"], make_performer_headers(performer["id"])),
        200,
    )
    assert accepted["status"] == "ACCEPTED"
    assert_cast_contract(accepted)


def test_cast_payout_weather_accrual_accumulates_per_day(api, any_headers):
    """PRD §3.2: "When a faire day is cancelled for weather, every contract in
    `ACCEPTED`, `REHEARSING`, or `PERFORMING` at that moment adds its weather rate:
    the `offered_day_rate_cents` multiplied by the contract's `weather_pay_pct`,
    rounded half up to whole cents for that day."
    PRD §3.1: "Upon opening, every cast contract of the season sitting in `ACCEPTED`
    or `REHEARSING` whose `completed_rehearsal_hours` has reached its
    `required_rehearsal_hours` moves automatically to `PERFORMING`"

    Design: Difficulty/dual_variant_calc/cast_payout_accrual_vs_guarantee_floor
    """
    ctx = setup_all_rain_cast_scenario()
    contract = validate_success(api.get_cast_contract(ctx["contract_id"], ANY), 200)
    # Five weather-cancelled days at round(20000 * 0.5) = 10000 each.
    assert contract["status"] == "PERFORMING"
    assert contract["accrued_payout_cents"] == 50000


def test_cast_payout_guarantee_floor_beats_accrual(api, operator_headers, any_headers):
    """PRD §3.2: "Contracts that survive to the season's strike are instead
    completed (see §3.9) and settled at the guarantee floor: the final payout is the
    greater of `accrued_payout_cents` and `guaranteed_days` times
    `offered_day_rate_cents`, minus a rehearsal-shortfall penalty."
    PRD §3.2: "The shortfall is the amount by which `required_rehearsal_hours`
    exceeds `completed_rehearsal_hours`, treated as zero when the requirement was
    met; each short hour costs 5,000 cents, with the penalty rounded half up to
    whole cents once, and the resulting `final_payout_cents` is floored at zero so a
    settlement can never go negative."

    Design: Difficulty/dual_variant_calc/cast_payout_accrual_vs_guarantee_floor
    """
    ctx = setup_all_rain_cast_scenario()
    validate_success(api.begin_strike(ctx["season_id"], operator_headers), 200)

    contract = validate_success(api.get_cast_contract(ctx["contract_id"], ANY), 200)
    assert contract["status"] == "COMPLETED"
    assert contract["accrued_payout_cents"] == 50000
    # Guarantee floor: max(50000, 3 * 20000) - 0 shortfall = 60000.
    assert contract["final_payout_cents"] == 60000
    assert contract["final_payout_cents"] != contract["accrued_payout_cents"]
