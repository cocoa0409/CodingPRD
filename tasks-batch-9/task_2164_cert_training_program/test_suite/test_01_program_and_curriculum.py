"""Program, curriculum, facilities and the platform-wide request contract."""

import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    TEST_USERS,
    api_client,
    assert_common_fields,
    assert_cohort,
    assert_curriculum_module,
    assert_instant,
    assert_iso8601_with_millis,
    assert_program,
    create_cohort,
    create_program,
    create_program_payload,
    create_cohort_payload,
    create_curriculum_module_payload,
    create_facility_payload,
    create_activation_payload,
    create_class_session_payload,
    read_module,
    setup_program_and_curriculum,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
EMERGENCY = TEST_USERS["emergency_headers"]


def test_create_program_returns_every_declared_field(api):
    """PRD §3.1: "A `ProgramCoordinator` creates one by supplying its `name`, the
    `sponsor_agency` that backs it, a `jurisdiction_code` such as a county-and-district
    identifier, and `equipment_budget_cents` — the ceiling, in whole cents, on the total
    replacement value of equipment that may be on issue at any one moment."
    PRD §3.1: "Three derived tallies open at 0 on a new program and are maintained
    thereafter by the server: `equipment_committed_cents`, the summed replacement value
    of every asset currently out on an active issuance; `active_member_count`, the number
    of trainees in the program whose enrollment standing is either enrolled or graduated;
    and `pending_graduation_count`, the number of the program's cohorts currently sitting
    in graduation review."

    Design: Corner/entities/create_program_returns_all_declared_fields
    """
    response = api.create_program(create_program_payload(), COORD)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["response_type"] == "object"
    program = validate_success(response, 201)

    assert_program(program)
    assert program["name"] == "Riverside CERT"
    assert program["sponsor_agency"] == "Riverside OES"
    assert program["jurisdiction_code"] == "CA-RIV-01"
    assert program["equipment_budget_cents"] == 5_000_000
    assert program["equipment_committed_cents"] == 0
    assert program["active_member_count"] == 0
    assert program["pending_graduation_count"] == 0
    assert program["version"] == 1


