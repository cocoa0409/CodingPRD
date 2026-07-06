"""Entity assertions and domain invariant checkers for the Wedding & Event
Planning API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_quad(data: dict):
    """Every resource carries id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_event(data: dict):
    _assert_audit_quad(data)
    assert isinstance(data["couple_names"], str) and len(data["couple_names"]) > 0
    assert data["package_type"] in ("FULL", "PARTIAL", "DAY_OF")
    assert data["status"] in ("DRAFT", "BOOKING", "COMPLETED", "CANCELLED")
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] >= 0
    assert isinstance(data["guest_count_estimate"], int) and data["guest_count_estimate"] >= 0
    for field in (
        "committed_spend_cents", "projected_spend_cents", "budget_balance_cents",
        "total_deposits_due_cents", "estimated_headcount", "confirmed_headcount",
        "cancellation_fee_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_budget_identity(data: dict):
    """PRD §3.3: budget_balance_cents == total_budget_cents - committed_spend_cents."""
    assert (
        data["budget_balance_cents"]
        == data["total_budget_cents"] - data["committed_spend_cents"]
    ), "budget_balance_cents must equal total_budget_cents - committed_spend_cents"


def assert_contract(data: dict):
    _assert_audit_quad(data)
    assert data["status"] in ("DRAFT", "SENT", "SIGNED", "COUNTERSIGNED", "VOID")
    assert data["package_type"] in ("FULL", "PARTIAL", "DAY_OF")
    assert isinstance(data["planner_fee_cents"], int) and data["planner_fee_cents"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_vendor(data: dict):
    _assert_audit_quad(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in (
        "CATERING", "FLORAL", "RENTAL", "PHOTO", "VENUE", "STAFFING", "OTHER",
    )


def assert_coi(data: dict):
    _assert_audit_quad(data)
    assert data["status"] in ("PENDING", "VERIFIED", "EXPIRED")
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] >= 0


def assert_vendor_booking(data: dict):
    _assert_audit_quad(data)
    assert data["status"] in ("PROPOSED", "BOOKED", "COMPLETED", "CANCELLED")
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0


def assert_booking_split_conserves(data: dict):
    """PRD §3.3: deposit_cents + balance_cents == contracted_cost_cents, with the
    balance absorbing the rounding residue (deposit rounded first)."""
    assert (
        data["deposit_cents"] + data["balance_cents"] == data["contracted_cost_cents"]
    ), "deposit_cents + balance_cents must sum back to contracted_cost_cents"


def assert_vendor_payment(data: dict):
    _assert_audit_quad(data)
    assert data["payment_type"] in ("DEPOSIT", "BALANCE")
    assert data["status"] in ("SCHEDULED", "PAID", "VOID")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_timeline_block(data: dict):
    _assert_audit_quad(data)
    assert data["zone"] in (
        "CEREMONY_SPACE", "RECEPTION_HALL", "KITCHEN", "LOADING_DOCK", "SUITE",
    )
    assert data["block_type"] in (
        "LOAD_IN", "SETUP", "CEREMONY", "COCKTAIL", "RECEPTION", "TEARDOWN",
    )
    assert data["end_offset_min"] > data["start_offset_min"]


def assert_guest(data: dict):
    _assert_audit_quad(data)
    assert data["rsvp_status"] in ("INVITED", "ACCEPTED", "DECLINED")
    assert data["meal_choice"] in ("NONE", "STANDARD", "VEGETARIAN", "VEGAN", "KIDS")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1


def assert_table(data: dict):
    _assert_audit_quad(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["occupied_seats"], int) and data["occupied_seats"] >= 0


def assert_seat_assignment(data: dict):
    _assert_audit_quad(data)
    assert isinstance(data["seats_used"], int) and data["seats_used"] >= 1


def assert_staff_member(data: dict):
    _assert_audit_quad(data)
    assert data["role_title"] in ("COORDINATOR", "SERVER", "BARTENDER", "SECURITY", "RUNNER")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_staff_assignment(data: dict):
    _assert_audit_quad(data)
    assert isinstance(data["labor_cost_cents"], int) and data["labor_cost_cents"] >= 0
    assert data["shift_end_offset_min"] > data["shift_start_offset_min"]
