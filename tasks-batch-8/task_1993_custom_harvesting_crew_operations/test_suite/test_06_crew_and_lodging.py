"""Crew activation visa gate, release gating on future lodging, and the
per-night aggregate bed-capacity rule."""
from test_helpers import (
    ApiErrorId,
    add_lodging_site,
    book_lodging,
    create_active_season,
    create_committed_contract,
    create_route_stop,
    onboard_active_crew,
    onboard_crew_member,
    validate_error,
    validate_success,
)


def test_visa_expired_h2a_activation_rejected(api, harvest_operator_headers):
    """PRD section 3.3: "if the worker's `visa_type` is `H2A` or `TN`, the
    `visa_expiry_date` must be strictly greater than the season's current
    logical date as read from the logical clock; an expiry date equal to or
    earlier than the logical date is rejected with `ERR_VISA_EXPIRED` (HTTP
    422)."
    PRD section 2.5: "Before anyone has advanced it, the logical clock reads
    exactly `2026-08-01T00:00:00Z`".

    Design: Corner/validations/visa_expired_h2a_activation_rejected
    """
    ctx = create_active_season()
    member = onboard_crew_member(
        ctx["season"]["id"],
        full_name="H2A worker",
        visa_type="H2A",
        visa_expiry_date="2026-08-01",
        hourly_rate_cents=1500,
    )
    resp = api.activate_crew_member(member["id"], harvest_operator_headers)
    validate_error(resp, ApiErrorId.ERR_VISA_EXPIRED)


def test_lodging_bed_capacity_exceeded(api, crew_boss_headers):
    """PRD section 3.6: "for each calendar date within the requested stay
    range, the system sums the `bed_count` of every reservation at the same
    lodging site in `BOOKED` or `CHECKED_IN` status whose own stay range
    covers that date; if the occupied total plus the new reservation's
    `bed_count` would exceed the site's `total_beds` on any night of the stay,
    the booking is rejected with `ERR_LODGING_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/lodging_bed_capacity_aggregate_per_night
    """
    ctx = create_active_season()
    site = add_lodging_site(ctx["season"]["id"], site_name="Motel-6", total_beds=2)
    crew_a = onboard_active_crew(ctx["season"]["id"], full_name="Alice")
    crew_b = onboard_active_crew(ctx["season"]["id"], full_name="Bob")
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1,
                             planned_start_date="2026-08-05", planned_end_date="2026-08-08")
    book_lodging(stop["id"], crew_a["id"], site["id"],
                 stay_start_date="2026-08-05", stay_end_date="2026-08-08", bed_count=2)

    resp = api.create_lodging_reservation(
        stop["id"],
        {"crew_member_id": crew_b["id"], "lodging_site_id": site["id"],
         "stay_start_date": "2026-08-06", "stay_end_date": "2026-08-09", "bed_count": 1},
        crew_boss_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LODGING_CAPACITY_EXCEEDED)


def test_lodging_bed_sharing_within_capacity_allowed(api, crew_boss_headers):
    """PRD section 3.6: "Beds are fungible, so capacity is checked per night
    rather than per reservation" and "overlapping stays are fine as long as
    no single night overflows the site."

    Design: Difficulty/resource_temporal_overlap/lodging_bed_capacity_aggregate_per_night
    """
    ctx = create_active_season()
    site = add_lodging_site(ctx["season"]["id"], site_name="Motel-6", total_beds=2)
    crew_a = onboard_active_crew(ctx["season"]["id"], full_name="Alice")
    crew_b = onboard_active_crew(ctx["season"]["id"], full_name="Bob")
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1,
                             planned_start_date="2026-08-05", planned_end_date="2026-08-08")
    book_lodging(stop["id"], crew_a["id"], site["id"],
                 stay_start_date="2026-08-05", stay_end_date="2026-08-08", bed_count=1)

    resp = api.create_lodging_reservation(
        stop["id"],
        {"crew_member_id": crew_b["id"], "lodging_site_id": site["id"],
         "stay_start_date": "2026-08-06", "stay_end_date": "2026-08-09", "bed_count": 1},
        crew_boss_headers,
    )
    reservation = validate_success(resp, 201)
    assert reservation["status"] == "BOOKED", (
        "two one-bed reservations fit a two-bed site on shared nights"
    )


def test_crew_release_with_active_lodging_blocked(api, harvest_operator_headers):
    """PRD section 3.3: "Releasing a crew member requires the member to be
    `ACTIVE` (otherwise `ERR_CREW_NOT_ACTIVE`, HTTP 409) and is blocked while
    the member holds any lodging reservation in `BOOKED` or `CHECKED_IN`
    status overlapping any future date (`ERR_ACTIVE_LODGING_EXISTS`, HTTP
    409)."

    Design: Corner/state_machines/crew_release_with_active_lodging_blocked
    """
    ctx = create_active_season()
    site = add_lodging_site(ctx["season"]["id"], total_beds=4)
    member = onboard_active_crew(ctx["season"]["id"], full_name="A")
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1,
                             planned_start_date="2026-08-05", planned_end_date="2026-08-08")
    book_lodging(stop["id"], member["id"], site["id"],
                 stay_start_date="2026-08-05", stay_end_date="2026-08-08", bed_count=1)

    resp = api.release_crew_member(member["id"], harvest_operator_headers)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_LODGING_EXISTS)


def test_err_reservation_not_booked_on_checkin(api, crew_boss_headers):
    """PRD section 3.6: "A booked reservation is checked in by the crew boss
    (`BOOKED → CHECKED_IN`; a reservation not in `BOOKED` yields
    `ERR_RESERVATION_NOT_BOOKED`, HTTP 409)" and "A `BOOKED` reservation may
    instead be cancelled by the crew boss (any other status yields
    `ERR_RESERVATION_NOT_CANCELLABLE`, HTTP 409), moving it to `CANCELLED`".

    Design: Corner/errors/err_reservation_not_booked_on_checkin
    """
    ctx = create_active_season()
    site = add_lodging_site(ctx["season"]["id"], total_beds=4)
    member = onboard_active_crew(ctx["season"]["id"], full_name="A")
    contract = create_committed_contract(ctx["season"]["id"])
    stop = create_route_stop(contract["id"], sequence_index=1,
                             planned_start_date="2026-08-05", planned_end_date="2026-08-08")
    reservation = book_lodging(stop["id"], member["id"], site["id"],
                               stay_start_date="2026-08-05", stay_end_date="2026-08-08",
                               bed_count=1)
    validate_success(api.cancel_reservation(reservation["id"], crew_boss_headers))

    resp = api.check_in_reservation(reservation["id"], crew_boss_headers)
    validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_BOOKED)
