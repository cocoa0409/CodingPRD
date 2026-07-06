"""Application intake: creation, computed fee/deposit/coverage/class, defaults,
draft edits, and create/edit-time validations.

Every test builds its own entities from scratch (fresh DB per test).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_applicant_headers, officer_headers,
    create_venue, create_applicant, create_closure_schedule, create_application,
    add_segment, setup_draft_with_segment,
)
import test_helpers.factories as F


# ==========================================================================
# Creation + computed fields
# ==========================================================================
def test_create_application_returns_computed_fields(api):
    """PRD §3.2: "The application is created in DRAFT, its applicant_user_id is set
    to the caller's X-User-ID". PRD §3.2: "an attendance from 1001 through 5000
    inclusive is MEDIUM". PRD §3.2 base fee "400.00 for MEDIUM"; deposit floor
    "500.00 for MEDIUM"; coverage "starts from a base of 1,000,000 and adds 100
    dollars for each attendee above 1000".

    Design: Corner/entities/create_permit_application_returns_computed_fields
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        F.create_application_payload(venue["id"], event_kind="FESTIVAL",
                                     expected_attendance=3000,
                                     occupy_start="2026-06-20T10:00:00Z",
                                     occupy_end="2026-06-20T14:00:00Z"),
        hdrs)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["permit_class"] == "MEDIUM"
    # 400 base + (3000-1000)*0.20=400 surcharge + 0 segments = 800.00
    assert data["application_fee"] == 800.00
    assert data["deposit_required"] == 500.00
    assert data["required_coverage_min"] == 1_200_000
    assert data["applicant_user_id"] == applicant["id"]


def test_application_large_class_computed_at_create(api):
    """PRD §3.2: "an attendance of 5001 or more is LARGE". PRD §3.2 base "900.00 for
    LARGE"; marginal surcharge "each head from 1001 up through 5000 adds 0.20" and
    "each head beyond 5000 adds a further 0.35". PRD §3.2 deposit floor "1500.00 for
    LARGE"; coverage "capped at 5,000,000".

    Design: Corner/entities/application_permit_class_large_computed
    """
    venue = create_venue(venue_type="STADIUM", max_capacity=20000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        F.create_application_payload(venue["id"], event_kind="RACE",
                                     expected_attendance=8000,
                                     occupy_start="2026-06-23T10:00:00Z",
                                     occupy_end="2026-06-23T14:00:00Z"),
        hdrs)
    data = validate_success(resp, expected_status=201)
    assert data["permit_class"] == "LARGE"
    # 900 base + (5000-1000)*0.20=800 + (8000-5000)*0.35=1050 = 2750.00 (0 segments).
    # (The design instance's application_fee literal of 2850.00 is arithmetically
    # inconsistent with its own annotation "900 base + 4000*0.20 + 3000*0.35" = 2750;
    # PRD §3.2 uniquely derives 2750.00, which is asserted here.)
    assert data["application_fee"] == 2750.00
    assert data["deposit_required"] == 1500.00
    assert data["required_coverage_min"] == 1_700_000


def test_deposit_per_head_exceeds_floor(api):
    """PRD §3.2: "It takes the larger of a class-based floor and a per-head figure...
    The per-head figure is the attendance multiplied by 0.10, rounded to two
    decimals. The deposit_required is the greater of those two values". PRD §3.2:
    coverage "capped at 5,000,000".

    Design: Corner/calculations/deposit_per_head_exceeds_floor
    """
    venue = create_venue(venue_type="STADIUM", max_capacity=50000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        F.create_application_payload(venue["id"], event_kind="RACE",
                                     expected_attendance=20000,
                                     occupy_start="2026-06-29T10:00:00Z",
                                     occupy_end="2026-06-29T14:00:00Z"),
        hdrs)
    data = validate_success(resp, expected_status=201)
    # per_head 0.10*20000=2000 > floor 1500 -> 2000.00 (the max branch selects per-head)
    assert data["deposit_required"] == 2000.00
    # PRD §3.2: 1,000,000 base + (20000-1000)*100 = 2,900,000, below the 5,000,000 cap.
    # (The design instance's "5000000 (capped)" literal is not PRD-derivable here:
    # 19000*100 + 1,000,000 = 2,900,000 < 5,000,000, so the cap does not bind.)
    assert data["required_coverage_min"] == 2_900_000


