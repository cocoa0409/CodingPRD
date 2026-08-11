"""Platform-wide rules: the logical clock, pagination bounds and the error families."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_same_instant,
    build_user_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def test_the_logical_clock_may_not_be_moved_backwards(api):
    """PRD 2.4: "Time never runs backwards: a supplied instant earlier than the
    current clock is rejected with `ERR_VALIDATION` (HTTP 400), while a value equal to
    the current clock is accepted."
    PRD 2.4: "It is moved only by an administrative clock-setting capability, which
    takes a single field `to_iso8601` and returns `current_utc` together with two
    counters, `expired_ingredient_lot_count` and `overdue_recall_notice_count`,
    describing what the move swept up."

    Design: Corner/validations/the_logical_clock_may_not_move_backwards
    """
    set_clock(api, "2026-05-06T00:00:00.000Z")

    response = api.set_clock({"to_iso8601": "2026-04-30T00:00:00.000Z"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    unchanged = validate_success(
        api.set_clock({"to_iso8601": "2026-05-06T00:00:00.000Z"}, ADMIN)
    )
    assert_same_instant(
        unchanged["current_utc"], "2026-05-06T00:00:00.000Z",
        "the clock still reads the value it held before the rejected move",
    )


def test_a_pagination_limit_above_the_maximum_is_refused(api):
    """PRD 2.3: "A `limit` that is not an integer, is below 1, or is above 100, and an
    `offset` that is not an integer or is below 0, are all rejected with
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/a_pagination_limit_above_the_maximum_is_refused
    """
    response = api.list_finished_lots(SALES, params={"limit": 101})
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)


def test_an_undeclared_role_header_is_answered_before_any_existence_check(api):
    """PRD 2.1: "The same rejection is issued when `X-User-Role` carries a string that
    is not one of the seven role names below — an unknown role is treated as no
    credential at all, not as a permission problem."
    PRD 2.9: "`X-User-Role` names one of the seven declared roles, on every endpoint —
    otherwise `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/a_request_whose_role_header_is_not_a_declared_role_is_unauthenticated
    """
    bogus = build_user_headers("nobody-1", "BrewMaster")

    response = api.get_recipe("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", bogus)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["data"]["error_id"] != "ERR_PRODUCTION_RESOURCE_NOT_FOUND"


def test_the_packaging_and_commercial_families_use_their_own_not_found_codes(api):
    """PRD 2.7: "`ERR_PACKAGING_RESOURCE_NOT_FOUND` (HTTP 404) covers a missing
    `PackagingRun`, `FinishedLot` or `Keg`."
    PRD 2.7: "`ERR_COMMERCIAL_RESOURCE_NOT_FOUND` (HTTP 404) covers a missing
    `Account`, `Shipment`, `ShipmentLine`, `Subscription`, `SubscriptionAllocation`,
    `TaproomFill` or `RecallNotice`."

    Design: Corner/errors/packaging_and_commercial_resource_not_found_use_their_own_error_ids
    """
    packaging = api.get_finished_lot("11111111-2222-4333-8444-555555555555", SALES)
    validate_error(packaging, ApiErrorId.ERR_PACKAGING_RESOURCE_NOT_FOUND.value, 404)

    commercial = api.get_shipment("66666666-7777-4888-8999-000000000000", SALES)
    validate_error(commercial, ApiErrorId.ERR_COMMERCIAL_RESOURCE_NOT_FOUND.value, 404)
