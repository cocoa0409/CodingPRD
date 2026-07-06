"""Entity assertions and domain helpers.

Uses the framework's generic validators internally. Only asserts fields the
PRD guarantees on each entity's response.
"""
from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import RETENTION_PCT


PROJECT_STATES = {
    "DRAFT", "QUOTED", "PENDING_APPROVALS", "CONTRACTED",
    "IN_PRODUCTION", "COMPLETED", "CANCELLED",
}


def round_half_up_cents(value) -> int:
    """Round a numeric value half-up to whole cents, matching PRD §2.6."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def retention_amount_cents(contract_value_cents: int) -> int:
    """Five percent of contract value, rounded half up (PRD §3.9)."""
    return int((Decimal(int(contract_value_cents)) * Decimal(str(RETENTION_PCT)))
               .quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_product(data: dict):
    _common(data)
    assert data["category"] in {"PAVER", "WALL_BLOCK", "FIRE_PIT", "OUTDOOR_KITCHEN"}
    assert data["unit"] in {"SQFT", "FACE_SQFT", "EACH", "LINEAR_FT"}
    assert isinstance(data["unit_price_cents"], int)


def assert_crew(data: dict):
    _common(data)
    assert isinstance(data["active_booking_count"], int)


def assert_project(data: dict):
    _common(data)
    assert data["status"] in PROJECT_STATES, f"unexpected project status {data.get('status')!r}"
    for field in ("estimated_total_cents", "contract_value_cents",
                  "amount_paid_cents", "balance_due_cents", "final_billed_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["hoa_required"], bool)


def assert_design_revision(data: dict):
    _common(data)
    assert data["status"] in {"DRAFTING", "RENDERED", "IN_REVIEW", "REVISION_REQUESTED", "APPROVED"}
    assert isinstance(data["revision_round"], int)


def assert_line_item(data: dict):
    _common(data)
    assert data["category"] in {"PAVER", "WALL_BLOCK", "FIRE_PIT", "OUTDOOR_KITCHEN"}
    assert data["origin"] in {"ORIGINAL", "CHANGE_ORDER"}


def assert_work_phase(data: dict):
    _common(data)
    assert data["status"] in {"PLANNED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "BLOCKED", "CANCELLED"}


def assert_progress_draw(data: dict):
    _common(data)
    assert data["draw_type"] in {"DEPOSIT", "PROGRESS", "RETENTION_RELEASE"}
    assert data["status"] in {"PENDING", "PAID", "REFUNDED", "VOID"}


def assert_balance_consistent(project: dict):
    """PRD §3.7: balance_due_cents == contract_value_cents - amount_paid_cents."""
    assert project["balance_due_cents"] == project["contract_value_cents"] - project["amount_paid_cents"], (
        f"balance_due {project['balance_due_cents']} != contract {project['contract_value_cents']} "
        f"- paid {project['amount_paid_cents']}"
    )
