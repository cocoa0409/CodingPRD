"""Booking consular interviews: capacity, jurisdiction, lead time and reschedules."""

from test_helpers import (
    ApiErrorId,
    assert_appointment,
    book_appointment,
    new_applicant,
    new_catalog_item,
    new_consulate,
    new_order,
    new_slot,
    read_applicant,
    read_appointment,
    read_slot,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import AGENCY, CASE_MANAGER, ADMIN


def _consulate_order(slot_specs, applicant_names, delivery_region_code="CA",
                     residence_region_code="CA"):
    """A mission covering CA and NV, one order that names it, and its travellers."""
    set_clock("2026-06-01T09:00:00Z")
    catalog = new_catalog_item(visa_type="TOURIST", requires_appointment=True)
    consulate = new_consulate()
    slots = [new_slot(consulate["id"], **spec) for spec in slot_specs]
    order = new_order(
        catalog["id"],
        consulate_id=consulate["id"],
        delivery_region_code=delivery_region_code,
    )
    applicants = [
        new_applicant(
            order["id"],
            full_name=name,
            date_of_birth=f"199{i}-03-04",
            residence_region_code=residence_region_code,
        )
        for i, name in enumerate(applicant_names)
    ]
    return consulate, slots, order, applicants


# ==========================================================================
# Aggregate-capacity interval semantics on an interview slot
# ==========================================================================
def test_second_booking_on_a_capacity_one_slot_is_refused(api):
    """PRD §3.7: "And the slot's `booked_count` must be strictly below its `capacity`, or
    the booking is `ERR_SLOT_CAPACITY_EXCEEDED`."
    PRD §3.3: "A slot tracks `booked_count`, defined as the number of appointments on it
    whose `booking_status` is `BOOKED` or `ATTENDED` — an attended interview continues to
    occupy its seat, while a no-show or a cancellation gives the seat back."

    Design: Difficulty/resource_temporal_overlap/appointment_slot_aggregate_capacity_at_one_instant
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [{"starts_at": "2026-06-05T10:00:00Z", "capacity": 1}], ["Slot One", "Slot Two"]
    )
    slot = slots[0]
    first = book_appointment(applicants[0]["id"], slot["id"])

    resp = api.create_appointment(
        {
            "applicant_id": applicants[1]["id"],
            "slot_id": slot["id"],
            "expected_slot_version": read_slot(slot["id"])["version"],
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)

    assert read_appointment(first["id"])["booking_status"] == "BOOKED"


def test_a_full_slot_reports_full_and_holds_exactly_one_booking(api):
    """PRD §3.3: "`status` is derived from that count and the calendar: `OPEN` while
    `booked_count` is strictly less than `capacity`, `FULL` when the two are equal, and
    `CLOSED` when the slot's calendar date appears in the owning mission's `closure_dates`."
    PRD §3.7: "A successful booking creates the appointment in `booking_status` `BOOKED`
    with `reschedule_count` and `no_show_count` at 0 and `booked_at` at the logical clock,
    increments the slot's `booked_count` and re-derives the slot's `status`."

    Design: Difficulty/resource_temporal_overlap/appointment_slot_aggregate_capacity_at_one_instant
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [{"starts_at": "2026-06-05T10:00:00Z", "capacity": 1}], ["Slot One", "Slot Two"]
    )
    slot = slots[0]
    book_appointment(applicants[0]["id"], slot["id"])

    refused = api.create_appointment(
        {
            "applicant_id": applicants[1]["id"],
            "slot_id": slot["id"],
            "expected_slot_version": read_slot(slot["id"])["version"],
        },
        CASE_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)

    stored_slot = read_slot(slot["id"])
    assert stored_slot["booked_count"] == 1, (
        f"the refused booking consumes no seat, got {stored_slot['booked_count']}"
    )
    assert stored_slot["status"] == "FULL"

    rows, meta = validate_paginated(
        api.list_appointments(CASE_MANAGER, {"slot_id": slot["id"]})
    )
    assert meta["total_count"] == 1, f"exactly one booking stands on the slot, got {meta['total_count']}"
    assert len(rows) == 1


# ==========================================================================
# Outcomes, filters and the ladder rungs that guard a booking
# ==========================================================================
def test_no_show_releases_the_seat_and_flips_the_slot_back_to_open(api):
    """PRD §3.7: "An `outcome` of `NO_SHOW` moves `BOOKED → NO_SHOW`, increments
    `no_show_count`, releases the slot's seat and re-derives the slot's `status`, and
    recomputes the traveller's readiness — potentially regressing it."
    PRD §3.3: "A slot transitions `OPEN → FULL` the moment a booking or an inbound
    reschedule fills the last seat, and `FULL → OPEN` the moment a cancellation, a no-show
    or an outbound reschedule frees one."

    Design: Corner/state_machines/corner_appointment_no_show_releases_slot_capacity
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [{"starts_at": "2026-06-05T10:00:00Z", "capacity": 1}], ["No Show"]
    )
    slot = slots[0]
    appointment = book_appointment(applicants[0]["id"], slot["id"])
    set_clock("2026-06-05T11:00:00Z")

    recorded = validate_success(
        api.record_appointment_outcome(appointment["id"], {"outcome": "NO_SHOW"}, AGENCY)
    )
    assert_appointment(recorded)
    assert recorded["booking_status"] == "NO_SHOW"
    assert recorded["no_show_count"] == 1
    assert recorded["reschedule_count"] == 0, (
        "a missed interview consumes a no-show attempt, not a reschedule attempt"
    )

    stored_slot = read_slot(slot["id"])
    assert stored_slot["booked_count"] == 0
    assert stored_slot["status"] == "OPEN"
    assert read_applicant(applicants[0]["id"])["readiness_status"] == "PENDING"


def test_appointment_list_filters_by_slot_id(api):
    """PRD §2.3: "Every filter query parameter compares by exact, case-sensitive string
    equality against the value stored on the row — there is no prefix matching, no case
    folding and no partial matching."
    PRD §2.3: "Identifier filters (`catalog_item_id`, `consulate_id`, `parent_order_id`,
    `applicant_id`, `slot_id`, `form_code`, `nationality_code`, `destination_country`)
    behave identically — an unknown value yields an empty page rather than a 404."

    Design: Corner/endpoints/corner_filtered_appointment_list_by_slot_id
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [
            {"starts_at": "2026-06-05T10:00:00Z", "capacity": 2},
            {"starts_at": "2026-06-05T14:00:00Z", "capacity": 2},
        ],
        ["Filter One", "Filter Two"],
    )
    slot_a, slot_b = slots
    appointment_a = book_appointment(applicants[0]["id"], slot_a["id"])
    appointment_b = book_appointment(applicants[1]["id"], slot_b["id"])

    rows, meta = validate_paginated(
        api.list_appointments(CASE_MANAGER, {"slot_id": slot_a["id"]})
    )
    assert meta["total_count"] == 1, f"only the bookings on slot A match, got {meta['total_count']}"
    assert [r["id"] for r in rows] == [appointment_a["id"]]
    assert appointment_b["id"] not in [r["id"] for r in rows]

    stored_slot = read_slot(slot_a["id"])
    assert stored_slot["booked_count"] == 1
    assert stored_slot["status"] == "OPEN", "one of two seats taken leaves the slot OPEN"


