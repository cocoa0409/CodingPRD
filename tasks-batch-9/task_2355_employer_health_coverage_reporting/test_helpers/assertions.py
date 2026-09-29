"""Domain assertions.

Two shape families exist. Nine mutable families carry ``id``, ``created_at``,
``updated_at`` and ``version``; seven append-only ledger families carry only
``id`` and ``created_at`` and must NOT expose ``updated_at`` or ``version``
(PRD §2.4).
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Shape primitives
# ---------------------------------------------------------------------------
def assert_mutable_shape(row, expected_version=None):
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at: {row['created_at']!r}"
    assert is_iso8601_timestamp(row["updated_at"]), f"bad updated_at: {row['updated_at']!r}"
    assert isinstance(row["version"], int) and row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_append_only_shape(row):
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at: {row['created_at']!r}"
    assert "updated_at" not in row, "append-only rows must not carry updated_at"
    assert "version" not in row, "append-only rows must not carry version"


def assert_fields(row, **expected):
    for field, value in expected.items():
        assert field in row, f"missing field {field!r}"
        assert row[field] == value, f"{field}: expected {value!r}, got {row[field]!r}"


# ---------------------------------------------------------------------------
# Mutable families
# ---------------------------------------------------------------------------
def assert_filing_season(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "tax_year",
        "status",
        "furnishing_deadline_date",
        "filing_deadline_date",
        "tier2_cutoff_date",
        "affordability_pct",
        "mainland_fpl_annual_cents",
        "penalty_a_annual_cents",
        "penalty_b_annual_cents",
        "electronic_filing_threshold",
        "open_correction_count",
        "locked_at",
    ):
        assert field in row, f"filing season missing {field!r}"
    assert_fields(row, **expected)


def assert_controlled_group(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "filing_season_id",
        "name",
        "determination_state",
        "monthly_group_fte",
        "seasonal_exception_applied",
        "open_correction_count",
    ):
        assert field in row, f"controlled group missing {field!r}"
    assert_fields(row, **expected)


def assert_group_member(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "controlled_group_id",
        "ein",
        "legal_name",
        "ownership_pct",
        "measurement_method",
        "member_status",
        "generated_form_count",
        "unattached_form_count",
        "attached_form_count",
        "reporting_year_ft_months",
        "allocated_exclusion_employees",
        "allocated_penalty_cents",
        "furnishing_penalty_total_cents",
    ):
        assert field in row, f"group member missing {field!r}"
    assert_fields(row, **expected)


def assert_employee(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "group_member_id",
        "full_name",
        "ssn_last4",
        "hire_date",
        "employment_type",
        "employment_status",
        "effective_measurement_method",
        "full_time_months",
        "full_time_month_count",
        "ft_source_by_month",
    ):
        assert field in row, f"employee missing {field!r}"
    assert_fields(row, **expected)


def assert_furnishing_consent(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in ("employee_id", "electronic_address", "consent_status", "grant_count"):
        assert field in row, f"consent missing {field!r}"
    assert_fields(row, **expected)


def assert_form_1095c(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "employee_id",
        "form_type",
        "plan_start_month",
        "safe_harbor_preference",
        "furnishing_status",
        "filing_status",
        "ft_month_count",
        "offered_month_count",
        "assessable_month_count",
        "line15_total_cents",
        "late_furnishing_penalty_cents",
        "generated_by_user_id",
    ):
        assert field in row, f"form missing {field!r}"
    assert_fields(row, **expected)


def assert_transmittal(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "group_member_id",
        "transmission_type",
        "authoritative_indicator",
        "status",
        "cycle_number",
        "form_count",
        "aggregate_return_count",
        "required_channel",
        "monthly_ft_counts",
        "error_count",
        "open_error_count",
    ):
        assert field in row, f"transmittal missing {field!r}"
    assert_fields(row, **expected)


def assert_transmittal_error(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in ("transmittal_id", "error_code", "error_field", "severity", "resolution_status"):
        assert field in row, f"transmittal error missing {field!r}"
    assert_fields(row, **expected)


def assert_penalty_notice(row, expected_version=None, **expected):
    assert_mutable_shape(row, expected_version)
    for field in (
        "controlled_group_id",
        "notice_number",
        "notice_date",
        "response_due_date",
        "proposed_amount_cents",
        "asserted_a_months",
        "asserted_b_employee_months",
        "status",
        "evidence_count",
        "applied_evidence_count",
        "allocated_total_cents",
        "unallocated_amount_cents",
    ):
        assert field in row, f"penalty notice missing {field!r}"
    assert_fields(row, **expected)


# ---------------------------------------------------------------------------
# Append-only families
# ---------------------------------------------------------------------------
def assert_monthly_headcount(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "group_member_id",
        "count_year",
        "month",
        "full_time_employee_count",
        "part_time_hours_total",
        "total_employee_count",
        "seasonal_excess_count",
        "member_fte",
    ):
        assert field in row, f"headcount missing {field!r}"
    assert_fields(row, **expected)


def assert_measurement_cycle(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "group_member_id",
        "cycle_type",
        "measurement_start_date",
        "measurement_end_date",
        "admin_period_end_date",
        "stability_start_date",
        "stability_end_date",
        "hours_threshold_monthly",
    ):
        assert field in row, f"measurement cycle missing {field!r}"
    assert_fields(row, **expected)


def assert_hours_record(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "employee_id",
        "measurement_year",
        "month",
        "hours_of_service",
        "paid_leave_hours",
        "special_unpaid_leave_hours",
        "counted_hours",
        "excluded_from_denominator",
    ):
        assert field in row, f"hours record missing {field!r}"
    assert_fields(row, **expected)


def assert_employment_event(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "employee_id",
        "event_type",
        "effective_date",
        "resulting_status",
        "recorded_by_user_id",
    ):
        assert field in row, f"employment event missing {field!r}"
    assert_fields(row, **expected)


def assert_coverage_offer(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "employee_id",
        "offer_kind",
        "minimum_value",
        "lowest_cost_self_only_cents",
        "effective_start_date",
        "effective_end_date",
        "covered_months",
        "enrolled",
    ):
        assert field in row, f"coverage offer missing {field!r}"
    assert_fields(row, **expected)


def assert_monthly_coverage_line(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "form_1095c_id",
        "month",
        "line14_code",
        "line15_amount_cents",
        "line16_code",
        "full_time_flag",
        "ft_source",
        "special_situation",
        "assessable",
    ):
        assert field in row, f"coverage line missing {field!r}"
    assert_fields(row, **expected)


def assert_penalty_evidence(row, **expected):
    assert_append_only_shape(row)
    for field in (
        "penalty_notice_id",
        "evidence_type",
        "month",
        "document_ref",
        "applied",
        "filed_by_user_id",
    ):
        assert field in row, f"penalty evidence missing {field!r}"
    assert_fields(row, **expected)


# ---------------------------------------------------------------------------
# Domain invariant helpers
# ---------------------------------------------------------------------------
def lines_by_month(lines):
    """Index a list of monthly coverage lines by their ``month``."""
    indexed = {line["month"]: line for line in lines}
    assert len(indexed) == len(lines), "duplicate month among coverage lines"
    return indexed


def assert_twelve_coverage_lines(lines):
    assert len(lines) == 12, f"expected twelve coverage lines, got {len(lines)}"
    assert sorted(line["month"] for line in lines) == list(range(1, 13))
    for line in lines:
        assert_append_only_shape(line)


def assert_allocation_conserved(notice, member_rows):
    """The member allocations must sum to the notice's ``allocated_total_cents``
    and the recalculated amount must split with nothing left unallocated."""
    total = sum(member["allocated_penalty_cents"] for member in member_rows)
    assert total == notice["allocated_total_cents"], (
        f"member allocations sum to {total} but notice reports "
        f"{notice['allocated_total_cents']}"
    )
    assert (
        notice["allocated_total_cents"] + notice["unallocated_amount_cents"]
        == notice["recalculated_amount_cents"]
    )
