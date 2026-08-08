"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ROOM_STATES = ["VACANT", "RESERVED", "OCCUPIED", "NOTICE_PENDING", "OUT_OF_SERVICE"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
TENANCY_STATES = ["PENDING_MOVE_IN", "ACTIVE", "NOTICE_GIVEN", "MOVED_OUT", "CANCELLED"]
BILLING_STATES = ["CURRENT", "PAST_DUE", "SETTLED"]
APP_STATES = ["SUBMITTED", "SCREENED", "APPROVED", "CONDITIONAL", "DENIED", "CONVERTED"]
INVOICE_STATES = ["OPEN", "PARTIAL", "PAST_DUE", "PAID"]
INCIDENT_STATES = ["REPORTED", "UPHELD", "DISMISSED", "DISPUTED"]
TICKET_STATES = ["OPEN", "SCHEDULED", "RESOLVED"]
PAYOUT_STATES = ["DRAFT", "PROJECTED", "RELEASED"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be dashed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_host(data: dict):
    _common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["payout_account_ref"], str) and data["payout_account_ref"]
    assert "@" in data["contact_email"]
    assert data["version"] >= 1


def assert_house(data: dict):
    _common(data)
    assert data["compliance_posture"] in POSTURES
    for f in ("total_room_count", "vacant_room_count", "reserved_room_count",
              "occupied_room_count", "notice_pending_room_count", "out_of_service_room_count"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    assert_house_partition(data)


def assert_house_partition(data: dict):
    """Room-state partition invariant (§2.8): total == sum of the five buckets."""
    buckets = (data["vacant_room_count"] + data["reserved_room_count"]
               + data["occupied_room_count"] + data["notice_pending_room_count"]
               + data["out_of_service_room_count"])
    assert data["total_room_count"] == buckets, (
        f"partition broken: total={data['total_room_count']} != sum={buckets}")


def assert_room(data: dict):
    _common(data)
    assert data["occupancy_state"] in ROOM_STATES
    assert data["weekly_rate_cents"] > 0 and data["monthly_rate_cents"] > 0
    assert isinstance(data["private_bath"], bool)


def assert_member(data: dict):
    _common(data)
    assert "@" in data["email"]
    assert isinstance(data["strike_points"], int) and data["strike_points"] >= 0
    assert data["standing_band"] in ["GOOD", "WATCH", "PROBATION"]


def assert_application(data: dict):
    _common(data)
    assert data["status"] in APP_STATES
    assert data["billing_cycle"] in ["WEEKLY", "MONTHLY"]
    for f in ("screening_round", "monthly_equivalent_cents", "required_income_cents",
              "required_deposit_cents"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_screening_report(data: dict):
    _common(data)
    assert "version" not in data, "ScreeningReport is append-only: no version field"
    assert "updated_at" not in data, "ScreeningReport is append-only: no updated_at field"
    assert data["background_result"] in ["CLEAR", "FLAGGED", "FAILED"]
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1


def assert_membership(data: dict):
    _common(data)
    assert data["tenancy_status"] in TENANCY_STATES
    assert data["billing_status"] in BILLING_STATES
    assert data["period_days"] in (7, 30)
    assert data["base_period_rate_cents"] > 0
    assert isinstance(data["balance_due_cents"], int)


def assert_invoice(data: dict):
    _common(data)
    assert data["status"] in INVOICE_STATES
    assert data["subtotal_cents"] == data["base_rent_cents"] + data["utility_share_cents"], (
        "subtotal must equal base_rent + utility_share (§3.5)")
    assert data["total_amount_cents"] == (
        data["subtotal_cents"] + data["proration_adjustment_cents"] + data["late_fee_cents"]), (
        "total must equal subtotal + proration + late_fee (§3.5)")


def assert_payment(data: dict):
    _common(data)
    assert "version" not in data, "Payment is append-only: no version field"
    assert "updated_at" not in data, "Payment is append-only: no updated_at field"
    assert data["amount_cents"] > 0
    assert data["method"] in ["CARD", "ACH", "CASH"]
    assert is_iso8601_timestamp(data.get("applied_at", "")), "applied_at must be ISO 8601"


def assert_incident(data: dict):
    _common(data)
    assert data["status"] in INCIDENT_STATES
    assert data["severity"] in ["MINOR", "MAJOR", "SEVERE"]
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0


def assert_ticket(data: dict):
    _common(data)
    assert data["status"] in TICKET_STATES
    assert data["area"] in ["ROOM", "SHARED_KITCHEN", "SHARED_BATH", "LAUNDRY", "COMMON_AREA"]
    assert data["severity"] in ["CRITICAL", "HIGH", "NORMAL"]
    assert is_iso8601_timestamp(data.get("sla_deadline_at", "")), "sla_deadline_at must be ISO 8601"
    assert isinstance(data["breach_hours"], int) and data["breach_hours"] >= 0
    assert isinstance(data["rent_credit_cents"], int) and data["rent_credit_cents"] >= 0


def assert_payout(data: dict):
    _common(data)
    assert data["status"] in PAYOUT_STATES
    assert data["variant_applied"] in ["NONE", "ACCRUAL_PROJECTION", "CASH_FINAL"]
    assert data["net_payout_cents"] >= 0, "net_payout is floored at 0 (§3.10)"