def test_booking_outside_the_missions_jurisdiction_is_refused(api):
    """PRD §3.7: "The traveller's `residence_region_code` must appear in the target slot's
    mission's `jurisdiction_region_codes`, and that mission must be the order's
    `consulate_id`, or the booking is `ERR_OUT_OF_JURISDICTION`."

    Design: Corner/errors/corner_error_out_of_jurisdiction_booking
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [{"starts_at": "2026-06-05T10:00:00Z", "capacity": 2}],
        ["Texas Resident"],
        delivery_region_code="TX",
        residence_region_code="TX",
    )
    slot = slots[0]

    resp = api.create_appointment(
        {
            "applicant_id": applicants[0]["id"],
            "slot_id": slot["id"],
            "expected_slot_version": slot["version"],
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_OUT_OF_JURISDICTION.value)

    stored_slot = read_slot(slot["id"])
    assert stored_slot["booked_count"] == 0
    assert stored_slot["status"] == "OPEN"


def test_lead_time_boundary_admits_exactly_forty_eight_hours(api):
    """PRD §3.7: "The slot's `starts_at` must be at least **48 hours** after the logical
    clock, with exactly 48 hours passing, or the booking is `ERR_LEAD_TIME_VIOLATION`."

    Design: Corner/errors/corner_error_lead_time_violation_booking
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [
            {"starts_at": "2026-06-02T10:00:00Z", "capacity": 2},
            {"starts_at": "2026-06-03T09:00:00Z", "capacity": 2},
        ],
        ["Lead Time"],
    )
    near, edge = slots
    applicant = applicants[0]

    refused = api.create_appointment(
        {
            "applicant_id": applicant["id"],
            "slot_id": near["id"],
            "expected_slot_version": near["version"],
        },
        CASE_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_LEAD_TIME_VIOLATION.value)

    accepted = validate_success(
        api.create_appointment(
            {
                "applicant_id": applicant["id"],
                "slot_id": edge["id"],
                "expected_slot_version": edge["version"],
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    assert accepted["booking_status"] == "BOOKED", "exactly 48 hours out is admitted"
    assert read_slot(near["id"])["booked_count"] == 0
    assert read_slot(edge["id"])["booked_count"] == 1


def test_third_reschedule_from_booked_is_refused_at_the_cap(api):
    """PRD §3.7: "From `BOOKED`, the booking stays `BOOKED`, the old slot gives its seat
    back and re-derives its `status`, the new slot takes one and re-derives its `status`,
    `reschedule_count` increments and `booked_at` is restamped; a booking may be moved at
    most **twice** this way."
    PRD §3.7: "Exceeding either counter is `ERR_RESCHEDULE_CAP_EXCEEDED`. Both flavours of
    reschedule re-run the closure, jurisdiction, lead-time and capacity checks against the
    target slot."

    Design: Corner/errors/corner_error_reschedule_cap_exceeded
    """
    _consulate, slots, _order, applicants = _consulate_order(
        [
            {"starts_at": "2026-06-05T10:00:00Z", "capacity": 2},
            {"starts_at": "2026-06-08T10:00:00Z", "capacity": 2},
            {"starts_at": "2026-06-09T10:00:00Z", "capacity": 2},
            {"starts_at": "2026-06-10T10:00:00Z", "capacity": 2},
        ],
        ["Resched"],
    )
    s1, s2, s3, s4 = slots
    appointment = book_appointment(applicants[0]["id"], s1["id"])
    validate_success(api.reschedule_appointment(appointment["id"], {"slot_id": s2["id"]}, CASE_MANAGER))
    validate_success(api.reschedule_appointment(appointment["id"], {"slot_id": s3["id"]}, CASE_MANAGER))

    resp = api.reschedule_appointment(appointment["id"], {"slot_id": s4["id"]}, CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_RESCHEDULE_CAP_EXCEEDED.value)

    stored = read_appointment(appointment["id"])
    assert stored["reschedule_count"] == 2
    assert stored["slot_id"] == s3["id"], "the refused move leaves the booking where it was"
    assert read_slot(s4["id"])["booked_count"] == 0
    assert read_slot(s3["id"])["booked_count"] == 1