def test_coi_coverage_floor_at_base(api):
    """PRD §3.2: "An event of 1000 or fewer therefore requires exactly the 1,000,000
    base". PRD §3.2: "an attendance of 1000 or fewer is SMALL".

    Design: Corner/calculations/coi_coverage_floor_at_base
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        F.create_application_payload(venue["id"], event_kind="PARADE",
                                     expected_attendance=500,
                                     occupy_start="2026-06-30T10:00:00Z",
                                     occupy_end="2026-06-30T14:00:00Z"),
        hdrs)
    data = validate_success(resp, expected_status=201)
    assert data["required_coverage_min"] == 1_000_000
    assert data["permit_class"] == "SMALL"


# NOTE: Corner/calculations/fee_recomputed_on_draft_edit is SKIPPED.
# Its literal expected value (application_fee == 2850.00 for attendance 6000, 0
# segments) is not PRD-derivable: PRD §3.2 yields 900 base + (5000-1000)*0.20=800
# + (6000-5000)*0.35=350 = 2050.00. The design instance's own annotation shows
# "900 + 4000*0.20 + 1000*0.35" (=2050) yet asserts 2850.00 — an internal
# contradiction. Emitting either value would make the test fail a faithful PRD
# implementation, so under the unique-derivability rule the instance is skipped.
# (The LARGE-class computation itself is still covered at create by
# application_permit_class_large_computed with its own PRD-consistent literals.)


# ==========================================================================
# Combinatorial fee (queue A) + boundary (queue A)
# ==========================================================================
def test_fee_tiered_marginal_surcharge_plus_segment(api):
    """PRD §3.2: "There is no surcharge on the first 1000 attendees. For attendance
    above 1000, each head from 1001 up through 5000 adds 0.20". PRD §3.2: "a closure
    fee is levied at 75.00 for every route segment attached to this application".
    PRD §3.2: "The application_fee is then the base plus the rounded surcharge plus
    the closure fee".

    Design: Difficulty/combinatorial_formula/fee_tiered_marginal_surcharge_plus_segment
    """
    venue = create_venue(max_capacity=6000)
    schedule = create_closure_schedule(corridor_name="Elm St")
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="FESTIVAL",
                             expected_attendance=3000,
                             occupy_start="2026-06-03T10:00:00Z",
                             occupy_end="2026-06-03T14:00:00Z")
    hdrs = make_applicant_headers(applicant["id"])
    api.add_route_segment(app["id"],
                          F.create_route_segment_payload(schedule["id"],
                                                         segment_label="Elm 1-3",
                                                         closure_start="2026-06-03T09:00:00Z",
                                                         closure_end="2026-06-03T15:00:00Z"),
                          hdrs)
    data = validate_success(api.get_application(app["id"], hdrs))
    assert data["permit_class"] == "MEDIUM"
    # 400 base + 2000*0.20=400 surcharge + 1*75 segment = 875.00
    assert data["application_fee"] == 875.00


def test_fee_marginal_surcharge_plus_segment_via_immediate_get(api):
    """PRD §3.2: "adding a route segment while the application is DRAFT recomputes the
    fee." PRD §3.2: "a closure fee is levied at 75.00 for every route segment".

    Design: Difficulty/combinatorial_formula/fee_tiered_marginal_surcharge_plus_segment
    """
    ctx = setup_draft_with_segment(attendance=3000, max_capacity=6000)
    hdrs = make_applicant_headers(ctx["applicant"]["id"])
    data = validate_success(api.get_application(ctx["application"]["id"], hdrs))
    # MEDIUM base 400 + 2000*0.20=400 + 1*75 = 875.00
    assert data["application_fee"] == 875.00


def test_attendance_tier_boundary_1000_is_small_no_surcharge(api):
    """PRD §3.2: "an attendance of 1000 or fewer is SMALL". PRD §3.2: "an event of
    exactly 1000 pays no surcharge while an event of 1001 pays the surcharge for a
    single head." PRD §3.2 base "150.00 for SMALL".

    Design: Difficulty/boundary_precision_check/attendance_tier_boundary_1000_vs_1001
    """
    venue = create_venue(venue_type="STADIUM", max_capacity=20000)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RACE",
                             expected_attendance=1000,
                             occupy_start="2026-06-11T10:00:00Z",
                             occupy_end="2026-06-11T14:00:00Z")
    hdrs = make_applicant_headers(applicant["id"])
    data = validate_success(api.get_application(app["id"], hdrs))
    assert data["permit_class"] == "SMALL"
    assert data["application_fee"] == 150.00


def test_attendance_tier_boundary_1001_is_medium_one_head_surcharge(api):
    """PRD §3.2: "an attendance from 1001 through 5000 inclusive is MEDIUM". PRD §3.2:
    "an event of 1001 pays the surcharge for a single head." PRD §3.2 base "400.00
    for MEDIUM".

    Design: Difficulty/boundary_precision_check/attendance_tier_boundary_1000_vs_1001
    """
    venue = create_venue(venue_type="STADIUM", max_capacity=20000)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RACE",
                             expected_attendance=1001,
                             occupy_start="2026-06-12T10:00:00Z",
                             occupy_end="2026-06-12T14:00:00Z")
    hdrs = make_applicant_headers(applicant["id"])
    data = validate_success(api.get_application(app["id"], hdrs))
    assert data["permit_class"] == "MEDIUM"
    # 400 base + 1*0.20 = 400.20
    assert data["application_fee"] == 400.20


# ==========================================================================
# Immediate consistency (queue B)
# ==========================================================================
def test_fee_reflects_added_segment_in_same_get(api):
    """PRD §3.2: "Because segments enter the closure fee, adding a route segment
    while the application is DRAFT recomputes the fee." PRD §3.2: "a closure fee is
    levied at 75.00 for every route segment attached to this application".

    Design: Corner/consistency_model/immediate_visibility_of_fee_after_segment_add
    """
    venue = create_venue(venue_type="STREET_CORRIDOR", max_capacity=6000)
    schedule = create_closure_schedule(corridor_name="JJ St")
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RACE",
                             expected_attendance=3000,
                             occupy_start="2026-07-20T08:00:00Z",
                             occupy_end="2026-07-20T16:00:00Z")
    hdrs = make_applicant_headers(applicant["id"])
    # DRAFT MEDIUM, 0 segments -> fee 400.00
    api.add_route_segment(app["id"],
                          F.create_route_segment_payload(schedule["id"],
                                                         segment_label="JJ 1",
                                                         closure_start="2026-07-20T10:00:00Z",
                                                         closure_end="2026-07-20T12:00:00Z"),
                          hdrs)
    data = validate_success(api.get_application(app["id"], hdrs))
    # 400 base + (3000-1000)*0.20=400 surcharge + 1*75 segment = 875.00
    assert data["application_fee"] == 875.00


# ==========================================================================
# Defaults (queue B)
# ==========================================================================
def test_venue_default_setup_buffer_applied(api):
    """PRD §2.7: "The setup_buffer_minutes (which defaults to 60 when not supplied)".
    PRD §3.1: "the venue is born ACTIVE with version 1."

    Design: Corner/entities/venue_default_setup_buffer_applied
    """
    resp = api.create_venue(F.create_venue_payload(name="V", venue_type="PARK",
                                                   max_capacity=6000),
                            officer_headers())
    data = validate_success(resp, expected_status=201)
    assert data["setup_buffer_minutes"] == 60
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_closure_schedule_default_min_gap(api):
    """PRD §2.8: "The min_gap_minutes (defaulting to 30)". PRD §3.1: "the schedule
    opens in OPEN status."

    Design: Corner/entities/closure_schedule_default_min_gap
    """
    resp = api.create_closure_schedule(
        F.create_closure_schedule_payload(corridor_name="Q St"), officer_headers())
    data = validate_success(resp, expected_status=201)
    assert data["min_gap_minutes"] == 30
    assert data["status"] == "OPEN"


# ==========================================================================
# Not found / required / time window / parent (queue B)
# ==========================================================================
def test_get_application_not_found_returns_404(api):
    """PRD §2.5: "The parent application is resolved first; if it does not exist, the
    request fails with ERR_APPLICATION_NOT_FOUND (HTTP 404)".

    Design: Corner/entities/get_application_not_found_returns_404
    """
    resp = api.get_application(NON_EXISTENT_UUID, officer_headers())
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND, expected_status=404)


def test_create_application_missing_required_field_rejected(api):
    """PRD §3.2: "An Applicant opens a new permit application by supplying the
    sponsoring applicant_org, the venue_id of the site to occupy, the event_kind ...,
    the expected_attendance as a peak headcount, and the occupancy window".

    Design: Corner/entities/create_application_missing_required_field_rejected
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    payload = {
        "applicant_org": "Org Y", "venue_id": venue["id"], "event_kind": "FESTIVAL",
        "occupy_start": "2026-06-21T10:00:00Z", "occupy_end": "2026-06-21T14:00:00Z",
    }  # expected_attendance omitted
    resp = api.create_application(payload, hdrs)
    assert resp.status_code >= 400, "missing required field must be a 4xx error"


