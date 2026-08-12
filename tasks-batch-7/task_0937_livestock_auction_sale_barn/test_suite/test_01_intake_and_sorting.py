"""Counterparties, sale days, consignments and sorting head into lots."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_lot,
    assert_party,
    assert_same_instant,
    assert_sale_day,
    BARN_ADMIN,
    SETTLEMENT_CLERK,
    YARD_OPERATOR,
    assign_pen,
    check_in_consignment,
    create_consignment,
    create_lot,
    create_lot_payload,
    create_party_payload,
    create_sale_day,
    read_consignment,
    read_lot,
    read_pen,
    report_loss,
    set_clock,
    setup_checked_in_consignment,
    setup_yard,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_register_party_mints_common_fields_and_starts_active(api):
    """PRD §3.1: "Every new counterparty starts with `status` `ACTIVE`."
    PRD §2.4: "Every resource carries a server-minted `id` — a UUID string with no
    type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional
    digits."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that starts at 1 and increments by one on
    every mutation of that row."

    Design: Corner/entities/corner_create_party_returns_201_with_server_minted_common_fields
    """
    set_clock("2026-06-01T08:00:00Z")
    response = api.create_party(create_party_payload(), BARN_ADMIN)
    data = validate_success(response, 201)

    assert_party(data)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["legal_name"] == "Rocking R Ranch"

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_read_sale_day_echoes_scheduled_posture_and_counters(api):
    """PRD §3.2: "A newly scheduled sale day is `SCHEDULED`, with `next_ring_order`
    at 10 and `reopen_count` at zero."

    Design: Corner/entities/corner_get_sale_day_by_id_returns_the_stored_row
    """
    set_clock("2026-06-01T08:00:00Z")
    sale_day = create_sale_day()

    data = validate_success(api.get_sale_day(sale_day["id"], SETTLEMENT_CLERK))
    assert_sale_day(data)
    assert data["status"] == "SCHEDULED"
    assert data["next_ring_order"] == 10
    assert data["reopen_count"] == 0
    assert data["barn_state_code"] == "NE"


def test_list_lots_pages_by_limit_and_offset_in_created_at_order(api):
    """PRD §2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1,
    and may not be larger than 100."
    PRD §2.3: "Results are always sorted by `created_at` in ascending order, so the
    oldest matching row is returned first and pagination is stable across pages."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filter before pagination is
    applied) and `has_more` (true when rows remain beyond the current window)."

    Design: Corner/entities/corner_list_lots_paginates_with_total_count_and_has_more
    """
    scn = setup_checked_in_consignment(head_received=17)
    first = create_lot(scn.consignment["id"], head_count=10)
    second = create_lot(
        scn.consignment["id"],
        head_count=2,
        livestock_class="CALF",
        bid_basis="PER_HEAD",
        opening_bid=40.00,
        reserve_price=45.00,
    )
    third = create_lot(
        scn.consignment["id"], head_count=5, livestock_class="FEEDER_HEIFER"
    )

    page_one, meta_one = validate_paginated(
        api.list_lots(
            YARD_OPERATOR,
            params={"consignment_id": scn.consignment["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [first["id"], second["id"]]

    page_two, meta_two = validate_paginated(
        api.list_lots(
            YARD_OPERATOR,
            params={"consignment_id": scn.consignment["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert page_two[0]["id"] == third["id"]


def test_read_lot_with_unknown_path_id_is_not_found(api):
    """PRD §2.4: "The same code answers any unresolvable path id anywhere in the
    system."
    PRD §2.7 rung 3: "Every id embedded in the path resolves to an existing row,
    checked left to right | `ERR_RESOURCE_NOT_FOUND` | 404"

    Design: Corner/entities/corner_get_lot_with_unknown_id_returns_not_found
    """
    set_clock("2026-06-01T08:00:00Z")
    response = api.get_lot(NON_EXISTENT_UUID, YARD_OPERATOR)

    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_consignment_without_weigh_basis_is_an_invalid_request(api):
    """PRD §3.3: "`weigh_basis` decides how settle weight is derived and is
    required."
    PRD §2.7 rung 4: "Every required body field is present and carries the declared
    JSON type | `ERR_INVALID_REQUEST` | 400 | every endpoint with a request body"

    Design: Corner/entities/corner_create_consignment_missing_weigh_basis_returns_invalid_request
    """
    scn = setup_yard(with_pen=False, with_scale=False)

    response = api.create_consignment(
        {
            "sale_day_id": scn.sale_day["id"],
            "consignor_party_id": scn.consignor["id"],
            "species_class": "CATTLE",
            "head_received": 10,
        },
        scn.consignor_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(
        api.list_consignments(BARN_ADMIN, params={"sale_day_id": scn.sale_day["id"]})
    )
    assert meta["total_count"] == 0


def test_consignment_optional_fields_take_their_declared_defaults(api):
    """PRD §3.3: "`pencil_shrink_pct` is the contractual shrink fraction, defaulting
    to 0.03 and never allowed above 0.06."
    PRD §3.3: "`yardage_basis` defaults to `PER_HEAD_DAY`, `commission_basis`
    defaults to `TIERED_VALUE`, `ration_type` defaults to `NONE` and `days_on_feed`
    defaults to zero."
    PRD §3.3: "`advances_amount` records cash already handed to the consignor and
    defaults to zero; it is deducted from net proceeds at settlement."
    PRD §3.3: "`hold_until_funds` defaults to false; when true, the consignment's
    settlement is created in a held posture and cannot be released until every buyer
    invoice covering its sold lots has been paid in full."
    PRD §3.3: "A new consignment is `INTAKE`, and its `head_unassigned` counter is
    initialised to `head_received`."

    Design: Corner/entities/corner_consignment_optional_fields_take_declared_defaults
    """
    scn = setup_yard(with_pen=False, with_scale=False)

    data = validate_success(
        api.create_consignment(
            {
                "sale_day_id": scn.sale_day["id"],
                "consignor_party_id": scn.consignor["id"],
                "species_class": "CATTLE",
                "head_received": 10,
                "weigh_basis": "PENCIL_SHRINK",
            },
            scn.consignor_headers,
        ),
        201,
    )

    assert data["pencil_shrink_pct"] == 0.03
    assert data["yardage_basis"] == "PER_HEAD_DAY"
    assert data["commission_basis"] == "TIERED_VALUE"
    assert data["ration_type"] == "NONE"
    assert data["days_on_feed"] == 0
    assert data["advances_amount"] == 0
    assert data["hold_until_funds"] is False
    assert data["status"] == "INTAKE"
    assert data["head_unassigned"] == 10
    assert data["head_in_lots"] == 0
    assert data["head_balance_ok"] is True


def test_new_lot_carries_no_weight_until_a_ticket_is_captured(api):
    """PRD §3.4: "If no captured ticket remains on the lot, `settle_weight_lb` is
    null."
    PRD §3.4: "and `weight_class` is `NONE` while there is no settle weight, `LIGHT`
    when the average weight is below 500.0 pounds, `MEDIUM` when it is at least 500.0
    and below 800.0 pounds, and `HEAVY` at 800.0 pounds and above."
    PRD §3.3: "A new lot is `DRAFT` on the sale axis and `BARN` on the custody axis."
    PRD §3.3: "A lot draws from exactly one consignment — commingled lots are not
    permitted in this design — and inherits `sale_day_id` from that consignment."

    Design: Corner/entities/corner_lot_weight_fields_are_computed_and_null_before_capture
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)

    data = validate_success(
        api.create_lot(create_lot_payload(scn.consignment["id"]), YARD_OPERATOR), 201
    )
    assert_lot(data)
    assert data["settle_weight_lb"] is None
    assert data["weight_class"] == "NONE"
    assert data["sale_status"] == "DRAFT"
    assert data["custody_status"] == "BARN"
    assert data["sale_day_id"] == scn.sale_day["id"]
    assert data["rering_count"] == 0
    assert data["quarantine_hold"] is False

    consignment = read_consignment(scn.consignment["id"])
    assert consignment["head_unassigned"] == 0
    assert consignment["status"] == "SORTED"


