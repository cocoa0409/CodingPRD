"""Registration, case opening, computed defaults, and the consultant capacity boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_case,
    assert_consultant,
    assert_family,
    create_case_payload,
    create_consultant,
    create_consultant_payload,
    create_plan_for_case,
    get_consultant,
    make_parent_headers,
    open_case,
    register_family,
    register_family_payload,
    review_case_questionnaire,
    review_log_entry,
    setup_case_in_active_support,
    submit_log_for_case,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["practice_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_consultant_creation_computed_defaults(api):
    """PRD §3.1: "A `PracticeAdmin` onboards each certified sleep consultant with a
    display `full_name`, a `certification_no`, and a `max_active_cases` cap of at least 1.
    A new consultant's `active_case_count` is zero".
    PRD §2.5: "At startup the clock reads exactly 2026-08-01T00:00:00Z, and it never
    silently falls back to the host's real time."

    Design: Corner/entities/consultant_creation_computed_defaults
    """
    res = api.create_consultant(
        create_consultant_payload(
            full_name="Dana Sleep", certification_no="CERT-200", max_active_cases=3
        ),
        ADMIN,
    )
    consultant = validate_success(res, 201)
    assert_consultant(consultant)
    assert consultant["active_case_count"] == 0, (
        f"A new consultant's active_case_count must be zero, got {consultant['active_case_count']}"
    )
    assert isinstance(consultant["version"], int)
    # created_at/updated_at are stamped from the logical clock (2026-08-01T00:00:00Z
    # at startup, rendered with fractional digits) and match on a fresh resource.
    assert consultant["created_at"].startswith("2026-08-01T00:00:00")
    assert consultant["updated_at"].startswith("2026-08-01T00:00:00")
    assert consultant["created_at"] == consultant["updated_at"]


def test_family_registration_defaults(api):
    """PRD §3.1: "A freshly registered family has a `credit_balance_cents` of zero
    and `is_repeat_client` false; the repeat flag later becomes true as soon as the
    family has at least one case in `COMPLETED` status, and it too is recomputed on
    every read and at case completion."

    Design: Corner/entities/family_registration_defaults
    """
    res = api.register_family(
        register_family_payload(full_name="Fam Z", email="z@x.com"), ANON
    )
    family = validate_success(res, 201)
    assert_family(family)
    assert family["credit_balance_cents"] == 0
    assert family["is_repeat_client"] is False


def test_case_computed_age_fields(api):
    """PRD §3.1: "`child_age_months` is the number of whole months between
    `child_birth_date` and the logical clock date: twelve times the difference in
    years plus the difference in months, minus one when the clock's day-of-month is
    earlier than the birth day-of-month, and never below zero. `age_band` is then
    `NEWBORN` at three months or younger, `INFANT` from four through eleven months,
    `TODDLER` from twelve through thirty-five months, and `PRESCHOOL` at thirty-six
    months or older; band boundaries are inclusive at the lower edge, so a child
    exactly four months old is `INFANT`."
    PRD §3.1: "The new case starts in `INTAKE` with `completed_at` null."

    Design: Corner/entities/case_computed_age_fields
    """
    consultant = create_consultant(max_active_cases=3, certification_no="CERT-201")
    family = register_family()
    res = api.create_case(
        create_case_payload(family["id"], consultant["id"], child_birth_date="2026-05-01"),
        make_parent_headers(family["id"]),
    )
    case = validate_success(res, 201)
    assert_case(case)
    # 2026-05-01 -> default clock 2026-08-01: (0*12) + (8-5) = 3 months, day 1 >= day 1.
    assert case["child_age_months"] == 3
    assert case["age_band"] == "NEWBORN"
    assert case["status"] == "INTAKE"
    assert case["completed_at"] is None


def test_case_create_missing_required_field_rejected(api):
    """PRD §2.8: "Required fields are present, enum members are valid, and integer
    and range constraints hold — `max_active_cases` at least 1, course `capacity` at
    least 1, all counts at least 0, `adjustment_points` between −30 and +30 inclusive,
    session duration between 15 and 120 minutes inclusive with `scheduled_end` after
    `scheduled_start`, `log_date` not in the future, and `apply_credit_cents` within
    both the family balance and the credit cap; failures yield `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "With both sides registered, a `Parent` opens a case for their own
    family (a `PracticeAdmin` may also open one), supplying `family_id`,
    `consultant_id`, the child's `child_birth_date` as an ISO date, the
    `delivery_mode` — `ONE_ON_ONE` or `GROUP_COURSE`, a choice that later gates
    package purchases versus course enrollment — and the
    `guarantee_goal_night_wakings`, the maximum acceptable number of night wakings
    per night under the guarantee, zero or more."

    Design: Corner/validations/case_create_missing_required_field_rejected
    """
    consultant = create_consultant(max_active_cases=3, certification_no="CERT-224")
    family = register_family()
    payload = create_case_payload(family["id"], consultant["id"])
    del payload["guarantee_goal_night_wakings"]
    res = api.create_case(payload, make_parent_headers(family["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    # No case was created: the family's case list stays empty.
    data, _ = validate_paginated(api.list_cases(make_parent_headers(family["id"])))
    assert len(data) == 0


def test_case_create_invalid_enum_rejected(api):
    """PRD §2.8: "Required fields are present, enum members are valid, and integer
    and range constraints hold — `max_active_cases` at least 1, course `capacity` at
    least 1, all counts at least 0, `adjustment_points` between −30 and +30 inclusive,
    session duration between 15 and 120 minutes inclusive with `scheduled_end` after
    `scheduled_start`, `log_date` not in the future, and `apply_credit_cents` within
    both the family balance and the credit cap; failures yield `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "the `delivery_mode` — `ONE_ON_ONE` or `GROUP_COURSE`, a choice that
    later gates package purchases versus course enrollment".

    Design: Corner/validations/case_create_invalid_enum_rejected
    """
    consultant = create_consultant(max_active_cases=3, certification_no="CERT-225")
    family = register_family()
    payload = create_case_payload(
        family["id"], consultant["id"], delivery_mode="HYBRID"
    )
    res = api.create_case(payload, make_parent_headers(family["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_consultant_capacity_boundary_rejects_at_max(api):
    """PRD §3.1: "Before the case is accepted, the assigned consultant's capacity is
    checked: if the consultant's `active_case_count` has already reached
    `max_active_cases`, the request is rejected with `ERR_CONSULTANT_AT_CAPACITY`;
    one below the cap still accepts, while exactly at the cap rejects."

    Design: Difficulty/boundary_precision_check/consultant_capacity_boundary
    """
    consultant = create_consultant(max_active_cases=1, certification_no="CERT-111")
    family = register_family(full_name="Fam J", email="j@x.com")
    # count == 0 == max - 1: the first case is accepted.
    case1 = open_case(family, consultant)
    q = submit_questionnaire(case1, family)
    review_case_questionnaire(q["id"], consultant)
    create_plan_for_case(case1["id"], consultant)  # case1 -> ACTIVE_SUPPORT
    fresh = get_consultant(consultant["id"])
    assert fresh["active_case_count"] == 1, (
        f"expected active_case_count 1 with one ACTIVE_SUPPORT case, got {fresh['active_case_count']}"
    )
    # count == 1 == max: the second case is rejected.
    res = api.create_case(
        create_case_payload(
            family["id"],
            consultant["id"],
            child_birth_date="2026-06-01",
            delivery_mode="GROUP_COURSE",
            guarantee_goal_night_wakings=1,
        ),
        make_parent_headers(family["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CONSULTANT_AT_CAPACITY.value, expected_status=409)


def test_consultant_capacity_excludes_needs_attention(api):
    """PRD §3.1: "A new consultant's `active_case_count` is zero; thereafter it is
    defined as the number of that consultant's cases currently in `ACTIVE_SUPPORT`
    status — cases in `NEEDS_ATTENTION` and every other status are excluded — and it
    is recomputed on every read and on every case status mutation, which is why the
    workflows below repeatedly describe it moving up or down by one."
    PRD §3.1: "if the consultant's `active_case_count` has already reached
    `max_active_cases`, the request is rejected with `ERR_CONSULTANT_AT_CAPACITY`;
    one below the cap still accepts, while exactly at the cap rejects."

    Design: Difficulty/boundary_precision_check/consultant_capacity_boundary
    """
    bundle = setup_case_in_active_support(max_active_cases=1)
    consultant, family, case = bundle["consultant"], bundle["family"], bundle["case"]
    assert get_consultant(consultant["id"])["active_case_count"] == 1
    # A REGRESSION review moves the case to NEEDS_ATTENTION, which does not count.
    log = submit_log_for_case(case["id"], family, "2026-08-01", night_wake_count=6)
    review_log_entry(log["id"], consultant, outcome="REGRESSION")
    assert get_consultant(consultant["id"])["active_case_count"] == 0
    # count == 0 == max - 1: a new case for the same consultant is accepted again.
    case2 = open_case(family, consultant, child_birth_date="2026-06-01")
    assert case2["status"] == "INTAKE"
