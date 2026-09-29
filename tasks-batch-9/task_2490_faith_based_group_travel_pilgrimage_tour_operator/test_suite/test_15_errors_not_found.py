"""Identifier resolution and the advisory publication guards: each collection
answers with its own 404 code, a body foreign key answers like a path one, and a
draft advisory may be published once and only once it has taken effect."""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    create_advisory,
    departure_payload,
    publish_advisory,
    read_advisory,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
RISK = TEST_USERS["risk_officer"]
AIR_DESK = TEST_USERS["air_desk_agent"]
LAND = TEST_USERS["land_contractor"]
FINANCE = TEST_USERS["finance_controller"]
PROTECTION = TEST_USERS["protection_administrator"]


def test_a_departure_drawn_on_an_unknown_program_is_a_program_miss(api):
    """PRD §2.8: "Identifiers supplied inside a request body are resolved the
    same way and answer with the same codes, and they are checked **in the order
    they appear in that operation's input list**. Creating a departure resolves
    `program_id`; creating a leader agreement resolves `departure_id`; enrolling
    a traveler resolves `departure_id` and then `recruited_by_agreement_id`;
    opening a seat block resolves `departure_id`; holding a service resolves
    `departure_id` and then `sacred_site_id`; drawing a land line resolves
    `land_resource_id` and then `departure_id`; quoting a protection resolves
    `pilgrim_id`; and assigning rooming resolves `roommate_pilgrim_id`. A body
    identifier that names no stored row yields the owning collection's 404 code
    — a missing recruiting agreement yields `ERR_AGREEMENT_NOT_FOUND`, a missing
    rooming partner yields `ERR_PILGRIM_NOT_FOUND`."

    Design: Corner/errors/unknown_program_fk_on_departure_create_returns_program_not_found
    """
    response = api_client.create_departure(
        departure_payload(NON_EXISTENT_UUID), PLANNER
    )

    validate_error(response, ApiErrorId.PROGRAM_NOT_FOUND.value)


def test_an_unknown_traveler_id_answers_with_the_traveler_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`." And: "Which code is
    returned is decided by the collection segment that owns the failing path
    parameter, not by the resource the caller was ultimately after."

    Design: Corner/errors/unknown_pilgrim_path_id_returns_pilgrim_not_found
    """
    response = api_client.get_pilgrim(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, ApiErrorId.PILGRIM_NOT_FOUND.value)


def test_an_unknown_agreement_id_answers_with_the_agreement_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`."

    Design: Corner/errors/unknown_agreement_path_id_returns_agreement_not_found
    """
    response = api_client.get_agreement(NON_EXISTENT_UUID, FINANCE)

    validate_error(response, ApiErrorId.AGREEMENT_NOT_FOUND.value)


def test_an_unknown_air_block_id_answers_with_the_air_block_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`."

    Design: Corner/errors/unknown_air_block_path_id_returns_air_block_not_found
    """
    response = api_client.get_air_block(NON_EXISTENT_UUID, AIR_DESK)

    validate_error(response, ApiErrorId.AIR_BLOCK_NOT_FOUND.value)


def test_an_unknown_service_booking_id_answers_with_the_booking_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`." And: "Which code is
    returned is decided by the collection segment that owns the failing path
    parameter, not by the resource the caller was ultimately after."

    Design: Corner/errors/unknown_service_booking_path_id_returns_service_booking_not_found
    """
    response = api_client.get_service_booking(NON_EXISTENT_UUID, RISK)

    validate_error(response, ApiErrorId.SERVICE_BOOKING_NOT_FOUND.value)


def test_an_unknown_land_resource_id_answers_with_the_resource_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`."

    Design: Corner/errors/unknown_land_resource_path_id_returns_land_resource_not_found
    """
    response = api_client.get_land_resource(NON_EXISTENT_UUID, LAND)

    validate_error(response, ApiErrorId.LAND_RESOURCE_NOT_FOUND.value)


def test_an_unknown_land_assignment_id_answers_with_the_line_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`." And: "Which code is
    returned is decided by the collection segment that owns the failing path
    parameter, not by the resource the caller was ultimately after."

    Design: Corner/errors/unknown_land_assignment_path_id_returns_land_assignment_not_found
    """
    response = api_client.get_land_assignment(NON_EXISTENT_UUID, LAND)

    validate_error(response, ApiErrorId.LAND_ASSIGNMENT_NOT_FOUND.value)


