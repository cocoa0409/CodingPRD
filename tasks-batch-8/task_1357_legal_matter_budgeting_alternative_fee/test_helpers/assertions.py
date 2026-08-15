"""Entity assertions and domain invariant checkers (PRD sections 2.4, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_firm(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["fiscal_year_start_month"], int)
    assert 1 <= data["fiscal_year_start_month"] <= 12
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["closed_through_period_index"], int)


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["client_number"], str)
    assert isinstance(data["accrual_reporting_required"], bool)
    assert isinstance(data["accrual_reporting_cadence_periods"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_matter(data: dict):
    _assert_common(data)
    assert isinstance(data["matter_number"], str)
    assert isinstance(data["title"], str)
    assert data["litigation_stage"] in (
        "INTAKE", "PLEADINGS", "DISCOVERY", "PRETRIAL", "TRIAL", "APPEAL")
    assert isinstance(data["responsible_partner_id"], str)
    assert data["status"] in (
        "OPEN", "ACTIVE", "SUSPENDED", "CLOSED", "REOPENED")
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["actual_fees_cents"], int)
    assert isinstance(data["write_down_total_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["variance_pct_bp"] is None or \
        isinstance(data["variance_pct_bp"], int)
    assert data["variance_alert_level"] in ("NONE", "WATCH", "WARNING",
                                            "BREACH")
    assert isinstance(data["revised_forecast_cents"], int)
    assert isinstance(data["realization_rate_bp"], int)


def assert_fee_arrangement(data: dict):
    _assert_common(data)
    assert data["arrangement_type"] in (
        "FLAT_FEE", "CAPPED_FEE", "SUCCESS_FEE", "COLLAR")
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUPERSEDED", "REJECTED")
    assert isinstance(data["fiscal_year_index"], int)


def assert_phase_budget(data: dict):
    _assert_common(data)
    assert data["litigation_stage"] in (
        "INTAKE", "PLEADINGS", "DISCOVERY", "PRETRIAL", "TRIAL", "APPEAL")
    assert isinstance(data["task_code"], str)
    assert isinstance(data["original_budget_cents"], int)
    assert isinstance(data["current_budget_cents"], int)
    assert isinstance(data["actual_to_date_cents"], int)
    assert isinstance(data["etc_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "AMENDED", "VOIDED")
    assert isinstance(data["version_in_force"], int)


def assert_time_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["timekeeper_id"], str)
    assert isinstance(data["task_code"], str)
    assert isinstance(data["hours_worked_milli"], int)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["billable_amount_cents"], int)
    assert isinstance(data["entry_date"], str)
    assert isinstance(data["period_index"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "BILLED", "WRITTEN_DOWN",
        "REJECTED")


def assert_timekeeper(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["bar_number"], str)
    assert data["role_title"] in (
        "ASSOCIATE", "PARTNER", "OF_COUNSEL", "PARALEGAL")
    assert isinstance(data["standard_rate_cents"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_write_down_request(data: dict):
    _assert_common(data)
    assert isinstance(data["time_entry_ids"], list)
    assert isinstance(data["requested_amount_cents"], int)
    assert data["reason_code"] in (
        "CLIENT_RELATIONS", "BILLING_ERROR", "SCOPE_DISPUTE",
        "COLLECTIBILITY", "COURT_ORDER")
    assert data["status"] in (
        "DRAFT", "PENDING_PARTNER", "PENDING_MANAGING_PARTNER", "APPROVED",
        "APPLIED", "REJECTED", "CANCELLED")


def assert_budget_amendment(data: dict):
    _assert_common(data)
    assert isinstance(data["phase_budget_id"], str)
    assert isinstance(data["delta_cents"], int)
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_accrual_report(data: dict):
    _assert_common(data)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["accrued_fees_cents"], int)
    assert isinstance(data["unbilled_wip_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED",
                              "DISPUTED")


def assert_collar_true_up(data: dict):
    _assert_common(data)
    assert isinstance(data["actual_year_fees_cents"], int)
    assert isinstance(data["true_up_amount_cents"], int)
    assert data["direction"] in (
        "REBATE_TO_CLIENT", "COLLECT_FROM_CLIENT", "IN_BAND")
    assert data["status"] in ("COMPUTED", "SETTLED", "WAIVED")


def assert_matter_variance_invariants(matter: dict):
    """Derived-aggregate identities from PRD section 3.5 that must hold after
    any financial operation: variance identity, pct rounding, alert banding."""
    budget = matter["budget_total_cents"]
    actual = matter["actual_fees_cents"]
    assert matter["variance_cents"] == actual - budget, (
        f"variance_cents {matter['variance_cents']} != "
        f"actual {actual} - budget {budget}")
    if budget == 0:
        assert matter["variance_pct_bp"] is None
        assert matter["variance_alert_level"] == "NONE"
    else:
        expected_bp = round_half_up(10000 * matter["variance_cents"], budget)
        assert matter["variance_pct_bp"] == expected_bp, (
            f"variance_pct_bp {matter['variance_pct_bp']} != {expected_bp}")
        bp = matter["variance_pct_bp"]
        level = matter["variance_alert_level"]
        if bp >= 2000:
            assert level == "BREACH"
        elif bp >= 1000:
            assert level == "WARNING"
        elif bp >= 500:
            assert level == "WATCH"
        else:
            assert level == "NONE"


def round_half_up(numerator: int, denominator: int) -> int:
    """Round numerator/denominator to the nearest integer, halves away from
    zero for positive values (the rounding convention of PRD section 2.5)."""
    import decimal
    quotient = decimal.Decimal(numerator) / decimal.Decimal(denominator)
    return int(quotient.quantize(decimal.Decimal("1"),
                                 rounding=decimal.ROUND_HALF_UP))
