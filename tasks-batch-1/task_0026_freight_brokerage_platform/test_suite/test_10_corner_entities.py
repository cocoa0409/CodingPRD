"""Corner-design section: entities.

Creation, not-found, type-constraint, and FK-integrity claims on the entity
table — each rooted in a single PRD sentence that pins the observable
outcome.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_carrier,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_carrier_payload,
    create_quote_request_payload,
    create_shipper_payload,
)


def test_create_shipper_returns_201_with_defaults(api):
    """PRD §3.1: "The new row's `status` is `ACTIVE` and the system-managed
    `open_ar_cents` accumulator begins at zero."
    PRD §2.4: "a non-negative integer that starts at 1 (or any value the
    implementation chooses) on creation and increments by exactly one on
    every mutation, including state transitions and computed-field
    refreshes."

    Design: Corner/entities/create_shipper_returns_201_with_all_fields
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_shipper(
        create_shipper_payload(
            legal_name="Sierra Shippers",
            billing_email="ap@sierra.test",
            credit_limit_cents=50_000_000,
        ),
        TEST_USERS["broker_ops_headers"],
    )
    body = validate_success(res, 201)
    assert body["status"] == "ACTIVE"
    assert body["open_ar_cents"] == 0
    # PRD §2.4 says version is a non-negative integer; the most natural read
    # is that "starts at 1" pins the initial value. The PRD parenthetical
    # ("or any value the implementation chooses") leaves the exact starting
    # number underdetermined, so we assert that it is an int >= 1.
    assert isinstance(body["version"], int) and body["version"] >= 1


def test_get_shipper_not_found_returns_404(api):
    """PRD §2.7: "existence of every path-parameter resource resolved
    strictly left-to-right (`ERR_RESOURCE_NOT_FOUND`)"
    PRD §5: ERR_RESOURCE_NOT_FOUND carries HTTP 404.

    Design: Corner/entities/get_shipper_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_shipper(NON_EXISTENT_UUID, TEST_USERS["broker_ops_headers"])
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


def test_carrier_with_duplicate_mc_number_rejected(api):
    """PRD §3.1: "The `mc_number` must be a 6- or 7-digit numeric string and
    the `usdot_number` a 5- to 8-digit numeric string; each value must be
    unique across the carrier table. A registration that violates the
    format or uniqueness rule is rejected with `ERR_INVALID_MC_USDOT`."

    Design: Corner/entities/carrier_mc_number_unique_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    # First carrier with a specific mc_number.
    create_carrier(mc_number="2424241", usdot_number="24242421",
                   smartway_tier="NONE",
                   insurance_expiry_utc="2027-01-01T00:00:00Z",
                   safety_score=30.0)
    # Second carrier with the same mc_number but different usdot_number.
    res = api.create_carrier(
        create_carrier_payload(
            legal_name="Tango Carrier Two",
            mc_number="2424241",
            usdot_number="24242422",
            smartway_tier="NONE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        ),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_INVALID_MC_USDOT")


def test_quote_request_with_nonexistent_shipper_returns_fk_not_found(api):
    """PRD §2.7: "existence of every foreign-key reference present in the
    request body (`ERR_FK_NOT_FOUND`)"
    PRD §5: ERR_FK_NOT_FOUND carries HTTP 422.

    Design: Corner/entities/quote_request_fk_shipper_not_found
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_quote_request(
        create_quote_request_payload(
            NON_EXISTENT_UUID,
            lane_origin="10001", lane_destination="30303", distance_miles=400,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="DRY_VAN",
        ),
        TEST_USERS["broker_ops_headers"],
    )
    validate_error(res, "ERR_FK_NOT_FOUND")
