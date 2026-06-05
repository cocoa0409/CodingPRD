"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version for versioned records."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["original_contract_sum_cents"], int)
    assert isinstance(data["revised_contract_sum_cents"], int)
    assert isinstance(data["total_completed_and_stored_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)
    assert data["status"] in ["ACTIVE", "SUBSTANTIALLY_COMPLETE", "CLOSED"]


def assert_sov_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["item_no"], str)
    assert isinstance(data["scheduled_value_cents"], int)
    assert isinstance(data["work_completed_to_date_cents"], int)
    assert isinstance(data["materials_stored_cents"], int)
    assert isinstance(data["retainage_withheld_to_date_cents"], int)
    assert data["status"] in ["ACTIVE", "DELETED"]


def assert_change_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["co_number"], str)
    assert isinstance(data["change_order_amount_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]


def assert_pay_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["application_number"], int)
    assert isinstance(data["total_completed_and_stored_cents"], int)
    assert isinstance(data["total_retainage_cents"], int)
    assert isinstance(data["current_payment_due_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "CERTIFIED", "REJECTED"]


def assert_pay_app_line(data: dict):
    # PayAppLine is append-only: only id + created_at, no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "PayAppLine must not carry updated_at"
    assert "version" not in data, "PayAppLine must not carry version"
    assert is_valid_uuid(data.get("pay_app_id", "")), "pay_app_id must be a UUID"
    assert is_valid_uuid(data.get("sov_line_id", "")), "sov_line_id must be a UUID"
    assert isinstance(data["work_completed_this_period_cents"], int)
    assert isinstance(data["work_completed_previous_cents"], int)
    assert isinstance(data["line_retainage_cents"], int)


def assert_subcontractor_commitment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["committed_amount_cents"], int)
    assert isinstance(data["invoiced_to_date_cents"], int)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_rfi(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["ball_in_court"] in ["ARCHITECT", "CONTRACTOR"]
    assert data["status"] in ["OPEN", "ANSWERED", "CLOSED"]


def assert_submittal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["revision"], int)
    assert data["status"] in [
        "PENDING", "APPROVED", "APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT", "CLOSED"
    ]


def assert_lien_waiver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("pay_app_id", "")), "pay_app_id must be a UUID"
    assert data["waiver_type"] in [
        "CONDITIONAL_PROGRESS", "UNCONDITIONAL_PROGRESS",
        "CONDITIONAL_FINAL", "UNCONDITIONAL_FINAL",
    ]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["PENDING", "EFFECTIVE", "VOID"]


def assert_punch_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["severity"] in ["MINOR", "MAJOR"]
    assert data["status"] in ["OPEN", "READY_FOR_REVIEW", "VERIFIED", "REOPENED"]


def assert_inspection_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["buffer_minutes"], int)
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED"]


def assert_retention_release(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_retainage_held_equals_sov_sum(project: dict, active_sov_lines: list):
    """PRD §2.5: retainage_held_cents is the roll-up of retainage withheld
    across schedule-of-values lines. The project field must equal the sum of
    retainage_withheld_to_date_cents over the active lines (no drift)."""
    line_sum = sum(s["retainage_withheld_to_date_cents"] for s in active_sov_lines)
    assert project["retainage_held_cents"] == line_sum, (
        f"retainage_held_cents {project['retainage_held_cents']} != "
        f"sum of SOV retainage {line_sum}"
    )


def assert_revised_sum_equals_sov_sum(project: dict, active_sov_lines: list):
    """PRD §3.1: the sum of scheduled_value_cents across the non-deleted lines
    equals the project's revised_contract_sum_cents."""
    line_sum = sum(s["scheduled_value_cents"] for s in active_sov_lines)
    assert project["revised_contract_sum_cents"] == line_sum, (
        f"revised_contract_sum_cents {project['revised_contract_sum_cents']} != "
        f"sum of ACTIVE SOV scheduled values {line_sum}"
    )
