"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

POLE_STATUSES = [
    "SURVEYED", "AUDIT_CLEARED", "SCHEDULED", "CONVERTED", "REWORK",
    "VERIFIED", "UNDER_REPAIR", "EXEMPT",
]
ROUTE_STATUSES = ["PLANNED", "RELEASED", "IN_PROGRESS", "SUSPENDED", "CLOSED", "CANCELLED"]
STOP_STATUSES = ["PENDING", "COMPLETE", "SKIPPED", "BLOCKED"]
WO_EXECUTION_STATUSES = [
    "PENDING", "DISPATCHED", "COMPLETED", "FAILED", "REWORK_PENDING", "CANCELLED",
]
WO_QC_STATUSES = ["NONE", "AWAITING_QC", "QC_PASSED", "QC_FAILED"]
TIERS = ["T1", "T2", "T3", "T4", "T5"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["program_budget_cents"], int) and data["program_budget_cents"] > 0
    assert isinstance(data["fy_rebate_cap_cents"], int)
    assert isinstance(data["rebate_cents_per_kwh"], int)
    assert isinstance(data["budget_balance_cents"], int)
    assert isinstance(data["current_billing_run_estimated_cents"], int)
    assert isinstance(data["converted_pole_count"], int)
    assert isinstance(data["pending_salvage_item_count"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "CLOSED"]


def assert_district(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["district_name"], str) and data["district_name"]
    assert data["zone"] in ["RESIDENTIAL", "ARTERIAL", "DOWNTOWN", "RURAL"]
    assert data["cct_cap_kelvin"] == {
        "RESIDENTIAL": 3000, "ARTERIAL": 4000, "DOWNTOWN": 2700, "RURAL": 2200,
    }[data["zone"]]
    assert data["full_cutoff_required"] == (data["zone"] in ("RESIDENTIAL", "RURAL"))


def assert_pole(data: dict):
    _assert_common(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["pole_number"], str) and data["pole_number"]
    assert data["ownership_type"] in ["MUNICIPAL", "UTILITY_OWNED"]
    assert data["fixture_class"] in ["COBRA_HEAD", "FLOOD", "POST_TOP", "DECORATIVE"]
    assert isinstance(data["nameplate_wattage"], int) and data["nameplate_wattage"] > 0
    assert isinstance(data["effective_wattage"], int) and data["effective_wattage"] > 0
    assert data["status"] in POLE_STATUSES
    assert data["wattage_tier"] in TIERS
    assert isinstance(data["billing_wattage"], int)


def assert_audit(data: dict):
    _assert_common(data)
    assert isinstance(data["pole_id"], str)
    assert isinstance(data["audited_wattage"], int) and data["audited_wattage"] > 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "DISPUTED", "SUPERSEDED"]


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["crew_name"], str) and data["crew_name"]
    assert isinstance(data["base_stops_per_shift"], int) and data["base_stops_per_shift"] > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0


def assert_route(data: dict):
    _assert_common(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["traffic_control_required"], bool)
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0
    assert isinstance(data["blocked_stop_count"], int) and data["blocked_stop_count"] >= 0
    assert isinstance(data["total_workload_minutes"], int)
    assert isinstance(data["required_shifts"], int)
    assert data["status"] in ROUTE_STATUSES


def assert_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["pole_id"], str)
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] > 0
    assert data["difficulty_class"] in ["STANDARD", "HEAVY", "COMPLEX"]
    assert data["stop_minutes"] == {
        "STANDARD": 45, "HEAVY": 75, "COMPLEX": 120,
    }[data["difficulty_class"]]
    assert data["status"] in STOP_STATUSES


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["pole_id"], str)
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["is_replacement"], bool)
    assert isinstance(data["stop_minutes"], int) and data["stop_minutes"] > 0
    assert data["execution_status"] in WO_EXECUTION_STATUSES
    assert data["qc_status"] in WO_QC_STATUSES


def assert_rate_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert data["ownership_class"] in ["MUNICIPAL", "UTILITY_OWNED"]
    assert isinstance(data["effective_from"], str)
    assert data["status"] in ["DRAFT", "FILED", "EFFECTIVE", "SUPERSEDED"]
    tier_rates = data["tier_rates"]
    assert set(tier_rates.keys()) == {"T1", "T2", "T3", "T4", "T5"}
    for tier, cents in tier_rates.items():
        assert isinstance(cents, int) and cents > 0, f"tier_rates[{tier}] must be positive int"


def assert_tariff_account(data: dict):
    _assert_common(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["ownership_class"] in ["MUNICIPAL", "UTILITY_OWNED"]
    assert isinstance(data["current_period"], str) and len(data["current_period"]) == 7
    assert isinstance(data["current_period_estimated_cents"], int)
    assert isinstance(data["ytd_billed_cents"], int)
    assert data["status"] in ["OPEN", "FROZEN"]


def assert_billing_line(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["pole_id"], str)
    assert isinstance(data["rate_schedule_id"], str)
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["line_type"] in ["REGULAR", "ADJUSTMENT"]
    assert isinstance(data["billing_wattage"], int)
    assert data["tier"] in TIERS
    assert isinstance(data["charge_cents"], int)
    assert data["status"] in ["ESTIMATED", "BILLED", "SUPERSEDED"]


def assert_outage_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["pole_id"], str)
    assert isinstance(data["reporter_user_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["hazard_flag"], bool)
    assert is_iso8601_timestamp(data.get("reported_at", "")), "reported_at must be ISO 8601"
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in [
        "OPEN", "TRIAGED", "DISPATCHED", "RESOLVED", "VERIFIED", "REOPENED", "DUPLICATE",
    ]


def assert_salvage_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["batch_label"], str) and data["batch_label"]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    assert isinstance(data["total_weight_lbs"], (int, float))
    assert data["status"] in ["ACCUMULATING", "SEALED", "MANIFESTED", "SETTLED", "REJECTED"]


def assert_salvage_item(data: dict):
    _assert_common(data)
    assert isinstance(data["pole_id"], str)
    assert data["fixture_class"] in ["COBRA_HEAD", "FLOOD", "POST_TOP", "DECORATIVE"]
    assert isinstance(data["weight_lbs"], (int, float))
    assert isinstance(data["mercury_flag"], bool)


def assert_savings_report(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["method"] in ["ENGINEERING_ESTIMATE", "METERED_ACTUAL"]
    assert isinstance(data["fiscal_year_label"], str)
    assert isinstance(data["baseline_kwh"], (int, float))
    assert isinstance(data["actual_kwh"], (int, float))
    assert isinstance(data["savings_kwh"], (int, float))
    assert isinstance(data["raw_credit_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ATTESTED", "REJECTED", "SUPERSEDED"]


def assert_compliance_exception(data: dict):
    _assert_common(data)
    assert isinstance(data["pole_id"], str)
    assert data["exception_kind"] in ["CCT_WAIVER", "CONVERSION_EXEMPTION"]
    assert isinstance(data["valid_until"], str)
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED", "EXPIRED"]
