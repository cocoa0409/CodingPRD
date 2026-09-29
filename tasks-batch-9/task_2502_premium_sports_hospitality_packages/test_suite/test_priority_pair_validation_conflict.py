"""Requests that violate two rules at once, where the order of checks decides.

Each scenario is built so that two distinct rejections are simultaneously
earned, the declared precedence picks one, and then the winning condition is
repaired so the loser surfaces on a byte-identical retry.
"""

from typing import Any, Dict

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    ERR_BOOKING_NOT_ALLOCATED,
    ERR_BUILD_NOT_READY,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_INVALID_PACKAGE_STATE,
    ApiClient,
    allocate_booking,
    approve_build,
    assert_block_position,
    assert_booking_dimensions,
    assert_total_count,
    booking_payload,
    get_success_data,
    gold_sales_floor,
    make_booking,
    make_build,
    make_client,
    make_committed_deal,
    make_event,
    make_priced_gold_package,
    publish_package,
    read_block,
    read_booking,
    read_client,
    ready_build,
    reset_clock,
    validate_error,
)


def _priced_but_unpublished_package_and_a_thinly_funded_client(
    api: ApiClient,
) -> Dict[str, Any]:
    """A PRICED-not-PUBLISHED package and a client with a 1000-cent limit.

    A 10-unit booking on this pair earns two rejections at once: the package is
    not in a bookable state, and the price it would carry is a thousand times
    the client's remaining credit.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    package = make_priced_gold_package(api, event["id"])
    client = make_client(api, name="Thinly Funded Ltd", credit_limit_cents=1000)
    return {
        "event": event,
        "deal": deal,
        "package": package,
        "client": client,
        "payload": booking_payload(client["id"], package["id"], units=10),
    }


def _unallocated_booking_and_a_planned_build(api: ApiClient) -> Dict[str, Any]:
    """A RESERVED booking on a fixture whose only build is still PLANNED.

    Issuing credentials against this pair earns two rejections at once: the
    zone's build is not READY, and the booking holds no allocation.
    """
    floor = gold_sales_floor(api)
    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=10)
    floor["booking"] = booking
    floor["build"] = make_build(api, floor["event"]["id"])
    return floor


# --------------------------------------------------------------------------
# Package state beats credit limit on booking creation
# --------------------------------------------------------------------------


def test_an_unpublished_package_is_reported_before_the_client_runs_out_of_credit(
    api: ApiClient,
) -> None:
    """Both rules are broken and the state rule is the one the caller sees.

    The package is PRICED at a list price of 177115, so a 10-unit booking would
    cost 1637605 against a credit limit of 1000 — the credit rule is genuinely
    broken. The response is nonetheless the package-state rejection, because
    referential and state validation is ordered ahead of business-rule
    validation, and the credit code never appears.

    PRD §2.7: "**Fiscal gates**, evaluated last, in the order: client credit
    standing (`ERR_CLIENT_NOT_ACTIVE`), block units unavailable
    (`ERR_ALLOCATION_UNITS_UNAVAILABLE`), credit limit
    (`ERR_CREDIT_LIMIT_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/package_state_conflict_beats_credit_limit_on_create_booking
    """
    scenario = _priced_but_unpublished_package_and_a_thinly_funded_client(api)
    assert scenario["package"]["package_status"] == "PRICED"
    assert scenario["package"]["list_price_cents"] == 177115
    assert scenario["client"]["credit_limit_cents"] == 1000

    response = api.create_booking(scenario["payload"], CLIENT_SERVICE_AGENT)

    body = validate_error(response, ERR_INVALID_PACKAGE_STATE, 409)
    assert body["error_id"] != ERR_CREDIT_LIMIT_EXCEEDED


def test_publishing_the_package_lets_the_credit_rejection_surface_unchanged(
    api: ApiClient,
) -> None:
    """The identical request now fails on the loser of the first conflict.

    Publishing the package repairs the only condition that outranked the credit
    rule; nothing about the client, the units or the payload changed. The same
    request is now rejected with a different status and a different code,
    proving both rules were live all along.

    PRD §3.5: "The target package must be `PUBLISHED`, or the sale is
    `ERR_INVALID_PACKAGE_STATE`, and its fixture must still be `SCHEDULED`,
    `POSTPONED` or `RESCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/package_state_conflict_beats_credit_limit_on_create_booking
    """
    scenario = _priced_but_unpublished_package_and_a_thinly_funded_client(api)
    payload = scenario["payload"]

    first = api.create_booking(payload, CLIENT_SERVICE_AGENT)
    validate_error(first, ERR_INVALID_PACKAGE_STATE, 409)

    published = publish_package(api, scenario["package"]["id"])
    assert published["package_status"] == "PUBLISHED"

    second = api.create_booking(payload, CLIENT_SERVICE_AGENT)
    validate_error(second, ERR_CREDIT_LIMIT_EXCEEDED, 402)


def test_neither_rejection_leaves_a_booking_or_moves_the_client(
    api: ApiClient,
) -> None:
    """Two rejected creation attempts write nothing at all.

    After the state rejection and the credit rejection the client holds no
    bookings, and its exposure and credit standing are still the opening values
    a new client is registered with, because neither rejected sale ever became
    an input to them.

    PRD §3.5: "A new client opens with `client_status` at `ACTIVE`,
    `outstanding_cents` at 0 and `overdue_installment_count` at 0."

    Design: Difficulty/priority_pair_validation_conflict/package_state_conflict_beats_credit_limit_on_create_booking
    """
    scenario = _priced_but_unpublished_package_and_a_thinly_funded_client(api)
    client_id = scenario["client"]["id"]

    validate_error(api.create_booking(scenario["payload"], CLIENT_SERVICE_AGENT),
                   ERR_INVALID_PACKAGE_STATE, 409)
    publish_package(api, scenario["package"]["id"])
    validate_error(api.create_booking(scenario["payload"], CLIENT_SERVICE_AGENT),
                   ERR_CREDIT_LIMIT_EXCEEDED, 402)

    assert_total_count(
        api.list_bookings(CLIENT_SERVICE_AGENT, {"client_id": client_id}), 0
    )
    client = read_client(api, client_id)
    assert client["outstanding_cents"] == 0
    assert client["client_status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Build readiness beats allocation on credential issuance
# --------------------------------------------------------------------------


def test_a_planned_build_is_reported_before_the_missing_allocation(
    api: ApiClient,
) -> None:
    """Two 422s are earned and the build's readiness is the one returned.

    The booking has never been allocated and the fixture's only build is still
    PLANNED. Both conditions are checked with the same HTTP status, so only the
    error identity can distinguish them, and the readiness safety condition is
    the one that answers.

    PRD §3.7: "The readiness check precedes the allocation check, so a booking
    that is neither allocated nor served by a ready build reports
    `ERR_BUILD_NOT_READY`."

    Design: Difficulty/priority_pair_validation_conflict/build_not_ready_safety_beats_booking_not_allocated_referential
    """
    scenario = _unallocated_booking_and_a_planned_build(api)
    assert scenario["booking"]["fulfillment_status"] == "RESERVED"
    assert scenario["build"]["build_state"] == "PLANNED"

    response = api.issue_credentials(scenario["booking"]["id"], CLIENT_SERVICE_AGENT)

    body = validate_error(response, ERR_BUILD_NOT_READY, 422)
    assert body["error_id"] != ERR_BOOKING_NOT_ALLOCATED

    booking = read_booking(api, scenario["booking"]["id"])
    assert booking["fulfillment_status"] == "RESERVED"
    assert booking["credentials_issued_count"] == 0
    assert booking["allocation_block_id"] is None


def test_readying_the_build_exposes_the_allocation_rejection_at_the_same_status(
    api: ApiClient,
) -> None:
    """The same call, the same 422, a different error identity.

    Approving and readying the build repairs the winning condition without
    touching the booking. The identical request is still rejected, still with
    422, but now on the booking's own missing allocation — which is what makes
    the ordering observable rather than a matter of status codes.

    PRD §3.7: "And the booking's `allocation_block_id` must be non-null, because
    credentials can only be minted against inventory actually committed to this
    booking; a null gives `ERR_BOOKING_NOT_ALLOCATED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/build_not_ready_safety_beats_booking_not_allocated_referential
    """
    scenario = _unallocated_booking_and_a_planned_build(api)
    booking_id = scenario["booking"]["id"]

    first = api.issue_credentials(booking_id, CLIENT_SERVICE_AGENT)
    validate_error(first, ERR_BUILD_NOT_READY, 422)

    approve_build(api, scenario["build"]["id"])
    readied = ready_build(api, scenario["build"]["id"])
    assert readied["build_state"] == "READY"

    second = api.issue_credentials(booking_id, CLIENT_SERVICE_AGENT)
    validate_error(second, ERR_BOOKING_NOT_ALLOCATED, 422)

    assert read_booking(api, booking_id)["credentials_issued_count"] == 0


def test_repairing_both_conditions_lets_the_credentials_be_minted(
    api: ApiClient,
) -> None:
    """With the build READY and the booking ALLOCATED the third attempt lands.

    The same call that was rejected twice now succeeds: the booking becomes
    CREDENTIALED and mints 10 * (2 tickets + 1 hospitality pass) == 30
    credentials, while the block records the 20 committed ticket units the
    allocation consumed.

    PRD §3.7: "Issuance moves the booking `ALLOCATED → CREDENTIALED`, sets
    `credentials_issued_count` to the booking's `units` multiplied by one more
    than the package's `tickets_per_package` — one credential per ticket plus one
    hospitality credential per package unit — and stamps a
    `credential_serial_prefix` on the booking."

    Design: Difficulty/priority_pair_validation_conflict/build_not_ready_safety_beats_booking_not_allocated_referential
    """
    scenario = _unallocated_booking_and_a_planned_build(api)
    booking_id = scenario["booking"]["id"]

    validate_error(api.issue_credentials(booking_id, CLIENT_SERVICE_AGENT),
                   ERR_BUILD_NOT_READY, 422)
    approve_build(api, scenario["build"]["id"])
    ready_build(api, scenario["build"]["id"])
    validate_error(api.issue_credentials(booking_id, CLIENT_SERVICE_AGENT),
                   ERR_BOOKING_NOT_ALLOCATED, 422)

    allocate_booking(api, booking_id, scenario["block"]["id"])
    credentialed = get_success_data(
        api.issue_credentials(booking_id, CLIENT_SERVICE_AGENT)
    )

    assert_booking_dimensions(credentialed, fulfillment_status="CREDENTIALED",
                              payment_status="UNPAID")
    assert credentialed["credentials_issued_count"] == 30
    assert_block_position(read_block(api, scenario["block"]["id"]),
                          allocated=40, committed=20, released_back=0,
                          state="EXHAUSTED")
