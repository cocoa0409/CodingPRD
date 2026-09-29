"""Two rules failing on one request: the earlier rung is the one reported."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import assign, certify
from test_helpers.test_users import (
    STAFF_OPS_HEADERS,
    make_club_headers,
    make_manufacturer_headers,
)
from test_helpers.types import AssignmentRole, BookingAction


# ---------------------------------------------------------------------------
# Transition legality vs day capacity on the same APPROVE
# ---------------------------------------------------------------------------
def test_illegal_source_state_is_reported_ahead_of_the_capacity_conflict(
    api, capacity_precedence_setup
):
    """PRD §2.8: "Requests are validated in a fixed global order, and the first
    failing rung determines the response. Where several rules could reject the
    same request, the earlier rung wins and the later ones are never reached — so
    a caller with a bad role never learns whether the body was also malformed,
    and a mid-flight capacity conflict never masks a missing header." The
    transition-legality rung requires that "The target resource's current state
    must be a declared source state of the requested transition — otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_at_priority_9_beats_club_day_capacity_at_priority_32
    """
    club_headers = make_club_headers(capacity_precedence_setup["club"]["id"])

    error = validate_error(
        api.demo_event_transition(
            capacity_precedence_setup["draft_event_id"],
            {"action": BookingAction.APPROVE},
            club_headers,
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    assert error["error_id"] != ApiErrorId.CLUB_DAY_CAPACITY_FULL.value

    event = validate_success(
        api.get_demo_event(capacity_precedence_setup["draft_event_id"], club_headers)
    )
    assert event["booking_status"] == "DRAFT"
    assert event["approved_at"] is None


def test_capacity_conflict_surfaces_once_the_state_gate_is_satisfied(
    api, capacity_precedence_setup
):
    """PRD §2.8: "The count of events at the same club on the same `event_date`
    whose `booking_status` is `CONFIRMED` or `COMPLETED` must be strictly below
    the club's `daily_event_capacity` — otherwise `ERR_CLUB_DAY_CAPACITY_FULL`
    (409)." The rung was already violated while the state rung masked it, so the
    identical call reports it as soon as the event reaches a legal source state.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_at_priority_9_beats_club_day_capacity_at_priority_32
    """
    club_id = capacity_precedence_setup["club"]["id"]
    club_headers = make_club_headers(club_id)
    vendor_headers = make_manufacturer_headers(
        capacity_precedence_setup["manufacturer"]["id"]
    )
    draft_event_id = capacity_precedence_setup["draft_event_id"]

    validate_error(
        api.demo_event_transition(
            draft_event_id, {"action": BookingAction.APPROVE}, club_headers
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )
    validate_success(
        api.demo_event_transition(
            draft_event_id, {"action": BookingAction.SUBMIT}, vendor_headers
        )
    )
    validate_error(
        api.demo_event_transition(
            draft_event_id, {"action": BookingAction.APPROVE}, club_headers
        ),
        ApiErrorId.CLUB_DAY_CAPACITY_FULL,
        409,
    )

    blocked = validate_success(api.get_demo_event(draft_event_id, club_headers))
    banked = validate_success(
        api.get_demo_event(
            capacity_precedence_setup["confirmed_event_id"], club_headers
        )
    )
    capacity = validate_success(
        api.get_club_capacity(club_id, club_headers, "2026-09-14")
    )

    assert blocked["booking_status"] == "SUBMITTED"
    assert blocked["allocated_sample_cases"] == 0
    assert blocked["approved_at"] is None
    assert banked["booking_status"] == "CONFIRMED"
    assert capacity["confirmed_count"] == 1
    assert capacity["remaining_slots"] == 0


# ---------------------------------------------------------------------------
# Food-handler certification vs home club on the same assignment insert
# ---------------------------------------------------------------------------
def test_missing_food_certification_is_reported_ahead_of_the_home_club_mismatch(
    api, cert_precedence_setup
):
    """PRD §2.8: "Creating an assignment on a `FOOD_SAMPLING` event requires the
    demonstrator to hold a certification whose `cert_type` is `FOOD_HANDLER`,
    whose `revoked_at` is unset, and whose `expires_on` is on or after the event's
    `event_date` — otherwise `ERR_FOOD_CERT_INVALID` (422)." That rung sits above
    the home-club rung, so the worker's wrong home club is never reported here.

    Design: Difficulty/priority_pair_validation_conflict/food_cert_at_priority_17_beats_home_club_mismatch_at_priority_21
    """
    error = validate_error(
        api.create_assignment(
            cert_precedence_setup["event_id"],
            {
                "demonstrator_id": cert_precedence_setup["demonstrator"]["id"],
                "role": AssignmentRole.LEAD,
            },
            STAFF_OPS_HEADERS,
        ),
        ApiErrorId.FOOD_CERT_INVALID,
        422,
    )

    assert error["error_id"] != ApiErrorId.DEMONSTRATOR_CLUB_MISMATCH.value


def test_home_club_mismatch_surfaces_once_the_certification_exists(
    api, cert_precedence_setup
):
    """PRD §2.8: "The demonstrator's `home_club_id` must equal the event's
    `club_id` unless the assignment request sets `travel_authorized` to true —
    otherwise `ERR_DEMONSTRATOR_CLUB_MISMATCH` (422)." Both rejections are 422s
    and neither can be told from the other by status code alone.

    Design: Difficulty/priority_pair_validation_conflict/food_cert_at_priority_17_beats_home_club_mismatch_at_priority_21
    """
    demonstrator_id = cert_precedence_setup["demonstrator"]["id"]
    event_id = cert_precedence_setup["event_id"]
    payload = {"demonstrator_id": demonstrator_id, "role": AssignmentRole.LEAD}

    validate_error(
        api.create_assignment(event_id, payload, STAFF_OPS_HEADERS),
        ApiErrorId.FOOD_CERT_INVALID,
        422,
    )
    cert = certify(
        api,
        demonstrator_id,
        certificate_number="FH-2026-1101",
        issued_on="2026-04-01",
        expires_on="2027-04-01",
    )
    assert cert["cert_type"] == "FOOD_HANDLER"
    assert cert["cert_status"] == "VALID"

    validate_error(
        api.create_assignment(event_id, payload, STAFF_OPS_HEADERS),
        ApiErrorId.DEMONSTRATOR_CLUB_MISMATCH,
        422,
    )

    rows, meta = validate_paginated(
        api.list_assignments(STAFF_OPS_HEADERS, {"demo_event_id": event_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_travel_authorisation_clears_the_home_club_gate_and_staffs_the_event(
    api, cert_precedence_setup
):
    """PRD §3.4: "the worker's `home_club_id` must equal the event's `club_id`
    unless the request sets `travel_authorized` to true; and then the schedule and
    cap tests below." The shift the assignment occupies is derived, not supplied:
    `scheduled_start_utc` is the event's `event_window_start_utc` less 45 minutes
    of setup lead.

    Design: Difficulty/priority_pair_validation_conflict/food_cert_at_priority_17_beats_home_club_mismatch_at_priority_21
    """
    demonstrator_id = cert_precedence_setup["demonstrator"]["id"]
    event_id = cert_precedence_setup["event_id"]
    certify(
        api,
        demonstrator_id,
        certificate_number="FH-2026-1101",
        issued_on="2026-04-01",
        expires_on="2027-04-01",
    )

    assignment = assign(
        api, event_id, demonstrator_id, AssignmentRole.LEAD, travel_authorized=True
    )
    event = validate_success(api.get_demo_event(event_id, STAFF_OPS_HEADERS))

    assert assignment["travel_authorized"] is True
    assert assignment["assignment_status"] == "ASSIGNED"
    assert assignment["scheduled_start_utc"].startswith("2026-09-14T11:15:00")
    assert event["staffing_status"] == "FULLY_STAFFED"
    assert event["required_support_count"] == 0

    rows, meta = validate_paginated(
        api.list_assignments(STAFF_OPS_HEADERS, {"demo_event_id": event_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == assignment["id"]
