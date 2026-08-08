"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _uuid(data):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"


def _common_mutable(data):
    _uuid(data)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_timestamp_millis_z(ts):
    """A timestamp of the exact form YYYY-MM-DDTHH:MM:SS.mmmZ (three fractional digits, trailing Z)."""
    assert isinstance(ts, str), f"timestamp must be a string, got {ts!r}"
    assert ts.endswith("Z"), f"timestamp must end with Z, got {ts!r}"
    assert "." in ts, f"timestamp must carry fractional digits, got {ts!r}"
    frac = ts.split(".")[1][:-1]
    assert len(frac) == 3 and frac.isdigit(), f"timestamp must carry exactly three fractional digits, got {ts!r}"


def assert_clinician(data):
    _common_mutable(data)
    assert isinstance(data["full_name"], str)
    assert data["discipline"] in ["RN", "NP", "PHYSICIAN", "CRNA", "THERAPIST"]
    assert data["specialty"] in ["ICU", "ER", "MED_SURG", "OR", "L_AND_D", "TELEMETRY", "PSYCH", "HOSPITALIST"]
    assert data["employment_type"] in ["W2_EMPLOYEE", "CONTRACTOR_1099"]
    assert isinstance(data["primary_residence_state"], str) and len(data["primary_residence_state"]) == 2
    assert isinstance(data["tax_home_verified"], bool)
    assert data["status"] in ["AVAILABLE", "ON_ASSIGNMENT", "INACTIVE"]
    assert isinstance(data["active_assignment_count"], int)
    assert isinstance(data["ytd_taxable_wages_cents"], int)
    assert isinstance(data["ytd_nontaxable_stipend_cents"], int)


def assert_license(data):
    _common_mutable(data)
    assert isinstance(data["clinician_id"], str)
    assert len(data["state_code"]) == 2
    assert data["license_type"] in ["RN", "NP", "PHYSICIAN", "CRNA", "THERAPIST"]
    assert data["status"] in ["PENDING_VERIFICATION", "VERIFIED", "SUSPENDED", "EXPIRED"]
    assert isinstance(data["is_compact"], bool)


def assert_facility(data):
    _common_mutable(data)
    assert isinstance(data["name"], str)
    assert len(data["state_code"]) == 2
    assert isinstance(data["is_compact_member"], bool)
    assert isinstance(data["max_concurrent_travelers"], int) and data["max_concurrent_travelers"] >= 1


def assert_per_diem_locality_shape(data):
    """PerDiemLocality is common_fields:false — id + created_at ONLY, no version/updated_at."""
    _uuid(data)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "PerDiemLocality must not expose a version field"
    assert "updated_at" not in data, "PerDiemLocality must not expose an updated_at field"


def assert_assignment(data):
    _common_mutable(data)
    assert data["staffing_status"] in ["DRAFT", "PENDING_START", "ACTIVE", "COMPLETED", "CANCELLED"]
    assert data["compliance_status"] in ["PENDING_CREDENTIALS", "CLEARED", "SUSPENDED"]
    assert isinstance(data["term_weeks"], int) and 1 <= data["term_weeks"] <= 26


def assert_contract(data):
    _common_mutable(data)
    assert data["status"] in ["DRAFT", "SENT_FOR_SIGNATURE", "COUNTERSIGN_REQUESTED", "FULLY_EXECUTED", "VOIDED"]


def assert_credential_packet(data):
    _common_mutable(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "CLEARED", "REJECTED"]


def assert_credential_item(data):
    _common_mutable(data)
    assert data["status"] in ["PENDING", "VERIFIED", "REJECTED", "REVOKED", "EXPIRED"]


def assert_timesheet(data):
    _common_mutable(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DISPUTED", "VOIDED"]


def assert_earnings_statement(data):
    _common_mutable(data)
    assert data["kind"] in ["WEEKLY", "CANCELLATION_PENALTY"]
    assert data["status"] in ["FINALIZED", "POSTED", "REVERSED"]
    assert data["stipend_variant"] in ["FULL_WEEK_ACCRUAL", "DAILY_PRORATED", "NONE"]


def assert_payroll_run(data):
    _common_mutable(data)
    assert data["status"] in ["OPEN", "LOCKED", "POSTED"]


def assert_extension_request(data):
    _common_mutable(data)
    assert data["status"] in ["PROPOSED", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN"]


# --- Domain invariant checkers ---
def assert_money_partition(data):
    """On any statement / assignment ledger / run, gross bill == pay cost + margin."""
    if "gross_bill_cents" in data:
        assert data["gross_bill_cents"] == data["total_pay_cost_cents"] + data["gross_margin_cents"], (
            "statement money partition violated: "
            f"{data['gross_bill_cents']} != {data['total_pay_cost_cents']} + {data['gross_margin_cents']}"
        )


def assert_assignment_money_partition(a):
    assert a["realized_gross_bill_cents"] == a["realized_pay_cost_cents"] + a["realized_margin_cents"], (
        "assignment realized money partition violated"
    )


def assert_guaranteed_hours_partition(a):
    total = a["guaranteed_hours_consumed"] + a["guaranteed_hours_remaining"] + a["guaranteed_hours_waived"]
    assert abs(total - a["guaranteed_hours_total"]) < 1e-9, (
        f"guaranteed-hour partition violated: {total} != {a['guaranteed_hours_total']}"
    )


def assert_run_money_partition(r):
    assert r["total_gross_bill_cents"] == r["total_pay_cost_cents"] + r["total_margin_cents"], (
        "payroll run money partition violated"
    )