def test_create_application_wrong_venue_not_found(api):
    """PRD §2.5: "References to a missing venue, closure schedule, or applicant yield
    ERR_VENUE_NOT_FOUND, ERR_CLOSURE_SCHEDULE_NOT_FOUND, and ERR_APPLICANT_NOT_FOUND
    respectively. All not-found conditions return HTTP 404."

    Design: Corner/entities/create_application_wrong_venue_not_found
    """
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        F.create_application_payload(NON_EXISTENT_UUID, event_kind="PARADE",
                                     expected_attendance=500,
                                     occupy_start="2026-06-24T10:00:00Z",
                                     occupy_end="2026-06-24T14:00:00Z"),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_FOUND, expected_status=404)


def test_create_application_invalid_time_window_rejected(api):
    """PRD §3.2: "occupy_end must be strictly later than occupy_start, and a window
    that fails this is rejected with ERR_INVALID_TIME_WINDOW."

    Design: Corner/entities/create_application_invalid_time_window_rejected
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.create_application(
        F.create_application_payload(venue["id"], event_kind="PARADE",
                                     expected_attendance=500,
                                     occupy_start="2026-06-25T14:00:00Z",
                                     occupy_end="2026-06-25T10:00:00Z"),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW, expected_status=422)


# ==========================================================================
# Listing (queue B)
# ==========================================================================
def test_list_applications_pagination_envelope(api):
    """PRD §2.3: "Each list response reports the pagination fields limit, offset,
    total_count, and has_more inside meta". PRD §2.2: "The response_type is ...
    'array' for a list of resources."

    Design: Corner/entities/list_applications_pagination_envelope
    """
    venue = create_venue(max_capacity=6000)
    applicant = create_applicant()
    create_application(venue["id"], applicant["id"], event_kind="RACE",
                       expected_attendance=500,
                       occupy_start="2026-06-22T10:00:00Z",
                       occupy_end="2026-06-22T14:00:00Z")
    resp = api.list_applications(officer_headers(), params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
