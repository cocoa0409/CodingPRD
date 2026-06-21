"""Entity creation, defaults, immutability, type constraints, parent FK (queue B)."""
from test_helpers import (
    validate_success,
    validate_error,
    assert_household,
    assert_health_plan,
    create_household_payload,
    create_member_payload,
    create_health_plan_payload,
    make_applicant_headers,
    TEST_USERS,
)


def test_create_household_returns_201_with_system_fields(api):
    """PRD §3.1: "On creation the server stamps `applicant_user_id` from the caller's
    `X-User-ID`, and initializes the three derived income fields — `household_magi_cents`,
    `fpl_percent`, and `countable_size` — to 0."
    PRD §2.4: "`version` (integer): a system-managed counter that starts at 1 and
    increments by exactly 1 on every mutation of the resource."

    Design: Corner/entities/create_household_returns_201_with_system_fields
    """
    res = api.create_household(create_household_payload(coverage_year=2026, rating_area="RA01"),
                               make_applicant_headers("c-1"))
    hh = validate_success(res, 201)
    assert_household(hh)
    assert hh["version"] == 1
    assert hh["household_magi_cents"] == 0
    assert hh["countable_size"] == 0
    assert hh["applicant_user_id"] == "c-1"


def test_get_household_not_found_returns_404(api):
    """PRD §2.6: "the first identifier in the path that does not resolve to an existing
    resource produces `ERR_NOT_FOUND` (HTTP 404) before any deeper lookup or business rule
    is evaluated."

    Design: Corner/entities/get_household_not_found_returns_404
    """
    res = api.get_household("00000000-0000-4000-8000-000000000000", TEST_USERS["admin_headers"])
    validate_error(res, "ERR_NOT_FOUND")
    assert res.status_code == 404


def test_create_household_missing_required_field_returns_422(api):
    """PRD §3.8: "Schema validation of the body follows — required fields present, enums valid, and integers non-negative where constrained (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_household_missing_required_field_returns_422
    """
    res = api.create_household({"coverage_year": 2026}, make_applicant_headers("c-3"))
    validate_error(res, "ERR_INVALID_REQUEST")
    assert res.status_code == 422


def test_member_defaults_applies_for_coverage_and_income(api):
    """PRD §3.1: "annual_income_cents` — the member's projected annual MAGI income, which must be at least 0 and defaults to 0 if omitted — and `applies_for_coverage`, a boolean (defaulting to true) declaring whether the member is actually seeking coverage."
    PRD §3.1: "countable_size` is the count of members whose `applies_for_coverage` is true — note that a `DEPENDENT_NONFILER` excluded from the income sum still adds to `countable_size` if it is applying for coverage, because `countable_size` is the size used as the denominator in the Federal Poverty Level calculation."

    Design: Corner/entities/member_default_applies_for_coverage_true
    """
    hh = validate_success(
        api.create_household(create_household_payload(), make_applicant_headers("c-4")), 201)
    res = api.create_member(hh["id"],
                            {"full_name": "Def Ault", "relationship": "PRIMARY",
                             "tax_filing_status": "FILER"},
                            make_applicant_headers("c-4"))
    mem = validate_success(res, 201)
    assert mem["applies_for_coverage"] is True
    assert mem["annual_income_cents"] == 0
    got = validate_success(api.get_household(hh["id"], make_applicant_headers("c-4")), 200)
    assert got["countable_size"] == 1


def test_health_plan_immutable_no_version_field_csr_silver(api):
    """PRD §2.4: "A `HealthPlan` carries only `id` (a server-minted UUID) and `created_at`; it
    has no `updated_at` and no `version`, because catalog plans are immutable once registered."
    PRD §3.4: "the server computes `csr_eligible`, which is true exactly when the plan's
    `metal_tier` is `SILVER`, because cost-sharing reductions attach only to Silver plans."

    Design: Corner/entities/health_plan_immutable_no_version_field
    """
    res = api.create_health_plan(
        create_health_plan_payload(metal_tier="SILVER", gross_premium_cents=50_000,
                                   is_slcsp_benchmark=True),
        TEST_USERS["admin_headers"])
    plan = validate_success(res, 201)
    assert_health_plan(plan)
    assert plan["csr_eligible"] is True


def test_health_plan_csr_eligible_false_for_bronze(api):
    """PRD §3.4: "the server computes `csr_eligible`, which is true exactly when the plan's
    `metal_tier` is `SILVER`, because cost-sharing reductions attach only to Silver plans."

    Design: Corner/entities/health_plan_csr_eligible_false_for_bronze
    """
    res = api.create_health_plan(
        create_health_plan_payload(metal_tier="BRONZE", gross_premium_cents=30_000,
                                   is_slcsp_benchmark=False),
        TEST_USERS["admin_headers"])
    plan = validate_success(res, 201)
    assert plan["csr_eligible"] is False


def test_member_invalid_relationship_enum_returns_422(api):
    """PRD §3.1: "The `relationship` is one of `PRIMARY`, `SPOUSE`, or `DEPENDENT`, and a household may contain exactly one `PRIMARY` member — an attempt to add a second `PRIMARY` is rejected with `ERR_DUPLICATE_PRIMARY` (HTTP 409)."
    PRD §3.8: "Schema validation of the body follows — required fields present, enums
    valid, and integers non-negative where constrained (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/member_invalid_relationship_enum_returns_422
    """
    hh = validate_success(
        api.create_household(create_household_payload(), make_applicant_headers("c-7")), 201)
    res = api.create_member(hh["id"],
                            {"full_name": "Bad Enum", "relationship": "COUSIN",
                             "tax_filing_status": "FILER", "annual_income_cents": 100},
                            make_applicant_headers("c-7"))
    validate_error(res, "ERR_INVALID_REQUEST")
    assert res.status_code == 422


def test_application_requires_existing_household_parent(api):
    """PRD §2.6: "When a body field such as `household_id`, `application_id`, `plan_id`, or
    `enrollment_id` points to a resource that does not exist, the request is rejected with
    `ERR_REFERENCED_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/application_requires_existing_household_parent
    """
    res = api.create_application(
        {"household_id": "00000000-0000-4000-8000-000000000abc", "enrollment_window": "OEP"},
        make_applicant_headers("c-8"))
    validate_error(res, "ERR_REFERENCED_NOT_FOUND")
    assert res.status_code == 404