def test_lot_with_livestock_class_outside_its_vocabulary_is_an_enum_failure(api):
    """PRD §2.9: "Rung 5 routes to `ERR_INVALID_ENUM`, and the set of fields that
    route there is closed and exhaustive."
    PRD §2.9: "A lot's `livestock_class` is `FEEDER_STEER`, `FEEDER_HEIFER`,
    `BREEDING_BULL`, `BREEDING_FEMALE`, `CULL_COW` or `CALF`; its `bid_basis` is
    `PER_CWT` or `PER_HEAD`"

    Design: Corner/entities/corner_create_lot_with_invalid_livestock_class_returns_invalid_enum
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)

    response = api.create_lot(
        create_lot_payload(scn.consignment["id"], livestock_class="WAGYU_PRIME"),
        YARD_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)

    _, meta = validate_paginated(
        api.list_lots(YARD_OPERATOR, params={"consignment_id": scn.consignment["id"]})
    )
    assert meta["total_count"] == 0


def test_consignment_with_zero_head_received_is_a_range_failure(api):
    """PRD §2.7 rung 6: "Numeric body fields satisfy their sign and range
    constraints — head counts at least 1, money amounts at least 0,
    `pencil_shrink_pct` at most 0.06, payment and adjustment amounts strictly greater
    than 0 | `ERR_INVALID_REQUEST` | 400"

    Design: Corner/entities/corner_create_consignment_with_zero_head_received_returns_invalid_request
    """
    scn = setup_yard(with_pen=False, with_scale=False)

    response = api.create_consignment(
        {
            "sale_day_id": scn.sale_day["id"],
            "consignor_party_id": scn.consignor["id"],
            "species_class": "CATTLE",
            "head_received": 0,
            "weigh_basis": "PENCIL_SHRINK",
        },
        scn.consignor_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_lot_naming_an_unknown_consignment_is_a_reference_failure(api):
    """PRD §2.4: "A foreign key supplied inside a request body is a different
    failure: it answers `ERR_REFERENCE_NOT_FOUND`, also HTTP 404, so a client can
    distinguish "you addressed a resource that does not exist" from "you referred to
    one that does not exist"."

    Design: Corner/entities/corner_create_lot_with_unknown_consignment_returns_reference_not_found
    """
    set_clock("2026-06-01T08:00:00Z")

    response = api.create_lot(create_lot_payload(NON_EXISTENT_UUID), YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


def test_lot_drawing_more_head_than_remain_unassigned_is_refused(api):
    """PRD §3.3: "Creating it decrements `head_unassigned` by `head_count` and
    recomputes `head_in_lots` and `head_balance_ok`; a request for more head than the
    consignment still has unassigned is refused with `ERR_HEAD_COUNT_EXCEEDED`."

    Design: Corner/validations/corner_lot_head_count_above_unassigned_is_rejected
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)
    create_lot(scn.consignment["id"], head_count=6)

    response = api.create_lot(
        create_lot_payload(scn.consignment["id"], head_count=5, livestock_class="FEEDER_HEIFER"),
        YARD_OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_HEAD_COUNT_EXCEEDED.value)

    consignment = read_consignment(scn.consignment["id"])
    assert consignment["head_unassigned"] == 4
    assert consignment["head_in_lots"] == 6
    assert consignment["head_balance_ok"] is True

    _, meta = validate_paginated(
        api.list_lots(YARD_OPERATOR, params={"consignment_id": scn.consignment["id"]})
    )
    assert meta["total_count"] == 1


