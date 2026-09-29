"""The secondary market: transfer requests, resale credit and the seasonal cap."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_ticket_transfer,
    create_ticket_transfer_payload,
    decide_transfer,
    read_account,
    read_order,
    read_season,
    read_transfer,
    request_transfer,
    setup_marquee_transfer_world,
    setup_world_with_confirmed_order,
    setup_world_with_delinquent_order,
    setup_world_with_requested_resale,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
    RM_HEADERS,
    TEST_USERS,
)


def test_marquee_blackout_outranks_the_resale_floor():
    """PRD 3.10: "The **marquee blackout** refuses a transfer request on a game whose `opponent_tier` is `MARQUEE` unless the selling account's `tenure_years` is at least 3, rejecting shorter-tenured sellers with `ERR_TRANSFER_BLACKOUT`."
    PRD 2.9: "Rungs 17 through 33 are themselves evaluated in the order printed above, so — for one worked example — an order creation that simultaneously references an out-of-season seat, carries the wrong seat count and carries an excessive `discount_pct` reports `ERR_SEAT_SEASON_MISMATCH`."
    PRD 2.9: "**Marquee transfer blackout** — `ERR_TRANSFER_BLACKOUT` (422), guarding transfer requests."
    PRD 2.9: "**Resale floor** — `ERR_RESALE_PRICE_BELOW_FLOOR` (422), guarding transfer requests."

    Design: Difficulty/priority_pair_validation_conflict/transfer_blackout_outranks_resale_price_floor
    """
    world = setup_marquee_transfer_world(tenure_years=1)

    response = api_client.create_ticket_transfer(
        create_ticket_transfer_payload(
            world["order_id"], world["game"]["id"], world["seat_ids"][0],
            transfer_type="RESALE", resale_price_cents=1,
        ),
        world["account_headers"],
    )

    error = validate_error(response, ApiErrorId.ERR_TRANSFER_BLACKOUT.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_RESALE_PRICE_BELOW_FLOOR.value


def test_blackout_refusal_files_no_transfer_and_consumes_no_cap_slot():
    """PRD 3.10: "A successful request is minted in `REQUESTED` status with `credit_awarded_cents` at 0 and `decided_by_user_id` null, and the selling account's `transfer_count_season` increases by 1 — the request itself consumes a cap slot."
    PRD 3.10: "The **marquee blackout** refuses a transfer request on a game whose `opponent_tier` is `MARQUEE` unless the selling account's `tenure_years` is at least 3, rejecting shorter-tenured sellers with `ERR_TRANSFER_BLACKOUT`."

    Design: Difficulty/priority_pair_validation_conflict/transfer_blackout_outranks_resale_price_floor
    """
    world = setup_marquee_transfer_world(tenure_years=1)

    api_client.create_ticket_transfer(
        create_ticket_transfer_payload(
            world["order_id"], world["game"]["id"], world["seat_ids"][0],
            transfer_type="RESALE", resale_price_cents=1,
        ),
        world["account_headers"],
    )

    _, meta = validate_paginated(
        api_client.list_ticket_transfers(
            OPS_HEADERS, params={"order_id": world["order_id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_account(world["account_id"])["transfer_count_season"] == 0


def test_transfer_request_against_a_delinquent_order_is_rejected():
    """PRD 3.10: "The order must not be in `payment_status` `DELINQUENT`, or the request is `ERR_ORDER_DELINQUENT`."
    PRD 2.9: "**Delinquency gate.** The order behind a transfer request, a transfer decision or a relocation must not be in `payment_status` `DELINQUENT` — otherwise `ERR_ORDER_DELINQUENT` (409)."

    Design: Difficulty/cross_entity_state_dependency/transfer_request_blocked_by_delinquent_payment_dimension
    """
    world = setup_world_with_delinquent_order(installment_count=3)

    response = api_client.create_ticket_transfer(
        create_ticket_transfer_payload(
            world["order_id"], world["game"]["id"], world["seat_ids"][0],
            transfer_type="RESALE", resale_price_cents=9000,
        ),
        world["account_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ORDER_DELINQUENT.value, 409)
    _, meta = validate_paginated(
        api_client.list_ticket_transfers(
            OPS_HEADERS, params={"order_id": world["order_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_delinquent_order_keeps_its_confirmed_fulfilment_status():
    """PRD 3.7: "During its payment phase, a confirmed order whose `payment_status` is `SCHEDULED` or `PARTIALLY_PAID` moves to `DELINQUENT` when the current instant has reached or passed the due date of its earliest unpaid instalment plus a ten-day grace period."
    PRD 3.6: "The base amount is `final_total_cents` divided by that count, discarding any fraction; the remainder is `final_total_cents` minus the base amount multiplied by the count. The **first** instalment carries the base amount plus the entire remainder, and every subsequent instalment carries exactly the base amount."

    Design: Difficulty/cross_entity_state_dependency/transfer_request_blocked_by_delinquent_payment_dimension
    """
    world = setup_world_with_delinquent_order(installment_count=3)

    order = read_order(world["order_id"])
    assert order["order_status"] == "CONFIRMED"
    assert order["payment_status"] == "DELINQUENT"
    assert order["final_total_cents"] == 9905
    assert order["installments"][0]["amount_cents"] == 3303
    assert read_account(world["account_id"])["billing_status"] == "PAST_DUE"


def test_rejected_transfer_grants_no_credit_and_returns_the_cap_slot():
    """PRD 3.10: "**A `decision` of `REJECT`** moves `transfer_status` from `REQUESTED` to the terminal `REJECTED`, stamps `decided_by_user_id` and records the supplied `decision_reason`. It grants no credit and leaves the entitlement with the selling account. Its one ledger effect is the mirror image of the request: the seller's `transfer_count_season` decreases by 1, giving the seasonal cap slot back."
    PRD 3.10: "The `floor_price_cents` is 60 percent of `face_value_cents`, rounded half-up."

    Design: Corner/state_machines/sm_rejected_transfer_is_terminal_and_returns_the_seasonal_slot
    """
    world = setup_world_with_requested_resale(resale_price_cents=10000)
    assert world["transfer"]["face_value_cents"] == 9344
    assert world["transfer"]["floor_price_cents"] == 5606

    rejected = decide_transfer(
        world["transfer_id"], "REJECT", RM_HEADERS, decision_reason="policy hold"
    )

    assert_ticket_transfer(rejected)
    assert rejected["transfer_status"] == "REJECTED"
    assert rejected["credit_awarded_cents"] == 0
    assert rejected["decided_by_user_id"] == "rm-001"
    account = read_account(world["account_id"])
    assert account["loyalty_credit_cents"] == 0
    assert account["transfer_count_season"] == 0
    assert read_season(world["season_id"])["secondary_market_volume_cents"] == 0


def test_approved_resale_grants_the_eighty_five_percent_seller_credit():
    """PRD 3.10: "For a `RESALE`, `credit_awarded_cents` is set to 85 percent of `resale_price_cents`, rounded half-up; that credit is added to the selling account's `loyalty_credit_cents`; and the season's `secondary_market_volume_cents` grows by the full `resale_price_cents`."
    PRD 3.10: "The seller's `transfer_count_season` is left unchanged, because the `REQUESTED` row already counted toward the seasonal cap."

    Design: Corner/calculations/calc_approved_resale_grants_eighty_five_percent_seller_credit
    """
    world = setup_world_with_requested_resale(resale_price_cents=10000)

    approved = decide_transfer(world["transfer_id"], "APPROVE", RM_HEADERS)

    assert approved["transfer_status"] == "APPROVED"
    assert approved["face_value_cents"] == 9344
    assert approved["floor_price_cents"] == 5606
    assert approved["credit_awarded_cents"] == 8500
    account = read_account(world["account_id"])
    assert account["loyalty_credit_cents"] == 8500
    assert account["transfer_count_season"] == 1
    assert read_season(world["season_id"])["secondary_market_volume_cents"] == 10000


def test_third_transfer_request_in_one_season_is_rejected():
    """PRD 3.10: "Finally, the seasonal cap allows an account at most two transfers per season: `transfer_count_season` — the count of that account's transfers in this season whose `transfer_status` is `REQUESTED`, `APPROVED` or `COMPLETED` — must be strictly below 2 at request time, or the request is `ERR_TRANSFER_LIMIT_EXCEEDED`."

    Design: Corner/validations/val_third_transfer_request_in_one_season_rejected
    """
    world = setup_world_with_confirmed_order(
        seat_count=3,
        seat_ranges=[
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 3}
        ],
    )
    request_transfer(
        world["order_id"], world["game"]["id"], world["seat_ids"][0],
        world["account_headers"], transfer_type="RESALE", resale_price_cents=10000,
    )
    request_transfer(
        world["order_id"], world["game"]["id"], world["seat_ids"][1],
        world["account_headers"], transfer_type="RESALE", resale_price_cents=10000,
    )

    response = api_client.create_ticket_transfer(
        create_ticket_transfer_payload(
            world["order_id"], world["game"]["id"], world["seat_ids"][2],
            transfer_type="RESALE", resale_price_cents=10000,
        ),
        world["account_headers"],
    )

    validate_error(response, ApiErrorId.ERR_TRANSFER_LIMIT_EXCEEDED.value, 422)
    assert read_account(world["account_id"])["transfer_count_season"] == 2
    _, meta = validate_paginated(
        api_client.list_ticket_transfers(
            OPS_HEADERS, params={"order_id": world["order_id"]}
        )
    )
    assert meta["total_count"] == 2


def test_second_decision_on_a_decided_transfer_is_rejected():
    """PRD 3.10: "A decision requires the transfer to still be `REQUESTED` (otherwise `ERR_TRANSFER_NOT_PENDING`), the backing order not to be `DELINQUENT`, and the game still to be `SCHEDULED`."
    PRD 3.10: "For a `RESALE`, `credit_awarded_cents` is set to 85 percent of `resale_price_cents`, rounded half-up; that credit is added to the selling account's `loyalty_credit_cents`; and the season's `secondary_market_volume_cents` grows by the full `resale_price_cents`."

    Design: Corner/errors/err_second_decision_on_a_decided_transfer_rejected
    """
    world = setup_world_with_requested_resale(resale_price_cents=10000)
    decide_transfer(world["transfer_id"], "APPROVE", RM_HEADERS)

    response = api_client.decide_ticket_transfer(
        world["transfer_id"],
        {"decision": "REJECT", "decision_reason": "changed my mind"},
        TEST_USERS["second_revenue_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_TRANSFER_NOT_PENDING.value, 409)
    unchanged = read_transfer(world["transfer_id"])
    assert unchanged["transfer_status"] == "APPROVED"
    assert unchanged["decided_by_user_id"] == "rm-001"
    assert read_account(world["account_id"])["loyalty_credit_cents"] == 8500
    assert read_season(world["season_id"])["secondary_market_volume_cents"] == 10000
