"""The roster: registering sites, clinicians, students and guardians, plus the
list envelope every collection endpoint shares."""

import pytest

from test_helpers import (
    ADMIN,
    BILLING,
    NON_EXISTENT_UUID,
    REGISTRAR,
    ApiErrorId,
    assert_fpl_precision,
    assert_guardian,
    assert_instant_at_or_after,
    assert_no_type_prefix,
    assert_report,
    assert_same_date,
    assert_school,
    assert_student,
    assert_version_bumped_by,
    consent_payload,
    create_school,
    create_student,
    generate_report,
    guardian_payload,
    make_clinician_headers,
    set_clock,
    set_financial_profile,
    setup_pending_charge,
    setup_visit_completed,
    student_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_student_opens_pessimistic_on_every_derived_field(api):
    """PRD §3.2: "A freshly created student is deliberately pessimistic on every
    derived field: `fpl_percent` is 0.00 and `discount_tier` is `TIER_A` (an
    income of 0 in a household of 1 is 0.00% of the poverty level, which lands
    in the deepest-discount tier), `payer_route` is `SELF_PAY`,
    `insurance_member_id` is null, `household_income_annual_cents` is 0,
    `household_size` is 1, `immunization_exemption_type` is `NONE`,
    `immunization_compliance_status` is `NON_COMPLIANT`, all four dose counters
    — `valid_dose_count`, `invalid_dose_count`, `voided_dose_count` and
    `total_dose_count` — are 0, and `version` is 1."

    Design: Corner/entities/student_creation_initialises_every_computed_and_system_field
    """
    set_clock("2026-05-04T09:00:00Z")

    resp = api.create_student(
        student_payload(first_name="Ava", last_name="Nguyen", date_of_birth="2010-04-15"),
        REGISTRAR,
    )
    student = validate_success(resp, 201)

    assert_student(student)
    assert float(student["fpl_percent"]) == pytest.approx(0.00, abs=0.001)
    assert student["discount_tier"] == "TIER_A"
    assert student["payer_route"] == "SELF_PAY"
    assert student["insurance_member_id"] is None
    assert student["household_income_annual_cents"] == 0
    assert student["household_size"] == 1
    assert student["immunization_exemption_type"] == "NONE"
    assert student["immunization_compliance_status"] == "NON_COMPLIANT"
    assert student["valid_dose_count"] == 0
    assert student["invalid_dose_count"] == 0
    assert student["voided_dose_count"] == 0
    assert student["total_dose_count"] == 0
    assert student["version"] == 1


def test_student_read_reflects_the_recomputed_sliding_fee_position(api):
    """PRD §3.2: "It then divides the household's annual income by that
    threshold, multiplies by one hundred, keeps the quotient exact with no
    truncation along the way, and rounds the result half-up to 2 decimal places
    to produce `fpl_percent`."
    PRD §3.2: "above 175.00% and at or below 200.00% it is `TIER_D`; and
    strictly above 200.00% it is `TIER_E`."

    Design: Corner/entities/student_retrieval_reflects_recomputed_sliding_fee_position
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student(first_name="Nia", last_name="Bell")
    set_financial_profile(
        student["id"],
        household_income_annual_cents=4_500_000,
        household_size=2,
        payer_route="SELF_PAY",
    )

    read = validate_success(api.get_student(student["id"], REGISTRAR))

    # Threshold for a household of two is 2,110,000 cents; 4,500,000 / 2,110,000
    # is 213.2701...%, which rounds half-up to 213.27 and lands above 200.00%.
    assert float(read["fpl_percent"]) == pytest.approx(213.27, abs=0.001)
    assert_fpl_precision(read["fpl_percent"])
    assert read["discount_tier"] == "TIER_E"
    assert read["version"] == 2


def test_student_identifiers_are_server_minted_and_version_steps_by_one(api):
    """PRD §2.4: "Every stored resource is addressed by an `id` that the server
    mints as a UUID. Identifiers carry no type prefix and no embedded meaning; a
    client must never construct one."
    PRD §2.4: "and `version`, an integer that starts at 1 when the row is created
    and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/student_system_fields_are_server_minted_and_version_increments
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student()
    assert_no_type_prefix(student["id"])
    assert student["version"] == 1

    resp = api.update_financial_profile(
        student["id"],
        {
            "household_income_annual_cents": 3_000_000,
            "household_size": 4,
            "payer_route": "SELF_PAY",
        },
        REGISTRAR,
    )
    updated = validate_success(resp)

    assert_student(updated)
    assert_version_bumped_by(updated["version"], student["version"])
    assert_instant_at_or_after(updated["updated_at"], updated["created_at"], "Student.updated_at")


def test_optional_capacity_and_guardian_flags_take_their_declared_defaults(api):
    """PRD §3.1: "Registration may optionally supply
    `telehealth_concurrent_capacity`, the number of telehealth sessions the
    site's classroom and presenter staff can host at overlapping times; when it
    is omitted the value defaults to 1, and any supplied value must be at least
    1 and at most 4."
    PRD §3.1: "A newly registered site starts with `program_status` of `ACTIVE`,
    a `telehealth_booked_minutes_total` of 0 and a `suspended_count` of 0."
    PRD §3.2: "an optional `is_primary` flag that defaults to false. Every
    guardian also carries `notification_opt_out`, which defaults to false and
    can be flipped later by the guardian themself or by a `Registrar`"

    Design: Corner/entities/school_capacity_and_guardian_flags_default_when_omitted
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student()

    school_resp = api.create_school(
        {
            "name": "Lincoln High",
            "site_code": "LHS",
            "sponsor_hospital_name": "Mercy Sponsor Hospital",
        },
        ADMIN,
    )
    school = validate_success(school_resp, 201)
    assert_school(school)
    assert school["telehealth_concurrent_capacity"] == 1
    assert school["program_status"] == "ACTIVE"
    assert school["telehealth_booked_minutes_total"] == 0
    assert school["suspended_count"] == 0

    guardian_resp = api.add_guardian(
        student["id"],
        {
            "full_name": "Mai Nguyen",
            "relationship": "MOTHER",
            "contact_email": "mai@example.org",
        },
        REGISTRAR,
    )
    guardian = validate_success(guardian_resp, 201)
    assert_guardian(guardian)
    assert guardian["is_primary"] is False
    assert guardian["notification_opt_out"] is False


def test_school_create_without_a_site_code_is_refused(api):
    """PRD §3.1: "A school site is described by its `name`, which must be between
    1 and 120 characters; its `site_code`, a short identifier between 1 and 16
    characters that must be unique across all school rows, with uniqueness
    compared case-sensitively so that `NORTH1` and `north1` are two different
    sites; and `sponsor_hospital_name`, the hospital that owns the billing
    relationship for everything delivered at that site."
    PRD §2.6 rung 6: "Every required body field is present, and every enum,
    integer, boolean, date and datetime field is well formed and inside its
    declared range, on every endpoint that takes a request body. Otherwise
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/school_create_missing_required_site_code_returns_validation
    """
    set_clock("2026-05-04T09:00:00Z")

    resp = api.create_school(
        {"name": "Lincoln High", "sponsor_hospital_name": "Mercy Sponsor Hospital"}, ADMIN
    )

    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_encounter_read_with_an_unknown_identifier_is_a_visit_not_found(api):
    """PRD §2.6 rung 4: "Every identifier embedded in the URL path resolves to a
    stored row, validated left to right, on every endpoint that has a path
    identifier. Otherwise HTTP 404, carrying `ERR_STUDENT_NOT_FOUND`,
    `ERR_SCHOOL_NOT_FOUND`, `ERR_CLINICIAN_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
    `ERR_REFERRAL_NOT_FOUND` or `ERR_CHARGE_NOT_FOUND` for those six resource
    types"

    Design: Corner/entities/visit_get_with_unknown_uuid_returns_visit_not_found
    """
    set_clock("2026-05-04T09:00:00Z")

    resp = api.get_visit(NON_EXISTENT_UUID, make_clinician_headers("test-clinician-1"))

    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_FOUND.value, 404)


def test_guardian_create_under_an_unknown_student_resolves_the_parent_first(api):
    """PRD §2.9: "When a path carries more than one identifier, the identifiers
    are resolved **left to right** and the first one that fails to resolve
    decides the 404 — a screening recorded against a non-existent visit reports
    `ERR_VISIT_NOT_FOUND` without ever considering the body."
    PRD §2.6 rung 4: "Every identifier embedded in the URL path resolves to a
    stored row, validated left to right, on every endpoint that has a path
    identifier."

    Design: Corner/entities/guardian_create_under_unknown_student_returns_student_not_found
    """
    set_clock("2026-05-04T09:00:00Z")

    resp = api.add_guardian(NON_EXISTENT_UUID, guardian_payload(), REGISTRAR)

    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404)


def test_consent_create_with_an_undeclared_category_is_refused(api):
    """PRD §3.4: "Five categories exist: `GENERAL_TREATMENT`,
    `BEHAVIORAL_HEALTH`, `CONFIDENTIAL_SERVICES`, `DENTAL` and `TELEHEALTH`."
    PRD §2.6 rung 6: "Every required body field is present, and every enum,
    integer, boolean, date and datetime field is well formed and inside its
    declared range, on every endpoint that takes a request body. Otherwise
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/consent_create_with_unknown_category_enum_returns_validation
    """
    set_clock("2026-05-04T09:00:00Z")
    student = create_student()
    guardian = validate_success(
        api.add_guardian(student["id"], guardian_payload(), REGISTRAR), 201
    )

    resp = api.create_consent(
        student["id"],
        consent_payload("VISION_CARE", guardian["id"], student["version"]),
        REGISTRAR,
    )

    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)

    rows, _meta = validate_paginated(api.list_consents(student["id"], REGISTRAR))
    assert rows == [], "A refused consent create must leave no Consent row behind"


def test_enrollment_list_reports_limit_offset_total_count_and_has_more(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside `meta`: `total_count` is the number of rows that match the
    filters before pagination is applied, and `has_more` is true when rows remain
    beyond the current page."

    Design: Corner/entities/enrollment_list_honours_limit_offset_total_count_and_has_more
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()
    for first, last, dob in (
        ("One", "Alpha", "2010-04-15"),
        ("Two", "Beta", "2010-05-15"),
        ("Three", "Gamma", "2010-06-15"),
    ):
        student = create_student(first_name=first, last_name=last, date_of_birth=dob)
        validate_success(
            api.create_enrollment(
                student["id"],
                {
                    "school_id": school["id"],
                    "school_year": "2025-2026",
                    "expected_student_version": student["version"],
                },
                REGISTRAR,
            ),
            201,
        )

    first_page, first_meta = validate_paginated(
        api.list_enrollments(REGISTRAR, params={"school_id": school["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"Expected 2 rows on the first page, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api.list_enrollments(REGISTRAR, params={"school_id": school["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"Expected 1 row on the second page, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False


def test_pagination_limit_bounds_are_inclusive_between_one_and_one_hundred(api):
    """PRD §2.3: "A `limit` below 1 or above 100, or an `offset` below 0, or
    either parameter supplied as something other than an integer, is refused with
    `ERR_VALIDATION` and HTTP 400."

    Design: Corner/endpoints/pagination_limit_out_of_range_returns_validation
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()
    student = create_student()
    validate_success(
        api.create_enrollment(
            student["id"],
            {
                "school_id": school["id"],
                "school_year": "2025-2026",
                "expected_student_version": student["version"],
            },
            REGISTRAR,
        ),
        201,
    )

    validate_error(
        api.list_enrollments(REGISTRAR, params={"limit": 0}), ApiErrorId.ERR_VALIDATION.value, 400
    )
    validate_error(
        api.list_enrollments(REGISTRAR, params={"limit": 101}), ApiErrorId.ERR_VALIDATION.value, 400
    )

    rows, meta = validate_paginated(api.list_enrollments(REGISTRAR, params={"limit": 100}))
    assert len(rows) == 1, f"limit 100 must be accepted, got {len(rows)} rows"
    assert meta["total_count"] == 1


def test_charge_list_scopes_strictly_to_the_requested_encounter(api):
    """PRD §4: "List billable charges filtered by student, encounter, status or
    service category"
    PRD §3.10: "the base is 0 for a no-charge service category, 0 when the
    snapshotted payer route is `MEDICAID`, a flat 2,500 cents when it is
    `PRIVATE_INSURANCE`, and the full `gross_amount_cents` when it is
    `SELF_PAY`."

    Design: Corner/endpoints/charges_filtered_list_scopes_strictly_to_the_requested_visit
    """
    ctx = setup_pending_charge()
    first_visit = ctx["visit"]
    first_charge = ctx["charge"]

    second = setup_visit_completed(
        ctx, visit_type="ACUTE", disposition="NO_TREATMENT_NEEDED",
        scheduled_start_at="2026-05-04T13:00:00Z",
    )
    second_visit = second["visit"]

    scoped, scoped_meta = validate_paginated(
        api.list_charges(BILLING, params={"visit_id": first_visit["id"]})
    )
    assert len(scoped) == 1, f"Expected exactly one charge on the first encounter, got {len(scoped)}"
    assert scoped[0]["visit_id"] == first_visit["id"]
    assert scoped_meta["total_count"] == 1

    by_student, _ = validate_paginated(
        api.list_charges(BILLING, params={"student_id": ctx["student"]["id"]})
    )
    assert len(by_student) == 2, f"Expected both encounters' charges, got {len(by_student)}"

    reread = validate_success(api.get_charge(first_charge["id"], BILLING))
    assert reread["gross_amount_cents"] == 12_000
    assert reread["patient_responsibility_cents"] == 500
    assert validate_success(api.get_visit(first_visit["id"], REGISTRAR))[
        "patient_responsibility_total_cents"
    ] == 500
    assert validate_success(api.get_visit(second_visit["id"], REGISTRAR))[
        "patient_responsibility_total_cents"
    ] == 500


def test_report_snapshot_is_immutable_and_carries_no_version(api):
    """PRD §2.4: "The single exception is the aggregate report snapshot, which is
    immutable by construction: a report carries `id` and `created_at` only, and
    has neither `updated_at` nor `version`."

    Design: Corner/entities/report_snapshot_is_immutable_and_exposes_no_version_field
    """
    set_clock("2026-05-04T09:00:00Z")
    school = create_school()
    report = generate_report("2026-04-01", "2026-04-30", school_id=school["id"])

    read = validate_success(api.get_report(report["id"], ADMIN))

    assert_report(read)
    assert_same_date(read["period_start_date"], "2026-04-01", "period_start_date")
    assert_same_date(read["period_end_date"], "2026-04-30", "period_end_date")
    assert "version" not in read, "An immutable report must not expose a version field"
    assert read["total_visits"] == 0

    rows, meta = validate_paginated(api.list_reports(ADMIN, params={"school_id": school["id"]}))
    assert len(rows) == 1, f"Expected exactly one report for the site, got {len(rows)}"
    assert meta["total_count"] == 1
