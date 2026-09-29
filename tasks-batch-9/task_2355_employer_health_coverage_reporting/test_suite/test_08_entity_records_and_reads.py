"""Entity records: creation echoes, seeded system fields, defaults and read-backs.

Covers the filing season, the controlled group, the group member, the employee,
the monthly headcount ledger, the hours-of-service ledger and the coverage offer.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_controlled_group,
    assert_filing_season,
    assert_group_member,
    assert_hours_record,
    assert_monthly_headcount,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

# Syntactically valid UUIDs that resolve to nothing.
UNKNOWN_EMPLOYEE_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PARENT_EMPLOYEE_ID = "22222222-2222-4222-8222-222222222222"


def _season_with_group(api, headers, group_name="Northwind Group"):
    """Season plus one controlled group — the shortest prelude the entity reads
    and the member-shape checks need."""
    season = fixtures.create_filing_season(api, headers)
    group = fixtures.create_controlled_group(api, season["id"], headers, name=group_name)
    return season, group


# ---------------------------------------------------------------------------
# FilingSeason
# ---------------------------------------------------------------------------
def test_filing_season_created_with_all_declared_fields(api, compliance_officer_headers):
    """PRD §3.1: "Three dates are mandatory at creation: `furnishing_deadline_date`,
    the last date on which a statement can be handed to an employee without
    penalty; `filing_deadline_date`, the last date a submission is on time; and
    `tier2_cutoff_date`, the date at or after which a late statement is priced in
    the highest ordinary tier rather than the middle one."
    PRD §3.1: "A new season starts with `status` of `OPEN`, an
    `open_correction_count` of 0 and a null `locked_at`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/Entities/filing_season_created_with_all_declared_fields
    """
    payload = factories.filing_season_payload(
        tax_year=2026,
        furnishing_deadline_date="2027-03-02",
        filing_deadline_date="2027-03-31",
        tier2_cutoff_date="2027-08-01",
        affordability_pct=0.0902,
        mainland_fpl_annual_cents=1560000,
        penalty_a_annual_cents=296400,
        penalty_b_annual_cents=444000,
        electronic_filing_threshold=10,
    )

    season = validate_success(api.create_filing_season(payload, compliance_officer_headers), 201)

    assert_filing_season(
        season,
        tax_year=2026,
        status="OPEN",
        furnishing_deadline_date="2027-03-02",
        filing_deadline_date="2027-03-31",
        tier2_cutoff_date="2027-08-01",
        mainland_fpl_annual_cents=1560000,
        penalty_a_annual_cents=296400,
        penalty_b_annual_cents=444000,
        electronic_filing_threshold=10,
        open_correction_count=0,
        locked_at=None,
    )
    assert season["affordability_pct"] == pytest.approx(0.0902, abs=1e-6), (
        f"expected affordability_pct 0.0902, got {season['affordability_pct']!r}"
    )


def test_filing_season_defaults_applied_when_optional_constants_omitted(
    api, compliance_officer_headers
):
    """PRD §3.1: "Five further figures are optional and fall back to statutory
    defaults: `affordability_pct` defaults to 0.0902 and must lie strictly between
    0 and 1 with four decimal places; `mainland_fpl_annual_cents` defaults to
    1,560,000 cents; `penalty_a_annual_cents` defaults to 296,400 cents;
    `penalty_b_annual_cents` defaults to 444,000 cents; and
    `electronic_filing_threshold` defaults to 10 returns."
    PRD §3.1: "A new season starts with `status` of `OPEN`, an
    `open_correction_count` of 0 and a null `locked_at`."

    Design: Corner/Entities/filing_season_defaults_applied_when_optional_constants_omitted
    """
    payload = factories.filing_season_payload(
        tax_year=2026,
        furnishing_deadline_date="2027-03-02",
        filing_deadline_date="2027-03-31",
        tier2_cutoff_date="2027-08-01",
    )
    for omitted in (
        "affordability_pct",
        "mainland_fpl_annual_cents",
        "penalty_a_annual_cents",
        "penalty_b_annual_cents",
        "electronic_filing_threshold",
    ):
        assert omitted not in payload, f"{omitted} must be omitted to exercise its default"

    season = validate_success(api.create_filing_season(payload, compliance_officer_headers), 201)

    assert_filing_season(
        season,
        status="OPEN",
        mainland_fpl_annual_cents=1560000,
        penalty_a_annual_cents=296400,
        penalty_b_annual_cents=444000,
        electronic_filing_threshold=10,
        open_correction_count=0,
    )
    assert season["affordability_pct"] == pytest.approx(0.0902, abs=1e-6), (
        f"expected the statutory default affordability_pct 0.0902, "
        f"got {season['affordability_pct']!r}"
    )


# ---------------------------------------------------------------------------
# ControlledGroup
# ---------------------------------------------------------------------------
def test_controlled_group_get_by_id_returns_stored_row(
    api, compliance_officer_headers, preparer_headers
):
    """PRD §3.1: "Inside a season the officer registers a **ControlledGroup**,
    supplying the season it belongs to through `filing_season_id` and a `name` for
    the aggregated group."
    PRD §3.1: "A fresh group has `determination_state` of `NOT_DETERMINED`,
    `version` 1, `seasonal_exception_applied` false, `open_correction_count` 0, and
    null values for `determination_basis`, `ale_reason`, `single_member_id`,
    `determined_at` and `last_determination_user_id`."

    Design: Corner/Entities/controlled_group_get_by_id_returns_stored_row
    """
    season, group = _season_with_group(api, compliance_officer_headers)

    read_back = validate_success(api.get_controlled_group(group["id"], preparer_headers), 200)

    assert_controlled_group(
        read_back,
        filing_season_id=season["id"],
        name="Northwind Group",
        determination_state="NOT_DETERMINED",
        determination_basis=None,
        ale_reason=None,
        single_member_id=None,
        determined_at=None,
        last_determination_user_id=None,
        seasonal_exception_applied=False,
        open_correction_count=0,
    )
    assert read_back["id"] == group["id"], (
        f"single-resource read returned {read_back['id']!r}, expected {group['id']!r}"
    )


def test_controlled_group_system_fields_generated(api, compliance_officer_headers):
    """PRD §2.4: "Every resource in this system is addressed by an `id` that is a
    server-minted UUID with no type prefix."
    PRD §2.4: "Nine resource families additionally carry the full set of
    mutable-resource properties: the filing season, the controlled group, the group
    member, the employee, the furnishing consent, the Form 1095-C, the transmittal,
    the agency error row and the penalty notice each expose `created_at` and
    `updated_at` as ISO 8601 UTC timestamps with three fractional digits, plus a
    `version` integer that starts at 1 and increments by one on every mutation of
    that resource."
    PRD §3.1: "A fresh group has `determination_state` of `NOT_DETERMINED`,
    `version` 1, `seasonal_exception_applied` false, `open_correction_count` 0, and
    null values for `determination_basis`, `ale_reason`, `single_member_id`,
    `determined_at` and `last_determination_user_id`."

    Design: Corner/Entities/controlled_group_system_fields_generated
    """
    season = fixtures.create_filing_season(api, compliance_officer_headers)

    group = validate_success(
        api.create_controlled_group(
            factories.controlled_group_payload(season["id"], name="Northwind Group"),
            compliance_officer_headers,
        ),
        201,
    )

    assert is_valid_uuid(group["id"]), f"id is not a server-minted UUID: {group['id']!r}"
    assert is_iso8601_timestamp(group["created_at"]), f"bad created_at: {group['created_at']!r}"
    assert is_iso8601_timestamp(group["updated_at"]), f"bad updated_at: {group['updated_at']!r}"
    assert_controlled_group(
        group,
        expected_version=1,
        determination_state="NOT_DETERMINED",
        determined_at=None,
        last_determination_user_id=None,
        seasonal_exception_applied=False,
        open_correction_count=0,
    )


# ---------------------------------------------------------------------------
# GroupMember
# ---------------------------------------------------------------------------
def test_group_member_list_filtered_by_controlled_group(api, compliance_officer_headers):
    """PRD §2.5: "Each collection offers a single-resource read and a filtered list
    read, and that filtered list is the reverse-reachability channel for every
    foreign key in the model — including for rows that no create response can ever
    hand back, because they were produced by a cascade."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more` alongside the request identifier and timestamp."

    Design: Corner/Entities/group_member_list_filtered_by_controlled_group
    """
    season = fixtures.create_filing_season(api, compliance_officer_headers)
    group_a = fixtures.create_controlled_group(
        api, season["id"], compliance_officer_headers, name="Group A"
    )
    group_b = fixtures.create_controlled_group(
        api, season["id"], compliance_officer_headers, name="Group B"
    )
    member_a1 = fixtures.create_group_member(
        api,
        group_a["id"],
        "123456789",
        compliance_officer_headers,
        legal_name="A One LLC",
        ownership_pct=60,
        measurement_method="MONTHLY",
    )
    member_a2 = fixtures.create_group_member(
        api,
        group_a["id"],
        "223456789",
        compliance_officer_headers,
        legal_name="A Two LLC",
        ownership_pct=40,
        measurement_method="MONTHLY",
    )
    member_b1 = fixtures.create_group_member(
        api,
        group_b["id"],
        "323456789",
        compliance_officer_headers,
        legal_name="B One LLC",
        ownership_pct=100,
        measurement_method="MONTHLY",
    )

    rows, meta = validate_paginated(
        api.list_group_members(
            compliance_officer_headers, params={"controlled_group_id": group_a["id"]}
        )
    )

    assert meta["total_count"] == 2, (
        f"controlled_group_id filter must scope total_count to Group A's two members, "
        f"got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "two rows fit inside the default page, so has_more is false"
    returned_ids = {row["id"] for row in rows}
    assert returned_ids == {member_a1["id"], member_a2["id"]}, (
        f"expected exactly Group A's members, got {returned_ids}"
    )
    assert member_b1["id"] not in returned_ids, "Group B's member leaked into Group A's listing"


def test_group_member_list_limit_drives_has_more_without_changing_total_count(
    api, compliance_officer_headers
):
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may
    be no smaller than 1 and no larger than 100."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more` alongside the request identifier and timestamp."

    Design: Corner/Entities/group_member_list_filtered_by_controlled_group
    """
    season = fixtures.create_filing_season(api, compliance_officer_headers)
    group_a = fixtures.create_controlled_group(
        api, season["id"], compliance_officer_headers, name="Group A"
    )
    group_b = fixtures.create_controlled_group(
        api, season["id"], compliance_officer_headers, name="Group B"
    )
    member_a1 = fixtures.create_group_member(
        api, group_a["id"], "123456789", compliance_officer_headers, legal_name="A One LLC",
        ownership_pct=60, measurement_method="MONTHLY",
    )
    member_a2 = fixtures.create_group_member(
        api, group_a["id"], "223456789", compliance_officer_headers, legal_name="A Two LLC",
        ownership_pct=40, measurement_method="MONTHLY",
    )
    member_b1 = fixtures.create_group_member(
        api, group_b["id"], "323456789", compliance_officer_headers, legal_name="B One LLC",
        ownership_pct=100, measurement_method="MONTHLY",
    )

    rows, meta = validate_paginated(
        api.list_group_members(
            compliance_officer_headers,
            params={"controlled_group_id": group_a["id"], "limit": 1, "offset": 0},
        )
    )

    assert len(rows) == 1, f"limit=1 must return exactly one row, got {len(rows)}"
    assert meta["total_count"] == 2, (
        f"total_count counts every matching row, not the page, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "one of two matching rows was returned, so has_more is true"
    assert rows[0]["id"] in {member_a1["id"], member_a2["id"]}, (
        f"the single returned row must belong to Group A, got {rows[0]['id']!r}"
    )
    assert rows[0]["id"] != member_b1["id"], "Group B's member leaked into Group A's page"


@pytest.mark.parametrize("ownership_pct", [0, 100.5])
def test_group_member_ownership_pct_out_of_range_rejected(
    api, compliance_officer_headers, ownership_pct
):
    """PRD §2.6: "Request shape: required fields present, correct types, enum values
    in range, declared integers not negative, `ownership_pct` above 0 and at most
    100, `ssn_last4` exactly four digits, `ein` exactly nine digits, month values
    within 1 through 12, `months` arrays non-empty, `plan_start_month` within 0
    through 12, dates well-formed `YYYY-MM-DD`, agency-response `errors` entries
    well-formed, and the intra-body date orderings (a coverage offer's
    `effective_end_date` strictly after its `effective_start_date`; a measurement
    cycle's `measurement_end_date` on or after `measurement_start_date`,
    `admin_period_end_date` on or after `measurement_end_date`,
    `stability_start_date` strictly after `admin_period_end_date`,
    `stability_end_date` on or after `stability_start_date`; a notice's
    `response_due_date` strictly after its `notice_date`) — `ERR_INVALID_REQUEST`
    (400), all POST and PATCH endpoints."

    Design: Corner/Entities/group_member_ownership_pct_out_of_range_rejected
    """
    _season, group = _season_with_group(api, compliance_officer_headers)

    response = api.create_group_member(
        factories.group_member_payload(
            group["id"],
            "123456789",
            legal_name="Out Of Range LLC",
            ownership_pct=ownership_pct,
            measurement_method="MONTHLY",
        ),
        compliance_officer_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.list_group_members(
            compliance_officer_headers, params={"controlled_group_id": group["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a rejected member create must persist nothing, got {meta['total_count']} rows"
    )


def test_group_member_ownership_pct_of_exactly_100_accepted(api, compliance_officer_headers):
    """PRD §3.1: "Each EIN inside the group is registered as a **GroupMember**
    carrying its `controlled_group_id`, a nine-digit `ein` unique within that group,
    the `legal_name` printed on its 1094-C, its common-ownership `ownership_pct`
    above 0 and at most 100, and optionally its `measurement_method`, which defaults
    to `LOOK_BACK` and may instead be `MONTHLY`."
    PRD §3.1: "Members start with `member_status` of `ACTIVE` and every counter at
    zero: `generated_form_count`, `unattached_form_count`, `attached_form_count`,
    `reporting_year_ft_months`, `allocated_exclusion_employees`,
    `allocated_penalty_cents` and `furnishing_penalty_total_cents`, with a null
    `open_transmittal_id`."

    Design: Corner/Entities/group_member_ownership_pct_out_of_range_rejected
    """
    _season, group = _season_with_group(api, compliance_officer_headers)

    member = validate_success(
        api.create_group_member(
            factories.group_member_payload(
                group["id"],
                "323456789",
                legal_name="Exactly Hundred LLC",
                ownership_pct=100,
                measurement_method="MONTHLY",
            ),
            compliance_officer_headers,
        ),
        201,
    )

    assert_group_member(
        member,
        controlled_group_id=group["id"],
        ein="323456789",
        legal_name="Exactly Hundred LLC",
        member_status="ACTIVE",
        generated_form_count=0,
        unattached_form_count=0,
        attached_form_count=0,
        reporting_year_ft_months=0,
        allocated_exclusion_employees=0,
        allocated_penalty_cents=0,
        furnishing_penalty_total_cents=0,
        open_transmittal_id=None,
    )
    assert member["ownership_pct"] == pytest.approx(100, abs=0.01), (
        f"the inclusive upper bound must be stored as given, got {member['ownership_pct']!r}"
    )

    _rows, meta = validate_paginated(
        api.list_group_members(
            compliance_officer_headers, params={"controlled_group_id": group["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"only the in-range member should exist, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# MonthlyHeadcount
# ---------------------------------------------------------------------------
def test_monthly_headcount_member_fte_computed_from_hours(
    api, compliance_officer_headers, benefits_admin_headers
):
    """PRD §3.1: "Each created row freezes its own `member_fte` at creation: the
    month's `full_time_employee_count` plus the month's `part_time_hours_total`
    divided by 120 hours and rounded half up to two decimal places."
    PRD §2.11: "Recording headcounts creates one row per entry of the `months`
    array, all carrying the same counts; if any one of those member-year-month
    triples already exists, the entire call is rejected and nothing is created."

    Design: Corner/Entities/monthly_headcount_member_fte_computed_from_hours
    """
    _season, group = _season_with_group(api, compliance_officer_headers)
    member = fixtures.create_group_member(
        api,
        group["id"],
        "123456789",
        compliance_officer_headers,
        legal_name="Northwind Retail LLC",
        ownership_pct=100,
        measurement_method="MONTHLY",
    )

    rows = validate_success(
        api.create_monthly_headcounts(
            factories.monthly_headcounts_payload(
                member["id"],
                list(range(1, 13)),
                count_year="PRIOR_YEAR",
                full_time_employee_count=40,
                part_time_hours_total=1200,
                total_employee_count=60,
            ),
            benefits_admin_headers,
        ),
        201,
    )

    assert len(rows) == 12, f"one row per month of the batch, got {len(rows)}"
    assert sorted(row["month"] for row in rows) == list(range(1, 13)), (
        f"expected months 1..12, got {sorted(row['month'] for row in rows)}"
    )
    for row in rows:
        assert_monthly_headcount(
            row,
            group_member_id=member["id"],
            full_time_employee_count=40,
            part_time_hours_total=1200,
            total_employee_count=60,
        )
        assert row["member_fte"] == pytest.approx(50.00, abs=0.01), (
            f"month {row['month']}: expected member_fte 50.00 "
            f"(40 + 1200/120), got {row['member_fte']!r}"
        )


def test_monthly_headcount_member_fte_is_stored_not_recomputed_per_read(
    api, compliance_officer_headers, benefits_admin_headers
):
    """PRD §3.1: "Each created row freezes its own `member_fte` at creation: the
    month's `full_time_employee_count` plus the month's `part_time_hours_total`
    divided by 120 hours and rounded half up to two decimal places."
    PRD §3.1: "None of these rows is ever updated afterwards; they carry no
    `version`."

    Design: Corner/Entities/monthly_headcount_member_fte_computed_from_hours
    """
    _season, group = _season_with_group(api, compliance_officer_headers)
    member = fixtures.create_group_member(
        api,
        group["id"],
        "123456789",
        compliance_officer_headers,
        legal_name="Northwind Retail LLC",
        ownership_pct=100,
        measurement_method="MONTHLY",
    )
    rows = fixtures.record_headcounts(
        api,
        member["id"],
        list(range(1, 13)),
        compliance_officer_headers,
        count_year="PRIOR_YEAR",
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    january = next(row for row in rows if row["month"] == 1)

    read_back = validate_success(
        api.get_monthly_headcount(january["id"], benefits_admin_headers), 200
    )

    assert_monthly_headcount(read_back, group_member_id=member["id"], month=1)
    assert read_back["member_fte"] == pytest.approx(50.00, abs=0.01), (
        f"the frozen member_fte must survive the read, got {read_back['member_fte']!r}"
    )


def test_monthly_headcount_records_count_year_and_defaults_seasonal_excess_to_zero(
    api, compliance_officer_headers
):
    """PRD §3.1: "Each batch names a `count_year` — `PRIOR_YEAR` rows describe the
    calendar year one before the season's `tax_year` and are the only input to the
    applicable-large-employer determination, while `REPORTING_YEAR` rows describe
    the reporting year itself and feed the 1094-C Part III counts and the penalty
    arithmetic."
    PRD §3.1: "A batch carries the `months` it covers plus the counts shared by
    those months: `full_time_employee_count`, the employees averaging at least 130
    hours of service in the month; `part_time_hours_total`, the aggregate hours of
    everyone else, already capped at 120 hours per employee before submission;
    `total_employee_count`, everyone employed on any day of the month, which is what
    Part III column (b) prints; and optionally `seasonal_excess_count`, defaulting to
    0, recording how many of the counted employees were seasonal workers."

    Design: Corner/Entities/monthly_headcount_member_fte_computed_from_hours
    """
    _season, group = _season_with_group(api, compliance_officer_headers)
    member = fixtures.create_group_member(
        api,
        group["id"],
        "123456789",
        compliance_officer_headers,
        legal_name="Northwind Retail LLC",
        ownership_pct=100,
        measurement_method="MONTHLY",
    )
    payload = factories.monthly_headcounts_payload(
        member["id"],
        list(range(1, 13)),
        count_year="PRIOR_YEAR",
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    assert "seasonal_excess_count" not in payload, "the default is only exercised when omitted"

    rows = validate_success(
        api.create_monthly_headcounts(payload, compliance_officer_headers), 201
    )

    for row in rows:
        assert_monthly_headcount(row, count_year="PRIOR_YEAR", seasonal_excess_count=0)


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------
def test_employee_retrieval_unknown_id_not_found(api, benefits_admin_headers):
    """PRD §2.5: "Path identifiers are validated strictly left to right, and the
    first identifier that does not resolve determines the 404 that comes back."
    PRD §2.5: "Each family has its own not-found code —
    `ERR_FILING_SEASON_NOT_FOUND`, `ERR_CONTROLLED_GROUP_NOT_FOUND`,
    `ERR_GROUP_MEMBER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_CONSENT_NOT_FOUND`, `ERR_FORM_NOT_FOUND`, `ERR_TRANSMITTAL_NOT_FOUND`,
    `ERR_TRANSMITTAL_ERROR_NOT_FOUND` and `ERR_PENALTY_NOTICE_NOT_FOUND` — while
    the single-row reads of the seven append-only ledger families answer with
    `ERR_RECORD_NOT_FOUND`."

    Design: Corner/Entities/employee_retrieval_unknown_id_not_found
    """
    response = api.get_employee(UNKNOWN_EMPLOYEE_ID, benefits_admin_headers)

    validate_error(response, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND, 404)


def test_employee_create_missing_hire_date_invalid_request(api, benefits_admin_headers):
    """PRD §3.3: "A `BenefitsAdmin` hires an **Employee** into a member by supplying
    `group_member_id`, `full_name`, a four-digit `ssn_last4`, a `hire_date`, an
    `employment_type` of `FULL_TIME`, `PART_TIME`, `VARIABLE_HOUR` or `SEASONAL`,
    and the `is_hourly` flag that decides which wage figure the rate-of-pay safe
    harbor reads."
    PRD §2.6: "Request shape: required fields present, correct types, enum values in
    range, declared integers not negative, `ownership_pct` above 0 and at most 100,
    `ssn_last4` exactly four digits, `ein` exactly nine digits, month values within
    1 through 12, `months` arrays non-empty, `plan_start_month` within 0 through 12,
    dates well-formed `YYYY-MM-DD`, agency-response `errors` entries well-formed,
    and the intra-body date orderings (a coverage offer's `effective_end_date`
    strictly after its `effective_start_date`; a measurement cycle's
    `measurement_end_date` on or after `measurement_start_date`,
    `admin_period_end_date` on or after `measurement_end_date`,
    `stability_start_date` strictly after `admin_period_end_date`,
    `stability_end_date` on or after `stability_start_date`; a notice's
    `response_due_date` strictly after its `notice_date`) — `ERR_INVALID_REQUEST`
    (400), all POST and PATCH endpoints."

    Design: Corner/Entities/employee_create_missing_hire_date_invalid_request
    """
    ctx = fixtures.determined_ale_group(api)
    member_id = ctx["member"]["id"]

    response = api.create_employee(
        {
            "group_member_id": member_id,
            "full_name": "Lena Ortiz",
            "ssn_last4": "4321",
            "employment_type": "FULL_TIME",
            "is_hourly": False,
            "monthly_salary_cents": 400000,
        },
        benefits_admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api.list_employees(benefits_admin_headers, params={"group_member_id": member_id})
    )
    assert meta["total_count"] == 0, (
        f"a rejected hire must create no Employee row, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# HoursRecord — an append-only ledger
# ---------------------------------------------------------------------------
def test_hours_record_counted_hours_frozen_at_creation(api, benefits_admin_headers):
    """PRD §3.3: "`counted_hours` is `hours_of_service` plus `paid_leave_hours` —
    special unpaid leave is *never* added to the numerator."
    PRD §3.3: "`excluded_from_denominator` is true exactly when
    `special_unpaid_leave_hours` is at least 130, and a month so marked drops out of
    the look-back average altogether, from numerator and denominator alike."

    Design: Corner/Entities/hours_record_immutable_ledger_has_no_update_endpoint
    """
    ctx = fixtures.determined_ale_group_with_employee(
        api,
        employee_overrides={"full_name": "Lena Ortiz", "employment_type": "VARIABLE_HOUR"},
    )

    rows = validate_success(
        api.create_hours_records(
            factories.hours_records_payload(
                ctx["employee"]["id"],
                2026,
                [1],
                hours_of_service=120,
                paid_leave_hours=10,
            ),
            benefits_admin_headers,
        ),
        201,
    )

    assert len(rows) == 1, f"one row per entry of the months array, got {len(rows)}"
    assert_hours_record(
        rows[0],
        employee_id=ctx["employee"]["id"],
        measurement_year=2026,
        month=1,
        hours_of_service=120,
        paid_leave_hours=10,
        counted_hours=130,
        excluded_from_denominator=False,
    )


def test_hours_record_read_carries_no_version_or_updated_at(api, benefits_admin_headers):
    """PRD §2.4: "The remaining seven families are append-only ledger rows and carry
    only `id` and `created_at` — monthly headcounts, measurement cycles, hours
    records, employment events, coverage offers, monthly coverage lines and penalty
    evidence have **no** `updated_at` and **no** `version` field at all."

    Design: Corner/Entities/hours_record_immutable_ledger_has_no_update_endpoint
    """
    ctx = fixtures.determined_ale_group_with_employee(
        api,
        employee_overrides={"full_name": "Lena Ortiz", "employment_type": "VARIABLE_HOUR"},
    )
    created = fixtures.record_hours(
        api,
        ctx["employee"]["id"],
        2026,
        [1],
        benefits_admin_headers,
        hours_of_service=120,
        paid_leave_hours=10,
    )

    read_back = validate_success(
        api.get_hours_record(created[0]["id"], benefits_admin_headers), 200
    )

    assert_hours_record(read_back, employee_id=ctx["employee"]["id"], month=1)
    assert "version" not in read_back, "an append-only hours row must expose no version"
    assert "updated_at" not in read_back, "an append-only hours row must expose no updated_at"


def test_hours_record_duplicate_month_refused_rather_than_overwritten(
    api, benefits_admin_headers
):
    """PRD §2.6: "No hours row already exists for any requested employee-year-month
    triple — `ERR_DUPLICATE_HOURS_MONTH` (409), on hours-record creation."
    PRD §2.11: "Recording hours of service behaves identically over its own `months`
    array and its employee-year-month triples."

    Design: Corner/Entities/hours_record_immutable_ledger_has_no_update_endpoint
    """
    ctx = fixtures.determined_ale_group_with_employee(
        api,
        employee_overrides={"full_name": "Lena Ortiz", "employment_type": "VARIABLE_HOUR"},
    )
    employee_id = ctx["employee"]["id"]
    created = fixtures.record_hours(
        api, employee_id, 2026, [1], benefits_admin_headers,
        hours_of_service=120, paid_leave_hours=10,
    )
    original_id = created[0]["id"]

    response = api.create_hours_records(
        factories.hours_records_payload(
            employee_id, 2026, [1], hours_of_service=999, paid_leave_hours=0
        ),
        benefits_admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_HOURS_MONTH, 409)

    read_back = validate_success(api.get_hours_record(original_id, benefits_admin_headers), 200)
    assert_hours_record(
        read_back, hours_of_service=120, paid_leave_hours=10, counted_hours=130
    )
    _rows, meta = validate_paginated(
        api.list_hours_records(
            benefits_admin_headers, params={"employee_id": employee_id, "measurement_year": 2026}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused batch must append nothing, got {meta['total_count']} hours rows"
    )


# ---------------------------------------------------------------------------
# CoverageOffer
# ---------------------------------------------------------------------------
def test_coverage_offer_create_unknown_parent_employee_not_found(api, benefits_admin_headers):
    """PRD §2.6: "Every foreign key in the body exists — the matching not-found code
    (404), every POST carrying a foreign key."
    PRD §2.5: "Foreign keys carried in a request body are resolved the same way and
    answer with the not-found code of the referenced family: `filing_season_id`,
    `controlled_group_id`, `group_member_id`, `single_member_id`, `employee_id`,
    `to_group_member_id`, `form_1095c_id`, `penalty_notice_id` and each entry of
    `form_ids`."

    Design: Corner/Entities/coverage_offer_create_unknown_parent_employee_not_found
    """
    ctx = fixtures.determined_ale_group_with_employee(
        api, employee_overrides={"full_name": "Lena Ortiz"}
    )

    response = api.create_coverage_offer(
        factories.coverage_offer_payload(
            UNKNOWN_PARENT_EMPLOYEE_ID,
            offer_kind="MEC_MV_SELF_ONLY",
            effective_start_date="2026-01-01",
            effective_end_date="2027-01-01",
            minimum_value=True,
            lowest_cost_self_only_cents=17800,
        ),
        benefits_admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_coverage_offers(
            benefits_admin_headers, params={"employee_id": ctx["employee"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the real employee must be untouched by the failed offer, "
        f"got {meta['total_count']} offers"
    )
