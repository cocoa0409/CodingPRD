"""Clinic tickets, the POS total rounding order, sign-off cascades, station
reservations, and the slot/booking conflict rules.

Covers the round-per-line-then-sum POS total, the depth-2 sign-off cascade
(credit hours + release station), the clinic-phase gate, the half-open
station-assignment overlap rule, the 15-minute clinic buffer, the station-type
mismatch, the already-released invalid state, and the filtered list.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    setup_clinic_phase_enrollment, open_clinic_ticket, open_station_assignment,
    create_clinic_ticket_payload, create_station_assignment_payload,
    create_station,
    make_registrar_headers, make_instructor_headers,
)

REGISTRAR = make_registrar_headers()


# ==========================================================================
# combinatorial_formula / clinic_pos_round_per_line_then_sum  (queue A)
# ==========================================================================
def test_clinic_pos_total_rounds_per_line_then_sums(api):
    """PRD §3.5: "for each line item, multiply its `salon_price_cents` by one
    minus the `clinic_discount_pct`, round that single line to whole cents using
    round-half-up, and only then sum the rounded line amounts."

    [4501, 3301] at 0.50: round(2250.5)=2251 + round(1650.5)=1651 = 3902 (not the
    3901 that sum-then-round would give).

    Design: Difficulty/combinatorial_formula/clinic_pos_round_per_line_then_sum
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:30:00Z",
        line_items=[
            {"service_code": "CUT", "salon_price_cents": 4501},
            {"service_code": "STYLE", "salon_price_cents": 3301},
        ],
        clinic_discount_pct=0.50,
    )
    get_success_data(api.sign_off_clinic_ticket(ticket["id"], ins_headers))
    paid = validate_success(api.pay_clinic_ticket(ticket["id"], REGISTRAR))
    assert paid["ticket_total_cents"] == 3902, (
        f"POS total should be 3902 (round-per-line), got {paid['ticket_total_cents']}"
    )


def test_clinic_pos_pay_moves_ticket_to_paid(api):
    """PRD §3.3: "A `Registrar` takes the client's payment on a `SIGNED_OFF`
    ticket, moving it to `PAID` and computing the ticket's `ticket_total_cents` at
    that moment."

    Design: Difficulty/combinatorial_formula/clinic_pos_round_per_line_then_sum
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:30:00Z",
        line_items=[
            {"service_code": "CUT", "salon_price_cents": 4501},
            {"service_code": "STYLE", "salon_price_cents": 3301},
        ],
        clinic_discount_pct=0.50,
    )
    get_success_data(api.sign_off_clinic_ticket(ticket["id"], ins_headers))
    paid = validate_success(api.pay_clinic_ticket(ticket["id"], REGISTRAR))
    assert paid["status"] == "PAID"


# ==========================================================================
# transitive_cascade / clinic_signoff_depth2_station_release  (queue A)
# ==========================================================================
def test_clinic_signoff_credits_hours_and_releases_station(api):
    """PRD §3.3: "On sign-off the ticket's `clinic_hours` is credited into the
    enrollment's `actual_hours`, the enrollment's `pace_pct` is recomputed, the
    enrollment's `version` is bumped, and the occupied station is released from
    `OCCUPIED` back to `AVAILABLE`."

    A 1.50h slot credited onto actual_hours 320 yields 321.50 and frees the station.

    Design: Difficulty/transitive_cascade/clinic_signoff_depth2_station_release
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
        station_label="Styling-7",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:30:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    signed = validate_success(api.sign_off_clinic_ticket(ticket["id"], ins_headers))
    assert signed["status"] == "SIGNED_OFF"
    assert signed["clinic_hours"] == 1.50, f"clinic_hours should be 1.50, got {signed['clinic_hours']}"
    sta = validate_success(api.get_station(station["id"], REGISTRAR))
    assert sta["status"] == "AVAILABLE", "station must be released on sign-off"


