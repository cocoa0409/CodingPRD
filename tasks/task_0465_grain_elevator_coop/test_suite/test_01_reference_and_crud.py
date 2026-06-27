"""Reference setup, CRUD, listing, computed/system/default fields, and basic
state-machine transitions for the Grain Elevator Coop API.

Queue B (Corner) — sections: entities, state_machines.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_commodity, assert_member, assert_price_board,
    assert_contract, assert_storage_position, assert_scale_ticket,
    assert_hedge_position,
    create_commodity_payload, create_member_payload, create_price_board_payload,
    create_scale_ticket_payload, create_contract_payload, create_hedge_position_payload,
)
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]
CLERK = TEST_USERS["grade_clerk_headers"]
OFFICER = TEST_USERS["settlement_officer_headers"]
SHIPPER = TEST_USERS["shipping_clerk_headers"]
RISK = TEST_USERS["risk_manager_headers"]


def test_create_commodity_returns_201_with_all_fields(api):
    """PRD §4: "Resource creation endpoints return HTTP 201 with the created resource".
    PRD §2.4: "Every resource carries a server-minted `id` that is a UUID with no type
    prefix" and "an integer `version` that begins at 1 on creation".

    Design: Corner/entities/create_commodity_returns_201_with_all_fields
    """
    resp = api.create_commodity(create_commodity_payload(symbol="CORN"), MERCH)
    data = validate_success(resp, expected_status=201)
    assert_commodity(data)
    assert data["symbol"] == "CORN"
    assert data["test_weight_lbs_per_bushel"] == 56
    assert data["base_moisture_pct"] == 15.0
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"


def test_get_member_returns_default_ledger_fields(api):
    """PRD §3.1: "the three ledger fields — `equity_credit_dollars` (accumulated
    non-cash patronage equity), `cash_paid_dollars` (lifetime cash settlement plus
    cash patronage paid out), and `net_priced_bushels` (the running total of priced
    bushels in the open patronage period) — all initialize to 0".

    Design: Corner/entities/get_member_returns_stored_ledger_fields
    """
    member = fx.create_member(name="Pat Farm")
    resp = api.get_member(member["id"], MERCH)
    data = validate_success(resp)
    assert_member(data)
    assert data["equity_credit_dollars"] == 0
    assert data["cash_paid_dollars"] == 0
    assert data["net_priced_bushels"] == 0


def test_list_price_boards_paginated_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries the pagination fields
    `limit`, `offset`, `total_count` (the total number of matching records before the
    limit/offset window is applied), and `has_more`".

    Design: Corner/entities/list_price_boards_paginated_envelope
    """
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"], futures_price=4.50, cash_basis=-0.30)
    fx.create_price_board(commodity["id"], futures_price=4.80, cash_basis=-0.10)
    resp = api.list_price_boards(MERCH, params={"commodity_id": commodity["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_get_commodity_nonexistent_returns_not_found(api):
    """PRD §2.5: "the first identifier that fails to resolve causes the request to be
    rejected with `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_commodity_nonexistent_returns_not_found
    """
    resp = api.get_commodity(NON_EXISTENT_UUID, MERCH)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_scale_ticket_missing_required_moisture_returns_invalid_request(api):
    """PRD §2.5: "required fields must be present and well-typed, every enum value must
    fall within its declared set, every weight, bushel count, and contract count must be
    non-negative". PRD §3.2: "The clerk supplies the `member_id` delivering the load, the
    `commodity_id` delivered, the `gross_weight_lbs` of the loaded truck, the
    `tare_weight_lbs` of the empty truck, the measured `moisture_pct`".

    Design: Corner/entities/scale_ticket_missing_required_moisture_returns_invalid_request
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Q Farm")
    payload = {
        "member_id": member["id"],
        "commodity_id": commodity["id"],
        "gross_weight_lbs": 58000,
        "tare_weight_lbs": 18000,
        "deposit_account_type": "DELAYED_PRICE",
    }
    resp = api.create_scale_ticket(payload, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_scale_ticket_dockage_default_zero_applied(api):
    """PRD §3.2: "optionally the `dockage_pct` (foreign material as a percent of net
    weight, defaulting to 0)". PRD §3.2: "the `clean_weight_lbs` is the net weight minus
    those dockage pounds".

    Design: Corner/entities/scale_ticket_dockage_default_zero_applied
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="R Farm")
    ticket = fx.create_weighed_ticket(
        member["id"], commodity["id"],
        gross_weight_lbs=72000, tare_weight_lbs=16000, moisture_pct=15.0,
        deposit_account_type="DELAYED_PRICE",
    )
    # omit dockage_pct -> default 0
    payload = create_scale_ticket_payload(member["id"], commodity["id"])
    payload.pop("dockage_pct")
    resp = api.create_scale_ticket(payload, CLERK)
    created = validate_success(resp, expected_status=201)
    graded = fx.grade_ticket(created["id"])
    assert graded["dockage_pct"] == 0
    assert graded["clean_weight_lbs"] == 56000.0, (
        f"clean_weight should equal net_weight with zero dockage, got {graded['clean_weight_lbs']}"
    )


def test_price_board_cash_price_computed_and_is_current(api):
    """PRD §3.1: "the system computes the board's `cash_price` as the futures price plus
    the cash basis, and marks the new board's `is_current` flag. A board's `is_current`
    is true only when it is the board with the greatest `created_at` among all boards for
    its `commodity_id`".

    Design: Corner/entities/price_board_cash_price_computed_ignores_client_input
    """
    commodity = fx.create_commodity()
    resp = api.create_price_board(
        create_price_board_payload(commodity["id"], futures_price=4.80, cash_basis=-0.10), MERCH
    )
    board = validate_success(resp, expected_status=201)
    assert_price_board(board)
    assert board["cash_price"] == 4.70, f"cash_price should be 4.70, got {board['cash_price']}"
    assert board["is_current"] is True


def test_scale_ticket_status_is_system_weighed(api):
    """PRD §3.2: "a `GradeClerk` weighs in the load by creating a **scale ticket**, which
    is born in `WEIGHED` status". PRD §3.2: "The ticket's `storage_position_id` is set to
    the new position's id (it is null until grading)".

    Design: Corner/entities/scale_ticket_system_status_field_input_ignored
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="S Farm")
    resp = api.create_scale_ticket(
        create_scale_ticket_payload(
            member["id"], commodity["id"],
            gross_weight_lbs=58000, tare_weight_lbs=18000, moisture_pct=18.0, dockage_pct=1.5,
        ),
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "WEIGHED"
    assert data["storage_position_id"] is None


def test_scale_ticket_gross_not_greater_than_tare_returns_invalid_request(api):
    """PRD §3.2: "The gross weight must exceed the tare weight or the ticket is refused
    with `ERR_INVALID_REQUEST`".

    Design: Corner/entities/scale_ticket_gross_not_greater_than_tare_returns_invalid_request
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="T Farm")
    resp = api.create_scale_ticket(
        create_scale_ticket_payload(
            member["id"], commodity["id"],
            gross_weight_lbs=18000, tare_weight_lbs=18000, moisture_pct=16.0, dockage_pct=0,
        ),
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_patronage_allocation_is_immutable_append_only(api):
    """PRD §2.4: "an allocation is an append-only, immutable accounting entry that carries
    only `id` and `created_at` — it has no `updated_at` and no `version`".

    Design: Corner/entities/patronage_allocation_is_immutable_append_only
    """
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="U Farm")
    fx.settle_member_bushels(commodity["id"], member["id"], priced_bushels=1000, member_name="U Farm")
    period = fx.open_patronage_period(label="FY2026", pool_dollars=50000, qualified_cash_pct=0.20)
    fx.api_client.close_patronage_period(period["id"], MERCH)

    resp = api.list_member_allocations(member["id"], MERCH)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    allocation = data[0]
    assert "version" not in allocation, "allocation must not carry a version"
    assert "updated_at" not in allocation, "allocation must not carry an updated_at"
    assert "id" in allocation and "created_at" in allocation