def test_program_identity_and_version_are_server_minted(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a UUID
    string with no type prefix of any kind."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created and
    increases by exactly 1 on each mutation of that row, including mutations caused
    indirectly by a cascade originating on another resource."

    Design: Corner/entities/program_system_fields_are_server_minted
    """
    program = validate_success(api.create_program(create_program_payload(), COORD), 201)
    assert_common_fields(program, "Program")
    assert not program["id"].lower().startswith("prog"), (
        f"id must carry no type prefix, got {program['id']}"
    )
    assert_iso8601_with_millis(program["created_at"], "Program.created_at")
    assert_iso8601_with_millis(program["updated_at"], "Program.updated_at")
    assert program["version"] == 1
    created_at = program["created_at"]

    patched = validate_success(
        api.patch_program(program["id"], {"equipment_budget_cents": 6_000_000}, COORD)
    )
    assert patched["version"] == 2, "a PATCH must advance version by exactly 1"
    assert patched["equipment_budget_cents"] == 6_000_000
    assert patched["created_at"] == created_at, "created_at is written once"
    assert_iso8601_with_millis(patched["updated_at"], "Program.updated_at")


def test_curriculum_module_optional_attributes_take_their_declared_defaults(api):
    """PRD §3.1: "`is_core` defaults to true and marks the module as counting toward the
    graduation requirement."
    PRD §3.1: "`requires_skills_demo` defaults to false; when true, a trainee's completion
    of that module cannot reach a passing state on attendance alone and needs an
    evaluator's signature."
    PRD §3.1: "`refresher_eligible` defaults to false; when true, the hours a trainee
    earns from that module count toward keeping a credential current."
    PRD §3.1: "`status` defaults to `ACTIVE` and may otherwise be `RETIRED`; retired
    modules drop out of the graduation requirement, which is always computed over modules
    that are both core and active."
    PRD §3.1: "Modules form a **prerequisite graph** through `prerequisite_module_id`, a
    self-referential reference that is null for entry-level modules and otherwise names
    the module that must come first."

    Design: Corner/entities/curriculum_module_optional_flags_take_declared_defaults
    """
    module = validate_success(
        api.create_curriculum_module(
            create_curriculum_module_payload(
                module_code="CERT-900", title="Standalone Module",
                contact_hours=1.5, sequence_index=9,
            ),
            COORD,
        ),
        201,
    )
    assert_curriculum_module(module)
    assert module["is_core"] is True
    assert module["requires_skills_demo"] is False
    assert module["refresher_eligible"] is False
    assert module["status"] == "ACTIVE"
    assert module["prerequisite_module_id"] is None


def test_read_cohort_echoes_the_stored_entity(api):
    """PRD §3.2: "A coordinator opens it against a program by supplying `program_id`, a
    `cohort_code` that must be unique among that program's cohorts, a `seat_capacity` of
    at least 1, and the pair `session_window_start` and `session_window_end` that fence
    the period in which this cohort's classes may be held."
    PRD §3.2: "A new cohort opens in `RECRUITING`, with `seats_confirmed`,
    `seats_waitlisted`, and `delivered_contact_hours` at 0, `next_waitlist_position` at 1,
    and `graduation_reviewer_user_id` null."

    Design: Corner/entities/get_cohort_by_id_returns_the_stored_entity
    """
    ctx = setup_program_and_curriculum()
    cohort = validate_success(api.get_cohort(ctx["cohort"]["id"], AUDITOR))

    assert_cohort(cohort)
    assert cohort["cohort_code"] == "C-2026A"
    assert cohort["seat_capacity"] == 2
    assert_instant(cohort["session_window_start"], "2026-08-01T00:00:00Z",
                   "session_window_start")
    assert_instant(cohort["session_window_end"], "2026-12-31T23:00:00Z",
                   "session_window_end")
    assert cohort["status"] == "RECRUITING"
    assert cohort["graduation_reviewer_user_id"] is None


def test_cohort_listing_filters_by_program_and_paginates(api):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may be no
    smaller than 1, and may be no larger than 100."
    PRD §2.3: "For list responses the `meta` object carries `limit` and `offset` as they
    were applied, `total_count` giving the number of rows matching the filter before
    pagination is applied, and `has_more`, which is true exactly when the offset plus the
    number of returned rows is less than `total_count`."
    PRD §3.2: "Cohort listings may be filtered by `program_id` and by `status`; trainee
    listings may be filtered by `program_id`, `cohort_id`, `enrollment_status`, and
    `currency_status`."

    Design: Corner/entities/list_cohorts_filtered_by_program_paginates_with_total_count
    """
    program = create_program()
    for code in ("C-2026A", "C-2026B", "C-2026C"):
        create_cohort(program["id"], cohort_code=code)

    rows, meta = validate_paginated(
        api.list_cohorts(AUDITOR, {"program_id": program["id"], "limit": 2, "offset": 1})
    )
    body = api.list_cohorts(
        AUDITOR, {"program_id": program["id"], "limit": 2, "offset": 1}
    ).json()
    assert body["response_type"] == "array"
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 2

    all_rows, all_meta = validate_paginated(
        api.list_cohorts(AUDITOR, {"program_id": program["id"]})
    )
    assert len(all_rows) == 3
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0


def test_read_trainee_with_an_unmatched_uuid_is_not_found(api):
    """PRD §2.5: "Path parameters are validated strictly left to right, and the first
    segment that does not resolve determines the error."
    PRD §2.5: "Each entity type has its own not-found code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_COHORT_NOT_FOUND`, `ERR_CURRICULUM_MODULE_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_CLASS_SESSION_NOT_FOUND`, `ERR_TRAINEE_NOT_FOUND`,
    `ERR_MODULE_COMPLETION_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_ISSUANCE_NOT_FOUND`,
    `ERR_EQUIPMENT_ASSET_NOT_FOUND`, `ERR_EXERCISE_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
    `ERR_ACTIVATION_NOT_FOUND`, and `ERR_ROSTER_ASSIGNMENT_NOT_FOUND`, each returned with
    HTTP 404."

    Design: Corner/entities/get_trainee_with_unknown_id_returns_not_found
    """
    setup_program_and_curriculum()
    response = api.get_trainee(UNKNOWN_UUID, AUDITOR)
    validate_error(response, ApiErrorId.ERR_TRAINEE_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_creating_a_cohort_without_seat_capacity_is_a_malformed_request(api):
    """PRD §2.6: "Request-body shape: every required field present, every value of the
    declared type, every enumerated value a member of its declared set, every numeric
    bound honoured — `seat_capacity` at least 1, `requested_responders` at least 1,
    `unit_value_cents` at least 1, `attendance_minutes` at least 0, `contact_hours`
    strictly greater than 0, `demo_score` between 0 and 100 inclusive — every datetime a
    well-formed ISO 8601 UTC value, `limit` between 1 and 100 inclusive, and `offset` at
    least 0 (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/create_cohort_missing_seat_capacity_returns_invalid_request
    """
    program = create_program()
    create_cohort(program["id"], cohort_code="C-2026A")

    payload = create_cohort_payload(program["id"], cohort_code="C-2026Z")
    payload.pop("seat_capacity")
    validate_error(
        api.create_cohort(payload, COORD), ApiErrorId.ERR_INVALID_REQUEST.value
    )

    _, meta = validate_paginated(api.list_cohorts(AUDITOR, {"program_id": program["id"]}))
    assert meta["total_count"] == 1, "the rejected creation must leave no row behind"


def test_activation_enum_and_numeric_bounds_are_enforced(api):
    """PRD §3.9: "When an incident opens, emergency management raises an **activation**
    against the program: `program_id`, an `incident_number` unique within that program,
    the `requesting_agency`, a `severity` of `ROUTINE`, `URGENT`, or `CRITICAL`, and
    `requested_responders`, the headcount wanted, which must be at least 1."
    PRD §2.6: "Request-body shape: every required field present, every value of the
    declared type, every enumerated value a member of its declared set, every numeric
    bound honoured — `seat_capacity` at least 1, `requested_responders` at least 1,
    `unit_value_cents` at least 1, `attendance_minutes` at least 0, `contact_hours`
    strictly greater than 0, `demo_score` between 0 and 100 inclusive — every datetime a
    well-formed ISO 8601 UTC value, `limit` between 1 and 100 inclusive, and `offset` at
    least 0 (`ERR_INVALID_REQUEST`, 400)."

    Design: Corner/entities/create_activation_with_invalid_severity_returns_invalid_request
    """
    program = create_program()

    validate_error(
        api.create_activation(
            create_activation_payload(
                program["id"], incident_number="INC-BAD-1", severity="CATASTROPHIC",
                requested_responders=2,
            ),
            EMERGENCY,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api.create_activation(
            create_activation_payload(
                program["id"], incident_number="INC-BAD-2", severity="URGENT",
                requested_responders=0,
            ),
            EMERGENCY,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(
        api.list_activations(AUDITOR, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_class_session_with_an_unresolvable_cohort_reference_is_not_found(api):
    """PRD §2.5: "The same discipline governs foreign keys supplied inside a request body.
    Every reference in a creation payload must resolve to an existing row, and the
    references are checked in the order the fields appear in that endpoint's input list,
    so the first unresolvable reference decides which not-found code is returned."

    Design: Corner/entities/create_class_session_with_unknown_cohort_returns_not_found
    """
    ctx = setup_program_and_curriculum()
    response = api.create_class_session(
        create_class_session_payload(
            UNKNOWN_UUID, ctx["m101"]["id"], ctx["facility"]["id"],
            ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_COHORT_NOT_FOUND.value)

    _, meta = validate_paginated(
        api.list_class_sessions(AUDITOR, {"cohort_id": ctx["cohort"]["id"]})
    )
    assert meta["total_count"] == 0


def test_class_session_end_time_is_derived_from_the_modules_contact_hours(api):
    """PRD §3.3: "`ends_at` is derived by the server as `starts_at` advanced by the
    module's `contact_hours` converted to minutes — a module worth 2.5 contact hours
    produces a session 150 minutes long — and a client-supplied end time is ignored."
    PRD §3.3: "New sessions open in `SCHEDULED`, with `delivered_at` null and
    `recorded_completion_count` at 0; that counter tracks how many completions have been
    recorded against the session and excludes any that have been voided."

    Design: Corner/entities/class_session_ends_at_is_computed_from_module_contact_hours
    """
    ctx = setup_program_and_curriculum()
    session_a = validate_success(
        api.create_class_session(
            create_class_session_payload(
                ctx["cohort"]["id"], ctx["m101"]["id"], ctx["facility"]["id"],
                ctx["instructor1"]["id"], "2026-08-03T09:00:00Z",
            ),
            COORD,
        ),
        201,
    )
    # CERT-103 requires CERT-102, which must already stand scheduled on this cohort
    # with an earlier end time (PRD §3.3 prerequisite rule).
    validate_success(
        api.create_class_session(
            create_class_session_payload(
                ctx["cohort"]["id"], ctx["m102"]["id"], ctx["facility"]["id"],
                ctx["instructor1"]["id"], "2026-08-04T09:00:00Z",
            ),
            COORD,
        ),
        201,
    )
    session_c = validate_success(
        api.create_class_session(
            create_class_session_payload(
                ctx["cohort"]["id"], ctx["m103"]["id"], ctx["facility"]["id"],
                ctx["instructor1"]["id"], "2026-08-05T09:00:00Z",
            ),
            COORD,
        ),
        201,
    )

    assert_instant(session_a["ends_at"], "2026-08-03T11:30:00Z", "session A ends_at")
    assert_instant(session_c["ends_at"], "2026-08-05T14:00:00Z", "session C ends_at")
    assert session_c["status"] == "SCHEDULED"
    assert session_c["delivered_at"] is None
    assert session_c["recorded_completion_count"] == 0


def test_duplicate_module_code_and_room_code_are_global_key_violations(api):
    """PRD §3.1: "Attempting to register a module whose `module_code` is already taken, a
    facility whose `room_code` is already taken, or an asset whose `asset_tag` is already
    taken is rejected with `ERR_DUPLICATE_GLOBAL_KEY`, since all three of those keys are
    unique across the whole system rather than merely within a program."

    Design: Corner/validations/duplicate_module_code_returns_global_key_error
    """
    setup_program_and_curriculum()

    validate_error(
        api.create_curriculum_module(
            create_curriculum_module_payload(
                module_code="CERT-101", title="Duplicate Prep",
                contact_hours=1.0, sequence_index=7,
            ),
            COORD,
        ),
        ApiErrorId.ERR_DUPLICATE_GLOBAL_KEY.value,
    )
    validate_error(
        api.create_facility(
            create_facility_payload(name="Another Room", room_code="EOC-A",
                                    capacity_seats=10),
            COORD,
        ),
        ApiErrorId.ERR_DUPLICATE_GLOBAL_KEY.value,
    )

    _, meta = validate_paginated(api.list_curriculum_modules(AUDITOR, {"limit": 100}))
    assert meta["total_count"] == 3, "neither rejected creation may leave a row behind"


def test_duplicate_cohort_code_is_scoped_to_the_owning_program(api):
    """PRD §3.2: "A cohort whose `cohort_code` duplicates an existing one in the same
    program, a trainee whose `email` duplicates an existing one in the same program, or an
    activation whose `incident_number` duplicates an existing one in the same program are
    all rejected with `ERR_DUPLICATE_SCOPED_KEY`."

    Design: Corner/validations/duplicate_cohort_code_in_the_same_program_returns_scoped_key_error
    """
    program_a = create_program(name="Riverside CERT", jurisdiction_code="CA-RIV-01")
    create_cohort(program_a["id"], cohort_code="C-2026A")
    program_b = create_program(name="Foothill CERT", jurisdiction_code="CA-FOO-02")

    validate_error(
        api.create_cohort(create_cohort_payload(program_a["id"], cohort_code="C-2026A",
                                                seat_capacity=4), COORD),
        ApiErrorId.ERR_DUPLICATE_SCOPED_KEY.value,
    )
    reused = validate_success(
        api.create_cohort(create_cohort_payload(program_b["id"], cohort_code="C-2026A",
                                                seat_capacity=4), COORD),
        201,
    )
    assert reused["cohort_code"] == "C-2026A"

    _, meta = validate_paginated(api.list_cohorts(AUDITOR, {"program_id": program_a["id"]}))
    assert meta["total_count"] == 1


def test_repointing_a_prerequisite_into_a_cycle_is_rejected(api):
    """PRD §3.1: "Whenever a prerequisite edge is supplied — at creation or on a later
    change — the graph is checked for cycles, and a value that would make a module
    reachable from itself, including a module naming itself directly, is rejected with
    `ERR_CURRICULUM_CYCLE`. Both the creation path and the amendment path perform this
    check; neither is exempt."
    PRD §3.1: "A coordinator may re-point that edge, rename a module through `title`, or
    retire it through `status` at any time; each such change increments the module's
    `version`."

    Design: Corner/validations/repointing_a_prerequisite_into_a_cycle_returns_curriculum_cycle
    """
    ctx = setup_program_and_curriculum()

    validate_error(
        api.patch_curriculum_module(
            ctx["m101"]["id"], {"prerequisite_module_id": ctx["m102"]["id"]}, COORD
        ),
        ApiErrorId.ERR_CURRICULUM_CYCLE.value,
    )
    validate_error(
        api.patch_curriculum_module(
            ctx["m101"]["id"], {"prerequisite_module_id": ctx["m101"]["id"]}, COORD
        ),
        ApiErrorId.ERR_CURRICULUM_CYCLE.value,
    )
    assert read_module(ctx, "m101")["prerequisite_module_id"] is None

    retired = validate_success(
        api.patch_curriculum_module(ctx["m101"]["id"], {"status": "RETIRED"}, COORD)
    )
    assert retired["status"] == "RETIRED"


@pytest.mark.parametrize(
    "path,expected_error",
    [
        ("/programs", ApiErrorId.ERR_PROGRAM_NOT_FOUND.value),
        ("/cohorts", ApiErrorId.ERR_COHORT_NOT_FOUND.value),
        ("/curriculum-modules", ApiErrorId.ERR_CURRICULUM_MODULE_NOT_FOUND.value),
        ("/class-sessions", ApiErrorId.ERR_CLASS_SESSION_NOT_FOUND.value),
        ("/module-completions", ApiErrorId.ERR_MODULE_COMPLETION_NOT_FOUND.value),
        ("/credentials", ApiErrorId.ERR_CREDENTIAL_NOT_FOUND.value),
        ("/equipment-assets", ApiErrorId.ERR_EQUIPMENT_ASSET_NOT_FOUND.value),
        ("/equipment-issuances", ApiErrorId.ERR_ISSUANCE_NOT_FOUND.value),
        ("/exercises", ApiErrorId.ERR_EXERCISE_NOT_FOUND.value),
        ("/exercise-participations", ApiErrorId.ERR_PARTICIPATION_NOT_FOUND.value),
        ("/activations", ApiErrorId.ERR_ACTIVATION_NOT_FOUND.value),
        ("/roster-assignments", ApiErrorId.ERR_ROSTER_ASSIGNMENT_NOT_FOUND.value),
    ],
)
def test_each_single_resource_read_has_its_own_not_found_code(api, path, expected_error):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_COHORT_NOT_FOUND`, `ERR_CURRICULUM_MODULE_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_CLASS_SESSION_NOT_FOUND`, `ERR_TRAINEE_NOT_FOUND`,
    `ERR_MODULE_COMPLETION_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_ISSUANCE_NOT_FOUND`,
    `ERR_EQUIPMENT_ASSET_NOT_FOUND`, `ERR_EXERCISE_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
    `ERR_ACTIVATION_NOT_FOUND`, and `ERR_ROSTER_ASSIGNMENT_NOT_FOUND`, each returned with
    HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found_errors
    """
    setup_program_and_curriculum()
    response = api.raw_get(f"{path}/{UNKNOWN_UUID}", AUDITOR)
    assert response.status_code == 404, response.text
    assert response.json()["response_type"] == "error"
    validate_error(response, expected_error)


def test_instructor_patch_on_an_unmatched_uuid_is_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found code: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_COHORT_NOT_FOUND`, `ERR_CURRICULUM_MODULE_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
    `ERR_INSTRUCTOR_NOT_FOUND`, `ERR_CLASS_SESSION_NOT_FOUND`, `ERR_TRAINEE_NOT_FOUND`,
    `ERR_MODULE_COMPLETION_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_ISSUANCE_NOT_FOUND`,
    `ERR_EQUIPMENT_ASSET_NOT_FOUND`, `ERR_EXERCISE_NOT_FOUND`, `ERR_PARTICIPATION_NOT_FOUND`,
    `ERR_ACTIVATION_NOT_FOUND`, and `ERR_ROSTER_ASSIGNMENT_NOT_FOUND`, each returned with
    HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_entity_specific_not_found_errors
    """
    setup_program_and_curriculum()
    validate_error(
        api.patch_instructor(UNKNOWN_UUID, {"status": "INACTIVE"}, COORD),
        ApiErrorId.ERR_INSTRUCTOR_NOT_FOUND.value,
    )


def test_pagination_parameters_outside_their_declared_range_are_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100 inclusive, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` and
    HTTP 400."

    Design: Corner/validations/pagination_limit_outside_the_declared_range_returns_invalid_request
    """
    ctx = setup_program_and_curriculum()
    api_client.create_trainee(
        {
            "program_id": ctx["program"]["id"], "cohort_id": ctx["cohort"]["id"],
            "full_name": "Tara Nolan", "email": "tara@riverside.example",
        },
        COORD,
    )
    program_id = ctx["program"]["id"]

    for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
        query = {"program_id": program_id}
        query.update(params)
        validate_error(
            api.list_trainees(AUDITOR, query), ApiErrorId.ERR_INVALID_REQUEST.value
        )

    rows, meta = validate_paginated(
        api.list_trainees(AUDITOR, {"program_id": program_id, "limit": 100})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1


def test_missing_or_undeclared_role_headers_are_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming the capacity in which that user is acting.
    If either header is absent, or if `X-User-Role` is not exactly one of the seven
    declared role names, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    program = create_program()
    create_cohort(program["id"], cohort_code="C-2026A")
    payload = create_cohort_payload(program["id"], cohort_code="C-2026Q", seat_capacity=4)

    validate_error(
        api.create_cohort(payload, {"Content-Type": "application/json"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )
    validate_error(
        api.create_cohort(
            payload,
            {"X-User-ID": "someone", "X-User-Role": "Bystander",
             "Content-Type": "application/json"},
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    _, meta = validate_paginated(api.list_cohorts(AUDITOR, {"program_id": program["id"]}))
    assert meta["total_count"] == 1


def test_auditor_may_read_everything_but_may_write_nothing(api):
    """PRD §2.1: "Section 4 lists, for every endpoint, the roles permitted to invoke it; a
    syntactically valid request from a role that does not appear in that list is rejected
    with `ERR_UNAUTHORIZED` and HTTP 403. Every listing and single-resource read in the
    system is open to all seven roles, which is what makes `Auditor` useful: it holds no
    write capability whatsoever and exists purely for oversight on behalf of the
    sponsoring agency."

    Design: Corner/rbac/auditor_cannot_create_a_cohort
    """
    program = create_program()

    validate_error(
        api.create_cohort(
            create_cohort_payload(program["id"], cohort_code="C-2026Z", seat_capacity=4),
            AUDITOR,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    rows, meta = validate_paginated(api.list_cohorts(AUDITOR, {"program_id": program["id"]}))
    assert meta["total_count"] == 0
    assert rows == []