def test_second_check_in_on_the_same_consignment_is_refused(api):
    """PRD §3.3: "Checking in at the receiving dock is a `YardOperator` action, legal
    only while the consignment is `INTAKE` and the sale day is `CHECK_IN_OPEN`."
    PRD §3.3: "It moves the consignment `INTAKE → CHECKED_IN` and stamps
    `checked_in_at` from the logical clock — the instant from which the yardage day
    count runs."
    PRD §2.7 rung 16: "The target row's current state appears in the from-set of the
    requested transition | `ERR_INVALID_STATE` | 409 | every state-transition
    endpoint"

    Design: Corner/state_machines/corner_second_check_in_on_same_consignment_is_rejected
    """
    scn = setup_checked_in_consignment(head_received=10, with_pen=False, with_scale=False)
    set_clock("2026-06-01T11:00:00Z")

    response = api.check_in_consignment(scn.consignment["id"], YARD_OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    consignment = read_consignment(scn.consignment["id"])
    assert consignment["status"] == "CHECKED_IN"
    assert_same_instant(
        consignment["checked_in_at"],
        "2026-06-01T08:00:00Z",
        "checked_in_at must keep the instant of the first check-in:",
    )


def _sorted_consignment_of_seventeen():
    """17 head fully sorted into lots of 10 (penned), 2 and 5."""
    scn = setup_yard()
    scn.consignment = create_consignment(
        scn.sale_day["id"], scn.consignor["id"], head_received=17
    )
    scn.consignment = check_in_consignment(scn.consignment["id"])
    scn.lot_a = create_lot(scn.consignment["id"], head_count=10)
    scn.lot_c = create_lot(
        scn.consignment["id"],
        head_count=2,
        livestock_class="CALF",
        bid_basis="PER_HEAD",
        opening_bid=40.00,
        reserve_price=45.00,
    )
    scn.lot_b = create_lot(
        scn.consignment["id"], head_count=5, livestock_class="FEEDER_HEIFER"
    )
    scn.lot_a = assign_pen(scn.lot_a["id"], scn.pen["id"])
    scn.consignment = read_consignment(scn.consignment["id"])
    return scn


def test_withdrawing_a_lot_returns_its_head_to_the_unassigned_pool(api):
    """PRD §3.3: "Naming a lot withdraws that lot: its `sale_status` moves to
    `WITHDRAWN` from `DRAFT`, `PENNED`, `READY` or `NO_SALE`, and the lot's head
    **return to `head_unassigned`** because those animals are still standing on the
    yard."
    PRD §3.3: "`head_withdrawn` is deliberately not touched on this path — it counts
    only head hauled back home without ever having been lotted."
    PRD §3.3: "The lot leaves `head_in_lots`, the pen it stood in recomputes
    `current_head` and may flip `OCCUPIED → AVAILABLE`, and because `head_unassigned`
    has risen above zero the consignment may re-enter `SORTED → CHECKED_IN`."

    Design: Difficulty/compensating_invariant/lot_withdraw_then_relot_preserves_consignment_head_balance
    """
    scn = _sorted_consignment_of_seventeen()
    assert scn.consignment["status"] == "SORTED"
    assert scn.consignment["head_unassigned"] == 0
    assert scn.consignment["head_in_lots"] == 17

    report_loss(
        scn.consignment["id"],
        scn.consignor["id"],
        loss_type="WITHDRAWN",
        head=10,
        lot_id=scn.lot_a["id"],
    )

    assert read_lot(scn.lot_a["id"])["sale_status"] == "WITHDRAWN"
    consignment = read_consignment(scn.consignment["id"])
    assert consignment["head_unassigned"] == 10
    assert consignment["head_in_lots"] == 7
    assert consignment["head_withdrawn"] == 0
    assert consignment["status"] == "CHECKED_IN"
    assert consignment["head_balance_ok"] is True

    pen = read_pen(scn.pen["id"])
    assert pen["current_head"] == 0
    assert pen["status"] == "AVAILABLE"


def test_relotting_withdrawn_head_restores_the_consignment_head_balance(api):
    """PRD §2.10: "A consignment's `head_balance_ok` is true when its `head_received`
    equals the sum of four things: the head standing in its lots (the total
    `head_count` of its lots whose `sale_status` is any of `DRAFT`, `PENNED`, `READY`,
    `IN_RING`, `SOLD` or `NO_SALE`), plus its `head_unassigned`, plus its `head_dead`,
    plus its `head_condemned`, plus its `head_withdrawn`."
    PRD §3.3: "When `head_unassigned` reaches zero the consignment automatically
    transitions `CHECKED_IN → SORTED`."

    Design: Difficulty/compensating_invariant/lot_withdraw_then_relot_preserves_consignment_head_balance
    """
    scn = _sorted_consignment_of_seventeen()
    report_loss(
        scn.consignment["id"],
        scn.consignor["id"],
        loss_type="WITHDRAWN",
        head=10,
        lot_id=scn.lot_a["id"],
    )

    fresh_lot = create_lot(scn.consignment["id"], head_count=10)

    consignment = read_consignment(scn.consignment["id"])
    assert consignment["head_in_lots"] == 17
    assert consignment["head_unassigned"] == 0
    assert consignment["status"] == "SORTED"
    assert consignment["head_received"] == 17
    assert consignment["head_balance_ok"] is True

    fresh = read_lot(fresh_lot["id"])
    assert fresh["head_count"] == 10
    assert fresh["sale_status"] == "DRAFT"
