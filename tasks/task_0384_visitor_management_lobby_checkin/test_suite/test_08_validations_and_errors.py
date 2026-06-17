"""Sign-in business preconditions, segregation of duties, and reservation
conflicts.

Corner queue (B): sections validations and errors.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_site_floor_host,
    create_site, create_floor, create_host,
    create_visit, screen_visit, create_cleared_visit, create_flagged_visit,
    create_contractor_pass, create_agreement, create_meeting_room,
    get_floor_version, sign_in_visit, set_clock,
    setup_floor_at_capacity_with_pending_second_visit,
    make_security_officer_headers,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


def test_signin_with_pending_agreement_rejected(api):
    """PRD 3.6: "every agreement attached to the visit must be `SIGNED` with none left
    `PENDING`, or the request is rejected with `ERR_AGREEMENT_NOT_SIGNED`".

    Sign-in on a CLEARED visit that still has a PENDING agreement ->
    ERR_AGREEMENT_NOT_SIGNED; visit stays CLEARED.

    Design: Corner/validations/signin_with_pending_agreement_returns_agreement_not_signed
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_visit(site["id"], host["id"], floor["id"],
                         visitor_full_name="Pend V", visitor_company="PendCo")
    create_agreement(visit["id"], document_kind="NDA", document_version="NDA-v3")
    screen_visit(visit["id"])  # -> CLEARED
    fv = get_floor_version(floor["id"])
    res = api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_NOT_SIGNED)
    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_signin_no_badge_available_rejected(api):
    """PRD 3.6: "the site must have at least one free badge — `badge_available` of 1 or
    more — or the request is rejected with `ERR_NO_BADGE_AVAILABLE`."
    PRD 2.9: "`badge_available` is `badge_total` minus `badge_in_use`."

    On a badge_total-1 site with one badge already in use, a second sign-in ->
    ERR_NO_BADGE_AVAILABLE; second visit stays CLEARED.

    Design: Corner/validations/signin_no_badge_available_returns_no_badge
    """
    set_clock("2026-06-16T09:00:00Z")
    site = create_site(badge_total=1)
    floor = create_floor(site["id"], capacity=5)
    host = create_host(site["id"])
    v1 = create_cleared_visit(site["id"], host["id"], floor["id"],
                              visitor_full_name="First In", visitor_company="FirstCo")
    sign_in_visit(v1["id"], floor["id"])
    v2 = create_cleared_visit(site["id"], host["id"], floor["id"],
                              visitor_full_name="Second In", visitor_company="SecondCo")
    fv = get_floor_version(floor["id"])
    res = api.sign_in_visit(v2["id"], {"expected_floor_version": fv}, LA)
    validate_error(res, ApiErrorId.ERR_NO_BADGE_AVAILABLE)
    fetched = validate_success(api.get_visit(v2["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_contractor_signin_outside_window_rejected(api):
    """PRD 3.6: "for a contractor-covered visit the `scheduled_start` must fall on or
    after `access_valid_from` and on or before `access_valid_until`, the inclusive
    recurring-access window, or the request is rejected with `ERR_PASS_WINDOW`."

    A covered visit scheduled_start 2026-07-15 outside the pass window
    [2026-06-01, 2026-06-30] -> ERR_PASS_WINDOW on sign-in; visit stays CLEARED.

    Design: Corner/validations/contractor_signin_outside_window_returns_pass_window
    """
    set_clock("2026-07-15T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    pass_ = create_contractor_pass(
        host["id"],
        access_valid_from="2026-06-01T00:00:00Z",
        access_valid_until="2026-06-30T23:59:59Z",
    )
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        contractor_pass_id=pass_["id"],
        visitor_full_name="Pat Builder", visitor_company="BuildCo",
        scheduled_start="2026-07-15T09:00:00Z", scheduled_end="2026-07-15T11:00:00Z",
    )
    fv = get_floor_version(floor["id"])
    res = api.sign_in_visit(visit["id"], {"expected_floor_version": fv}, LA)
    validate_error(res, ApiErrorId.ERR_PASS_WINDOW)
    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_host_cannot_clear_own_flagged_visit(api):
    """PRD 3.4: "the adjudicating officer's `X-User-ID` must not equal the visit's
    `host_id`, because a host may not clear a flag on their own guest; a violation is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    A SecurityOfficer whose X-User-ID equals the visit's host_id clears a FLAGGED visit
    -> ERR_SEGREGATION_OF_DUTIES; visit stays FLAGGED.

    Design: Corner/validations/segregation_host_cannot_clear_own_flagged_visit
    """
    site, floor, host = setup_site_floor_host()
    flagged = create_flagged_visit(site["id"], host["id"], floor["id"])
    res = api.clearance_visit(
        flagged["id"],
        {"decision": "CLEAR", "expected_visit_version": flagged["version"]},
        make_security_officer_headers(host["id"]),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    fetched = validate_success(api.get_visit(flagged["id"], LA))
    assert fetched["status"] == "FLAGGED", f"expected FLAGGED, got {fetched['status']}"


def test_room_overlap_returns_room_conflict(api):
    """PRD 3.3: "The booking is rejected with `ERR_ROOM_CONFLICT` (HTTP 409) if it
    overlaps any existing booking on that same room".

    A second booking 09:30-10:30 overlapping an existing 09:00-10:00 booking ->
    ERR_ROOM_CONFLICT.

    Design: Corner/errors/room_conflict_overlap_returns_room_conflict
    """
    site, floor, host = setup_site_floor_host()
    room = create_meeting_room(floor["id"], name="Room 1", seats=6)
    create_visit(site["id"], host["id"], floor["id"], room_id=room["id"],
                 visitor_full_name="Visitor A", visitor_company="ACo",
                 scheduled_start="2026-06-16T09:00:00Z",
                 scheduled_end="2026-06-16T10:00:00Z")
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "room_id": room["id"], "visitor_full_name": "Visitor B",
            "visitor_company": "BCo",
            "scheduled_start": "2026-06-16T09:30:00Z",
            "scheduled_end": "2026-06-16T10:30:00Z", "id_scanned": True,
        },
        LA,
    )
    validate_error(res, ApiErrorId.ERR_ROOM_CONFLICT)


def test_floor_at_capacity_returns_floor_at_capacity(api):
    """PRD 3.6: "The floor must then have at least one free slot — `available_slots` of
    1 or more — or the request is rejected with `ERR_FLOOR_AT_CAPACITY`".

    Sign-in on a capacity-1 floor already holding one SIGNED_IN visitor (second visit
    id_scanned true) -> ERR_FLOOR_AT_CAPACITY; second visit stays CLEARED.

    Design: Corner/errors/floor_at_capacity_returns_floor_at_capacity
    """
    site, floor, host, v1, v2, floor_v_after = (
        setup_floor_at_capacity_with_pending_second_visit(second_id_scanned=True)
    )
    res = api.sign_in_visit(v2["id"], {"expected_floor_version": floor_v_after}, LA)
    validate_error(res, ApiErrorId.ERR_FLOOR_AT_CAPACITY)
    fetched = validate_success(api.get_visit(v2["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"
