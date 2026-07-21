"""Lending library: parallel status/condition dimensions, checkout gated on the
reservation's SEATED state, availability conservation, condition/loss fees, and
the open-checkout close guard."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    create_table, create_game_copy, create_seated_reservation, create_checkout,
    setup_seated_session_with_checkout,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


def _zero_rate_table(api, label):
    return create_table(api, label=label, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                        cover_fee_cents=0, min_spend_cents=0)


def _seated(api, label, when="2026-07-05T12:00:00Z"):
    table = _zero_rate_table(api, label)
    return create_seated_reservation(
        api, table_id=table["id"], party_size=2,
        start_at=when, end_at="2026-07-05T14:00:00Z",
        seated_at=when, booking_clock=when,
    )


# ─── Difficulty/non_linear_state_machine/game_copy_parallel_status_and_condition_dimensions ─
def test_checkout_advances_status_only_condition_unchanged(api):
    """PRD §3.5: "On a successful checkout the copy's `status` becomes `CHECKED_OUT` while
    its condition dimension is unchanged, `checked_out_at` is stamped with the current
    logical clock, and `checkout_condition` captures the copy's condition at that moment
    as the baseline for any return fee."

    Design: Difficulty/non_linear_state_machine/game_copy_parallel_status_and_condition_dimensions
    """
    resv = _seated(api, "T5a")
    gc = create_game_copy(api, "BC-GC-1a", condition="GOOD", replacement_value_cents=4000)
    create_checkout(api, gc["id"], resv["id"])
    after = validate_success(api.get_game_copy(gc["id"], STAFF))
    assert after["status"] == "CHECKED_OUT"
    assert after["condition"] == "GOOD", "condition dimension unchanged by checkout"


def test_return_advances_condition_independently_of_status(api):
    """PRD §3.5: "the copy's `status` returns to `AVAILABLE`, and its `condition` is updated
    to the reported `return_condition`, which may differ from the checkout baseline."

    Design: Difficulty/non_linear_state_machine/game_copy_parallel_status_and_condition_dimensions
    """
    resv = _seated(api, "T5b")
    gc = create_game_copy(api, "BC-GC-1b", condition="GOOD", replacement_value_cents=4000)
    co = create_checkout(api, gc["id"], resv["id"])
    validate_success(api.return_checkout(co["id"], {"return_condition": "WORN"}, STAFF))
    after = validate_success(api.get_game_copy(gc["id"], STAFF))
    assert after["status"] == "AVAILABLE"
    assert after["condition"] == "WORN", "condition advanced independently of status"


# ─── Difficulty/cross_entity_state_dependency/checkout_depends_on_reservation_seated_state ─
def test_checkout_against_booked_reservation_rejected(api):
    """PRD §3.5: "The referenced reservation must be `SEATED` — a game may only be lent to
    a seated session, and otherwise the request is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/checkout_depends_on_reservation_seated_state
    """
    from test_helpers import create_reservation, set_clock
    table = _zero_rate_table(api, "T10a")
    gc = create_game_copy(api, "BC-WS-1a", replacement_value_cents=5000)
    set_clock(api, "2026-07-05T12:00:00Z")
    resv = create_reservation(api, table["id"], "2026-07-05T12:00:00Z", "2026-07-05T14:00:00Z",
                              party_size=2)  # still BOOKED
    res = api.create_checkout({"game_copy_id": gc["id"], "reservation_id": resv["id"]}, STAFF)
    validate_error(res, "ERR_INVALID_STATE")


def test_checkout_after_seating_succeeds(api):
    """PRD §3.5: "On a successful checkout the copy's `status` becomes `CHECKED_OUT` while
    its condition dimension is unchanged, `checked_out_at` is stamped with the current
    logical clock, and `checkout_condition` captures the copy's condition at that moment
    as the baseline for any return fee."

    Design: Difficulty/cross_entity_state_dependency/checkout_depends_on_reservation_seated_state
    """
    resv = _seated(api, "T10b")
    gc = create_game_copy(api, "BC-WS-1b", replacement_value_cents=5000)
    co = validate_success(
        api.create_checkout({"game_copy_id": gc["id"], "reservation_id": resv["id"]}, STAFF),
        expected_status=201)
    assert co["status"] == "ACTIVE"
    assert validate_success(api.get_game_copy(gc["id"], STAFF))["status"] == "CHECKED_OUT"


# ─── Difficulty/compensating_invariant/game_checkout_return_conserves_available_copy_count ─
def test_checkout_return_same_condition_zero_fee(api):
    """PRD §3.5: "if the returned grade is at or better than the `checkout_condition` grade
    (that is, its ordinal value is less than or equal to the baseline's), there is no fee."

    Design: Difficulty/compensating_invariant/game_checkout_return_conserves_available_copy_count
    """
    resv = _seated(api, "T12a")
    gc1 = create_game_copy(api, "BC-CAT-1a", condition="GOOD", replacement_value_cents=4000)
    create_game_copy(api, "BC-CAT-2a", condition="GOOD", replacement_value_cents=4000)
    co = create_checkout(api, gc1["id"], resv["id"])
    returned = validate_success(api.return_checkout(co["id"], {"return_condition": "GOOD"}, STAFF))
    assert returned["condition_fee_cents"] == 0, "returned GOOD == checkout GOOD, no degradation"
    after = validate_success(api.get_game_copy(gc1["id"], STAFF))
    assert after["status"] == "AVAILABLE" and after["condition"] == "GOOD"


def test_checkout_return_conserves_available_count(api):
    """PRD §3.5: "the copy's `status` returns to `AVAILABLE`, and its `condition` is updated
    to the reported `return_condition`, which may differ from the checkout baseline."
    PRD §3.6: "Copies can be listed and filtered by `title`, by `status`, and by `condition`."

    Design: Difficulty/compensating_invariant/game_checkout_return_conserves_available_copy_count
    """
    resv = _seated(api, "T12b")
    gc1 = create_game_copy(api, "BC-CAT-1b", condition="GOOD", replacement_value_cents=4000)
    create_game_copy(api, "BC-CAT-2b", condition="GOOD", replacement_value_cents=4000)
    co = create_checkout(api, gc1["id"], resv["id"])
    validate_success(api.return_checkout(co["id"], {"return_condition": "GOOD"}, STAFF))
    _, meta = validate_paginated(
        api.list_game_copies(STAFF, params={"title": "Catan", "status": "AVAILABLE"}))
    assert meta["total_count"] == 2, "both copies AVAILABLE after checkout+return round trip"


# ─── Corner/calculations/condition_fee_worn_from_good_is_one_step ──────────
def test_return_worn_from_good_charges_one_step(api):
    """PRD §3.5: "If the copy comes back worse, the fee is the number of grades it dropped
    — the returned grade's ordinal minus the checkout grade's ordinal — multiplied by 800
    cents per grade of degradation."

    Design: Corner/calculations/condition_fee_worn_from_good_is_one_step
    """
    resv = _seated(api, "C9")
    gc = create_game_copy(api, "BC-SP-1", condition="GOOD", replacement_value_cents=3000)
    co = create_checkout(api, gc["id"], resv["id"])
    returned = validate_success(api.return_checkout(co["id"], {"return_condition": "WORN"}, STAFF))
    assert returned["condition_fee_cents"] == 800, "(ord WORN 2 - ord GOOD 1) * 800"
    assert validate_success(api.get_game_copy(gc["id"], STAFF))["condition"] == "WORN"


# ─── Corner/state_machines/checkout_damaged_copy_returns_game_not_available ─
def test_checkout_damaged_copy_returns_game_not_available(api):
    """PRD §3.5: "a copy that is checked out, retired, `DAMAGED`, or `LOST` is not lendable
    and the request is rejected with `ERR_GAME_NOT_AVAILABLE`."

    Design: Corner/state_machines/checkout_damaged_copy_returns_game_not_available
    """
    resv = _seated(api, "C6")
    gc = create_game_copy(api, "BC-RK-1", condition="DAMAGED", replacement_value_cents=3000)
    res = api.create_checkout({"game_copy_id": gc["id"], "reservation_id": resv["id"]}, STAFF)
    validate_error(res, "ERR_GAME_NOT_AVAILABLE")


# ─── Corner/state_machines/close_with_active_checkout_returns_session_has_open_checkouts ─
def test_close_with_active_checkout_rejected(api):
    """PRD §3.3: "A session may not be closed while any `Checkout` referencing it is still
    `ACTIVE`; such an attempt is rejected with `ERR_SESSION_HAS_OPEN_CHECKOUTS`."

    Design: Corner/state_machines/close_with_active_checkout_returns_session_has_open_checkouts
    """
    resv, gc, checkout = setup_seated_session_with_checkout(api, barcode="BC-DX-1")
    res = api.close_reservation(resv["id"], STAFF)
    validate_error(res, "ERR_SESSION_HAS_OPEN_CHECKOUTS")


# ─── Corner/state_machines/report_lost_retires_copy_and_sets_lost ──────────
def test_report_lost_charges_replacement_and_retires_copy(api):
    """PRD §3.5: "In this case `condition_fee_cents` is the copy's full
    `replacement_value_cents`, the copy's `condition` is set to `LOST`, and its `status` is
    driven to the terminal `RETIRED`."

    Design: Corner/state_machines/report_lost_retires_copy_and_sets_lost
    """
    resv, gc, checkout = setup_seated_session_with_checkout(
        api, barcode="BC-RT-1", replacement_value_cents=5000)
    lost = validate_success(api.report_lost_checkout(checkout["id"], STAFF))
    assert lost["condition_fee_cents"] == 5000 and lost["status"] == "LOST"
    after = validate_success(api.get_game_copy(gc["id"], STAFF))
    assert after["condition"] == "LOST" and after["status"] == "RETIRED"


# ─── Corner/entities/game_copy_default_condition_good_when_omitted ─────────
def test_game_copy_defaults_to_good_available(api):
    """PRD §3.5: "A game copy is created by a `Manager` with a `title`, a unique `barcode`,
    and a `replacement_value_cents`, starting `AVAILABLE` with `condition` defaulting to
    `GOOD`."

    Design: Corner/entities/game_copy_default_condition_good_when_omitted
    """
    data = validate_success(api.create_game_copy(
        {"title": "Azul", "barcode": "BC-AZ-1", "replacement_value_cents": 3500}, MGR),
        expected_status=201)
    assert data["condition"] == "GOOD"
    assert data["status"] == "AVAILABLE"


# ─── Corner/endpoints/list_checkouts_by_reservation_finds_child ────────────
def test_list_checkouts_filtered_by_reservation(api):
    """PRD §3.5: "Checkouts can be listed and filtered by `game_copy_id`, by
    `reservation_id`, and by `status`."

    Design: Corner/endpoints/list_checkouts_by_reservation_finds_child
    """
    resv, gc, checkout = setup_seated_session_with_checkout(api, barcode="BC-CL-1")
    data, meta = validate_paginated(
        api.list_checkouts(STAFF, params={"reservation_id": resv["id"]}))
    assert meta["total_count"] == 1
    assert any(c["id"] == checkout["id"] for c in data)
