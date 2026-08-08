"""Lactation and sleep support: benefit pools, the consultant calendar and overage."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_consult_booking,
    assert_grant_conservation,
    assert_instant_equals,
    api_client,
    book_consult,
    create_consult_booking_payload,
    get_booking,
    get_grant,
    grant_for,
    issue_invoice,
    open_invoice,
    service_lines_for_membership,
    set_clock,
    setup_active_membership,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _active_household(**kwargs):
    kwargs.setdefault("clock", "2026-06-01T00:00:00Z")
    return setup_active_membership(**kwargs)


def _suspended_household_holding_one_booking():
    """An ACTIVE membership with one SCHEDULED consult, then suspended for non-payment."""
    scenario = _active_household(household_name="Moreau", child_first_name="Zoe")
    booking = book_consult(
        scenario["membership"]["id"],
        scenario["physician"]["id"],
        "2026-06-20T09:00:00Z",
        "2026-06-20T09:45:00Z",
    )
    july = issue_invoice(open_invoice(scenario["family"]["id"], "2026-07-01")["id"])
    set_clock("2026-06-16T00:00:00Z")
    validate_success(
        api_client.suspend_membership(
            scenario["membership"]["id"], {"reason": "July invoice past due"}, BILLING
        )
    )
    scenario["booking"] = booking
    scenario["july_invoice"] = july
    return scenario


# ==========================================================================
# Membership state outranks the calendar
# ==========================================================================


def test_suspended_membership_is_reported_before_the_schedule_conflict(api):
    """PRD §3.8: "The membership must be `ACTIVE`, refusing anything else with
    `ERR_MEMBERSHIP_NOT_ACTIVE`."
    PRD §2.7: "Rules are evaluated in a strict ascending order and the **first** rule that
    fails determines the response."
    PRD §2.7: "**Temporal overlap.** Consult-booking creation and reschedule run the
    buffered calendar test of §3.8 against the consultant's other `SCHEDULED` bookings,
    and a collision is `ERR_SCHEDULE_CONFLICT` (409)."

    Design: Difficulty/priority_pair_validation_conflict/membership_not_active_outranks_consult_schedule_conflict
    """
    scenario = _suspended_household_holding_one_booking()

    resp = api.create_consult_booking(
        create_consult_booking_payload(
            scenario["membership"]["id"],
            scenario["physician"]["id"],
            "2026-06-20T09:30:00Z",
            "2026-06-20T10:15:00Z",
        ),
        COORDINATOR,
    )
    error = validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)
    assert resp.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_SCHEDULE_CONFLICT.value


def test_the_refused_booking_moves_no_entitlement_counter(api):
    """PRD §2.7: "No later rule runs and no partial mutation is persisted."
    PRD §2.10: "For every entitlement grant, `available_count` plus `booked_count` plus
    `consumed_count` always equals `granted_count`."

    Design: Difficulty/priority_pair_validation_conflict/membership_not_active_outranks_consult_schedule_conflict
    """
    scenario = _suspended_household_holding_one_booking()
    grant_id = scenario["booking"]["grant_id"]

    validate_error(
        api.create_consult_booking(
            create_consult_booking_payload(
                scenario["membership"]["id"],
                scenario["physician"]["id"],
                "2026-06-20T09:30:00Z",
                "2026-06-20T10:15:00Z",
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE,
    )

    rows, meta = validate_paginated(
        api.list_consult_bookings(
            COORDINATOR, params={"membership_id": scenario["membership"]["id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1

    grant = get_grant(grant_id)
    assert grant["granted_count"] == 3
    assert grant["booked_count"] == 1
    assert grant["available_count"] == 2
    assert_grant_conservation(grant)


# ==========================================================================
# The consultant calendar
# ==========================================================================


def test_a_booking_inside_the_turnaround_buffer_collides(api):
    """PRD §3.8: "A booking occupies from its `scheduled_start` inclusive up to but not
    including its `scheduled_end`, and that occupancy is then extended by a fifteen-minute
    turnaround on the trailing edge only."
    PRD §3.8: "A booking that begins exactly at a prior booking's `scheduled_end` plus
    fifteen minutes does **not** collide — the buffer is satisfied at equality. Anything
    closer does collide, and a collision is refused with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/consult_calendar_half_open_interval_plus_turnaround_buffer
    """
    scenario = _active_household(household_name="Ubeda", child_first_name="Uma")
    book_consult(
        scenario["membership"]["id"],
        scenario["physician"]["id"],
        "2026-06-20T09:00:00Z",
        "2026-06-20T09:45:00Z",
    )

    resp = api.create_consult_booking(
        create_consult_booking_payload(
            scenario["membership"]["id"],
            scenario["physician"]["id"],
            "2026-06-20T09:59:00Z",
            "2026-06-20T10:44:00Z",
        ),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)
    assert resp.status_code == 409


def test_a_booking_exactly_at_the_buffer_edge_is_accepted(api):
    """PRD §3.8: "A booking that begins exactly at a prior booking's `scheduled_end` plus
    fifteen minutes does **not** collide — the buffer is satisfied at equality."
    PRD §3.8: "If the selected grant's `available_count` is strictly greater than 0 at the
    moment of creation, the booking takes `coverage_route` `ENTITLEMENT` and the grant's
    `booked_count` rises by 1."

    Design: Difficulty/resource_temporal_overlap/consult_calendar_half_open_interval_plus_turnaround_buffer
    """
    scenario = _active_household(household_name="Ubeda", child_first_name="Uma")
    doc_id = scenario["physician"]["id"]
    first = book_consult(
        scenario["membership"]["id"], doc_id, "2026-06-20T09:00:00Z", "2026-06-20T09:45:00Z"
    )
    grant_id = first["grant_id"]

    validate_error(
        api.create_consult_booking(
            create_consult_booking_payload(
                scenario["membership"]["id"], doc_id,
                "2026-06-20T09:59:00Z", "2026-06-20T10:44:00Z",
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_SCHEDULE_CONFLICT,
    )

    second = validate_success(
        api.create_consult_booking(
            create_consult_booking_payload(
                scenario["membership"]["id"], doc_id,
                "2026-06-20T10:00:00Z", "2026-06-20T10:45:00Z",
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_consult_booking(second)
    assert second["status"] == "SCHEDULED"
    assert second["coverage_route"] == "ENTITLEMENT"

    rows, meta = validate_paginated(
        api.list_consult_bookings(COORDINATOR, params={"consultant_physician_id": doc_id})
    )
    assert meta["total_count"] == 2 and len(rows) == 2

    grant = get_grant(grant_id)
    assert grant["granted_count"] == 3
    assert grant["booked_count"] == 2
    assert grant["consumed_count"] == 0
    assert grant["available_count"] == 1
    assert_grant_conservation(grant)


def test_consult_end_equal_to_its_start_is_refused(api):
    """PRD §3.8: "a `scheduled_start` and a `scheduled_end` that must be strictly after
    it"
    PRD §2.7: "Then ordering is checked, failing which the response is
    `ERR_INVALID_DATE_RANGE` (400): `scheduled_end` must be strictly after
    `scheduled_start` on consult-booking creation and reschedule"

    Design: Corner/validations/corner_consult_end_before_start_returns_invalid_date_range
    """
    scenario = _active_household(household_name="Jarvis", child_first_name="Kit")

    resp = api.create_consult_booking(
        create_consult_booking_payload(
            scenario["membership"]["id"],
            scenario["physician"]["id"],
            "2026-06-20T09:00:00Z",
            "2026-06-20T09:00:00Z",
            consult_type="SLEEP_CONSULT",
        ),
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
    assert resp.status_code == 400

    rows, meta = validate_paginated(
        api.list_consult_bookings(
            COORDINATOR, params={"membership_id": scenario["membership"]["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []

    sleep_grant = grant_for(scenario["membership"]["id"], "SLEEP_CONSULT")
    assert sleep_grant["booked_count"] == 0
    assert sleep_grant["available_count"] == 2


# ==========================================================================
# Benefit-pool conservation
# ==========================================================================


def _four_lactation_bookings(scenario):
    doc_id = scenario["physician"]["id"]
    membership_id = scenario["membership"]["id"]
    slots = [
        ("2026-06-20T09:00:00Z", "2026-06-20T09:45:00Z"),
        ("2026-06-20T10:00:00Z", "2026-06-20T10:45:00Z"),
        ("2026-06-20T11:00:00Z", "2026-06-20T11:45:00Z"),
        ("2026-06-20T12:00:00Z", "2026-06-20T12:45:00Z"),
    ]
    return [book_consult(membership_id, doc_id, start, end) for start, end in slots]


def test_pool_exhausts_at_three_bookings_and_the_fourth_takes_the_overage_route(api):
    """PRD §3.8: "Otherwise the booking takes `coverage_route` `OVERAGE` and the grant's
    `overage_count` rises by 1; an overage booking never touches `booked_count` or
    `consumed_count` at all. Whenever a counter update leaves `available_count` at 0, the
    grant transitions `OPEN → EXHAUSTED`, and subsequent bookings against it are created
    on the overage route."
    PRD §2.10: "For every entitlement grant, `available_count` plus `booked_count` plus
    `consumed_count` always equals `granted_count`."

    Design: Difficulty/compensating_invariant/entitlement_pool_identity_survives_book_exhaust_overage_and_cancel
    """
    scenario = _active_household(household_name="Weiss", child_first_name="Tess")
    grant_before = grant_for(scenario["membership"]["id"], "LACTATION_CONSULT")

    assert grant_before["granted_count"] == 3
    assert grant_before["available_count"] == 3
    assert grant_before["booked_count"] == 0
    assert grant_before["consumed_count"] == 0
    assert grant_before["released_count"] == 0
    assert grant_before["status"] == "OPEN"

    bookings = _four_lactation_bookings(scenario)
    grant_id = bookings[0]["grant_id"]

    assert bookings[3]["coverage_route"] == "OVERAGE"

    grant = get_grant(grant_id)
    assert grant["booked_count"] == 3
    assert grant["available_count"] == 0
    assert grant["consumed_count"] == 0
    assert grant["overage_count"] == 1
    assert grant["status"] == "EXHAUSTED"
    assert_grant_conservation(grant)


def test_cancelling_a_booking_restores_the_pool_exactly(api):
    """PRD §2.10: "A create followed by a cancel therefore restores `available_count` to
    its exact pre-create value, leaves `booked_count` and `consumed_count` unchanged, and
    advances `released_count` by one."
    PRD §3.8: "Second, because `available_count` has become strictly positive, a grant
    sitting in `EXHAUSTED` transitions back to `OPEN` — closing a loop the pool may
    traverse any number of times."
    PRD §3.8: "**No service line is created by a cancellation**; nothing was delivered, so
    nothing is charged."

    Design: Difficulty/compensating_invariant/entitlement_pool_identity_survives_book_exhaust_overage_and_cancel
    """
    scenario = _active_household(household_name="Weiss", child_first_name="Tess")
    bookings = _four_lactation_bookings(scenario)
    grant_id = bookings[0]["grant_id"]

    cancelled = validate_success(api.cancel_consult_booking(bookings[1]["id"], COORDINATOR))
    assert cancelled["status"] == "CANCELLED"

    grant = get_grant(grant_id)
    assert grant["booked_count"] == 2
    assert grant["released_count"] == 1
    assert grant["available_count"] == 1
    assert grant["consumed_count"] == 0
    assert grant["status"] == "OPEN"
    assert_grant_conservation(grant)
    assert grant["available_count"] + grant["booked_count"] + grant["consumed_count"] == 3

    assert service_lines_for_membership(scenario["membership"]["id"]) == []


def test_reschedule_is_capped_at_two_successful_moves(api):
    """PRD §3.8: "The booking's `reschedule_count` must be strictly less than 2 before the
    move is applied, so a booking may be moved twice and the third attempt is refused with
    `ERR_RESCHEDULE_LIMIT_REACHED`. On success the interval is overwritten and
    `reschedule_count` rises by 1. **No entitlement counter moves on a reschedule** — the
    hold the booking placed at creation is exactly the hold it still has afterwards."

    Design: Corner/state_machines/corner_consult_reschedule_capped_at_two_attempts
    """
    scenario = _active_household(household_name="Ortega", child_first_name="Luz")
    booking = book_consult(
        scenario["membership"]["id"],
        scenario["physician"]["id"],
        "2026-06-20T09:00:00Z",
        "2026-06-20T09:45:00Z",
    )
    grant_id = booking["grant_id"]

    first = validate_success(
        api.reschedule_consult_booking(
            booking["id"],
            {"scheduled_start": "2026-06-21T09:00:00Z", "scheduled_end": "2026-06-21T09:45:00Z"},
            COORDINATOR,
        )
    )
    assert first["reschedule_count"] == 1
    assert_instant_equals(first["scheduled_start"], "2026-06-21T09:00:00.000Z", "scheduled_start")

    second = validate_success(
        api.reschedule_consult_booking(
            booking["id"],
            {"scheduled_start": "2026-06-22T09:00:00Z", "scheduled_end": "2026-06-22T09:45:00Z"},
            COORDINATOR,
        )
    )
    assert second["reschedule_count"] == 2
    assert_instant_equals(second["scheduled_start"], "2026-06-22T09:00:00.000Z", "scheduled_start")

    third = api.reschedule_consult_booking(
        booking["id"],
        {"scheduled_start": "2026-06-23T09:00:00Z", "scheduled_end": "2026-06-23T09:45:00Z"},
        COORDINATOR,
    )
    validate_error(third, ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED)
    assert third.status_code == 409

    unchanged = get_booking(booking["id"])
    assert unchanged["reschedule_count"] == 2
    assert_instant_equals(
        unchanged["scheduled_start"], "2026-06-22T09:00:00.000Z", "scheduled_start"
    )
    assert unchanged["status"] == "SCHEDULED"

    grant = get_grant(grant_id)
    assert grant["booked_count"] == 1
    assert grant["available_count"] == 2
    assert_grant_conservation(grant)


def test_completing_an_overage_consult_bills_the_plan_overage_fee(api):
    """PRD §3.8: "Either way a service line is produced, carrying the `consult_booking_id`
    and a `service_code` equal to the booking's `consult_type`: on the entitlement route
    it is routed `COVERED_BY_MEMBERSHIP` with `billed_amount_cents` 0, and on the overage
    route it is routed `PATIENT_RESPONSIBILITY` with `billed_amount_cents` equal to the
    plan's `overage_consult_fee_cents`. In both cases the line is created directly in
    status `SETTLED`."
    PRD §3.8: "On the entitlement route the grant's `booked_count` falls by 1 and its
    `consumed_count` rises by 1, which leaves `available_count` exactly where it was, so
    an `EXHAUSTED` grant stays `EXHAUSTED` through a completion."

    Design: Corner/calculations/corner_overage_consult_completion_bills_the_plan_overage_fee
    """
    scenario = _active_household(household_name="Zabala", child_first_name="Iker")
    bookings = _four_lactation_bookings(scenario)
    grant_id = bookings[0]["grant_id"]

    set_clock("2026-06-20T23:00:00Z")

    entitled = validate_success(api.complete_consult_booking(bookings[0]["id"], COORDINATOR))
    overage = validate_success(api.complete_consult_booking(bookings[3]["id"], COORDINATOR))
    assert entitled["status"] == "COMPLETED"
    assert overage["status"] == "COMPLETED"
    assert entitled["coverage_route"] == "ENTITLEMENT"
    assert overage["coverage_route"] == "OVERAGE"

    entitled_lines, _ = validate_paginated(
        api.list_service_lines(BILLING, params={"consult_booking_id": bookings[0]["id"]})
    )
    assert len(entitled_lines) == 1
    assert entitled_lines[0]["service_code"] == "LACTATION_CONSULT"
    assert entitled_lines[0]["route"] == "COVERED_BY_MEMBERSHIP"
    assert entitled_lines[0]["billed_amount_cents"] == 0
    assert entitled_lines[0]["patient_responsibility_cents"] == 0
    assert entitled_lines[0]["status"] == "SETTLED"

    overage_lines, _ = validate_paginated(
        api.list_service_lines(BILLING, params={"consult_booking_id": bookings[3]["id"]})
    )
    assert len(overage_lines) == 1
    assert overage_lines[0]["service_code"] == "LACTATION_CONSULT"
    assert overage_lines[0]["route"] == "PATIENT_RESPONSIBILITY"
    assert overage_lines[0]["billed_amount_cents"] == 15000
    assert overage_lines[0]["patient_responsibility_cents"] == 15000
    assert overage_lines[0]["status"] == "SETTLED"

    grant = get_grant(grant_id)
    assert grant["booked_count"] == 2
    assert grant["consumed_count"] == 1
    assert grant["available_count"] == 0
    assert grant["overage_count"] == 1
    assert grant["status"] == "EXHAUSTED"
    assert_grant_conservation(grant)
