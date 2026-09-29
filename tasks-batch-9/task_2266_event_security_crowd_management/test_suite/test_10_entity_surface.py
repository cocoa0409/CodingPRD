"""The read and write surface of the entities themselves.

Field echoes, declared defaults, system-managed fields that the client cannot
seed, the paginated list contract, the 404 vocabulary, the request-shape
rejections and the junction row that has to be reachable from both of its
parents. These are the claims about shape rather than about behaviour.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    AssignmentStatus,
    DensityLevel,
    DutyStatus,
    EventStatus,
    EventType,
    GatePosture,
    IngressStatus,
    PostStatus,
    PostType,
    VerificationStatus,
    OMIT,
    ZoneType,
    assert_density_reading,
    assert_guard,
    assert_post_fill,
    assert_security_event,
    assert_three_decimals,
    assert_venue,
    assert_zone,
    build_clock_world,
    build_event_world,
    build_plan_with_perimeter_post_world,
    build_venue_world,
    create_verified_guard,
    density_reading_payload,
    event_payload,
    guard_payload,
    post_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
    venue_payload,
    zone_payload,
)

UNKNOWN_ID = "11111111-1111-4111-8111-111111111111"


def test_registering_a_venue_echoes_every_declared_input_and_opens_it_active():
    """The topology root has no parent, so its creation is a pure field echo.

    Nothing is resolved, defaulted or computed on the way in: the four physical
    measurements, the licence flag and the historical incident rate all come back
    exactly as supplied, the status opens at ACTIVE and the row is at version 1.

    PRD: "A `SecurityDirector` registers a **Venue** with its trade `name` (non-empty, at most 120 characters), its licensed all-in `gross_capacity` (at least 1), the number of public ingress doors `door_count` (at least 1), the `egress_capacity_per_minute` it can discharge in a full evacuation (at least 1), and its outer `perimeter_length_m` in metres (at least 1)."
    Design: Corner/entities/venue_creation_returns_all_declared_fields
    """
    api = ApiClient()
    build_clock_world(api)

    response = api.create_venue(
        venue_payload(
            name="Harbor Arena",
            gross_capacity=8000,
            door_count=4,
            egress_capacity_per_minute=500,
            perimeter_length_m=400,
            alcohol_licensed=True,
            prior_incident_rate=1.25,
        ),
        DIRECTOR_HEADERS,
    )
    venue = validate_success(response, expected_status=201)

    assert_venue(venue)
    assert venue["name"] == "Harbor Arena"
    assert venue["gross_capacity"] == 8000
    assert venue["door_count"] == 4
    assert venue["egress_capacity_per_minute"] == 500
    assert venue["perimeter_length_m"] == 400
    assert venue["alcohol_licensed"] is True
    assert venue["prior_incident_rate"] == 1.25
    assert venue["status"] == "ACTIVE"
    assert venue["version"] == 1

    meta = response.json()["meta"]
    assert meta["api_request_id"]
    assert meta["api_request_timestamp"]


def test_each_of_the_three_occupancy_ceilings_can_be_the_binding_one():
    """Three zones, three different binding terms, three different safe occupancies.

    A 200 square metre seated zone with one exit unit is egress-bound at 100; a
    50 square metre corridor is area-bound at 76 because the fire-code allowance
    is 0.65 square metres a head; and a concourse with two exit units is bound by
    its own placard at 150.

    PRD: "`max_safe_occupancy` is the smallest of those three whole numbers."
    Design: Corner/entities/zone_creation_computes_max_safe_occupancy_from_three_way_min
    """
    api = ApiClient()
    world = build_venue_world(api, gross_capacity=8000, door_count=1)

    egress_bound = validate_success(
        api.create_zone(
            world.venue_id,
            zone_payload(
                zone_code="ZG",
                zone_type=ZoneType.SEATED,
                floor_area_sqm=200,
                posted_capacity=300,
                exit_units=1,
                post_slot_capacity=8,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    area_bound = validate_success(
        api.create_zone(
            world.venue_id,
            zone_payload(
                zone_code="ZE",
                zone_type=ZoneType.EXIT_CORRIDOR,
                floor_area_sqm=50,
                posted_capacity=80,
                exit_units=1,
                post_slot_capacity=6,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    placard_bound = validate_success(
        api.create_zone(
            world.venue_id,
            zone_payload(
                zone_code="ZI",
                zone_type=ZoneType.CONCOURSE,
                floor_area_sqm=100,
                posted_capacity=150,
                exit_units=2,
                post_slot_capacity=12,
                is_ingress_zone=True,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )

    assert egress_bound["max_safe_occupancy"] == 100
    assert area_bound["max_safe_occupancy"] == 76
    assert placard_bound["max_safe_occupancy"] == 150

    for zone in (egress_bound, area_bound, placard_bound):
        assert_zone(zone)
        assert zone["version"] == 1
    assert egress_bound["zone_code"] == "ZG"
    assert egress_bound["floor_area_sqm"] == 200
    assert egress_bound["post_slot_capacity"] == 8
    assert placard_bound["is_ingress_zone"] is True
    assert egress_bound["is_ingress_zone"] is False
    assert area_bound["is_ingress_zone"] is False


def test_reading_an_event_returns_its_stored_schedule_and_its_derived_gate():
    """A freshly registered event reads back PLANNING, NORMAL and OPEN.

    The three scheduled instants and the attendance figures come straight back,
    with no ticketed figure yet reported. The gate is derived immediately, and
    with no plan in existence the pre-plan variant of the ladder leaves it OPEN.

    PRD: "A new event's `status` is `PLANNING`, its `ingress_status` is `NORMAL`, its `open_critical_incident_count` is 0, and its `gate_posture` is derived immediately under the pre-plan variant described in §2.7."
    Design: Corner/entities/security_event_retrieval_returns_stored_and_derived_fields
    """
    api = ApiClient()
    world = build_event_world(api)

    event = validate_success(api.get_event(world.event_id, COORDINATOR_HEADERS))

    assert_security_event(event)
    assert event["event_name"] == "Autumn Gala"
    assert event["event_type"] == EventType.CONCERT
    assert event["doors_open_at"] == "2026-09-12T17:00:00Z"
    assert event["event_start_at"] == "2026-09-12T18:30:00Z"
    assert event["event_end_at"] == "2026-09-12T22:30:00Z"
    assert event["expected_attendance"] == 200
    assert event["ticketed_attendance"] is None
    assert event["status"] == EventStatus.PLANNING
    assert event["ingress_status"] == IngressStatus.NORMAL
    assert event["gate_posture"] == GatePosture.OPEN
    assert event["open_critical_incident_count"] == 0
    assert event["venue_id"] == world.venue_id
    assert event["version"] == 1


def test_the_guard_list_paginates_by_the_declared_defaults_and_filters_by_status():
    """Three guards, two pages of two, and one exact-match filter.

    The first page carries two rows with the total and a further page flagged;
    the second carries the remaining row with no further page. Filtering on the
    verification status returns only the cleared guard, and an unparameterised
    call falls back to a limit of 10 from an offset of 0.

    PRD: "`limit` caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100."
    Design: Corner/entities/guard_listing_paginates_and_filters_by_verification_status
    """
    api = ApiClient()
    build_clock_world(api)
    create_verified_guard(api, "GC-5001", full_name="Gale One")
    for license_number, level, name in (("GC-5002", 2, "Gale Two"), ("GC-5003", 3, "Gale Three")):
        validate_success(
            api.create_guard(
                guard_payload(license_number, credential_level=level, full_name=name),
                COORDINATOR_HEADERS,
            ),
            expected_status=201,
        )

    first_page, first_meta = validate_paginated(
        api.list_guards(COORDINATOR_HEADERS, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_guards(COORDINATOR_HEADERS, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["has_more"] is False

    cleared, cleared_meta = validate_paginated(
        api.list_guards(AUDITOR_HEADERS, params={"verification_status": VerificationStatus.VERIFIED})
    )
    assert cleared_meta["total_count"] == 1
    assert cleared[0]["license_number"] == "GC-5001"

    everything, all_meta = validate_paginated(api.list_guards(COORDINATOR_HEADERS))
    assert len(everything) == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert all_meta["has_more"] is False

    qualified = {row["license_number"]: row["is_supervisor_qualified"] for row in everything}
    assert qualified == {"GC-5001": False, "GC-5002": False, "GC-5003": True}


def test_reading_a_plan_that_does_not_exist_names_the_plan_in_the_404():
    """The 404 vocabulary is per entity, so an unknown plan id is not a generic miss.

    Path identifiers are resolved left to right and each one has its own error
    identifier; a bare plan read therefore reports the plan-specific not-found.

    PRD: "**Path existence** — each identifier in the path is resolved left to right, and the first one that does not resolve produces its own 404: `ERR_VENUE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_POST_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_GUARD_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND`, `ERR_LANE_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` or `ERR_READING_NOT_FOUND`."
    Design: Corner/entities/staffing_plan_get_with_unknown_uuid_returns_plan_not_found
    """
    api = ApiClient()
    build_clock_world(api)

    validate_error(
        api.get_staffing_plan(UNKNOWN_ID, COORDINATOR_HEADERS), ApiErrorId.PLAN_NOT_FOUND
    )

    plans, meta = validate_paginated(api.list_staffing_plans(COORDINATOR_HEADERS))
    assert meta["total_count"] == 0
    assert plans == []


def test_booking_a_shift_without_naming_a_guard_is_a_request_shape_error():
    """A missing required foreign key is a 400, not a 404 about the absent guard.

    The body schema check runs before any identifier is resolved, so the omission
    is reported as an invalid request and nothing is written — the post keeps its
    empty roster.

    PRD: "**Body schema** — required fields present, enum values drawn from the declared member sets, integers and numbers inside their declared ranges, `window_end` strictly after `window_start`, `event_start_at` strictly after `doors_open_at`, `event_end_at` strictly after `event_start_at`, and a guard whose `employment_type` is `SUBCONTRACTED` carrying a `subcontractor_id` while a guard whose `employment_type` is `EMPLOYEE` carries none."
    Design: Corner/entities/post_assignment_create_rejects_missing_guard_id
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)

    validate_error(
        api.create_post_assignment(
            post_assignment_payload(world.p1_id, guard_id=OMIT), COORDINATOR_HEADERS
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    rows, meta = validate_paginated(api.list_post_assignments(COORDINATOR_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []

    post = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(post, 0, PostStatus.OPEN)


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults():
    """A minimal venue and a minimal event both come back fully populated.

    Neither request mentions the licence flag, the historical rate, the ticketed
    attendance, the alcohol flag or the protectee flag, and every one of them is
    filled in from the declared default rather than left absent or null.

    PRD: "Two optional flags round out the record: `alcohol_licensed`, which defaults to false, and `prior_incident_rate`, the historical incidents per thousand attendees observed at this venue, which defaults to 0, must lie between 0 and 25 inclusive, and carries two decimal places."
    Design: Corner/entities/venue_and_event_optional_fields_apply_declared_defaults
    """
    api = ApiClient()
    build_clock_world(api)

    venue = validate_success(
        api.create_venue(
            venue_payload(
                name="Quiet Hall",
                gross_capacity=2000,
                door_count=2,
                egress_capacity_per_minute=300,
                perimeter_length_m=200,
                alcohol_licensed=OMIT,
                prior_incident_rate=OMIT,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert venue["alcohol_licensed"] is False
    assert venue["prior_incident_rate"] == 0
    assert venue["status"] == "ACTIVE"

    event = validate_success(
        api.create_event(
            event_payload(
                venue["id"],
                event_name="Chamber Recital",
                event_type=EventType.CONVENTION,
                expected_attendance=150,
                alcohol_served=OMIT,
                vip_present=OMIT,
            ),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert event["ticketed_attendance"] is None
    assert event["alcohol_served"] is False
    assert event["vip_present"] is False
    assert event["status"] == EventStatus.PLANNING
    assert event["ingress_status"] == IngressStatus.NORMAL
    assert event["open_critical_incident_count"] == 0


def test_system_managed_guard_fields_cannot_be_seeded_from_the_request_body():
    """A body that tries to arrive pre-verified is ignored on every system field.

    The clearance state, the clearance stamp, the identifier and the version are
    all server-owned, and the supervisor-qualified flag is recomputed from the
    credential level rather than taken from the request's contradictory false.

    PRD: "A new guard's `verification_status` is `UNVERIFIED`, `verified_at` is null, and `is_supervisor_qualified` is derived as true exactly when `credential_level` is 3 or higher — level 3 is the supervisor-qualified threshold."
    Design: Corner/entities/guard_create_with_system_fields_in_body_input_ignored
    """
    api = ApiClient()
    build_clock_world(api)

    guard = validate_success(
        api.create_guard(
            guard_payload(
                "GC-4001",
                full_name="Sam Sentinel",
                credential_level=3,
                verification_status=VerificationStatus.VERIFIED,
                verified_at="2026-01-01T00:00:00Z",
                is_supervisor_qualified=False,
                id=UNKNOWN_ID,
                version=99,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )

    assert_guard(guard)
    assert guard["verification_status"] == VerificationStatus.UNVERIFIED
    assert guard["verified_at"] is None
    assert guard["is_supervisor_qualified"] is True
    assert guard["id"] != UNKNOWN_ID
    assert guard["version"] == 1
    assert guard["full_name"] == "Sam Sentinel"
    assert guard["credential_level"] == 3
    assert guard["license_number"] == "GC-4001"
    assert guard["credential_expires_on"] == "2026-12-31T00:00:00Z"
    assert guard["base_hourly_rate_cents"] == 2200
    assert guard["subcontractor_id"] is None


def test_a_density_reading_is_an_append_only_observation():
    """The same observation posted twice yields two rows, not one updated row.

    A reading carries an identifier and a creation stamp and nothing else from the
    common block — no update stamp and no version, because there is no second
    state for it to be in. Posting the identical body again therefore appends.

    PRD: "The one exception is `DensityReading`: a reading is immutable once recorded, so it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it entirely."
    Design: Corner/entities/density_reading_is_immutable_with_no_version_field
    """
    api = ApiClient()
    world = build_event_world(api)

    first = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-12T16:30:00Z", 100),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert_density_reading(first)
    assert_three_decimals(first["density_persons_per_sqm"], 0.500)
    assert_three_decimals(first["occupancy_ratio"], 0.333)
    assert_three_decimals(first["rolling_mean_persons_per_sqm"], 0.500)
    assert first["instantaneous_level"] == DensityLevel.GREEN
    assert first["rolling_level"] == DensityLevel.GREEN
    assert first["effective_level"] == DensityLevel.GREEN
    assert first["reported_by_user_id"] == "director-1"

    second = validate_success(
        api.create_density_reading(
            world.event_id,
            density_reading_payload(world.zf_id, "2026-09-12T16:30:00Z", 100),
            DIRECTOR_HEADERS,
        ),
        expected_status=201,
    )
    assert second["id"] != first["id"]

    readings, meta = validate_paginated(
        api.list_density_readings(COORDINATOR_HEADERS, params={"zone_id": world.zf_id})
    )
    assert meta["total_count"] == 2
    assert len(readings) == 2


def test_creating_a_zone_under_an_unknown_venue_names_the_venue_in_the_404():
    """The parent in the path is resolved before the body is even considered.

    A perfectly valid zone body under an unknown venue is a venue-not-found, and
    the real venue that does exist is left with an empty zone collection, so no
    orphan was written on the way past.

    PRD: "When a path names more than one resource — a zone under a venue, an assessment or a lane or a reading under an event — the identifiers are resolved strictly left to right, and the first identifier that fails to resolve determines the 404 returned."
    Design: Corner/entities/zone_create_under_unknown_venue_returns_venue_not_found
    """
    api = ApiClient()
    world = build_venue_world(api)

    validate_error(
        api.create_zone(UNKNOWN_ID, zone_payload(), DIRECTOR_HEADERS), ApiErrorId.VENUE_NOT_FOUND
    )

    zones, meta = validate_paginated(api.list_venue_zones(world.venue_id, DIRECTOR_HEADERS))
    assert meta["total_count"] == 0
    assert zones == []


def test_the_event_body_schema_rejects_bad_enums_intervals_and_over_capacity_crowds():
    """Three separate shape defects, three identical 400s and no event written.

    An event type outside the declared member set, a start that is not strictly
    later than the doors opening, and an expected attendance above the venue's
    licensed capacity are all body-schema violations rather than business
    conflicts.

    PRD: "A `SecurityDirector` creates a **SecurityEvent** against a venue, supplying `venue_id`, an `event_name`, an `event_type` drawn from `CONCERT`, `SPORTING`, `FESTIVAL`, `CONVENTION` and `CIVIC_PROTEST`, the three scheduled instants `doors_open_at`, `event_start_at` and `event_end_at` (each strictly later than the previous one), and an `expected_attendance` of at least 1 that may not exceed the venue's `gross_capacity`."
    Design: Corner/entities/security_event_create_rejects_invalid_enum_and_inverted_interval
    """
    api = ApiClient()
    world = build_venue_world(api)

    validate_error(
        api.create_event(
            event_payload(world.venue_id, event_type="PARADE"), DIRECTOR_HEADERS
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_event(
            event_payload(world.venue_id, doors_open_at="2026-09-12T19:00:00Z"), DIRECTOR_HEADERS
        ),
        ApiErrorId.INVALID_REQUEST,
    )
    validate_error(
        api.create_event(
            event_payload(world.venue_id, expected_attendance=8001), DIRECTOR_HEADERS
        ),
        ApiErrorId.INVALID_REQUEST,
    )

    events, meta = validate_paginated(
        api.list_events(DIRECTOR_HEADERS, params={"venue_id": world.venue_id})
    )
    assert meta["total_count"] == 0
    assert events == []


def test_a_booked_shift_is_reachable_from_its_post_and_from_its_guard():
    """The junction row carries both foreign keys and both filtered listings find it.

    A pencilled-in row opens TENTATIVE on the roster dimension and PENDING_BRIEF
    on the duty dimension. It can be read directly, found by its post, found by
    its guard, and its post can be found from the plan — so the whole
    event-plan-post-guard chain is navigable in both directions.

    PRD: "A new row starts `TENTATIVE` on the roster dimension and `PENDING_BRIEF` on the duty dimension, with `billed_hours`, `billed_cost_cents`, `radio_channel`, `training_module_code`, `briefed_at`, `check_in_at`, `relieved_at` and `cancellation_reason` all null."
    Design: Corner/entities/post_assignment_junction_links_post_and_guard_and_is_reverse_reachable
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    guard_id = create_verified_guard(api, "GC-7001", full_name="Gale One")

    created = validate_success(
        api.create_post_assignment(
            post_assignment_payload(world.p1_id, guard_id), COORDINATOR_HEADERS
        ),
        expected_status=201,
    )
    assert created["post_id"] == world.p1_id
    assert created["guard_id"] == guard_id
    assert created["assignment_status"] == AssignmentStatus.TENTATIVE
    assert created["duty_status"] == DutyStatus.PENDING_BRIEF

    direct = validate_success(api.get_post_assignment(created["id"], COORDINATOR_HEADERS))
    assert direct["id"] == created["id"]

    by_post, post_meta = validate_paginated(
        api.list_post_assignments(COORDINATOR_HEADERS, params={"post_id": world.p1_id})
    )
    assert post_meta["total_count"] == 1
    assert by_post[0]["id"] == created["id"]

    by_guard, guard_meta = validate_paginated(
        api.list_post_assignments(COORDINATOR_HEADERS, params={"guard_id": guard_id})
    )
    assert guard_meta["total_count"] == 1
    assert by_guard[0]["id"] == created["id"]

    posts, plan_meta = validate_paginated(
        api.list_posts(COORDINATOR_HEADERS, params={"staffing_plan_id": world.plan_id})
    )
    assert plan_meta["total_count"] == 1
    assert posts[0]["id"] == world.p1_id
    assert posts[0]["post_type"] == PostType.PERIMETER
