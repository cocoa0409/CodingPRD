"""Action endpoints, program close, list filters, OCC stale-version rejection, RBAC
forbidden-role checks, and pagination validation. Corner sections: endpoints, errors,
rbac, cross_cutting_complexity_layers (OCC).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_member_headers,
    make_instructor_headers,
    ApiErrorId,
    create_facility,
    create_lane,
    create_instructor,
    create_member,
    sign_waiver,
    top_up,
    request_booking,
    confirm_booking,
    create_confirmed_booking,
    create_program,
    enroll_member,
    setup_member_ready,
)

MANAGER = {"X-User-ID": "test-manager-1", "X-User-Role": "FacilityManager", "Content-Type": "application/json"}
FRONT_DESK = {"X-User-ID": "test-frontdesk-1", "X-User-Role": "FrontDesk", "Content-Type": "application/json"}


# ─── endpoints corner: wallet_topup_increments_balance ─────────────────────────

def test_wallet_topup_increments_balance(api):
    """PRD §3.1: "Either a FacilityManager or a FrontDesk operator may register a member
    and top up a member's wallet; a top-up adds the supplied number of tokens to the
    member's token_balance."

    Design: Corner/endpoints/wallet_topup_increments_balance
    """
    facility = create_facility()
    member = create_member(facility["id"], tier="NONE")
    res = api.wallet_top_up(member["id"], {"tokens": 25}, FRONT_DESK)
    updated = validate_success(res, 200)
    assert updated["token_balance"] == 25


# ─── endpoints corner: program_close_blocks_enrollment ─────────────────────────

def test_closed_program_rejects_enrollment(api):
    """PRD §3.8: "A FacilityManager may close a program, moving it from OPEN or FULL to
    CLOSED; existing ENROLLED enrollments stay enrolled, but new enrollment is blocked."
    PRD §3.8: "Enrollment is allowed only when ... its status is not CLOSED ... a request
    that violates any of these is rejected with ERR_PROGRAM_FULL."

    Design: Corner/endpoints/program_close_blocks_enrollment
    """
    facility = create_facility(token_price_cents=500)
    lane = create_lane(facility["id"], kind="LANE", label="Lane A", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    program = create_program(facility, lane["id"], kind="LEAGUE", capacity=5, price_cents=5000)
    validate_success(api.close_program(program["id"], MANAGER), 200)
    closed = get_success_data(api.get_program(program["id"], MANAGER))

    res = api.create_enrollment(
        program["id"],
        {"member_id": member["id"], "expected_program_version": closed["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PROGRAM_FULL.value)


# ─── endpoints corner: list_bookings_filter_by_status ──────────────────────────

def test_list_bookings_filter_by_status(api):
    """PRD §4 (endpoint): "List bookings; filter by facility_id, lane_id, member_id,
    instructor_id, machine_id, team_lane_ids, status". PRD §3.4: "it places the booking
    in REQUESTED status".

    Design: Corner/endpoints/list_bookings_filter_by_status
    """
    facility = create_facility(hourly_rate_cents=4000)
    lane = create_lane(facility["id"], kind="CAGE", buffer_minutes=0)
    member = create_member(facility["id"], tier="NONE")
    request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "HOURLY",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    data, meta = validate_paginated(
        api.list_bookings(MANAGER, params={"status": "REQUESTED"})
    )
    assert meta["total_count"] == 1
    assert data[0]["status"] == "REQUESTED"


# ─── errors corner: validation_bad_pagination_limit ────────────────────────────

def test_bad_pagination_limit_rejected(api):
    """PRD §2.3: "with a minimum of 1 and a maximum of 100". PRD §2.3: "A request whose
    pagination parameters fall outside these bounds ... is rejected with ERR_VALIDATION."

    Design: Corner/errors/validation_bad_pagination_limit
    """
    create_facility()
    res = api.list_lanes(MANAGER, params={"limit": 0})
    validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ─── rbac corner: member_cannot_create_lane ────────────────────────────────────

def test_member_cannot_create_lane(api):
    """PRD §2.1: "A FacilityManager owns facility configuration — creating facilities,
    lanes, machines, instructors, and programs". PRD §2.1: "When a request is
    authenticated but the acting role is not permitted to perform the requested operation
    under the access matrix, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/member_cannot_create_lane
    """
    facility = create_facility()
    member = create_member(facility["id"], tier="NONE")
    payload = {"facility_id": facility["id"], "label": "X", "kind": "CAGE", "buffer_minutes": 0}
    res = api.create_lane(payload, make_member_headers(member["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac corner: instructor_cannot_check_in_booking ───────────────────────────

def test_instructor_cannot_check_in_booking(api):
    """PRD §2.1: "an Instructor is a coach with read-only capability in this version of
    the system." PRD §4 (endpoint): check-in is authorized for FrontDesk. PRD §2.1: "the
    request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/instructor_cannot_check_in_booking
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    instructor = create_instructor(facility["id"], rate_cents_per_hour=6000)
    booking = create_confirmed_booking(
        facility, lane, member,
        start_utc="2026-04-01T09:00:00Z", end_utc="2026-04-01T10:00:00Z",
    )
    res = api.check_in_booking(booking["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── rbac corner: frontdesk_cannot_create_facility ─────────────────────────────

def test_frontdesk_cannot_create_facility(api):
    """PRD §4: POST /v1/facilities is authorized for FacilityManager only. PRD §2.11:
    "Authorization is second: a role not permitted for the operation yields
    ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/frontdesk_cannot_create_facility
    """
    res = api.create_facility({"name": "Fac"}, FRONT_DESK)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── cross_cutting corner: occ_stale_lane_version_on_confirm ───────────────────

def test_stale_lane_version_rejected_on_confirm(api):
    """PRD §2.8: "If another writer has advanced the lane's version since then ... the
    confirm is rejected with ERR_STALE_LANE_VERSION at HTTP 412." PRD §3.5: "the
    confirmation increments the parent Lane's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lane_version_on_confirm
    """
    facility, lane, member = setup_member_ready(tier="NONE", waiver=True, tokens=100)
    stale_version = lane["version"]  # version as first observed
    bk_first = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z",
    )
    # Confirming the first booking bumps lane.version, making stale_version stale.
    confirm_booking(bk_first["id"], member["id"], lane["id"])
    bk_second = request_booking(
        facility, lane["id"], member, "OPEN_SLOT", "TOKEN",
        "2026-04-02T11:00:00Z", "2026-04-02T12:00:00Z",
    )
    res = api.confirm_booking(
        bk_second["id"], {"expected_lane_version": stale_version},
        make_member_headers(member["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_LANE_VERSION.value)


# ─── cross_cutting corner: occ_stale_program_version_on_enroll ─────────────────

def test_stale_program_version_rejected_on_enroll(api):
    """PRD §2.8: "If another writer has advanced the program's version since then ... the
    create is rejected with ERR_STALE_PROGRAM_VERSION at HTTP 412." PRD §3.8: "increments
    the parent Program's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_program_version_on_enroll
    """
    facility = create_facility(token_price_cents=500)
    lane = create_lane(facility["id"], kind="LANE", label="Lane A", buffer_minutes=0)
    m1 = create_member(facility["id"], tier="NONE", full_name="M1")
    m2 = create_member(facility["id"], tier="NONE", full_name="M2")
    program = create_program(facility, lane["id"], kind="LEAGUE", capacity=5, price_cents=5000)
    stale_version = program["version"]
    # First enrollment bumps program.version, making stale_version stale.
    enroll_member(program["id"], m1["id"], stale_version)
    res = api.create_enrollment(
        program["id"],
        {"member_id": m2["id"], "expected_program_version": stale_version},
        make_member_headers(m2["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)
