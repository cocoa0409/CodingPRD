"""Sailings, cabin inventory, and the sailing lifecycle.

Covers entity creation/retrieval/listing, inventory uniqueness and range
constraints, sailing-open inventory boundary, invalid/terminal transitions,
and the Sailing.version increment contract.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_sailing_payload, create_cabin_category_payload, create_cabin_payload,
    assert_sailing, assert_cabin,
    setup_sailing_with_inventory, setup_open_sailing, create_sailing, create_category,
)

RM = TEST_USERS["revenue_manager_headers"]
RA = TEST_USERS["reservations_agent_headers"]


# ===========================================================================
# Entity creation / retrieval / listing
# ===========================================================================
def test_create_sailing_returns_draft_with_system_fields(api):
    """PRD 3.1: "A voyage begins with a `Sailing`, created by a `RevenueManager`
    in `DRAFT` status." and "A fresh sailing reports `total_cabins` and
    `available_cabins` of 0". PRD 2.4: "an integer `version` that begins at 1 on
    creation".

    Design: Corner/entities/create_sailing_minimal_returns_201_with_system_fields
    """
    resp = api.create_sailing(create_sailing_payload(), RM)
    data = validate_success(resp, expected_status=201)
    assert_sailing(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["total_cabins"] == 0
    assert data["available_cabins"] == 0


def test_get_sailing_returns_stored_entity(api):
    """PRD 3.1: "Creation captures the `ship_name`, an `itinerary_code` such as a
    route designator, the `embark_date` and `disembark_date` (both ISO 8601 UTC),
    and the number of `nights`."

    Design: Corner/entities/get_sailing_by_id_returns_stored_entity
    """
    created = create_sailing(ship_name="Aurora", itinerary_code="WCAR7N")
    resp = api.get_sailing(created["id"], RA)
    data = validate_success(resp)
    assert data["ship_name"] == "Aurora"
    assert data["itinerary_code"] == "WCAR7N"


def test_list_sailings_paginated_envelope(api):
    """PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_sailings_paginated_envelope
    """
    create_sailing(ship_name="Aurora", itinerary_code="WCAR7N")
    create_sailing(ship_name="Borealis", itinerary_code="NEUR10N",
                   embark_date="2026-10-01T16:00:00Z",
                   disembark_date="2026-10-11T16:00:00Z", nights=10)
    resp = api.list_sailings(RM)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_get_sailing_nonexistent_returns_not_found(api):
    """PRD 2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` before any later
    identifier is examined and before any business rule runs."

    Design: Corner/entities/get_sailing_nonexistent_returns_not_found
    """
    resp = api.get_sailing("11111111-1111-4111-8111-111111111111", RM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_cabin_category_missing_required_field_invalid_request(api):
    """PRD 3.1: "It records a `base_fare_per_guest_cents` — the full per-guest fare
    for the first and second occupants of a cabin, which must be greater than
    zero". PRD 2.9: "These input-shape rules, when violated, surface as
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_cabin_category_missing_required_field_invalid_request
    """
    sailing = create_sailing()
    payload = create_cabin_category_payload(sailing["id"])
    del payload["base_fare_per_guest_cents"]
    resp = api.create_cabin_category(payload, RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_cabin_status_system_field_defaults_available(api):
    """PRD 3.1: "On creation the cabin enters `AVAILABLE` status, its `sailing_id`
    is denormalized from the parent category for filtering, and its
    `group_block_id` and `booking_id` both start null."

    Design: Corner/entities/cabin_status_system_field_ignores_client_input
    """
    sailing = create_sailing()
    category = create_category(sailing["id"])
    resp = api.create_cabin(create_cabin_payload(category["id"], "8001", deck=8), RM)
    data = validate_success(resp, expected_status=201)
    assert_cabin(data)
    assert data["status"] == "AVAILABLE"
    assert data["booking_id"] is None


def test_create_cabin_deck_out_of_range_rejected(api):
    """PRD 3.1: "the `deck` must fall within the owning category's `deck_low`-to-
    `deck_high` band inclusive, with an out-of-band value rejected as
    `ERR_DECK_OUT_OF_RANGE`."

    Design: Corner/entities/create_cabin_deck_out_of_category_range_rejected
    """
    sailing = create_sailing()
    category = create_category(sailing["id"], deck_low=8, deck_high=10)
    resp = api.create_cabin(create_cabin_payload(category["id"], "8001", deck=12), RM)
    validate_error(resp, ApiErrorId.ERR_DECK_OUT_OF_RANGE.value)


def test_duplicate_category_code_on_sailing_rejected(api):
    """PRD 3.1: "the code must be unique among the categories of that sailing, and a
    repeat is rejected with `ERR_DUPLICATE_CATEGORY_CODE`."

    Design: Corner/entities/duplicate_category_code_on_sailing_rejected
    """
    sailing = create_sailing()
    create_category(sailing["id"], code="BALCONY")
    resp = api.create_cabin_category(
        create_cabin_category_payload(sailing["id"], code="BALCONY",
                                      deck_low=11, deck_high=12,
                                      base_fare_per_guest_cents=129900),
        RM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CATEGORY_CODE.value)


def test_duplicate_cabin_number_on_sailing_rejected(api):
    """PRD 3.1: "The `cabin_number` must be unique across the whole sailing — a
    collision yields `ERR_DUPLICATE_CABIN_NUMBER`".

    Design: Corner/entities/duplicate_cabin_number_on_sailing_rejected
    """
    sailing = create_sailing()
    category = create_category(sailing["id"])
    get_success_data(api.create_cabin(create_cabin_payload(category["id"], "8001", deck=8), RM))
    resp = api.create_cabin(create_cabin_payload(category["id"], "8001", deck=9), RM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CABIN_NUMBER.value)


def test_create_cabin_nonexistent_category_not_found(api):
    """PRD 2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND` before any later
    identifier is examined and before any business rule runs."

    Design: Corner/entities/create_cabin_nonexistent_category_not_found
    """
    resp = api.create_cabin(
        create_cabin_payload("22222222-2222-4222-8222-222222222222", "8001", deck=8), RM
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_filtered_list_cabins_by_category(api):
    """PRD 3.1: "its `sailing_id` is denormalized from the parent category for
    filtering". PRD 2.3 lists are paginated with `total_count` in meta.

    Design: Corner/entities/filtered_list_cabins_by_category_fk_reverse_reachability
    """
    sailing = create_sailing()
    category = create_category(sailing["id"])
    get_success_data(api.create_cabin(create_cabin_payload(category["id"], "8001", deck=8), RM))
    get_success_data(api.create_cabin(create_cabin_payload(category["id"], "8002", deck=8), RM))
    resp = api.list_cabins(RM, params={"cabin_category_id": category["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


# ===========================================================================
# Sailing lifecycle transitions
# ===========================================================================
def test_open_already_open_sailing_invalid_state(api):
    """PRD 3.1: "Opening a sailing — transitioning it `DRAFT → OPEN`". PRD 2.5:
    "then the legality of the requested state transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/open_sailing_already_open_invalid_state
    """
    sailing, _category, _cabins = setup_open_sailing(num_cabins=1)
    resp = api.open_sailing(sailing["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_depart_before_embark_date_not_departable(api):
    """PRD 3.1: "Departing is permitted from either `OPEN` or `CLOSED` and moves the
    sailing to `SAILED`, but only when the current clock time has reached or passed
    the `embark_date`; an early attempt is rejected with
    `ERR_SAILING_NOT_DEPARTABLE`."

    Design: Corner/state_machines/depart_before_embark_date_not_departable
    """
    from test_helpers import set_clock
    set_clock("2026-06-18T16:00:00Z")
    sailing, _category, _cabins = setup_open_sailing(num_cabins=1)
    resp = api.depart_sailing(sailing["id"], TEST_USERS["port_agent_headers"])
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_DEPARTABLE.value)


def test_terminal_cancelled_sailing_cannot_reopen(api):
    """PRD 3.1: "A sailing advances through `DRAFT`, `OPEN`, `CLOSED`, `SAILED`, and
    `CANCELLED`, where `SAILED` and `CANCELLED` are terminal." PRD 2.5: "then the
    legality of the requested state transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/terminal_sailing_cancelled_cannot_reopen
    """
    sailing = create_sailing()
    get_success_data(api.cancel_sailing(sailing["id"], RM))
    resp = api.open_sailing(sailing["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_open_sailing_with_zero_cabins_rejected(api):
    """PRD 3.1: "Opening a sailing — transitioning it `DRAFT → OPEN` — is performed
    by a `RevenueManager` and requires that the sailing already hold at least one
    cabin category that itself holds at least one cabin; opening an empty sailing
    is rejected with `ERR_NO_INVENTORY`."

    Design: Difficulty/boundary_precision_check/open_sailing_with_zero_cabins_empty_inventory
    """
    sailing = create_sailing()
    create_category(sailing["id"])  # category but NO cabins
    resp = api.open_sailing(sailing["id"], RM)
    validate_error(resp, ApiErrorId.ERR_NO_INVENTORY.value)
    after = get_success_data(api.get_sailing(sailing["id"], RM))
    assert after["status"] == "DRAFT"


def test_open_sailing_with_one_cabin_succeeds(api):
    """PRD 3.1: "requires that the sailing already hold at least one cabin category
    that itself holds at least one cabin; opening an empty sailing is rejected with
    `ERR_NO_INVENTORY`."

    Design: Difficulty/boundary_precision_check/open_sailing_with_zero_cabins_empty_inventory
    """
    sailing = create_sailing()
    category = create_category(sailing["id"])
    get_success_data(api.create_cabin(create_cabin_payload(category["id"], "8001", deck=8), RM))
    resp = api.open_sailing(sailing["id"], RM)
    data = validate_success(resp)
    assert data["status"] == "OPEN"


# ===========================================================================
# Sailing.version increment contract
# ===========================================================================
def test_version_increments_on_open_then_close(api):
    """PRD 3.1: "Each of opening, closing, and re-opening increments the sailing's
    `version` by 1." PRD 2.4: "an integer `version` that begins at 1 on creation
    and increments by 1 on each subsequent mutation."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_sailing_mutation
    """
    sailing, _category, _cabins = setup_sailing_with_inventory(num_cabins=1)
    assert sailing["version"] == 1
    opened = get_success_data(api.open_sailing(sailing["id"], RM))
    assert opened["version"] == 2
    closed = get_success_data(api.close_sailing(sailing["id"], RM))
    assert closed["status"] == "CLOSED"
    assert closed["version"] == 3


def test_version_increments_by_exactly_one_per_mutation(api):
    """PRD 3.1: "Each of opening, closing, and re-opening increments the sailing's
    `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_sailing_mutation
    """
    sailing, _category, _cabins = setup_sailing_with_inventory(num_cabins=1)
    opened = get_success_data(api.open_sailing(sailing["id"], RM))
    assert opened["version"] == sailing["version"] + 1