def test_clinic_signoff_accrues_clinic_hours_into_enrollment(api):
    """PRD §3.3: "On sign-off the ticket's `clinic_hours` is credited into the
    enrollment's `actual_hours`."

    actual_hours 320.00 + 1.50 clinic = 321.50.

    Design: Difficulty/transitive_cascade/clinic_signoff_depth2_station_release
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
        station_label="Styling-7b",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:30:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    get_success_data(api.sign_off_clinic_ticket(ticket["id"], ins_headers))
    enr = validate_success(api.get_enrollment(enrollment["id"], REGISTRAR))
    assert enr["actual_hours"] == 321.50, (
        f"actual_hours should be 321.50, got {enr['actual_hours']}"
    )


# ==========================================================================
# cross_entity_state_dependency / clinic_signoff_requires_enrollment_phase (queue A)
# ==========================================================================
def test_clinic_signoff_blocked_before_clinic_phase(api):
    """PRD §3.3: "sign-off is only allowed once the student has reached the clinic
    phase: the owning enrollment's `actual_hours` must be at least the program's
    `clinic_phase_start_hour`. A sign-off attempted before that threshold is
    rejected with `ERR_CLINIC_PHASE_NOT_REACHED`."

    actual_hours 100 < clinic_phase_start_hour 300.

    Design: Difficulty/cross_entity_state_dependency/clinic_signoff_requires_enrollment_phase
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=100, scheduled_hours_to_date=100, station_type="HAIR",
        station_label="Styling-10",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    validate_error(
        api.sign_off_clinic_ticket(ticket["id"], ins_headers),
        ApiErrorId.ERR_CLINIC_PHASE_NOT_REACHED.value,
    )


def test_clinic_signoff_below_phase_leaves_ticket_open(api):
    """PRD §3.3: "A sign-off attempted before that threshold is rejected with
    `ERR_CLINIC_PHASE_NOT_REACHED`."

    The rejected sign-off must leave the ticket in OPEN (no transition occurred).

    Design: Difficulty/cross_entity_state_dependency/clinic_signoff_requires_enrollment_phase
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=100, scheduled_hours_to_date=100, station_type="HAIR",
        station_label="Styling-10b",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    ticket = open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    validate_error(
        api.sign_off_clinic_ticket(ticket["id"], ins_headers),
        ApiErrorId.ERR_CLINIC_PHASE_NOT_REACHED.value,
    )
    still = validate_success(api.get_clinic_ticket(ticket["id"], REGISTRAR))
    assert still["status"] == "OPEN"


# ==========================================================================
# resource_temporal_overlap / station_assignment_overlap_half_open  (queue A)
# ==========================================================================
def test_station_assignment_overlap_rejected(api):
    """PRD §3.3: "The reserved window, treated as the half-open interval from
    `start_iso` up to but not including `end_iso`, must not overlap any existing
    `RESERVED` assignment on the same station; an overlapping reservation is
    rejected with `ERR_STATION_DOUBLE_BOOKED`."

    [10:30,11:30) overlaps a RESERVED [10:00,11:00) on the same station.

    Design: Difficulty/resource_temporal_overlap/station_assignment_overlap_half_open
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=100, scheduled_hours_to_date=100, station_type="HAIR",
        station_label="Styling-16",
    )
    open_station_assignment(
        station["id"], enrollment["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:00:00Z",
    )
    resp = api.create_station_assignment(
        create_station_assignment_payload(
            station["id"], enrollment["id"], instructor["id"],
            start_iso="2026-06-01T10:30:00Z", end_iso="2026-06-01T11:30:00Z",
        ),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STATION_DOUBLE_BOOKED.value)


def test_station_assignment_adjacent_window_allowed(api):
    """PRD §3.3: "Adjacency is permitted — a reservation whose start equals
    another's end does not overlap."

    A [11:00,12:00) reservation abutting an existing [10:00,11:00) on the same
    station is accepted (the half-open boundary is exclusive at end).

    Design: Difficulty/resource_temporal_overlap/station_assignment_overlap_half_open
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=100, scheduled_hours_to_date=100, station_type="HAIR",
        station_label="Styling-16b",
    )
    open_station_assignment(
        station["id"], enrollment["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:00:00Z",
    )
    accepted = validate_success(
        api.create_station_assignment(
            create_station_assignment_payload(
                station["id"], enrollment["id"], instructor["id"],
                start_iso="2026-06-01T11:00:00Z", end_iso="2026-06-01T12:00:00Z",
            ),
            make_instructor_headers(instructor["id"]),
        ),
        201,
    )
    assert accepted["status"] == "RESERVED"


# ==========================================================================
# resource_temporal_overlap / clinic_ticket_buffer_conflict_within_15_min (queue A)
# ==========================================================================
def test_clinic_ticket_buffer_conflict_within_15_minutes(api):
    """PRD §3.3: "the ticket's `start_iso`-to-`end_iso` slot, extended by a
    15-minute turnover buffer, must not collide with any non-`VOIDED` ticket on
    the same station; two tickets on one station that fall within 15 minutes of
    each other are rejected with `ERR_CLINIC_SLOT_CONFLICT` even when their raw
    time windows do not actually overlap."

    A slot starting 10 minutes after the first ticket ends (geometrically
    disjoint) is still rejected.

    Design: Difficulty/resource_temporal_overlap/clinic_ticket_buffer_conflict_within_15_min
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
        station_label="Styling-17",
    )
    open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        client_name="Walk In", start_iso="2026-06-01T10:00:00Z",
        end_iso="2026-06-01T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    resp = api.create_clinic_ticket(
        create_clinic_ticket_payload(
            enrollment["id"], station["id"], instructor["id"],
            client_name="Walk In 2", start_iso="2026-06-01T11:10:00Z",
            end_iso="2026-06-01T12:00:00Z",
            line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
            clinic_discount_pct=0.50,
        ),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLINIC_SLOT_CONFLICT.value)


