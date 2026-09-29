"""The identity layer: the two headers that must be present and recognised, the exclusive
write surface of each of the five roles, and the two segregation-of-duties comparisons — one
between opaque operator identifiers, one between applicator rows."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_1dp,
    assert_2dp,
    assert_3dp,
    assert_application,
    assert_course,
    assert_equipment_unit,
    assert_plan,
    assert_plan_task,
    assert_play_event,
    assert_total_count,
)
from test_helpers.factories import (
    AERATION,
    MOWING,
    application_payload,
    approve_plan_payload,
    maintenance_window_payload,
    plan_payload,
    retire_payload,
    void_payload,
)
from test_helpers.fixtures import (
    approve_plan,
    certify_conditions,
    create_applicator,
    create_course,
    create_equipment_unit,
    create_green,
    create_plan,
    create_plan_task,
    create_playability_reading,
    create_product,
    create_tournament_round,
    get_application,
    get_course,
    get_plan,
    get_plan_task,
    get_play_event,
    get_turf_area,
    list_applicators,
    log_equipment_hours,
    record_application,
    set_clock,
    submit_plan,
    verify_application,
)
from test_helpers.test_users import (
    AGRO_HEADERS,
    APPLICATOR_WITHOUT_USER_ID_HEADERS,
    DUAL_AGRO_HEADERS,
    DUAL_ROLE_OPERATOR,
    DUAL_SUPER_HEADERS,
    NO_ROLE_HEADERS,
    SUPER_HEADERS,
    TECH_HEADERS,
    TOURN_HEADERS,
    UNDECLARED_ROLE_HEADERS,
    make_applicator_headers,
)
from test_helpers.types import (
    EquipmentStatus,
    LicenseCategory,
    PlanStatus,
    PlanTaskStatus,
    PlayEventStatus,
    PlayPosture,
    ReadinessStatus,
    RecordStatus,
    UnitType,
    VoidReason,
)


def _submitted_plan_whose_author_also_wears_the_superintendent_hat():
    """A 2026 plan authored and submitted by the operator `dual-1`, who is about to present
    themselves as the approver."""
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=5500,
                          distance_to_water_ft=40)
    plan = create_plan(
        course["id"], headers=DUAL_AGRO_HEADERS, plan_year=2026,
        nitrogen_budget_lb=40.0,
    )
    task1 = create_plan_task(
        plan["id"], green7["id"], headers=DUAL_AGRO_HEADERS, task_type=AERATION
    )
    submitted = submit_plan(plan["id"], headers=DUAL_AGRO_HEADERS)
    return plan, task1, submitted


def _danas_spray_awaiting_a_second_pair_of_eyes():
    """Dana's 150 lb per acre urea pass on a 4000 sq ft green, and Miguel, the only other
    licensed applicator on the books."""
    set_clock("2026-08-01T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=4000,
                          distance_to_water_ft=40)
    dana = create_applicator(
        full_name="Dana Reyes",
        license_number="OR-CAT3-16001",
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2027-06-30",
    )
    miguel = create_applicator(
        full_name="Miguel Santos",
        license_number="OR-CAT3-16002",
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2028-01-31",
    )
    urea = create_product(epa_reg_no="NA-FERT-0004")
    record = record_application(
        green7["id"], urea["id"], dana["id"], "2026-08-01T06:00:00Z",
        rate_lb_per_acre=150, wind_speed_mph=4, distance_to_water_ft=40,
    )
    return green7, dana, miguel, record


def _a_course_ready_for_five_roles_to_each_do_their_own_work():
    """Three on-target greens inside the readiness window of an afternoon round, plus the
    applicator, the label, and the brand-new triplex each specialist will need."""
    set_clock("2026-08-05T06:00:00Z")
    course = create_course(annual_water_allocation_gal=500000)
    green3 = create_green(course["id"], hole_number=3, area_sq_ft=5000,
                          distance_to_water_ft=40, headers=AGRO_HEADERS)
    green7 = create_green(course["id"], hole_number=7, area_sq_ft=4000,
                          distance_to_water_ft=40, headers=SUPER_HEADERS)
    green12 = create_green(course["id"], hole_number=12, area_sq_ft=5500,
                           distance_to_water_ft=60, headers=AGRO_HEADERS)
    dana = create_applicator(
        full_name="Dana Reyes",
        license_number="OR-CAT3-17001",
        license_category=LicenseCategory.CAT_3_TURF.value,
        license_expires_on="2027-06-30",
    )
    urea = create_product(epa_reg_no="NA-FERT-0005")
    round_posted = create_tournament_round(
        course["id"],
        start_at="2026-08-05T14:00:00Z",
        end_at="2026-08-05T18:00:00Z",
        holes_in_play=18,
        field_size=78,
    )
    mower = create_equipment_unit(
        course["id"], unit_type=UnitType.TRIPLEX_GREENS_MOWER.value, model_year=2024,
        purchase_cost=48000, expected_life_hours=6000,
        service_interval_hours=250, avg_daily_hours=3.5,
    )
    for area_id, headers in (
        (green3["id"], AGRO_HEADERS),
        (green7["id"], TOURN_HEADERS),
        (green12["id"], AGRO_HEADERS),
    ):
        create_playability_reading(
            area_id, "2026-08-05T06:00:00Z",
            green_speed_ft=11.0, firmness_gravities=1.35, moisture_pct=18.0,
            headers=headers,
        )
    return course, green7, dana, urea, round_posted, mower


# --------------------------------------------------------------------------
# The two identity headers
# --------------------------------------------------------------------------
def test_a_missing_or_unrecognised_identity_never_reaches_the_endpoint():
    """An omitted role, a role outside the declared five, and an `Applicator` with no
    `X-User-ID` all answer 401 `ERR_UNAUTHENTICATED` — the last of them in preference to the
    not-found the target id would otherwise earn.

    "A request that omits `X-User-Role`, or that presents a role value which is not one of
    those five, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    "`X-User-ID` is likewise required on every endpoint where the acting identity is itself
    part of a rule — the plan submit and approve pair, application verification, and every
    endpoint whose effect is recorded against a caller — and a missing `X-User-ID` on such an
    endpoint is also `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/request_without_a_valid_role_header_is_unauthenticated
    """
    course = create_course(annual_water_allocation_gal=500000)

    validate_error(
        api_client.get_course(course["id"], NO_ROLE_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api_client.get_course(course["id"], UNDECLARED_ROLE_HEADERS),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api_client.verify_application(
            NON_EXISTENT_UUID, APPLICATOR_WITHOUT_USER_ID_HEADERS
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    assert_course(get_course(course["id"]), expected_version=1)


# --------------------------------------------------------------------------
# The exclusive write surface of each role
# --------------------------------------------------------------------------
def test_no_role_may_reach_across_into_another_roles_exclusive_write():
    """Six writes attempted by the wrong role all answer 403 `ERR_UNAUTHORIZED` and none of
    them answers 404, which places authorisation ahead of the existence band.

    "Once authenticated, a caller whose role does not appear in the authorised-role list for
    the endpoint being called is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    "A `Superintendent` owns the course record and its water allocation, the applicator and
    product registries, the weather log, the capital fate of the fleet, and the integrity of
    the application record; it is the only role that may void an application, reverse an
    irrigation run, approve or return a plan, retire a machine, declare or clear weather, or
    drive the logical clock."

    "An `Agronomist` authors the annual plan, submits it, adds and schedules its tasks, books
    and runs crew windows, and schedules and completes irrigation."

    "An `Applicator` records applications, verifies them, and releases field postings."

    Design: Corner/rbac/each_role_cannot_perform_another_roles_exclusive_operation
    """
    course = create_course(annual_water_allocation_gal=500000)
    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)

    validate_error(
        api_client.void_application(
            NON_EXISTENT_UUID, void_payload(VoidReason.DATA_ENTRY_ERROR.value), AGRO_HEADERS
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.retire_equipment_unit(
            NON_EXISTENT_UUID, TECH_HEADERS, retire_payload()
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_maintenance_window(
            maintenance_window_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, MOWING,
                "2026-08-15T06:00:00Z", "2026-08-15T08:00:00Z", crew_size=2,
            ),
            TOURN_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.approve_plan(
            plan["id"],
            approve_plan_payload(plan["version"]),
            make_applicator_headers(NON_EXISTENT_UUID),
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_application(
            application_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                "2026-08-01T06:00:00Z",
                rate_lb_per_acre=100, wind_speed_mph=4, distance_to_water_ft=40,
            ),
            SUPER_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api_client.create_plan(
            plan_payload(NON_EXISTENT_UUID, plan_year=2026, nitrogen_budget_lb=40.0),
            SUPER_HEADERS,
        ),
        ERR_UNAUTHORIZED,
        403,
    )

    _rows, meta = list_applicators()
    assert_total_count(meta, 0)
    assert_plan(
        get_plan(plan["id"]), expected_version=1, status=PlanStatus.DRAFT.value
    )


def test_each_role_exercises_the_writes_that_are_its_own():
    """The plan author, the licensed applicator, the tournament official and the shop
    technician each land their own exclusive write: a `DRAFT` plan, a 13.77 lb pass, a
    100.00 certification that leaves the schedule alone, and a 10 hour meter entry.

    "An `Applicator` records applications, verifies them, and releases field postings. A
    `TournamentOfficial` posts rounds — including simultaneous-start shotgun events — and
    certifies playing conditions. An `EquipmentTechnician` runs the shop: meter hours,
    completed services, and taking pump stations offline for repair."

    "A `readiness_index` of at least 82.00 sets `readiness_status` to `CERTIFIED`; anything
    below it sets `readiness_status` to `FAILED`."

    "The entry raises `engine_hours` and therefore `hours_since_service`, recomputes both
    replacement scores and the replacement flag, and increments the unit's `version` by 1."

    Design: Corner/rbac/each_role_can_exercise_its_own_exclusive_operations
    """
    course, green7, dana, urea, round_posted, mower = (
        _a_course_ready_for_five_roles_to_each_do_their_own_work()
    )

    plan = create_plan(course["id"], plan_year=2026, nitrogen_budget_lb=40.0)
    assert_plan(plan, expected_version=1, status=PlanStatus.DRAFT.value)

    record = record_application(
        green7["id"], urea["id"], dana["id"], "2026-08-05T06:00:00Z",
        rate_lb_per_acre=150, wind_speed_mph=4, distance_to_water_ft=40,
    )
    assert_2dp(record["total_lb"], 13.77)
    assert_2dp(record["nitrogen_lb"], 6.33)

    certified = certify_conditions(round_posted["id"])
    assert_play_event(
        certified,
        readiness_status=ReadinessStatus.CERTIFIED.value,
        status=PlayEventStatus.SCHEDULED.value,
    )
    assert_2dp(certified["readiness_index"], 100.00)
    assert get_play_event(round_posted["id"])["status"] == (
        PlayEventStatus.SCHEDULED.value
    )

    logged = log_equipment_hours(mower["id"], 10)
    assert_equipment_unit(logged, status=EquipmentStatus.IN_SERVICE.value)
    assert_1dp(logged["engine_hours"], 10.0)
    assert_1dp(logged["hours_since_service"], 10.0)
    assert get_course(course["id"])["play_posture"] == PlayPosture.OPEN.value


# --------------------------------------------------------------------------
# The two segregation-of-duties comparisons
# --------------------------------------------------------------------------
def test_the_submitting_operator_may_not_approve_their_own_plan():
    """`dual-1` legitimately holds the Superintendent role, so the refusal is 403
    `ERR_SEGREGATION_OF_DUTIES` rather than an authorisation failure, and the pinned version
    is still current for the colleague who approves next.

    "The one comparison it does make is between two opaque identifiers: the caller approving
    a plan must not be the caller recorded in `submitted_by_user_id`, and a match is
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/plan_approval_by_the_submitting_user_is_forbidden
    """
    plan, task1, submitted = (
        _submitted_plan_whose_author_also_wears_the_superintendent_hat()
    )

    assert_plan(
        submitted,
        expected_version=2,
        status=PlanStatus.SUBMITTED.value,
        submitted_by_user_id=DUAL_ROLE_OPERATOR,
    )

    refused = api_client.approve_plan(
        plan["id"], approve_plan_payload(submitted["version"]), DUAL_SUPER_HEADERS
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    assert_plan(
        get_plan(plan["id"]),
        expected_version=2,
        status=PlanStatus.SUBMITTED.value,
    )

    approved = approve_plan(plan["id"], submitted["version"])
    assert_plan(approved, expected_version=3, status=PlanStatus.ACTIVE.value)
    assert_plan_task(
        get_plan_task(task1["id"]), status=PlanTaskStatus.PLANNED.value
    )


def test_the_recording_applicator_may_not_verify_their_own_record():
    """Dana's own attempt is refused with 403 `ERR_SEGREGATION_OF_DUTIES` and moves nothing,
    while Miguel's verification is accepted — and the green's applied ledger reads 1.583
    throughout, because a recorded pass already counts.

    "Concretely, verification of an application resolves the verifying applicator by looking
    up `X-User-ID` as an `Applicator` id, so an `X-User-ID` that resolves to no applicator
    yields `ERR_APPLICATOR_NOT_FOUND`, and an `X-User-ID` equal to the record's own
    `applicator_id` yields `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/application_verification_by_the_recording_applicator_is_forbidden
    """
    green7, dana, miguel, record = _danas_spray_awaiting_a_second_pair_of_eyes()
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 1.583
    )

    refused = api_client.verify_application(
        record["id"], make_applicator_headers(dana["id"])
    )
    validate_error(refused, ERR_SEGREGATION_OF_DUTIES, 403)

    assert_application(
        get_application(record["id"]),
        expected_version=1,
        record_status=RecordStatus.RECORDED.value,
        verified_by_applicator_id=None,
    )

    verified = verify_application(record["id"], miguel["id"])
    assert_application(
        verified,
        expected_version=2,
        record_status=RecordStatus.VERIFIED.value,
        verified_by_applicator_id=miguel["id"],
    )
    assert_3dp(
        get_turf_area(green7["id"])["nitrogen_applied_lb_per_1000_ytd"], 1.583
    )
