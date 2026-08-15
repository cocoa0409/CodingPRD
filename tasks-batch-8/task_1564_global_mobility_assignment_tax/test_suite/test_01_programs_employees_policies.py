"""Programs, employees, and allowance policies: defaults, request shape,
half-open window semantics, and list pagination (PRD §2.3, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_policy,
    assert_program,
    create_employee_payload,
    create_policy_payload,
    create_program_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_program_creation_applies_defaults(api, admin_headers):
    """PRD §3.1: "`cost_overrun_threshold_pct` defaults to 110 and controls when an
    assignment's cost posture flips to overrun (§3.6); `max_assignment_duration_days`
    defaults to 1825 and caps the length of any assignment in the program;
    `per_diem_annual_day_cap` defaults to 365 and bounds cumulative per-diem days per
    assignment per tax year."
    PRD §3.1: "A program is created `ACTIVE` and stays `ACTIVE` — v1 exposes no
    archival transition."
    PRD §3.1: "Its `total_posted_chargeback_cents` starts at zero and thereafter
    tracks the signed sum of `amount_cents` over all chargeback entries in `POSTED`
    status belonging to assignments of the program."

    Design: Corner/entities/program_creation_applies_defaults
    """
    res = api.create_program(
        create_program_payload(name="Defaults Program", home_country_code="US"),
        admin_headers,
    )
    program = validate_success(res, 201)
    assert_program(program)
    assert program["cost_overrun_threshold_pct"] == 110
    assert program["max_assignment_duration_days"] == 1825
    assert program["per_diem_annual_day_cap"] == 365
    assert program["status"] == "ACTIVE"
    assert program["total_posted_chargeback_cents"] == 0
    assert isinstance(program["version"], int)


def test_employee_create_missing_required_field_returns_invalid_request(api, admin_headers):
    """PRD §2.10: "Required fields must be present; enums must lie in their declared
    sets; integers must satisfy their field constraints (percentages between 0 and 100
    inclusive, amounts non-negative, `period_month` between 1 and 12 inclusive);
    `effective_to` must be strictly after `effective_from`; `valid_until` strictly
    after `valid_from`; `planned_end_date` on or after `start_date` — else
    `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "`family_size`, the tax household size, defaults to 1, must be at least
    1, and sets the personal exemption used by the hypothetical tax schedule at 200000
    cents per family member"

    Design: Corner/entities/employee_create_missing_required_field_returns_invalid_request
    """
    missing_ref = create_employee_payload()
    del missing_ref["employee_ref"]
    res = api.create_employee(missing_ref, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    with_default = create_employee_payload(employee_ref="E9", full_name="Has Default")
    del with_default["family_size"]
    employee = validate_success(api.create_employee(with_default, admin_headers), 201)
    assert employee["family_size"] == 1, "family_size must default to 1"


def test_policy_create_inverted_window_rejected(api, admin_headers):
    """PRD §3.1: "An `effective_to` that is not strictly after `effective_from` is
    rejected as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/policy_create_inverted_window_rejected
    """
    payload = create_policy_payload(
        policy_name="Empty Window",
        effective_from="2026-06-01",
        effective_to="2026-06-01",
    )
    res = api.create_policy(payload, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_policy_window_adjacency_allowed(api, admin_headers):
    """PRD §3.1: "Because every policy is `ACTIVE` in v1, the half-open windows of any
    two policies for the same `host_country_code` must not intersect: a genuine overlap
    is rejected with `ERR_POLICY_WINDOW_OVERLAP`, while mere adjacency — one window's
    `effective_from` equal to another's `effective_to` — is allowed."

    Design: Difficulty/resource_temporal_overlap/policy_window_half_open_adjacency_allowed
    """
    policy_a = validate_success(api.create_policy(create_policy_payload(
        policy_name="JP FY26", host_country_code="JP",
        effective_from="2026-01-01", effective_to="2026-12-31",
    ), admin_headers), 201)

    res = api.create_policy(create_policy_payload(
        policy_name="JP FY27", host_country_code="JP",
        effective_from="2026-12-31", effective_to="2027-12-31",
        per_diem_daily_cents=7800, housing_monthly_cap_cents=310000, cola_pct=16,
    ), admin_headers)
    policy_b = validate_success(res, 201)
    assert_policy(policy_b)
    assert policy_b["effective_from"] == policy_a["effective_to"], (
        "adjacent policy must start exactly where the predecessor ends"
    )


def test_policy_window_genuine_overlap_rejected(api, admin_headers):
    """PRD §3.1: "Because every policy is `ACTIVE` in v1, the half-open windows of any
    two policies for the same `host_country_code` must not intersect: a genuine overlap
    is rejected with `ERR_POLICY_WINDOW_OVERLAP`, while mere adjacency — one window's
    `effective_from` equal to another's `effective_to` — is allowed."

    Design: Difficulty/resource_temporal_overlap/policy_window_half_open_adjacency_allowed
    """
    validate_success(api.create_policy(create_policy_payload(
        policy_name="JP FY26", host_country_code="JP",
        effective_from="2026-01-01", effective_to="2026-12-31",
    ), admin_headers), 201)

    res = api.create_policy(create_policy_payload(
        policy_name="JP Overlap", host_country_code="JP",
        effective_from="2026-06-01", effective_to="2027-06-01",
        per_diem_daily_cents=7000, housing_monthly_cap_cents=290000,
    ), admin_headers)
    validate_error(res, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP)


def test_policy_list_pagination_interaction(api, admin_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted
    by creation timestamp in ascending order — stable creation order."

    Design: Corner/endpoints/policy_list_pagination_interaction
    """
    created = []
    for name, country, rate, cap in (
        ("JP", "JP", 7500, 300000),
        ("SG", "SG", 6333, 250000),
        ("DE", "DE", 5000, 200000),
    ):
        created.append(validate_success(api.create_policy(create_policy_payload(
            policy_name=name, host_country_code=country,
            effective_from="2026-01-01", effective_to="2027-01-01",
            per_diem_daily_cents=rate, housing_monthly_cap_cents=cap, cola_pct=0,
        ), admin_headers), 201))

    page1, meta1 = validate_paginated(api.list_policies(admin_headers, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert [row["id"] for row in page1] == [created[0]["id"], created[1]["id"]], (
        "rows must be in stable creation order"
    )

    page2, meta2 = validate_paginated(api.list_policies(admin_headers, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["id"] == created[2]["id"]

    _, meta_default = validate_paginated(api.list_policies(admin_headers))
    assert meta_default["limit"] == 10, "default limit is 10"
    assert meta_default["offset"] == 0, "default offset is 0"
