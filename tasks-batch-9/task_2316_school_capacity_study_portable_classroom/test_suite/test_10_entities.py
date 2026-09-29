"""Entity surface: echoes, defaults, derived fields, listings and foreign keys."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ADMIN_HEADERS, ASSET_HEADERS, PLANNER_HEADERS
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_clock_stamp, assert_created_at
from test_helpers.factories import (
    placement_request_payload,
    projection_payload,
    room_payload,
    school_payload,
    site_payload,
    unit_payload,
)
from test_helpers.fixtures import (
    build_campus,
    create_school,
    create_site,
    create_study,
    create_unit,
    set_clock,
    study_version,
    submit_study,
)

CLOCK = "2027-03-01T00:00:00Z"


def test_campus_onboarding_echoes_every_input_and_opens_the_derived_fields(api):
    """PRD §3.1: "A `DistrictAdmin` onboards one by supplying its `name` ... its
    `grade_configuration`; its usable `site_acreage` ... `fire_lane_clear_width_ft` ...
    `electrical_spare_capacity_kw` ... `sewer_spare_connections` ...
    `consecutive_reliance_years` is the number of consecutive prior school years the
    campus has already leaned on portable classrooms ... Three campus fields are never
    supplied by a client — `hosted_portable_seats` begins at 0, `reliance_flag` begins at
    `NONE`, and `certified_study_id` begins as null." PRD §2.4: "Every persisted resource
    carries an `id`, which is a server-minted UUID with no type prefix ... a `version`, an
    integer that starts at 1 on creation".

    Design: Corner/entities/school_create_returns_all_declared_fields
    """
    set_clock(api, CLOCK)

    school = validate_success(
        api.create_school(
            school_payload(name="Northside Middle", grade_configuration="MIDDLE_68",
                           site_acreage=12.5, fire_lane_clear_width_ft=24,
                           electrical_spare_capacity_kw=60, sewer_spare_connections=2,
                           consecutive_reliance_years=3),
            ADMIN_HEADERS,
        ),
        expected_status=201,
    )

    assert school["name"] == "Northside Middle"
    assert school["grade_configuration"] == "MIDDLE_68"
    assert school["site_acreage"] == 12.5
    assert school["fire_lane_clear_width_ft"] == 24
    assert school["electrical_spare_capacity_kw"] == 60
    assert school["sewer_spare_connections"] == 2
    assert school["consecutive_reliance_years"] == 3
    assert school["hosted_portable_seats"] == 0
    assert school["reliance_flag"] == "NONE"
    assert school["certified_study_id"] is None
    assert school["version"] == 1
    assert is_valid_uuid(school["id"])
    assert_created_at(school, CLOCK)
    assert_clock_stamp(school["updated_at"], CLOCK)


def test_reading_one_room_returns_the_area_and_type_that_were_stored(api):
    """PRD §3.1: "A room is registered against a campus by `school_id`, labelled with a
    `room_number` of 1 to 20 characters that must be unique on that campus, typed by
    `room_type`, and sized by `area_sqft`, which must be greater than 0. Its `status` is
    not a client input at creation and begins at `IN_SERVICE`." PRD §2.5: "A room's campus,
    for example, is reached through the room's `school_id`".

    Design: Corner/entities/room_retrieval_returns_stored_values
    """
    set_clock(api, CLOCK)
    school = create_school(api, name="Northside Middle")
    created = validate_success(
        api.create_room(
            room_payload(school["id"], room_number="S-12", room_type="SCIENCE_LAB",
                         area_sqft=1000),
            ADMIN_HEADERS,
        ),
        expected_status=201,
    )

    room = validate_success(api.get_room(created["id"], PLANNER_HEADERS))
    assert room["id"] == created["id"]
    assert room["school_id"] == school["id"]
    assert room["room_number"] == "S-12"
    assert room["room_type"] == "SCIENCE_LAB"
    assert room["area_sqft"] == 1000
    assert room["status"] == "IN_SERVICE"


def test_inventory_listing_pages_counts_and_filters_the_whole_match_set(api):
    """PRD §2.3: "`limit` caps the number of rows returned; when it is omitted the server
    uses 10 ... `offset` is the number of rows to skip before the page begins; when it is
    omitted the server uses 0 ... The `meta` object of a list response carries `limit`,
    `offset`, `total_count` and `has_more`, where `total_count` counts every row matching
    the filters before the page window is applied." PRD §4 lists inventory "optionally
    filtered by hosting campus, replacement lineage, either state dimension or size class".

    Design: Corner/entities/portable_unit_listing_returns_pagination_envelope
    """
    set_clock(api, CLOCK)
    create_unit(api, asset_tag="PU-L001")
    create_unit(api, asset_tag="PU-L002", size_class="DOUBLE_28x64",
                condition_grade="A", acquisition_cost_cents=15_000_000,
                in_service_year=2021)
    create_unit(api, asset_tag="PU-L003", condition_grade="C", in_service_year=2009)

    first_page, meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    _, default_meta = validate_paginated(api.list_portable_units(ASSET_HEADERS))
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["total_count"] == 3
    assert default_meta["has_more"] is False

    _, filtered_meta = validate_paginated(
        api.list_portable_units(ASSET_HEADERS, {"size_class": "SINGLE_24x40"})
    )
    assert filtered_meta["total_count"] == 2


def test_reading_an_unknown_study_id_answers_with_the_study_specific_code(api):
    """PRD §2.6 rule 4: "Every identifier in the request path resolves, left to right —
    the 404 family, on every path-parameterised endpoint." PRD §2.5 names that family:
    "`ERR_STUDY_NOT_FOUND` ... each carrying 404." PRD §2.2: an error body carries
    "`error_id`" and a "`message`" that "provides a human-readable explanation of what
    went wrong."

    Design: Corner/entities/capacity_study_get_unknown_id_returns_study_not_found
    """
    set_clock(api, CLOCK)

    response = api.get_capacity_study(NON_EXISTENT_UUID, PLANNER_HEADERS)
    body = validate_error(response, ApiErrorId.STUDY_NOT_FOUND, expected_status=404)
    assert isinstance(body["message"], str) and body["message"]


def test_a_pad_without_a_pad_code_is_refused_and_the_optional_flags_default_false(api):
    """PRD §3.4: pads are "labelled with a `pad_code` of 1 to 20 characters unique on
    that campus ... an optional `sewer_connection_available` flag defaulting to false, and
    an optional `ada_path_of_travel_compliant` flag defaulting to false." PRD §2.6 rule 6:
    "Required body fields are present ... — `ERR_INVALID_REQUEST`, 422, on every
    endpoint."

    Design: Corner/entities/placement_site_create_missing_pad_code_rejected
    """
    set_clock(api, CLOCK)
    school = create_school(api, name="Northside Middle")

    incomplete = dict(site_payload(school["id"]))
    incomplete.pop("pad_code")
    incomplete.pop("sewer_connection_available")
    incomplete.pop("ada_path_of_travel_compliant")
    response = api.create_placement_site(incomplete, ADMIN_HEADERS)
    validate_error(response, ApiErrorId.INVALID_REQUEST, expected_status=422)

    _, meta = validate_paginated(
        api.list_placement_sites(ADMIN_HEADERS, {"school_id": school["id"]})
    )
    assert meta["total_count"] == 0

    control = dict(incomplete)
    control["pad_code"] = "PAD-A"
    pad = validate_success(
        api.create_placement_site(control, ADMIN_HEADERS), expected_status=201
    )
    assert pad["sewer_connection_available"] is False
    assert pad["ada_path_of_travel_compliant"] is False


def test_a_portable_created_without_its_optional_fields_takes_the_declared_defaults(api):
    """PRD §3.1: a unit carries "an optional `condition_grade` defaulting to `B`, an
    optional `ada_ramp_installed` flag defaulting to false, an optional `replaced_unit_id`
    naming the unit this one was bought to replace (null when it is not a replacement),
    and an optional `prior_relocation_count` ... defaulting to 0 ... sets `condition_status`
    to `SERVICEABLE` and `allocation_status` to `IN_STORAGE`, seeds
    `lifetime_relocation_count` from `prior_relocation_count`, leaves `current_school_id`
    null, and opens `accumulated_relocation_cost_cents` at 0." PRD §3.1 on the campus
    side: `consecutive_reliance_years` is "supplied at onboarding from the prior reporting
    system and defaulting to 0".

    Design: Corner/entities/portable_unit_create_omitting_optional_fields_applies_defaults
    """
    set_clock(api, CLOCK)

    minimal = {"asset_tag": "PU-D999", "size_class": "SINGLE_24x40",
               "acquisition_cost_cents": 9_600_000, "in_service_year": 2019}
    unit = validate_success(
        api.create_portable_unit(minimal, ASSET_HEADERS), expected_status=201
    )
    assert unit["condition_grade"] == "B"
    assert unit["ada_ramp_installed"] is False
    assert unit["replaced_unit_id"] is None
    assert unit["condition_status"] == "SERVICEABLE"
    assert unit["allocation_status"] == "IN_STORAGE"
    assert unit["current_school_id"] is None
    assert unit["lifetime_relocation_count"] == 0
    assert unit["accumulated_relocation_cost_cents"] == 0

    bare_school = dict(school_payload(name="Defaults Middle"))
    bare_school.pop("consecutive_reliance_years")
    school = validate_success(
        api.create_school(bare_school, ADMIN_HEADERS), expected_status=201
    )
    assert school["consecutive_reliance_years"] == 0


def test_rated_seats_are_derived_from_the_size_class_alone(api):
    """PRD §3.1: "On creation the server derives `rated_seats` from `size_class` — a
    `SINGLE_24x40` seats 24, a `DOUBLE_28x64` seats 48, a `TRIPLE_36x64` seats 60".

    Design: Corner/entities/portable_unit_rated_seats_derived_from_size_class
    """
    set_clock(api, CLOCK)

    single = create_unit(api, asset_tag="PU-C201")
    triple = validate_success(
        api.create_portable_unit(
            unit_payload(asset_tag="PU-C203", size_class="TRIPLE_36x64",
                         acquisition_cost_cents=22_000_000, in_service_year=2021),
            ASSET_HEADERS,
        ),
        expected_status=201,
    )
    double = validate_success(
        api.create_portable_unit(
            unit_payload(asset_tag="PU-C202", size_class="DOUBLE_28x64",
                         acquisition_cost_cents=15_000_000, in_service_year=2021),
            ASSET_HEADERS,
        ),
        expected_status=201,
    )

    assert double["rated_seats"] == 48
    assert validate_success(
        api.get_portable_unit(single["id"], ASSET_HEADERS)
    )["rated_seats"] == 24
    assert validate_success(
        api.get_portable_unit(triple["id"], ASSET_HEADERS)
    )["rated_seats"] == 60


def test_a_rooms_service_status_and_audit_fields_are_server_assigned(api):
    """PRD §3.1: a room's "`status` is not a client input at creation and begins at
    `IN_SERVICE`." PRD §2.4: "Every persisted resource carries an `id`, which is a
    server-minted UUID with no type prefix, and a `created_at`, which is an ISO 8601 UTC
    timestamp with three fractional digits ... a `version`, an integer that starts at 1 on
    creation".

    Design: Corner/entities/room_system_fields_are_server_assigned_and_input_ignored
    """
    set_clock(api, CLOCK)
    school = create_school(api, name="Northside Middle")

    payload = dict(room_payload(school["id"], room_number="R201"))
    payload.update({"status": "DECOMMISSIONED", "id": "client-supplied-id",
                    "version": 77, "created_at": "2000-01-01T00:00:00Z"})
    room = validate_success(api.create_room(payload, ADMIN_HEADERS), expected_status=201)

    assert room["status"] == "IN_SERVICE"
    assert room["id"] != "client-supplied-id"
    assert is_valid_uuid(room["id"])
    assert room["version"] == 1
    assert_created_at(room, CLOCK)
    assert_clock_stamp(room["updated_at"], CLOCK)


def test_undeclared_enum_members_and_out_of_range_numbers_are_refused(api):
    """PRD §2.6 rule 6: "Required body fields are present, types match, enum members are
    legal, numeric ranges hold, and dates parse in `YYYY-MM-DD` form —
    `ERR_INVALID_REQUEST`, 422, on every endpoint." PRD §3.1 fixes the ranges: a room is
    "sized by `area_sqft`, which must be greater than 0", and a projection row names "its
    `grade_level` as an integer from 0 through 12 where 0 means kindergarten".

    Design: Corner/entities/room_create_invalid_room_type_enum_rejected
    """
    set_clock(api, CLOCK)
    school = create_school(api, name="Northside Middle")

    bad_enum = api.create_room(
        room_payload(school["id"], room_number="R301", room_type="PORTABLE"),
        ADMIN_HEADERS,
    )
    validate_error(bad_enum, ApiErrorId.INVALID_REQUEST, expected_status=422)

    _, meta = validate_paginated(
        api.list_rooms(ADMIN_HEADERS, {"school_id": school["id"]})
    )
    assert meta["total_count"] == 0

    bad_area = api.create_room(
        room_payload(school["id"], room_number="R301", area_sqft=0), ADMIN_HEADERS
    )
    validate_error(bad_area, ApiErrorId.INVALID_REQUEST, expected_status=422)

    bad_grade = api.create_enrollment_projection(
        projection_payload(school["id"], grade_level=13, projected_students=20),
        PLANNER_HEADERS,
    )
    validate_error(bad_grade, ApiErrorId.INVALID_REQUEST, expected_status=422)


def test_a_projection_row_carries_no_version_and_is_displaced_not_edited(api):
    """PRD §2.4: "Three record types are append-only ledgers rather than living rows, and
    they carry only `id` and `created_at`: `ClassSizePolicy`, `EnrollmentProjection`, and
    `DisposalRecord` all have no `updated_at` and no `version` at all ... a projection row
    is never edited, only displaced by a newer row for the same campus, year and grade."
    PRD §3.1: "Rows are never edited; a newer row simply displaces an older one for the
    same campus, year and grade."

    Design: Corner/entities/enrollment_projection_is_immutable_and_versionless
    """
    set_clock(api, CLOCK)
    school = create_school(api, name="Northside Middle")
    original = validate_success(
        api.create_enrollment_projection(
            projection_payload(school["id"], grade_level=6, projected_students=44),
            PLANNER_HEADERS,
        ),
        expected_status=201,
    )

    row = validate_success(api.get_enrollment_projection(original["id"], PLANNER_HEADERS))
    assert "version" not in row
    assert "updated_at" not in row
    assert row["projected_students"] == 44

    validate_success(
        api.create_enrollment_projection(
            projection_payload(school["id"], grade_level=6, projected_students=52),
            PLANNER_HEADERS,
        ),
        expected_status=201,
    )
    assert validate_success(
        api.get_enrollment_projection(original["id"], PLANNER_HEADERS)
    )["projected_students"] == 44


def test_an_unknown_campus_on_a_room_body_outranks_field_validation(api):
    """PRD §2.6: rule 5 — "Every foreign key in the request body resolves, in
    entity-declaration order — the 404 family, on every endpoint that carries body foreign
    keys" — precedes rule 6 — "Required body fields are present, types match, enum members
    are legal ... — `ERR_INVALID_REQUEST`, 422". PRD §2.5: "Body-level failures raise
    `ERR_SCHOOL_NOT_FOUND` ... as appropriate."

    Design: Corner/entities/room_create_with_unknown_school_returns_school_not_found
    """
    set_clock(api, CLOCK)

    unknown = api.create_room(room_payload(NON_EXISTENT_UUID), ADMIN_HEADERS)
    validate_error(unknown, ApiErrorId.SCHOOL_NOT_FOUND, expected_status=404)

    unknown_and_invalid = api.create_room(
        room_payload(NON_EXISTENT_UUID, room_type="PORTABLE"), ADMIN_HEADERS
    )
    body = validate_error(unknown_and_invalid, ApiErrorId.SCHOOL_NOT_FOUND,
                          expected_status=404)
    assert body["error_id"] != ApiErrorId.INVALID_REQUEST


def test_each_request_foreign_key_reports_its_own_code_before_the_version_guard(api):
    """PRD §2.5: "a placement-request creation resolves `capacity_study_id` before
    `placement_site_id`, `placement_site_id` before `portable_unit_id`, and
    `portable_unit_id` before `capital_budget_id`. Body-level failures raise ...
    `ERR_STUDY_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`,
    `ERR_BUDGET_NOT_FOUND` ... as appropriate." PRD §2.6 puts body resolution at rule 5,
    ahead of rule 9 — "`expected_study_version` is equal to the study's `version` at the
    moment of the write — `ERR_STALE_STUDY_VERSION`, 412".

    Design: Corner/entities/placement_request_body_foreign_keys_resolved_before_version_check
    """
    ctx = build_campus(api, school_overrides={"name": "Northside Middle",
                                              "site_acreage": 10.0})
    site_id = create_site(api, ctx["school_id"], pad_code="PAD-A")["id"]
    unit_id = create_unit(api, asset_tag="PU-F101")["id"]
    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])

    def payload(**overrides):
        base = {"capacity_study_id": study["id"], "placement_site_id": site_id,
                "capital_budget_id": ctx["budget_id"], "portable_unit_id": unit_id,
                "expected_study_version": study_version(api, study["id"]),
                "haul_miles": 10}
        base.update(overrides)
        return placement_request_payload(base.pop("capacity_study_id"),
                                         base.pop("placement_site_id"),
                                         base.pop("capital_budget_id"),
                                         base.pop("expected_study_version"),
                                         **base)

    unknown_budget = api.create_placement_request(
        payload(capital_budget_id=NON_EXISTENT_UUID, expected_study_version=999),
        PLANNER_HEADERS,
    )
    body = validate_error(unknown_budget, ApiErrorId.BUDGET_NOT_FOUND,
                          expected_status=404)
    assert body["error_id"] != ApiErrorId.STALE_STUDY_VERSION

    _, meta = validate_paginated(
        api.list_placement_requests(PLANNER_HEADERS,
                                    {"capacity_study_id": study["id"]})
    )
    assert meta["total_count"] == 0
    assert validate_success(
        api.get_portable_unit(unit_id, PLANNER_HEADERS)
    )["allocation_status"] == "IN_STORAGE"

    validate_error(
        api.create_placement_request(payload(placement_site_id=NON_EXISTENT_UUID),
                                     PLANNER_HEADERS),
        ApiErrorId.SITE_NOT_FOUND, expected_status=404,
    )
    validate_error(
        api.create_placement_request(payload(capacity_study_id=NON_EXISTENT_UUID),
                                     PLANNER_HEADERS),
        ApiErrorId.STUDY_NOT_FOUND, expected_status=404,
    )
    validate_error(
        api.create_placement_request(payload(portable_unit_id=NON_EXISTENT_UUID),
                                     PLANNER_HEADERS),
        ApiErrorId.UNIT_NOT_FOUND, expected_status=404,
    )

    created = validate_success(
        api.create_placement_request(payload(), PLANNER_HEADERS), expected_status=201
    )
    assert created["school_id"] == ctx["school_id"]
