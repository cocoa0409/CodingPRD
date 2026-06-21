"""Resource temporal-overlap conflicts under two distinct interval semantics: the
second-shooter rule (half-open window plus a 60-minute travel buffer on each side)
and the lead-photographer rule (plain half-open, no buffer, adjacency allowed).

Queue A (difficulty) instances exercised here:
  resource_temporal_overlap / second_shooter_buffer_overlap_on_assignment
  resource_temporal_overlap / lead_photographer_no_buffer_overlap_on_schedule_create
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client, TEST_USERS,
    ApiErrorId, make_client_headers,
    # fixtures
    create_signed_contract, assign_second_shooter,
    # factories
    create_booking_payload, second_shooter_assignment_payload,
    create_session_package_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def _wedding_package(name):
    return get_success_data(api_client.create_session_package(create_session_package_payload(
        name=name, session_type="WEDDING", tier="STANDARD", base_fee_cents=200000,
        included_shoot_hours=6, overage_hourly_rate_cents=15000, included_edited_images=100,
        deposit_pct=0.30, requires_model_release=True, active=True), ADMIN))


def _portrait_package(name):
    return get_success_data(api_client.create_session_package(create_session_package_payload(
        name=name, session_type="PORTRAIT", tier="BASIC", base_fee_cents=100000,
        included_shoot_hours=2, overage_hourly_rate_cents=12000, included_edited_images=30,
        deposit_pct=0.30, requires_model_release=False, active=True), ADMIN))


# ===========================================================================
# resource_temporal_overlap / second_shooter_buffer_overlap_on_assignment
# ===========================================================================
def test_second_shooter_within_travel_buffer_double_booked(api):
    """PRD §3.5: "A second-shooter assignment is rejected if the same photographer is
    already ASSIGNED to an overlapping window elsewhere, where overlap is judged not on
    the bare half-open windows alone but with a sixty-minute travel buffer extended on
    each side - so two windows whose nearest edges sit less than sixty minutes apart are
    treated as conflicting even when they do not literally overlap. That collision is
    reported as ERR_SHOOTER_DOUBLE_BOOKED."

    second-shooter ASSIGNED to X (14:00-18:00). A second window Y starts 18:30 — a 30-min
    gap, inside the 60-min buffer — so assigning the same shooter to Y is double-booked.

    Design: Difficulty/resource_temporal_overlap/second_shooter_buffer_overlap_on_assignment
    """
    client = get_success_data(api.create_client(
        {"email": "ss-buf-c@studio.test", "full_name": "C", "phone": "1500"}, ADMIN))
    lead_a = get_success_data(api.create_photographer(
        {"email": "ss-buf-leada@studio.test", "full_name": "Lead A", "skills": ["PHOTO"],
         "hourly_rate_cents": 12000}, ADMIN))
    lead_b = get_success_data(api.create_photographer(
        {"email": "ss-buf-leadb@studio.test", "full_name": "Lead B", "skills": ["PHOTO"],
         "hourly_rate_cents": 12000}, ADMIN))
    second = get_success_data(api.create_photographer(
        {"email": "ss-buf-second@studio.test", "full_name": "Second", "skills": ["PHOTO"],
         "hourly_rate_cents": 8000}, ADMIN))
    pkg = _wedding_package("Wedding Buf")
    client_h = make_client_headers(client["id"])

    # Booking X with the shooter already assigned (14:00-18:00)
    bk_x = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead_a["id"], requested_shoot_hours=6), client_h))
    create_signed_contract(bk_x["id"], client["id"], includes_model_release=True)
    sch_x = get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_x["id"], "start_utc": "2026-09-01T14:00:00Z",
         "end_utc": "2026-09-01T18:00:00Z"}, ADMIN))
    validate_success(api.confirm_booking(bk_x["id"], client_h))
    assign_second_shooter(sch_x["id"], second["id"], sch_x["version"])

    # Booking Y starting 18:30 (30-min gap, < 60-min buffer)
    bk_y = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead_b["id"], requested_shoot_hours=6), client_h))
    create_signed_contract(bk_y["id"], client["id"], includes_model_release=True)
    sch_y = get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_y["id"], "start_utc": "2026-09-01T18:30:00Z",
         "end_utc": "2026-09-01T20:00:00Z"}, ADMIN))
    validate_success(api.confirm_booking(bk_y["id"], client_h))

    validate_error(
        api.create_second_shooter_assignment(
            sch_y["id"],
            second_shooter_assignment_payload(second["id"], sch_y["version"]),
            ADMIN,
        ),
        ApiErrorId.ERR_SHOOTER_DOUBLE_BOOKED.value,
    )


def test_second_shooter_outside_travel_buffer_allowed(api):
    """PRD §3.5: "overlap is judged not on the bare half-open windows alone but with a
    sixty-minute travel buffer extended on each side - so two windows whose nearest edges
    sit less than sixty minutes apart are treated as conflicting."

    Same shooter, but window Y now starts 19:00 — a full 60-minute gap from the
    14:00-18:00 window, i.e. NOT less than sixty minutes apart — so the assignment is
    accepted.

    Design: Difficulty/resource_temporal_overlap/second_shooter_buffer_overlap_on_assignment
    """
    client = get_success_data(api.create_client(
        {"email": "ss-ok-c@studio.test", "full_name": "C", "phone": "1501"}, ADMIN))
    lead_a = get_success_data(api.create_photographer(
        {"email": "ss-ok-leada@studio.test", "full_name": "Lead A", "skills": ["PHOTO"],
         "hourly_rate_cents": 12000}, ADMIN))
    lead_b = get_success_data(api.create_photographer(
        {"email": "ss-ok-leadb@studio.test", "full_name": "Lead B", "skills": ["PHOTO"],
         "hourly_rate_cents": 12000}, ADMIN))
    second = get_success_data(api.create_photographer(
        {"email": "ss-ok-second@studio.test", "full_name": "Second", "skills": ["PHOTO"],
         "hourly_rate_cents": 8000}, ADMIN))
    pkg = _wedding_package("Wedding Ok")
    client_h = make_client_headers(client["id"])

    bk_x = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead_a["id"], requested_shoot_hours=6), client_h))
    create_signed_contract(bk_x["id"], client["id"], includes_model_release=True)
    sch_x = get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_x["id"], "start_utc": "2026-09-01T14:00:00Z",
         "end_utc": "2026-09-01T18:00:00Z"}, ADMIN))
    validate_success(api.confirm_booking(bk_x["id"], client_h))
    assign_second_shooter(sch_x["id"], second["id"], sch_x["version"])

    bk_y = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead_b["id"], requested_shoot_hours=6), client_h))
    create_signed_contract(bk_y["id"], client["id"], includes_model_release=True)
    sch_y = get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_y["id"], "start_utc": "2026-09-01T19:00:00Z",
         "end_utc": "2026-09-01T21:00:00Z"}, ADMIN))
    validate_success(api.confirm_booking(bk_y["id"], client_h))

    assignment = validate_success(
        api.create_second_shooter_assignment(
            sch_y["id"],
            second_shooter_assignment_payload(second["id"], sch_y["version"]),
            ADMIN,
        ),
        expected_status=201,
    )
    assert assignment["status"] == "ASSIGNED"


# ===========================================================================
# resource_temporal_overlap / lead_photographer_no_buffer_overlap_on_schedule_create
# ===========================================================================
def test_lead_photographer_overlapping_window_rejected(api):
    """PRD §3.4: "A new window is refused if it strictly overlaps any other non-terminal
    (SCHEDULED or RESCHEDULED) shoot schedule of the same lead photographer; back-to-back
    windows that merely touch - where one ends exactly when the next begins - are allowed,
    with no buffer between them. The conflict is reported as ERR_LEAD_PHOTOGRAPHER_BUSY."

    lead16 has a SCHEDULED 10:00-12:00 window; a new 11:00-13:00 window for the same lead
    strictly overlaps -> ERR_LEAD_PHOTOGRAPHER_BUSY.

    Design: Difficulty/resource_temporal_overlap/lead_photographer_no_buffer_overlap_on_schedule_create
    """
    client = get_success_data(api.create_client(
        {"email": "lead-busy-c@studio.test", "full_name": "C", "phone": "1600"}, ADMIN))
    lead = get_success_data(api.create_photographer(
        {"email": "lead-busy-p@studio.test", "full_name": "Lead 16", "skills": ["PHOTO"],
         "hourly_rate_cents": 9000}, ADMIN))
    pkg = _portrait_package("Portrait Busy")
    client_h = make_client_headers(client["id"])

    bk_a = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead["id"], requested_shoot_hours=2), client_h))
    get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_a["id"], "start_utc": "2026-09-05T10:00:00Z",
         "end_utc": "2026-09-05T12:00:00Z"}, ADMIN))

    bk_b = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead["id"], requested_shoot_hours=2), client_h))
    validate_error(
        api.create_shoot_schedule(
            {"booking_id": bk_b["id"], "start_utc": "2026-09-05T11:00:00Z",
             "end_utc": "2026-09-05T13:00:00Z"}, ADMIN),
        ApiErrorId.ERR_LEAD_PHOTOGRAPHER_BUSY.value,
    )


def test_lead_photographer_adjacent_window_allowed(api):
    """PRD §3.4: "back-to-back windows that merely touch - where one ends exactly when the
    next begins - are allowed, with no buffer between them."

    lead16 has a SCHEDULED 10:00-12:00 window; a new 12:00-14:00 window touches at the
    boundary (end == next start) and is allowed — proving the no-buffer / half-open
    semantics, distinct from the buffered second-shooter rule.

    Design: Difficulty/resource_temporal_overlap/lead_photographer_no_buffer_overlap_on_schedule_create
    """
    client = get_success_data(api.create_client(
        {"email": "lead-adj-c@studio.test", "full_name": "C", "phone": "1601"}, ADMIN))
    lead = get_success_data(api.create_photographer(
        {"email": "lead-adj-p@studio.test", "full_name": "Lead Adj", "skills": ["PHOTO"],
         "hourly_rate_cents": 9000}, ADMIN))
    pkg = _portrait_package("Portrait Adj")
    client_h = make_client_headers(client["id"])

    bk_a = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead["id"], requested_shoot_hours=2), client_h))
    get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_a["id"], "start_utc": "2026-09-05T10:00:00Z",
         "end_utc": "2026-09-05T12:00:00Z"}, ADMIN))

    bk_b = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead["id"], requested_shoot_hours=2), client_h))
    schedule = validate_success(
        api.create_shoot_schedule(
            {"booking_id": bk_b["id"], "start_utc": "2026-09-05T12:00:00Z",
             "end_utc": "2026-09-05T14:00:00Z"}, ADMIN),
        expected_status=201,
    )
    assert schedule["status"] == "SCHEDULED"
