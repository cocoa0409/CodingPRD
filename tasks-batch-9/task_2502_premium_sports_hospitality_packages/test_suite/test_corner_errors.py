"""Error identity and error ordering probes across the whole entity catalogue.

Every scenario below is built so that the only thing under test is *which* error
comes back, not whether an error comes back: the calls are authorised, the
bodies are well formed, and the identifiers are the ones that cannot resolve.
Preconditions are built through the declared endpoints against an empty
database.
"""

from typing import Any, Dict, List, Tuple

import pytest

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_MANAGER,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_BLOCK_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_BUILD_NOT_FOUND,
    ERR_CLIENT_NOT_FOUND,
    ERR_COMPONENT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_HOST_NOT_FOUND,
    ERR_INSTALLMENT_NOT_FOUND,
    ERR_PACKAGE_NOT_FOUND,
    ERR_RIGHTS_DEAL_NOT_FOUND,
    ERR_TRANCHE_NOT_FOUND,
    FINANCE_CONTROLLER,
    NON_EXISTENT_UUID,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    ApiClient,
    allocate_booking,
    approve_build,
    booking_payload,
    get_success_data,
    host_assignment_payload,
    make_block,
    make_booking,
    make_build,
    make_client,
    make_committed_deal,
    make_event,
    make_host,
    make_published_bronze_package,
    release_deal,
    reset_clock,
    validate_error,
)

# Each row is one read endpoint, the role authorised to call it, and the 404
# that endpoint owns. The identifier fed to every one of them is the same.
READ_ENDPOINTS: List[Tuple[str, Dict[str, str], str]] = [
    ("get_event", RIGHTS_MANAGER, ERR_EVENT_NOT_FOUND),
    ("get_rights_deal", RIGHTS_MANAGER, ERR_RIGHTS_DEAL_NOT_FOUND),
    ("get_release_tranche", RIGHTS_MANAGER, ERR_TRANCHE_NOT_FOUND),
    ("get_allocation_block", COMMERCIAL_MANAGER, ERR_BLOCK_NOT_FOUND),
    ("get_package_product", COMMERCIAL_MANAGER, ERR_PACKAGE_NOT_FOUND),
    ("get_package_component", COMMERCIAL_MANAGER, ERR_COMPONENT_NOT_FOUND),
    ("get_client", CLIENT_SERVICE_AGENT, ERR_CLIENT_NOT_FOUND),
    ("get_booking", CLIENT_SERVICE_AGENT, ERR_BOOKING_NOT_FOUND),
    ("get_payment_installment", FINANCE_CONTROLLER, ERR_INSTALLMENT_NOT_FOUND),
    ("get_hospitality_build", OPERATIONS_MANAGER, ERR_BUILD_NOT_FOUND),
    ("get_on_site_host", OPERATIONS_MANAGER, ERR_HOST_NOT_FOUND),
    ("get_host_assignment", OPERATIONS_MANAGER, ERR_ASSIGNMENT_NOT_FOUND),
]


# --------------------------------------------------------------------------
# Every entity answers a missing identifier in its own name
# --------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint, headers, expected_error",
                         READ_ENDPOINTS,
                         ids=[row[2] for row in READ_ENDPOINTS])
def test_each_entity_reports_its_own_missing_row(
    api: ApiClient, endpoint: str, headers: Dict[str, str], expected_error: str,
) -> None:
    """The nil identifier resolves nowhere, and each read says which nowhere.

    The database is empty, so all twelve reads are equally doomed; the role on
    each call is one the endpoint authorises, which keeps the identity and
    authority checks out of the way. What remains under test is the machine-
    readable identity of the error, and a single shared not-found handler can only
    be right about one of these twelve.

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    Design: Corner/errors/each_not_found_row_answers_for_its_own_entity_on_a_nil_uuid
    """
    response = getattr(api, endpoint)(NON_EXISTENT_UUID, headers)

    validate_error(response, expected_error, 404)


def test_the_twelve_missing_row_reports_are_twelve_distinct_identities(
    api: ApiClient,
) -> None:
    """One sweep of the same identifier across the catalogue yields twelve names.

    Read back to back in a single sweep, no two of the twelve endpoints may agree
    on the error they return, because each names its own entity. A generic handler
    collapses this set to one member.

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/errors/each_not_found_row_answers_for_its_own_entity_on_a_nil_uuid
    """
    reported = []
    for endpoint, headers, expected_error in READ_ENDPOINTS:
        body = validate_error(
            getattr(api, endpoint)(NON_EXISTENT_UUID, headers), expected_error, 404
        )
        reported.append(body["error_id"])

    assert len(set(reported)) == 12


def test_a_missing_row_still_arrives_in_the_standard_error_envelope(
    api: ApiClient,
) -> None:
    """The 404 body carries the declared envelope, not a bare string.

    The response is the error envelope: `response_type` reads "error", `data`
    holds the machine-readable identity beside a human-readable message, and the
    error `meta` carries only the two request fields.

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/each_not_found_row_answers_for_its_own_entity_on_a_nil_uuid
    """
    response = api.get_event(NON_EXISTENT_UUID, RIGHTS_MANAGER)

    body = validate_error(response, ERR_EVENT_NOT_FOUND, 404)
    assert isinstance(body["message"], str)
    assert body["message"].strip()

    envelope = response.json()
    assert envelope["response_type"] == "error"
    assert set(envelope["meta"]) == {"api_request_id", "api_request_timestamp"}


# --------------------------------------------------------------------------
# Body foreign keys resolve in the declared order, not in body order
# --------------------------------------------------------------------------


