"""Entity creation, defaults, computed counts, not-found, and immediate visibility.

Corner queue B: entities, consistency_model.
"""
from test_helpers import (
    api_client, validate_success, validate_error, assert_item, assert_member,
    create_item_payload, create_member_payload, add_copy_payload,
    TEST_USERS, NON_EXISTENT_UUID,
)

COORD = TEST_USERS["coordinator_headers"]


# =========================================================================== #
# Corner/entities/create_item_returns_201_with_fields
# =========================================================================== #
def test_create_item_returns_201_and_echoes_fields(api):
    """Creating an item returns 201 and a freshly created item has all six derived
    counts at zero and version 1.

    PRD §3.2: "A freshly created item has all six derived counts at zero and
    `version` 1."

    Design: Corner/entities/create_item_returns_201_with_fields
    """
    payload = create_item_payload(name="Drill", category="TOOL",
                                  replacement_value_cents=12000, loan_period_days=7,
                                  daily_late_fee_cents=100)
    item = validate_success(api_client.create_item(payload, COORD), 201)
    assert_item(item)
    assert item["category"] == "TOOL"
    assert item["replacement_value_cents"] == 12000
    assert item["version"] == 1
    assert item["available_copies_count"] == 0


# =========================================================================== #
# Corner/entities/member_default_max_active_loans_applied
# =========================================================================== #
def test_member_default_max_active_loans_is_five(api):
    """Omitting max_active_loans applies the default of 5; the member starts ACTIVE
    with a zero ledger.

    PRD §3.1: "The registration may optionally set `max_active_loans`,
    `max_active_holds`, `balance_limit_cents`, and `membership_expires_at`; when
    omitted, `max_active_loans` defaults to 5, `max_active_holds` defaults to 3,
    and `balance_limit_cents` defaults to 2000."
    PRD §3.1: "A newly registered member starts in `ACTIVE` status with every
    ledger counter — `outstanding_balance_cents`, `total_assessed_cents`,
    `total_paid_cents`, and `total_waived_cents` — at zero."

    Design: Corner/entities/member_default_max_active_loans_applied
    """
    payload = create_member_payload(name="Def", tier="BASIC")
    payload.pop("max_active_loans", None)
    member = validate_success(api_client.create_member(payload, COORD), 201)
    assert member["max_active_loans"] == 5
    assert member["status"] == "ACTIVE"
    assert member["outstanding_balance_cents"] == 0


# =========================================================================== #
# Corner/entities/get_member_nonexistent_returns_not_found
# =========================================================================== #
def test_get_nonexistent_member_returns_not_found(api):
    """Fetching an unknown member id returns ERR_MEMBER_NOT_FOUND (404).

    PRD §2.9: "The not-found errors are `ERR_MEMBER_NOT_FOUND`,
    `ERR_ITEM_NOT_FOUND`, `ERR_COPY_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_FEE_NOT_FOUND`,
    `ERR_DONATION_NOT_FOUND`, and `ERR_TICKET_NOT_FOUND`, each HTTP 404."

    Design: Corner/entities/get_member_nonexistent_returns_not_found
    """
    res = api_client.get_member(NON_EXISTENT_UUID, COORD)
    validate_error(res, "ERR_MEMBER_NOT_FOUND")


# =========================================================================== #
# Corner/entities/item_computed_available_after_two_copies
# =========================================================================== #
def test_item_available_count_reflects_two_good_copies(api):
    """After adding two GOOD copies, available_copies_count and
    serviceable_copies_count both read 2.

    PRD §2.6: "`available_copies_count` is the number of copies that are
    simultaneously `AVAILABLE` on the availability axis and `GOOD` on the
    condition axis."
    PRD §2.6: "`serviceable_copies_count` is the number of copies whose
    `condition_status` is anything other than `RETIRED`."

    Design: Corner/entities/item_computed_available_after_two_copies
    """
    item = validate_success(api_client.create_item(
        create_item_payload(name="Axe", category="OUTDOOR", replacement_value_cents=4000,
                            loan_period_days=3, daily_late_fee_cents=200), COORD), 201)
    validate_success(api_client.add_copy(item["id"], add_copy_payload(asset_tag="AX-1"), COORD), 201)
    validate_success(api_client.add_copy(item["id"], add_copy_payload(asset_tag="AX-2"), COORD), 201)
    got = validate_success(api_client.get_item(item["id"], COORD), 200)
    assert got["available_copies_count"] == 2
    assert got["serviceable_copies_count"] == 2


# =========================================================================== #
# Corner/consistency_model/immediate_visibility_on_create_member
# =========================================================================== #
def test_create_member_immediately_visible_active(api):
    """The create response immediately carries the member as ACTIVE with the given
    tier (immediate consistency).

    PRD §3.1: "A newly registered member starts in `ACTIVE` status with every
    ledger counter — `outstanding_balance_cents`, `total_assessed_cents`,
    `total_paid_cents`, and `total_waived_cents` — at zero."

    Design: Corner/consistency_model/immediate_visibility_on_create_member
    """
    member = validate_success(api_client.create_member(
        create_member_payload(name="Imm", tier="PLUS"), COORD), 201)
    assert_member(member)
    assert member["status"] == "ACTIVE"
    assert member["tier"] == "PLUS"