def test_clinic_ticket_outside_buffer_allowed(api):
    """PRD §3.3: "the ticket's `start_iso`-to-`end_iso` slot, extended by a
    15-minute turnover buffer, must not collide with any non-`VOIDED` ticket on
    the same station; two tickets on one station that fall within 15 minutes of
    each other are rejected with `ERR_CLINIC_SLOT_CONFLICT` even when their raw
    time windows do not actually overlap."

    A second slot starting well beyond the 15-minute buffer (11:20 after an
    11:00 end) is accepted.

    Design: Difficulty/resource_temporal_overlap/clinic_ticket_buffer_conflict_within_15_min
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
        station_label="Styling-17b",
    )
    open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        client_name="Walk In", start_iso="2026-06-01T10:00:00Z",
        end_iso="2026-06-01T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    accepted = validate_success(
        api.create_clinic_ticket(
            create_clinic_ticket_payload(
                enrollment["id"], station["id"], instructor["id"],
                client_name="Walk In 2", start_iso="2026-06-01T11:20:00Z",
                end_iso="2026-06-01T12:00:00Z",
                line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
                clinic_discount_pct=0.50,
            ),
            make_instructor_headers(instructor["id"]),
        ),
        201,
    )
    assert accepted["status"] == "OPEN"


# ==========================================================================
# state_machines / station_release_already_released_invalid_state  (queue B)
# ==========================================================================
def test_release_already_released_assignment_invalid_state(api):
    """PRD §3.3: "An `Instructor` releases a `RESERVED` assignment, moving it to
    `RELEASED`." A release requested against an assignment not in the required
    originating state is an undefined transition.
    PRD §2.10: "the state-machine precondition that the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/station_release_already_released_invalid_state
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=100, scheduled_hours_to_date=100, station_type="HAIR",
        station_label="Styling-29",
    )
    ins_headers = make_instructor_headers(instructor["id"])
    assignment = open_station_assignment(
        station["id"], enrollment["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:00:00Z",
    )
    get_success_data(api.release_station_assignment(assignment["id"], ins_headers))
    validate_error(
        api.release_station_assignment(assignment["id"], ins_headers),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ==========================================================================
# endpoints / clinic_ticket_filtered_list_by_enrollment  (queue B)
# ==========================================================================
def test_clinic_tickets_filtered_list_by_enrollment(api):
    """PRD §4 / §2.3: "List clinic tickets; filter by enrollment, station,
    instructor" and "Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` inside the envelope's `meta` object."

    A filter by enrollment_id returns the single OPEN ticket for that enrollment.

    Design: Corner/endpoints/clinic_ticket_filtered_list_by_enrollment
    """
    program, student, instructor, station, enrollment = setup_clinic_phase_enrollment(
        actual_hours=320, scheduled_hours_to_date=320, station_type="HAIR",
        station_label="Styling-39",
    )
    open_clinic_ticket(
        enrollment["id"], station["id"], instructor,
        start_iso="2026-06-01T10:00:00Z", end_iso="2026-06-01T11:00:00Z",
        line_items=[{"service_code": "CUT", "salon_price_cents": 4000}],
        clinic_discount_pct=0.50,
    )
    resp = api.list_clinic_tickets(REGISTRAR, params={"enrollment_id": enrollment["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected exactly 1 ticket, got {meta['total_count']}"