def _rosterable_booking_build_and_host(api: ApiClient) -> Dict[str, Any]:
    """One real host, one approved build and one allocated booking.

    Every foreign key of a host assignment therefore has a valid value available,
    so each nil identifier in the probes below can be repaired one at a time
    without disturbing the others.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=40,
                               guaranteed_minimum_units=0)
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40)
    release_deal(api, deal["id"], 40)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api)
    booking = make_booking(api, client["id"], package["id"], units=5)
    allocate_booking(api, booking["id"], block["id"])
    build = make_build(api, event["id"], space_units=30, catering_covers=20,
                       staff_count=5)
    approved = approve_build(api, build["id"])
    host = make_host(api)
    return {
        "event": event,
        "deal": deal,
        "block": block,
        "package": package,
        "client": client,
        "booking": booking,
        "build": approved,
        "host": host,
    }


def test_three_unresolvable_foreign_keys_answer_on_the_booking_first(
    api: ApiClient,
) -> None:
    """Host, booking and build are all nil, and the booking is the one reported.

    All three foreign keys of the roster line are equally unresolvable, so nothing
    but the declared resolution order can choose between the three 404s. The
    booking precedes the build, which precedes the host, and the host is the key
    that appears first in the body — so an implementation walking the body in
    order answers with the wrong one.

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    PRD §5: "| `ERR_BOOKING_NOT_FOUND` | 404 |"

    Design: Corner/errors/body_foreign_keys_are_resolved_in_ascending_priority_order
    """
    _rosterable_booking_build_and_host(api)

    response = api.create_host_assignment(
        host_assignment_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                               NON_EXISTENT_UUID),
        OPERATIONS_MANAGER,
    )

    validate_error(response, ERR_BOOKING_NOT_FOUND, 404)


def test_repairing_the_keys_one_at_a_time_walks_the_declared_order(
    api: ApiClient,
) -> None:
    """Booking, then build, then host — the answers walk the order upwards.

    Each repair removes the current winner and lets the next unresolvable key
    speak, so the three 404s are observed in the declared sequence from one
    endpoint and one otherwise unchanging body. When the last key is repaired the
    roster line is finally created.

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    PRD §3.7: "A new assignment opens `ASSIGNED` with `released_at` unset, and it
    immediately triggers a recompute of the host's `active_assignment_count` and of
    the host list on the booking's itinerary."

    Design: Corner/errors/body_foreign_keys_are_resolved_in_ascending_priority_order
    """
    scenario = _rosterable_booking_build_and_host(api)
    booking_id = scenario["booking"]["id"]
    build_id = scenario["build"]["id"]
    host_id = scenario["host"]["id"]

    all_nil = api.create_host_assignment(
        host_assignment_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                               NON_EXISTENT_UUID),
        OPERATIONS_MANAGER,
    )
    validate_error(all_nil, ERR_BOOKING_NOT_FOUND, 404)

    booking_repaired = api.create_host_assignment(
        host_assignment_payload(NON_EXISTENT_UUID, booking_id, NON_EXISTENT_UUID),
        OPERATIONS_MANAGER,
    )
    validate_error(booking_repaired, ERR_BUILD_NOT_FOUND, 404)

    build_repaired = api.create_host_assignment(
        host_assignment_payload(NON_EXISTENT_UUID, booking_id, build_id),
        OPERATIONS_MANAGER,
    )
    validate_error(build_repaired, ERR_HOST_NOT_FOUND, 404)

    assigned = get_success_data(
        api.create_host_assignment(
            host_assignment_payload(host_id, booking_id, build_id),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert assigned["assignment_state"] == "ASSIGNED"
    assert assigned["released_at"] is None


def test_a_sale_with_an_unresolvable_buyer_reports_the_client_not_the_package(
    api: ApiClient,
) -> None:
    """The same discipline on another endpoint: the buyer resolves first.

    The package named by this sale is real and published, so the only broken thing
    is the buyer, and the answer is the client's own 404 rather than a package or
    business-rule complaint.

    PRD §2.7: "**Existence**, resolved for path identifiers left to right and then
    for body foreign keys, in this order: fixture (`ERR_EVENT_NOT_FOUND`), rights
    deal (`ERR_RIGHTS_DEAL_NOT_FOUND`), release tranche (`ERR_TRANCHE_NOT_FOUND`),
    allocation block (`ERR_BLOCK_NOT_FOUND`), package (`ERR_PACKAGE_NOT_FOUND`),
    package component (`ERR_COMPONENT_NOT_FOUND`), client
    (`ERR_CLIENT_NOT_FOUND`), booking (`ERR_BOOKING_NOT_FOUND`), payment
    installment (`ERR_INSTALLMENT_NOT_FOUND`), hospitality build
    (`ERR_BUILD_NOT_FOUND`), on-site host (`ERR_HOST_NOT_FOUND`), host assignment
    (`ERR_ASSIGNMENT_NOT_FOUND`)."

    PRD §5: "| `ERR_CLIENT_NOT_FOUND` | 404 |"

    Design: Corner/errors/body_foreign_keys_are_resolved_in_ascending_priority_order
    """
    scenario = _rosterable_booking_build_and_host(api)
    assert scenario["package"]["package_status"] == "PUBLISHED"

    response = api.create_booking(
        booking_payload(NON_EXISTENT_UUID, scenario["package"]["id"], units=5),
        CLIENT_SERVICE_AGENT,
    )

    validate_error(response, ERR_CLIENT_NOT_FOUND, 404)
