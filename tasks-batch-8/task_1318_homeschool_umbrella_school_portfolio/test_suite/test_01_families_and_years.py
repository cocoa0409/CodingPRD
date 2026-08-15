"""Family onboarding, academic-year creation, lookups, and list pagination."""
from test_helpers import (
    ApiErrorId,
    assert_academic_year,
    assert_enrollment,
    assert_family,
    create_academic_year_payload,
    create_coop_class_payload,
    create_enrollment_payload,
    create_family_payload,
    create_student_payload,
    create_year_with_registered_enrollment,
    get_success_data,
    make_parent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
SELF_REGISTER = TEST_USERS["parent_headers"]


def test_create_family_missing_required_district_code(api):
    """PRD §3.2: "a `Parent` caller creates the family account with a
    `display_name` and the `district_code` of the family's district of residence."
    PRD §2.8: "Body well-formedness: required fields present, types correct, enum
    members valid, and scalar ranges respected — instructional `minutes` between
    1 and 720 inclusive, `composite_percentile` between 1 and 99 inclusive,
    `grade_level` between 0 and 12 inclusive, capacities at least 1, and window
    ends after their starts — else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_family_missing_required_district_code_returns_invalid_request
    """
    resp = api.create_family({"display_name": "No District"}, SELF_REGISTER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_academic_year_defaults_applied(api):
    """PRD §3.1: "Four policy parameters may be overridden at creation:
    `testing_grades`, the grade levels (0 for kindergarten through 12) in which
    standardized testing is mandatory, defaulting to grades 3, 5, 8, and 11;
    `required_instructional_days`, defaulting to 180;
    `required_minutes_elementary`, the certified minutes required of grades K–5,
    defaulting to 54,000 (nine hundred hours); and
    `required_minutes_secondary`, the certified minutes required of grades 6–12,
    defaulting to 59,400 (nine hundred ninety hours)."
    PRD §3.1: "A new year is `PLANNING`."

    Design: Corner/entities/academic_year_defaults_applied
    """
    resp = api.create_academic_year(
        create_academic_year_payload(), DIRECTOR
    )
    year = validate_success(resp, 201)
    assert_academic_year(year)
    assert year["testing_grades"] == [3, 5, 8, 11]
    assert year["required_instructional_days"] == 180
    assert year["required_minutes_elementary"] == 54000
    assert year["required_minutes_secondary"] == 59400
    assert year["status"] == "PLANNING"


def test_enrollment_initial_state_and_testing_flag(api):
    """PRD §3.2: "The new enrollment opens with `enrollment_status` `REGISTERED`,
    `compliance_standing` `GOOD_STANDING`, `standing_locked` false, and all four
    progress counters — `provisional_days_counted`,
    `provisional_minutes_credited`, `certified_days_counted`,
    `certified_minutes_credited` — at zero."
    PRD §3.2: "Whether the student must sit a standardized test is decided at this
    moment: `testing_required` is true exactly when the chosen `grade_level` is a
    member of the year's `testing_grades`, and `testing_satisfied` begins false."

    Design: Corner/entities/enrollment_initial_state_and_testing_flag
    """
    year, family, _student, _enr = create_year_with_registered_enrollment(
        label="2026-2027", start_date="2026-08-01", end_date="2027-05-31",
        notice_filing_deadline="2026-09-15T00:00:00Z",
        portfolio_due_date="2027-04-30T00:00:00Z",
        state_report_due_date="2027-06-15T00:00:00Z",
        mid_year_date="2027-01-15", grade_level=5, family_name="Fam Init",
        district_code="D-30",
    )
    # The fixture enrollment is grade 5; add a grade-4 enrollment for the flag contrast.
    enr5 = _enr
    student4 = get_success_data(
        api.create_student(family["id"], create_student_payload(full_name="Kid Four"),
                           make_parent_headers(family["id"]))
    )
    enr4 = get_success_data(
        api.create_enrollment(
            student4["id"], create_enrollment_payload(year["id"], 4),
            make_parent_headers(family["id"]),
        )
    )
    assert_enrollment(enr5)
    assert enr5["enrollment_status"] == "REGISTERED"
    assert enr5["compliance_standing"] == "GOOD_STANDING"
    assert enr5["standing_locked"] is False
    assert enr5["testing_required"] is True
    assert enr5["testing_satisfied"] is False
    assert enr5["provisional_days_counted"] == 0
    assert enr5["provisional_minutes_credited"] == 0
    assert enr5["certified_days_counted"] == 0
    assert enr5["certified_minutes_credited"] == 0
    assert enr4["testing_required"] is False, "grade 4 is not in [3, 5, 8, 11]"


def test_create_family_computed_field_input_ignored(api):
    """PRD §3.2: "The family's fee ledger starts clean — `fee_balance_cents` at
    zero, `fee_status` at `CURRENT`, and `oldest_unpaid_charge_at` null."

    Design: Corner/entities/create_family_computed_field_input_ignored
    """
    resp = api.create_family(
        {
            "display_name": "Fam X",
            "district_code": "D-31",
            "fee_balance_cents": 5000,
            "fee_status": "OVERDUE",
        },
        SELF_REGISTER,
    )
    family = validate_success(resp, 201)
    assert_family(family)
    assert family["fee_balance_cents"] == 0
    assert family["fee_status"] == "CURRENT"


def test_get_nonexistent_enrollment_returns_not_found(api):
    """PRD §2.6: "Requests that address nested resources are validated strictly
    left-to-right along the path: the existence of each path identifier is
    confirmed in order, parent segment before child segment, and the request is
    rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does
    not correspond to an existing resource."
    PRD §2.6: "This ordering guarantee is part of the contract and applies
    uniformly to reads, creations, and transitions."

    Design: Corner/entities/get_nonexistent_enrollment_returns_not_found
    """
    resp = api.get_enrollment("12345678-1234-1234-1234-123456789abc", REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_parent_cannot_read_other_family(api):
    """PRD §2.1: "A parent therefore can never read or mutate another family's
    subtree: any such attempt fails with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/entities/parent_cannot_read_other_family
    """
    fam_a = get_success_data(
        api.create_family(create_family_payload(display_name="Fam A", district_code="D-32"),
                          SELF_REGISTER)
    )
    fam_b = get_success_data(
        api.create_family(create_family_payload(display_name="Fam B", district_code="D-33"),
                          SELF_REGISTER)
    )
    resp = api.get_family(fam_b["id"], make_parent_headers(fam_a["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, and any supplied value must be at least 1 and at
    most 100. The `offset` parameter skips a number of items from the front of
    the result set and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_pagination_envelope
    """
    year = get_success_data(api.create_academic_year(create_academic_year_payload(), DIRECTOR))
    for day, title in (("MON", "P1"), ("TUE", "P2"), ("WED", "P3")):
        get_success_data(
            api.create_coop_class(
                year["id"],
                create_coop_class_payload(
                    title=title, meeting_day=day, meeting_start_minutes=540,
                    meeting_end_minutes=600, start_date="2026-09-01",
                    end_date="2026-12-15", capacity=5, fee_base_cents=1000,
                    materials_fee_cents=0,
                ),
                REGISTRAR,
            )
        )
    page1, meta1 = validate_paginated(
        api.list_year_coop_classes(year["id"], REGISTRAR, params={"limit": 2, "offset": 0})
    )
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert len(page1) == 2
    page2, meta2 = validate_paginated(
        api.list_year_coop_classes(year["id"], REGISTRAR, params={"limit": 2, "offset": 2})
    )
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert len(page2) == 1
