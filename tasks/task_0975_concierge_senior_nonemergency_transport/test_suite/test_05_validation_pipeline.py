"""Validation-pipeline ordering: earlier pipeline stages pre-empt later ones
when one request violates both."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_booked_ride,
    create_client,
    create_ride_payload,
    set_clock,
    setup_overdue_ar_client,
    suspend_client,
    validate_error,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]


def test_suspended_client_error_beats_billing_hold_on_booking(api):
    """PRD §2.6: "Every request is evaluated against a fixed, ordered
    validation pipeline. A request fails at the first check it violates, so
    when several rules could reject the same request, the error the caller
    observes is determined by this order"
    PRD §3.4: "The client must be `ACTIVE` — booking for a `SUSPENDED` or
    `DEACTIVATED` client is rejected with `ERR_CLIENT_SUSPENDED`."
    PRD §3.4: "Last come the fiscal gates: an `ACTIVE` rate card must cover the
    derived service class at the pickup date (`ERR_RATE_CARD_NOT_ACTIVE`), and
    the client's overdue receivables must be below their hold limit."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_billing_hold_on_create
    """
    client, _ = setup_overdue_ar_client(limit_cents=1000)
    from test_helpers import get_success_data
    current = get_success_data(api_client.get_client(client["id"], COORD))
    suspend_client(client["id"], current["version"])
    # Both conditions now hold: SUSPENDED (state stage) and overdue AR
    # 1251 >= 1000 (fiscal stage). The state check runs first.
    resp = api_client.create_ride(
        create_ride_payload(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED)


def test_billing_hold_fires_on_its_own_when_client_active(api):
    """PRD §3.4: "The **billing hold** sums, over the client's invoices in
    `ISSUED` or `PARTIALLY_PAID` whose `due_date` is strictly before the
    logical today — an invoice due today is not yet overdue — the unpaid
    remainder of each, and when that sum is greater than or equal to
    `billing_hold_limit_cents` (exactly equal triggers the hold) the booking is
    rejected with `ERR_BILLING_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_billing_hold_on_create
    """
    client, _ = setup_overdue_ar_client(limit_cents=1000)
    resp = api_client.create_ride(
        create_ride_payload(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z"),
        COORD)
    # With the client still ACTIVE the state stage passes and the fiscal
    # gate is what fires.
    validate_error(resp, ApiErrorId.ERR_BILLING_HOLD)


def _setup_referential_vs_fiscal():
    """Client A over billing hold; client B owns a SCHEDULED APPOINTMENT ride.
    Returns (client_a, ride_b)."""
    client_a, _ = setup_overdue_ar_client(limit_cents=1000)
    client_b = create_client(full_name="Bob B", address="2 Elm St")
    ride_b = create_booked_ride(
        client_b["id"], kind="APPOINTMENT",
        scheduled_pickup_at="2026-06-03T10:00:00Z")
    return client_a, ride_b


def test_return_link_mismatch_beats_billing_hold_on_booking(api):
    """PRD §3.4: "Referential integrity comes later in the pipeline: a
    `linked_return_ride_id` must target a ride of the **same client**, of kind
    `APPOINTMENT`, still `SCHEDULED`, and with no return link of its own — any
    mismatch is `ERR_RETURN_LINK_MISMATCH` — and a
    `booked_by_family_member_id` naming a member attached to a different client
    is `ERR_FAMILY_CLIENT_MISMATCH`. Last come the fiscal gates"

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_billing_hold_on_create
    """
    client_a, ride_b = _setup_referential_vs_fiscal()
    resp = api_client.create_ride(
        create_ride_payload(client_a["id"], scheduled_pickup_at="2026-06-04T10:00:00Z",
                            linked_return_ride_id=ride_b["id"]),
        COORD)
    # Both referential (return link owned by another client) and fiscal
    # (overdue AR) failures hold; referential is earlier in the pipeline.
    validate_error(resp, ApiErrorId.ERR_RETURN_LINK_MISMATCH)


def test_referential_error_fires_without_any_fiscal_pressure(api):
    """PRD §3.4: "a `linked_return_ride_id` must target a ride of the **same
    client**, of kind `APPOINTMENT`, still `SCHEDULED`, and with no return link
    of its own — any mismatch is `ERR_RETURN_LINK_MISMATCH`"

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_billing_hold_on_create
    """
    from test_helpers import create_active_rate_card, set_clock as sc
    create_active_rate_card()
    client_a = create_client(full_name="Ada A")
    client_b = create_client(full_name="Bob B", address="2 Elm St")
    sc("2026-05-20T09:00:00Z")
    ride_b = create_booked_ride(
        client_b["id"], kind="APPOINTMENT",
        scheduled_pickup_at="2026-06-03T10:00:00Z")
    resp = api_client.create_ride(
        create_ride_payload(client_a["id"], scheduled_pickup_at="2026-06-04T10:00:00Z",
                            linked_return_ride_id=ride_b["id"]),
        COORD)
    validate_error(resp, ApiErrorId.ERR_RETURN_LINK_MISMATCH)
