"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Every assertion references only PRD-declared fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ORDER_STATES = {
    "DRAFT", "QUOTED", "CONFIRMED", "LOADED_OUT", "IN_EVENT",
    "LOADED_IN", "SETTLED", "CANCELLED",
}
_RESERVATION_STATES = {"HELD", "CHECKED_OUT", "CHECKED_IN", "DAMAGED", "RELEASED"}
_CREW_STATES = {"SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED"}
_SUB_RENTAL_STATES = {"REQUESTED", "CONFIRMED", "RETURNED", "CANCELLED"}
_COI_STATES = {"SUBMITTED", "APPROVED", "REJECTED"}
_DAMAGE_STATES = {"FILED", "ASSESSED", "CHARGED", "WAIVED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_full_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_full_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0


def assert_venue(data: dict):
    _assert_full_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["required_coverage_cents"], int) and data["required_coverage_cents"] >= 0
    assert data["dock_type"] in ("STREET_LEVEL", "LOADING_DOCK", "FREIGHT_ELEVATOR")


def assert_equipment(data: dict):
    _assert_full_common(data)
    assert data["category"] in ("SOUND", "LIGHTING", "STAGING", "LED")
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["daily_rate_cents"], int) and data["daily_rate_cents"] >= 0
    assert isinstance(data["replacement_value_cents"], int) and data["replacement_value_cents"] >= 0
    assert isinstance(data["requires_operator"], bool)


def assert_crew_member(data: dict):
    _assert_full_common(data)
    assert data["crew_role"] in ("TECH", "OPERATOR")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_rental_order(data: dict):
    _assert_full_common(data)
    assert data["status"] in _ORDER_STATES, f"unexpected order status {data.get('status')!r}"
    assert data["pricing_variant"] in ("NONE", "PROVISIONAL", "FINAL")
    assert isinstance(data["has_approved_coi"], bool)
    for money in (
        "equipment_subtotal_cents", "crew_subtotal_cents", "sub_rental_cost_cents",
        "volume_discount_cents", "rush_surcharge_cents", "quote_total_cents",
        "final_total_cents", "deposit_required_cents", "deposit_held_cents",
        "deposit_captured_cents", "deposit_refunded_cents", "deposit_released_cents",
        "deposit_outstanding_cents", "deposit_at_risk_cents", "balance_cents",
    ):
        assert isinstance(data[money], int), f"{money} must be an integer number of cents"
    assert isinstance(data["open_damage_count"], int) and data["open_damage_count"] >= 0


def assert_equipment_reservation(data: dict):
    _assert_full_common(data)
    assert data["status"] in _RESERVATION_STATES
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["billable_days"], int) and data["billable_days"] >= 1
    assert isinstance(data["is_standby"], bool)


def assert_crew_assignment(data: dict):
    _assert_full_common(data)
    assert data["status"] in _CREW_STATES
    assert data["assignment_role"] in ("TECH", "OPERATOR")


def assert_sub_rental(data: dict):
    _assert_full_common(data)
    assert data["status"] in _SUB_RENTAL_STATES
    assert data["direction"] in ("SUB_IN", "CROSS_OUT")


def assert_certificate_of_insurance(data: dict):
    _assert_full_common(data)
    assert data["status"] in _COI_STATES
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] >= 0


def assert_damage_report(data: dict):
    _assert_full_common(data)
    assert data["status"] in _DAMAGE_STATES
    assert isinstance(data["assessed_cost_cents"], int)
    assert isinstance(data["captured_cents"], int)


def assert_deposit_ledger_entry(data: dict):
    """Append-only entry (PRD §2.4): carries ONLY id + created_at (no version/updated_at)."""
    _assert_common(data)
    assert data["entry_type"] in ("HOLD", "CAPTURE", "REFUND", "RELEASE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_deposit_conservation_settled(order: dict):
    """PRD §3.9 conservation invariant for a SETTLED order:
    deposit_held_cents == deposit_captured_cents + deposit_refunded_cents."""
    assert order["deposit_held_cents"] == (
        order["deposit_captured_cents"] + order["deposit_refunded_cents"]
    ), "held must equal captured + refunded on a settled order"


def assert_deposit_conservation_cancelled(order: dict):
    """PRD §3.9 conservation invariant for a confirmed-then-cancelled order:
    deposit_released_cents == deposit_held_cents and deposit_outstanding_cents == 0."""
    assert order["deposit_released_cents"] == order["deposit_held_cents"]
    assert order["deposit_outstanding_cents"] == 0
