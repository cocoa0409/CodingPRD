"""Authentication/authorization envelope checks, shift window validation,
pass refunds, pagination defaults, listing filters, and the OCC guard on
lesson scheduling (PRD §2.1, §2.3, §2.7, §3.2, §3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, TEST_USERS, ApiErrorId,
    create_facility_payload, create_season_payload, create_shift_payload,
    create_chemistry_log_payload, create_lesson_session_payload,
    make_facility, make_season, make_pass_holder, make_lifeguard,
    make_season_pass, make_lesson_level, make_admission, set_clock,
    facility_version, make_lifeguard_headers,
)

MANAGER = TEST_USERS["manager_headers"]
GATE = TEST_USERS["gate_headers"]


def test_unauthenticated_missing_role_header_returns_401(api):
    """PRD §2.1: "Every request to the API must carry two authentication
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which names the operational capacity in which they act."
    PRD §2.1: "A request missing either header, or presenting a role outside
    this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_role_header_returns_401
    """
    resp = api.create_facility(
        create_facility_payload(
            name="F", address="1 A", max_bather_capacity=50, lap_lane_count=2
        ),
        {"X-User-ID": "some-user", "Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_forbidden_role_create_facility_returns_403(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/facilities` | Create a Facility | AquaticsManager |".

    Design: Corner/validations/forbidden_role_create_facility_returns_403
    """
    resp = api.create_facility(
        create_facility_payload(
            name="F", address="1 A", max_bather_capacity=50, lap_lane_count=2
        ),
        GATE,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_lifeguard_can_log_chemistry_but_cannot_create_facility(api):
    """PRD §4: "| POST | `/facilities/{id}/chemistry-logs` | Record a
    ChemistryLog; classification computed; may trigger closure cascade |
    Lifeguard, AquaticsManager |".
    PRD §4: "| POST | `/facilities` | Create a Facility | AquaticsManager |".
    PRD §2.1: "A request whose role is well-formed but not permitted for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/lifeguard_can_log_chemistry_but_cannot_create_facility
    """
    facility = make_facility()
    lifeguard = make_lifeguard()
    set_clock("2026-06-15T10:00:00Z")
    log = validate_success(
        api.create_chemistry_log(
            facility["id"],
            create_chemistry_log_payload(
                lifeguard["id"],
                recorded_at="2026-06-15T10:00:00Z",
                free_chlorine_ppm=2.5, ph=7.5, combined_chlorine_ppm=0.2,
            ),
            make_lifeguard_headers(lifeguard["id"]),
        ),
        expected_status=201,
    )
    assert log["id"]
    resp = api.create_facility(
        create_facility_payload(
            name="F2", address="2 B", max_bather_capacity=100,
            lap_lane_count=2,
        ),
        make_lifeguard_headers(lifeguard["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_shift_window_invalid_returns_422(api):
    """PRD §3.5: "The shift window must be well-formed — `shift_start`
    strictly before `shift_end` — and both endpoints must lie within the
    allowed booking horizon of one hour in the past to 60 days in the future;
    otherwise the creation fails with `ERR_SHIFT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/shift_window_invalid_returns_422
    """
    facility = make_facility()
    lifeguard = make_lifeguard()
    set_clock("2026-06-15T00:00:00Z")
    resp = api.create_shift(
        create_shift_payload(
            facility["id"], lifeguard["id"],
            shift_start="2026-07-01T10:00:00Z",
            shift_end="2026-07-01T10:00:00Z",
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_WINDOW_INVALID)


def test_pass_refund_transition(api):
    """PRD §3.2: "A manager may refund an `ACTIVE` pass while the clock is
    still before `end_date`; the refund transition moves the pass to
    `REFUNDED`, sets `refunded_cents` to the full `purchase_price_cents`, and
    rejects any future daily admissions that reference it."
    PRD §3.2: "The system snapshots `purchase_price_cents` from the season's
    price book at the moment of purchase: `resident_pass_price_cents` if the
    holder is a `RESIDENT`, otherwise `non_resident_pass_price_cents`."

    Design: Corner/state_machines/pass_refund_transition
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=2)
    season = make_season(
        facility["id"],
        resident_pass_price_cents=15000,
        non_resident_pass_price_cents=25000,
    )
    holder = make_pass_holder(full_name="P", residency_status="RESIDENT")
    set_clock("2026-07-01T00:00:00Z")
    season_pass = make_season_pass(holder["id"], season["id"])
    assert season_pass["status"] == "ACTIVE"
    assert season_pass["purchase_price_cents"] == 15000
    refunded = validate_success(api.refund_pass(season_pass["id"], MANAGER))
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 15000, (
        f"refunded_cents must equal the full purchase price 15000, "
        f"got {refunded['refunded_cents']}"
    )


def test_list_facilities_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10 when omitted, accepts a minimum of 1, and
    accepts a maximum of 100."
    PRD §2.3: "The `offset` parameter specifies how many items to skip from
    the start of the result set and defaults to 0."
    PRD §2.3: "Paginated list responses include `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` block of the envelope."

    Design: Corner/endpoints/list_facilities_pagination_defaults
    """
    make_facility(name="F1", max_bather_capacity=50, lap_lane_count=2)
    make_facility(name="F2", max_bather_capacity=60, lap_lane_count=3)
    make_facility(name="F3", max_bather_capacity=70, lap_lane_count=4)
    data, meta = validate_paginated(api.list_facilities(MANAGER))
    assert meta["total_count"] == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert isinstance(data, list) and len(data) == 3


def test_list_seasons_filtered_by_facility(api):
    """PRD §4: "| GET | `/seasons` | List MembershipSeasons (filterable by
    facility_id) | AquaticsManager, GateAttendant, PassHolder, Lifeguard |".

    Design: Corner/endpoints/list_seasons_filtered_by_facility
    """
    f1 = make_facility(name="F1", max_bather_capacity=50, lap_lane_count=2)
    f2 = make_facility(name="F2", max_bather_capacity=50, lap_lane_count=2)
    s1 = make_season(f1["id"], publish=False, season_name="S1")
    s2 = make_season(f2["id"], publish=False, season_name="S2")
    data, meta = validate_paginated(
        api.list_seasons(MANAGER, params={"facility_id": f1["id"]})
    )
    assert len(data) >= 1
    assert all(s["facility_id"] == f1["id"] for s in data), (
        "Filtering by facility_id must return only that facility's seasons"
    )
    returned_ids = {s["id"] for s in data}
    assert s1["id"] in returned_ids
    assert s2["id"] not in returned_ids


def test_occ_lesson_schedule_stale_version(api):
    """PRD §2.7: "Scheduling a lesson session requires the same field,
    `expected_facility_version`, carrying the client's last observed
    `version` of the parent `Facility`. A lane-allocation release or a
    bather-count change may have invalidated the lane availability the
    scheduler relied on, so a stale view is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_lesson_schedule_stale_version
    """
    facility = make_facility(max_bather_capacity=100, lap_lane_count=4)
    season = make_season(facility["id"])
    level = make_lesson_level(level_code="L1", display_name="L1")
    session = get_success_data(
        api.create_lesson_session(
            create_lesson_session_payload(
                facility["id"], level["id"], season["id"]
            ),
            MANAGER,
        )
    )
    stale_fv = facility_version(facility["id"])
    # A gate entry is an explicit facility mutation (PRD §2.4) that advances
    # the version observed by the scheduler.
    holder = make_pass_holder()
    set_clock("2026-06-15T10:00:00Z")
    admission = make_admission(
        facility["id"], holder["id"], "2026-06-15T00:00:00Z"
    )
    get_success_data(api.enter_admission(admission["id"], GATE))
    resp = api.schedule_lesson_session(
        session["id"], {"expected_facility_version": stale_fv}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    session_after = validate_success(api.get_lesson_session(session["id"], MANAGER))
    assert session_after["status"] == "DRAFT"