def test_storage_position_member_fk_reverse_reachable_via_filter(api):
    """PRD §4 (GET /commodities/storage-positions): "List storage positions, optionally
    filtered by member, commodity, scale ticket, or receipt". PRD §3.2: the graded
    position copies the ticket's `member_id`.

    Design: Corner/entities/fk_storage_position_member_reverse_reachable_via_filter
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="V Farm")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"]
    )
    resp = api.list_storage_positions(MERCH, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["member_id"] == member["id"]
    assert data[0]["id"] == position["id"]


def test_grade_weighed_ticket_transitions_to_graded_and_creates_position(api):
    """PRD §3.2: "Grading a weighed ticket is the heart of the inbound flow and advances
    the ticket from `WEIGHED` to `GRADED`". PRD §3.2: "The same grade action creates a
    **storage position** whose `program` equals the ticket's deposit account type, whose
    `bushels` and `bushels_available` are both set to the computed net dry bushels, whose
    `status` is `STORED`".

    Design: Corner/state_machines/grade_weighed_ticket_transitions_to_graded_and_creates_position
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="W Farm")
    ticket = fx.create_weighed_ticket(member["id"], commodity["id"])
    graded = fx.grade_ticket(ticket["id"])
    assert graded["status"] == "GRADED"
    assert graded["storage_position_id"] is not None
    position = validate_success(api.get_storage_position(graded["storage_position_id"], OFFICER))
    assert_storage_position(position)
    assert position["status"] == "STORED"
    assert position["program"] == "DELAYED_PRICE"
    assert position["bushels"] == 1000.0
    assert position["bushels_available"] == 1000.0


