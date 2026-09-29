"""The shape of the stored rows themselves: which fields the server echoes, which it
defaults, which it mints, which it derives from other rows, and which it refuses to store
at all."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_COURSE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TASK_TURF_AREA_MISMATCH,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_applicator,
    assert_course,
    assert_immutable_record,
    assert_instant,
    assert_object_response,
    assert_page,
    assert_plan,
    assert_total_count,
    assert_turf_area,
)
from test_helpers.factories import (
    AERATION,
    course_payload,
    plan_task_payload,
    turf_area_payload,
    without,
)
from test_helpers.fixtures import (
    create_applicator,
    create_course,
    create_green,
    create_plan,
    create_playability_reading,
    create_turf_area,
    get_applicator,
    get_course,
    get_plan,
    get_turf_area,
    list_applicators,
    list_plan_tasks,
    list_playability_readings,
    list_turf_areas,
    set_clock,
)
from test_helpers.test_users import AGRO_HEADERS, SUPER_HEADERS, TOURN_HEADERS
from test_helpers.types import (
    AgronomicStatus,
    AreaType,
    LicenseCategory,
    LicenseStatus,
    PlanStatus,
    PlayPosture,
    SoilType,
    WaterPosture,
)


# --------------------------------------------------------------------------
# Creation and defaults
# --------------------------------------------------------------------------
def test_registering_a_course_echoes_every_declared_field():
    """A registration carrying both optional thresholds answers 201 with all nine declared
    course fields, the audit set, and a version of exactly 1.

    "A newly registered course starts with `water_used_gal` at 0, `water_posture` at `OPEN`,
    `play_posture` at `OPEN`, `frost_delay_minutes` at 0, and `version` at 1."

    Design: Corner/entities/course_creation_returns_every_declared_field
    """
    response = api_client.create_course(
        course_payload(
            name="Cedar Ridge GC",
            region_code="OR",
            annual_water_allocation_gal=500000,
            water_restricted_threshold_pct=85,
            water_suspended_threshold_pct=105,
        ),
        SUPER_HEADERS,
    )
    course = validate_success(response, 201)

    assert_course(
        course,
        expected_version=1,
        name="Cedar Ridge GC",
        region_code="OR",
        annual_water_allocation_gal=500000,
        water_restricted_threshold_pct=85,
        water_suspended_threshold_pct=105,
        water_used_gal=0,
        water_posture=WaterPosture.OPEN.value,
        play_posture=PlayPosture.OPEN.value,
        frost_delay_minutes=0,
    )
    assert assert_object_response(response)["id"] == course["id"]


def test_omitting_both_posture_thresholds_stores_eighty_and_one_hundred():
    """A registration that supplies neither threshold carries the declared defaults, not
    nulls.

    "Two optional posture thresholds may also be supplied: `water_restricted_threshold_pct`,
    which defaults to 80, and `water_suspended_threshold_pct`, which defaults to 100."

    Design: Corner/entities/course_defaults_applied_when_thresholds_are_omitted
    """
    course = create_course(
        name="Birch Hollow GC", region_code="WA", annual_water_allocation_gal=250000
    )

    assert_course(
        course,
        water_restricted_threshold_pct=80,
        water_suspended_threshold_pct=100,
        water_posture=WaterPosture.OPEN.value,
    )


def test_a_turf_area_defaults_its_target_moisture_and_derives_nothing_else():
    """Created without a target moisture the area carries 18, while the measured and ledger
    fields stay empty because no reading and no task has touched it yet.

    "A newly registered area starts with `agronomic_status` at `ACTIVE`, both nitrogen
    ledgers at 0, `current_moisture_pct` null, `rei_expires_at` null, and `version` 1."

    Design: Corner/entities/turf_area_defaults_target_moisture_and_leaves_derived_fields_empty
    """
    course = create_course(annual_water_allocation_gal=500000)

    green7 = create_turf_area(
        course["id"],
        area_type=AreaType.GREEN.value,
        hole_number=7,
        area_sq_ft=5500,
        mowing_height_mm=3.2,
        distance_to_water_ft=40,
        soil_type=SoilType.SAND_USGA.value,
        headers=AGRO_HEADERS,
    )

    assert_turf_area(
        green7,
        expected_version=1,
        target_moisture_pct=18,
        current_moisture_pct=None,
        agronomic_status=AgronomicStatus.ACTIVE.value,
        nitrogen_applied_lb_per_1000_ytd=0,
        nitrogen_projected_lb_per_1000=0,
        rei_expires_at=None,
    )


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------
def test_reading_a_course_back_returns_the_stored_row_untouched():
    """An Agronomist's read of a course registered with non-default thresholds returns the
    stored values and leaves the version where registration put it.

    "The rule is mechanical: each resource that is actually mutated by the request has its
    own `version` incremented by 1 and its own `updated_at` refreshed, and a resource that a
    request merely reads is not touched."

    Design: Corner/entities/course_retrieval_returns_the_stored_row
    """
    created = create_course(
        annual_water_allocation_gal=500000,
        water_restricted_threshold_pct=75,
        water_suspended_threshold_pct=95,
    )

    fetched = get_course(created["id"], headers=AGRO_HEADERS)

    assert_course(
        fetched,
        expected_version=1,
        name="Cedar Ridge GC",
        water_restricted_threshold_pct=75,
        water_suspended_threshold_pct=95,
    )
    assert_instant(fetched["created_at"], created["created_at"])


def test_the_applicator_list_pages_the_whole_filtered_set():
    """Three applicators on file split into a page of 2 and a page of 1, and `total_count`
    describes the set rather than the page.

    "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta`
    object of the envelope, where `total_count` is the number of rows matching the filter
    before pagination is applied and `has_more` states whether any matching row remains
    beyond the returned page."

    Design: Corner/entities/applicator_listing_paginates_with_total_count_and_has_more
    """
    dana = create_applicator(
        full_name="Dana Reyes",
        license_number="OR-CAT3-11001",
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2027-06-30",
    )
    miguel = create_applicator(
        full_name="Miguel Santos",
        license_number="OR-CAT3-11002",
        license_category=LicenseCategory.CAT_3_AND_7.value,
        license_expires_on="2028-01-31",
    )
    priya = create_applicator(
        full_name="Priya Nair",
        license_number="OR-CAT7-11003",
        license_category=LicenseCategory.CAT_7_AQUATIC.value,
        license_expires_on="2027-12-31",
    )

    first_rows, first_meta = list_applicators(limit=2, offset=0)
    second_rows, second_meta = list_applicators(limit=2, offset=2)

    assert len(first_rows) == 2
    assert_page(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert len(second_rows) == 1
    assert_page(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    seen = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert len(set(seen)) == 3
    assert set(seen) == {dana["id"], miguel["id"], priya["id"]}


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------
def test_a_turf_area_without_a_soil_type_is_refused():
    """`soil_type` has no default, so omitting it is a malformed request and no area row is
    written.

    "`ERR_INVALID_REQUEST` (400) — the body parses; every required field is present and
    non-null; every field has its declared type; every enum value is a declared member;
    every id is a well-formed UUID; every number is inside its declared range; and every
    interval satisfies end strictly after start."

    Design: Corner/entities/turf_area_creation_missing_required_soil_type
    """
    course = create_course(annual_water_allocation_gal=500000)

    refused = api_client.create_turf_area(
        without(turf_area_payload(course["id"]), "soil_type"), AGRO_HEADERS
    )
    validate_error(refused, ERR_INVALID_REQUEST, 400)

    _rows, meta = list_turf_areas(course_id=course["id"])
    assert_total_count(meta, 0)


def test_an_area_type_outside_the_declared_six_is_refused():
    """`LINKS` is plausible but undeclared, so it is rejected rather than stored verbatim.

    "The `area_type` classification is one of `GREEN`, `TEE`, `FAIRWAY`, `ROUGH`,
    `APPROACH`, or `PRACTICE_GREEN`, and it drives both the mowing regime and the regulatory
    nutrient ceiling."

    Design: Corner/entities/turf_area_rejects_an_undeclared_area_type_enum_member
    """
    course = create_course(annual_water_allocation_gal=500000)

    refused = api_client.create_turf_area(
        turf_area_payload(course["id"], area_type="LINKS"), AGRO_HEADERS
    )
    validate_error(refused, ERR_INVALID_REQUEST, 400)

    _rows, meta = list_turf_areas(course_id=course["id"])
    assert_total_count(meta, 0)


def test_a_planned_nitrogen_rate_above_six_is_a_malformed_request():
    """7.5 lb per thousand is outside the field's declared range, so the request shape rule
    decides the response before any agronomic ceiling is consulted and the plan ledger never
    moves.

    "a planned nitrogen rate greater than 0 and at most 6, required when the task is a
    fertility task and null otherwise"

    Design: Corner/entities/plan_task_rejects_a_nitrogen_rate_above_its_declared_range
    """
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)

    refused = api_client.create_plan_task(
        plan_task_payload(plan["id"], green7["id"], nitrogen_lb_per_1000=7.5),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_INVALID_REQUEST, 400)

    _rows, meta = list_plan_tasks(plan_id=plan["id"])
    assert_total_count(meta, 0)
    assert_plan(
        get_plan(plan["id"]), expected_version=1, committed_nitrogen_lb=0
    )


# --------------------------------------------------------------------------
# Server-minted and derived fields
# --------------------------------------------------------------------------
def test_the_server_mints_the_identity_and_audit_fields_of_each_course():
    """Two registrations get two distinct UUIDs, each with `created_at` equal to
    `updated_at` and each starting its own version count at 1.

    "Every resource in the system carries an `id`, which is a server-minted UUID with no
    type prefix, and a `created_at`, which is an ISO 8601 UTC timestamp with three fractional
    digits recording when the row was first written."

    Design: Corner/entities/course_system_fields_are_server_minted
    """
    cedar = create_course(annual_water_allocation_gal=500000)
    birch = create_course(
        name="Birch Hollow GC", region_code="WA", annual_water_allocation_gal=250000
    )

    assert is_valid_uuid(cedar["id"])
    assert is_valid_uuid(birch["id"])
    assert cedar["id"] != birch["id"]
    assert_instant(cedar["updated_at"], cedar["created_at"])
    assert cedar["version"] == 1
    assert birch["version"] == 1


def test_the_area_reports_the_newest_reading_rather_than_an_average():
    """After a 22.0 percent reading at 05:00 and a 15.5 percent reading at 07:00 the area
    reads 15.5, and each reading's tournament-spec flag is computed on its own numbers.

    "The `current_moisture_pct` field mirrors the latest measurement rather than an input: it
    is the moisture percentage of the most recent playability reading on the area, selected
    by the greatest `measured_at` and breaking a tie by the greatest `created_at`, and it
    stays null while the area has no readings at all."

    Design: Corner/entities/turf_area_current_moisture_tracks_the_latest_reading
    """
    set_clock("2026-08-01T08:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)

    on_spec = create_playability_reading(
        green7["id"], "2026-08-01T05:00:00Z",
        green_speed_ft=11.5, firmness_gravities=1.4, moisture_pct=22.0,
    )
    off_spec = create_playability_reading(
        green7["id"], "2026-08-01T07:00:00Z",
        green_speed_ft=9.0, firmness_gravities=1.1, moisture_pct=15.5,
    )

    assert on_spec["within_tournament_spec"] is True
    assert off_spec["within_tournament_spec"] is False
    assert_turf_area(
        get_turf_area(green7["id"]),
        current_moisture_pct=15.5,
        target_moisture_pct=18,
    )


def test_a_licence_lapses_with_the_clock_and_not_with_a_write():
    """The same applicator row reads `ACTIVE` at 23:00 on the expiry date and `EXPIRED` an
    hour later, with no write and no version bump in between.

    "A new applicator record carries `suspended_at` null and `version` 1, and its
    `license_status` is derived rather than supplied: it reads `ACTIVE` while the logical
    clock's calendar date is at or before `license_expires_on` and no suspension has been
    recorded, reads `EXPIRED` once the logical clock's calendar date is after
    `license_expires_on`, and reads `SUSPENDED` once any application record made by that
    applicator has been voided for a safety violation."

    Design: Corner/entities/applicator_license_status_expires_with_the_logical_clock
    """
    dana = create_applicator(license_expires_on="2026-08-10")

    set_clock("2026-08-10T23:00:00Z")
    still_good = get_applicator(dana["id"])
    assert_applicator(
        still_good,
        expected_version=dana["version"],
        license_status=LicenseStatus.ACTIVE.value,
        suspended_at=None,
    )

    set_clock("2026-08-11T00:00:00Z")
    lapsed = get_applicator(dana["id"])
    assert_applicator(
        lapsed,
        expected_version=dana["version"],
        license_status=LicenseStatus.EXPIRED.value,
        suspended_at=None,
    )


def test_playability_readings_are_append_only_and_carry_no_version():
    """Both readings come back newest first, neither carries an `updated_at` or a `version`,
    and the earlier measurement still reads 22.0 after the later one lands.

    "Two resource types are exceptions and carry only `id` and `created_at`: **pesticide
    products**, which are immutable label records with no update endpoint, and **playability
    readings**, which are append-only measurement events with no update or delete endpoint."

    Design: Corner/entities/playability_reading_is_immutable_and_versionless
    """
    set_clock("2026-08-01T08:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    earlier = create_playability_reading(
        green7["id"], "2026-08-01T05:00:00Z",
        green_speed_ft=11.5, firmness_gravities=1.4, moisture_pct=22.0,
    )
    later = create_playability_reading(
        green7["id"], "2026-08-01T07:00:00Z",
        green_speed_ft=10.8, firmness_gravities=1.3, moisture_pct=17.0,
        headers=TOURN_HEADERS,
    )

    rows, meta = list_playability_readings(green7["id"], limit=10, offset=0)

    assert_total_count(meta, 2)
    assert [row["id"] for row in rows] == [later["id"], earlier["id"]]
    for row in rows:
        assert_immutable_record(row)
    stored_earlier = next(row for row in rows if row["id"] == earlier["id"])
    assert_1dp(stored_earlier["moisture_pct"], 22.0)


# --------------------------------------------------------------------------
# Referential outcomes
# --------------------------------------------------------------------------
def test_an_unresolvable_course_id_is_a_miss_and_not_a_malformed_request():
    """A well-formed UUID that matches no row answers 404 `ERR_COURSE_NOT_FOUND`, and the
    course that does exist is still readable.

    "`ERR_COURSE_NOT_FOUND` (404) — for `GET /courses/{id}`,
    `GET /courses/{id}/water-assessment`, `GET /courses/{id}/weather-events`,
    `PATCH /courses/{id}/water-allocation`, `POST /turf-areas`, `POST /agronomic-plans`,
    `POST /pump-stations`, `POST /maintenance-windows`, `POST /play-events`,
    `POST /equipment-units`, `POST /weather-events`."

    Design: Corner/entities/course_get_with_an_unknown_id_returns_not_found
    """
    course = create_course(annual_water_allocation_gal=500000)

    missed = api_client.get_course(NON_EXISTENT_UUID, SUPER_HEADERS)
    validate_error(missed, ERR_COURSE_NOT_FOUND, 404)

    assert get_course(course["id"])["id"] == course["id"]


def test_a_task_cannot_reach_across_to_another_courses_turf_area():
    """Both ids resolve, but the green belongs to the other course, so containment is
    refused with 422 `ERR_TASK_TURF_AREA_MISMATCH` and the plan stays an empty draft.

    "A plan task's turf area must belong to the course its plan governs."

    Design: Corner/entities/plan_task_rejects_a_turf_area_owned_by_another_course
    """
    course_a = create_course(annual_water_allocation_gal=500000)
    course_b = create_course(
        name="Birch Hollow GC", region_code="WA", annual_water_allocation_gal=250000
    )
    green_b = create_green(course_b["id"], hole_number=7, area_sq_ft=5500,
                           distance_to_water_ft=40)
    plan_a = create_plan(course_a["id"], plan_year=2026, nitrogen_budget_lb=40.0)

    refused = api_client.create_plan_task(
        plan_task_payload(plan_a["id"], green_b["id"], task_type=AERATION),
        AGRO_HEADERS,
    )
    validate_error(refused, ERR_TASK_TURF_AREA_MISMATCH, 422)

    _rows, meta = list_plan_tasks(plan_id=plan_a["id"])
    assert_total_count(meta, 0)
    assert_plan(
        get_plan(plan_a["id"]),
        expected_version=1,
        status=PlanStatus.DRAFT.value,
    )