def test_an_unknown_plan_id_answers_with_the_plan_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`." And: "Which code is
    returned is decided by the collection segment that owns the failing path
    parameter, not by the resource the caller was ultimately after."

    Design: Corner/errors/unknown_payment_plan_path_id_returns_payment_plan_not_found
    """
    response = api_client.get_payment_plan(NON_EXISTENT_UUID, FINANCE)

    validate_error(response, ApiErrorId.PAYMENT_PLAN_NOT_FOUND.value)


def test_reversing_a_receipt_that_was_never_recorded_is_a_receipt_miss(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`." The ladder in §2.9
    puts that resolution above every state rule: "**Path existence** — an
    unresolvable path identifier yields that collection's 404 code, per §2.8.
    This applies to every endpoint carrying a path parameter."

    Design: Corner/errors/reversing_an_unknown_payment_returns_payment_not_found
    """
    response = api_client.reverse_payment(
        NON_EXISTENT_UUID, {"reversal_reason": "BANK_RETURNED_THE_TRANSFER"}, FINANCE
    )

    validate_error(response, ApiErrorId.PAYMENT_NOT_FOUND.value)


def test_an_unknown_protection_id_answers_with_the_protection_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`." And: "Which code is
    returned is decided by the collection segment that owns the failing path
    parameter, not by the resource the caller was ultimately after."

    Design: Corner/errors/unknown_protection_path_id_returns_protection_not_found
    """
    response = api_client.get_protection(NON_EXISTENT_UUID, PROTECTION)

    validate_error(response, ApiErrorId.PROTECTION_NOT_FOUND.value)


def test_an_unknown_advisory_id_answers_with_the_advisory_code(api):
    """PRD §2.8: "Path identifiers are resolved strictly left to right, and the
    first identifier that does not name a stored row terminates the request with
    that collection's own 404 code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_DEPARTURE_NOT_FOUND`, `ERR_PILGRIM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_AIR_BLOCK_NOT_FOUND`,
    `ERR_SACRED_SITE_NOT_FOUND`, `ERR_SERVICE_BOOKING_NOT_FOUND`,
    `ERR_LAND_RESOURCE_NOT_FOUND`, `ERR_LAND_ASSIGNMENT_NOT_FOUND`,
    `ERR_PAYMENT_PLAN_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`,
    `ERR_PROTECTION_NOT_FOUND` or `ERR_ADVISORY_NOT_FOUND`."

    Design: Corner/errors/unknown_advisory_path_id_returns_advisory_not_found
    """
    response = api_client.get_advisory(NON_EXISTENT_UUID, RISK)

    validate_error(response, ApiErrorId.ADVISORY_NOT_FOUND.value)


def test_the_same_advisory_cannot_be_published_twice(api):
    """PRD §3.9: "Publishing requires the advisory to be in `DRAFT`, and
    publishing a `PUBLISHED` or `SUPERSEDED` advisory is
    `ERR_ADVISORY_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/publishing_an_already_published_advisory_returns_advisory_invalid_state
    """
    advisory = create_advisory(
        country="IL",
        level="EXERCISE_CAUTION",
        effective_from="2026-08-01T00:00:00Z",
        source="MOFA",
    )
    published = publish_advisory(advisory["id"])
    assert published["status"] == "PUBLISHED"

    response = api_client.publish_advisory(advisory["id"], RISK)
    validate_error(response, ApiErrorId.ADVISORY_INVALID_STATE.value)

    assert read_advisory(advisory["id"])["status"] == "PUBLISHED"


def test_an_advisory_dated_a_month_ahead_cannot_be_published_yet(api):
    """PRD §3.9: "It also requires `effective_from` to be at or before the
    logical clock, since an advisory may not be published before it takes
    effect; a future-dated advisory is rejected with
    `ERR_ADVISORY_EFFECTIVE_IN_FUTURE` (HTTP 422)."

    Design: Corner/errors/publishing_an_advisory_before_its_effective_date_rejected
    """
    # The clock sits at its default 2026-08-01; this notice governs from September.
    advisory = create_advisory(
        country="IL",
        level="RECONSIDER",
        effective_from="2026-09-01T00:00:00Z",
        source="MOFA",
    )
    assert advisory["status"] == "DRAFT"

    response = api_client.publish_advisory(advisory["id"], RISK)
    validate_error(response, ApiErrorId.ADVISORY_EFFECTIVE_IN_FUTURE.value)

    still_draft = read_advisory(advisory["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["affected_departure_count"] == 0