def test_grade_already_graded_ticket_returns_invalid_state(api):
    """PRD §3.2: "A ticket may only be graded out of `WEIGHED`; attempting to grade a
    ticket in any other status is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/grade_already_graded_ticket_returns_invalid_state
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="X Farm")
    ticket = fx.create_weighed_ticket(member["id"], commodity["id"])
    fx.grade_ticket(ticket["id"])
    resp = api.grade_scale_ticket(ticket["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_void_graded_ticket_returns_invalid_state(api):
    """PRD §3.2: "Only a `WEIGHED` ticket may be voided — once a ticket is graded and a
    storage position exists, the ticket can no longer be voided and the attempt returns
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/void_graded_ticket_returns_invalid_state
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Y Farm")
    ticket = fx.create_weighed_ticket(member["id"], commodity["id"])
    fx.grade_ticket(ticket["id"])
    resp = api.void_scale_ticket(ticket["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_contract_starts_in_open_initial_state(api):
    """PRD §3.4: "A contract is born `OPEN`." and "a `CASH` contract requires neither leg
    at create." and "The `priced_bushels` field starts at 0".

    Design: Corner/state_machines/contract_starts_in_open_initial_state
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="Z Farm")
    resp = api.create_contract(
        create_contract_payload(member["id"], commodity["id"], contract_type="CASH", contracted_bushels=1000),
        MERCH,
    )
    data = validate_success(resp, expected_status=201)
    assert_contract(data)
    assert data["status"] == "OPEN"
    assert data["futures_leg"] is None
    assert data["basis_leg"] is None
    assert data["priced_bushels"] == 0


def test_cancel_settled_contract_from_terminal_returns_invalid_state(api):
    """PRD §3.4: "A contract not in `OPEN` or `PRICED` cannot be cancelled
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_settled_contract_from_terminal_returns_invalid_state
    """
    commodity = fx.create_commodity()
    fx.create_price_board(commodity["id"])
    member = fx.create_member(name="AA Farm")
    _, contract, settled = fx.settle_member_bushels(
        commodity["id"], member["id"], priced_bushels=1000, member_name="AA Farm"
    )
    contract_now = validate_success(api.get_contract(contract["id"], MERCH))
    assert contract_now["status"] == "SETTLED"
    resp = api.cancel_contract(contract["id"], MERCH)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_loaded_shipment_returns_invalid_state(api):
    """PRD §3.7: "A `LOADED` shipment cannot be cancelled (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/cancel_loaded_shipment_returns_invalid_state
    """
    commodity = fx.create_commodity()
    member = fx.create_member(name="CC Farm")
    bay = fx.create_loadout_bay(name="BAY-2")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT",
    )
    shipment = fx.schedule_shipment(
        commodity["id"], position["id"], bay["id"], bushels=500,
        bay_window_start="2026-02-01T08:00:00Z", bay_window_end="2026-02-01T10:00:00Z",
    )
    loaded = fx.load_shipment(shipment["id"])
    assert loaded["status"] == "LOADED"
    resp = api.cancel_shipment(shipment["id"], SHIPPER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_hedge_open_to_open_self_loop_on_benign_mark(api):
    """PRD §3.8: "When the recomputed account equity is at or above the maintenance margin
    total, the position stays `OPEN`, and the `margin_call_dollars` remain 0." PRD §3.8:
    "For a `SHORT` position, the `unrealized_pnl_dollars` are the entry futures price
    minus the mark futures price, that difference multiplied by the contract size and by
    the number of contracts".

    Design: Corner/state_machines/hedge_open_to_open_self_loop_on_benign_mark
    """
    commodity = fx.create_commodity()
    hedge = fx.open_hedge(commodity["id"], side="SHORT", contracts=3, entry_futures_price=4.50)
    resp = api.mark_hedge_position(hedge["id"], {"mark_futures_price": 4.40}, RISK)
    data = validate_success(resp)
    assert_hedge_position(data)
    assert data["status"] == "OPEN"
    assert data["unrealized_pnl_dollars"] == 1500.00
    assert data["account_equity_dollars"] == 7500.00
    assert data["margin_call_dollars"] == 0


def test_meet_call_second_meet_from_open_returns_invalid_state(api):
    """PRD §3.8: "**Meeting a margin call** ... moves the position from `MARGIN_CALL` back
    to `OPEN`. ... The position must be in `MARGIN_CALL` (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/meet_call_idempotency_second_meet_from_open_returns_invalid_state
    """
    commodity = fx.create_commodity()
    hedge, _marked = fx.open_hedge_in_margin_call(commodity_id=commodity["id"])
    cured = fx.meet_call(hedge["id"], deposit_dollars=4500)
    assert cured["status"] == "OPEN"
    hp = validate_success(api.get_hedge_position(hedge["id"], RISK))
    resp = api.meet_call(
        hedge["id"],
        {"deposit_dollars": 1000, "expected_hedge_position_version": hp["version"]},
        RISK,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
