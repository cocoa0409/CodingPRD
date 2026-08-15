"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §2.7)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD §2.4: created_at / updated_at are "an ISO 8601 UTC timestamp with three
# fractional digits".
_THREE_FRACTIONAL_DIGITS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_timestamp_ms(value, field_name="timestamp"):
    """Assert a resource timestamp is ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert _THREE_FRACTIONAL_DIGITS.match(value), (
        f"{field_name} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def _assert_common_fields(data, label):
    """Primary-resource common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert "-" in data["id"] and not data["id"].startswith(("prod_", "req_")), (
        f"{label}.id must have no type prefix"
    )
    assert_timestamp_ms(data.get("created_at", ""), f"{label}.created_at")
    assert_timestamp_ms(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_append_only_fields(data, label):
    """LookRequirement / TimeEvent carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert_timestamp_ms(data.get("created_at", ""), f"{label}.created_at")
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_production(data):
    _assert_common_fields(data, "Production")
    assert data["status"] in ["SETUP", "ACTIVE", "WRAPPED"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["studio_code"], str)
    assert isinstance(data["payroll_company_name"], str)
    assert isinstance(data["compliance_index"], int)
    assert isinstance(data["payroll_exposure_cents"], int)


def assert_actor(data):
    _assert_common_fields(data, "BackgroundActor")
    assert data["status"] in ["REGISTERED", "ELIGIBLE", "SUSPENDED"]
    assert data["union_status"] in ["SAG_AFTRA", "NONUNION"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["no_show_count"], int)
    assert isinstance(data["reliability_score"], int)


def assert_casting_call(data):
    _assert_common_fields(data, "CastingCall")
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "LOCKED", "SHOOTING", "WRAPPED", "CANCELLED",
    ]
    assert isinstance(data["union_slots"], int)
    assert isinstance(data["nonunion_slots"], int)
    assert isinstance(data["slots_available"], int)
    assert isinstance(data["required_union_slots"], int)
    assert isinstance(data["approved_waiver_reduction"], int)
    assert isinstance(data["union_bookings_active"], int)
    assert isinstance(data["nonunion_bookings_active"], int)
    assert isinstance(data["projected_union_count"], int)
    assert isinstance(data["actual_union_checkins"], int)


def assert_holding_area(data):
    _assert_common_fields(data, "HoldingArea")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["current_occupancy"], int)


def assert_booking(data):
    _assert_common_fields(data, "Booking")
    assert data["status"] in [
        "OFFERED", "CONFIRMED", "CHECKED_IN", "WRAPPED",
        "DECLINED", "EXPIRED", "CANCELLED", "NO_SHOW",
    ]
    assert data["slot_type"] in ["UNION", "NONUNION"]
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["is_replacement"], bool)
    assert is_iso8601_timestamp(data.get("call_time", "")), "call_time must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expected_wrap_time", "")), (
        "expected_wrap_time must be ISO 8601"
    )


def assert_voucher(data):
    _assert_common_fields(data, "Voucher")
    assert data["status"] in [
        "DRAFT", "ISSUED", "DISPUTED", "SUBMITTED", "REJECTED", "PAID",
    ]
    assert is_valid_uuid(data.get("booking_id", "")), "Voucher.booking_id must be a UUID"


def assert_bump_adjustment(data):
    _assert_common_fields(data, "BumpAdjustment")
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]
    assert data["category"] in [
        "WARDROBE_OWN", "FORMAL_WEAR", "PERIOD_COSTUME",
        "HAIR_MAKEUP", "PROPS_OWN", "SPECIAL_ABILITY",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["requested_by_user_id"], str)


def assert_payroll_batch(data):
    _assert_common_fields(data, "PayrollBatch")
    assert data["status"] in ["OPEN", "SUBMITTED", "PARTIALLY_REJECTED", "ACKNOWLEDGED"]
    assert isinstance(data["gross_total_cents"], int)
    assert isinstance(data["voucher_count"], int)


def assert_replacement_case(data):
    _assert_common_fields(data, "ReplacementCase")
    assert data["status"] in ["OPEN", "CANDIDATE_OFFERED", "FILLED", "EXPIRED"]
    assert data["required_slot_type"] in ["UNION", "NONUNION"]
    assert data["reason"] in ["NO_SHOW", "CANCELLATION"]
    assert isinstance(data["attempts_count"], int)
    assert isinstance(data["excluded_actor_ids"], list)


def assert_standby_entry(data):
    _assert_common_fields(data, "StandbyEntry")
    assert data["status"] in ["ACTIVE", "WITHDRAWN", "PROMOTED", "EXPIRED"]
    assert data["slot_type"] in ["UNION", "NONUNION"]


def assert_ratio_waiver(data):
    _assert_common_fields(data, "RatioWaiver")
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED", "REVOKED"]
    assert isinstance(data["union_slot_reduction"], int)
    assert isinstance(data["requested_by_user_id"], str)


def assert_look_requirement(data):
    _assert_append_only_fields(data, "LookRequirement")
    assert data["category"] in [
        "WARDROBE_OWN", "FORMAL_WEAR", "PERIOD_COSTUME",
        "HAIR_MAKEUP", "PROPS_OWN", "SPECIAL_ABILITY",
    ]
    assert isinstance(data["description"], str)
    assert isinstance(data["bump_amount_cents"], int) and data["bump_amount_cents"] > 0


def assert_time_event(data):
    _assert_append_only_fields(data, "TimeEvent")
    assert data["event_type"] in ["CHECK_IN", "MEAL_OUT", "MEAL_IN", "WRAP_OUT"]
    assert is_iso8601_timestamp(data.get("occurred_at", "")), (
        "occurred_at must be ISO 8601"
    )
    assert isinstance(data["recorded_by"], str)


# --- Domain invariants ---

def assert_slot_invariant(call_data):
    """PRD §2.6: union_slots + nonunion_slots == slots_available + active bookings
    (OFFERED | CONFIRMED | CHECKED_IN | WRAPPED) after every request."""
    active = data_active_booking_count(call_data)
    total = call_data["union_slots"] + call_data["nonunion_slots"]
    assert total == call_data["slots_available"] + active, (
        f"Slot invariant violated: {total} != {call_data['slots_available']} + {active}"
    )


def data_active_booking_count(call_data):
    return call_data["union_bookings_active"] + call_data["nonunion_bookings_active"]


def assert_batch_ledger_invariant(batch_data, member_vouchers):
    """PRD §2.7: batch gross_total_cents == sum of member voucher grosses;
    voucher_count == number of member vouchers."""
    expected_gross = sum(v["gross_total_cents"] for v in member_vouchers)
    assert batch_data["gross_total_cents"] == expected_gross, (
        f"Batch gross {batch_data['gross_total_cents']} != member sum {expected_gross}"
    )
    assert batch_data["voucher_count"] == len(member_vouchers), (
        f"Batch count {batch_data['voucher_count']} != {len(member_vouchers)}"
    )
