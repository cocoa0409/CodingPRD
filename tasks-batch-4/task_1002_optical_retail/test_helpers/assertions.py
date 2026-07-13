"""Entity assertions and domain invariant checkers for the Optical Retail API."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppointmentStatus,
    ClaimStatus,
    DeliveryMethod,
    FrameStatus,
    FulfillmentStatus,
    KitItemOutcome,
    KitStatus,
    LabOrderStatus,
    LensCategory,
    LensOptionStatus,
    PaymentStatus,
    PolicyNetwork,
    PrescriptionStatus,
    QuoteVariant,
    StoreStatus,
    WarrantyClaimStatus,
    WarrantyReason,
)

_ENUM_VALUES = lambda e: [m.value for m in e]  # noqa: E731


# ─── Shared field discipline (PRD §2.4) ──────────────────────────────────────

def assert_common_fields(data: Dict[str, Any], entity_name: str = "resource") -> None:
    """PRD §2.4 — every persisted resource but the try-on kit item carries
    id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(
        data.get("version"), int
    ), f"{entity_name}.version must be an integer, got {data.get('version')!r}"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant the API returned, tolerating either a `Z`
    suffix or an explicit +00:00 offset, with or without fractional seconds.

    PRD §2.5 pins the *instant* the logical clock reports; it does not pin the
    serialization, so temporal assertions compare parsed instants.
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )


# ─── Entity assertions ───────────────────────────────────────────────────────

def assert_insurance_policy(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "InsurancePolicy")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert data["network"] in _ENUM_VALUES(PolicyNetwork)
    for field in (
        "frame_allowance_cents",
        "frame_allowance_remaining_cents",
        "lens_copay_cents",
        "annual_max_cents",
        "annual_reimbursed_cents",
    ):
        assert isinstance(data[field], int), f"InsurancePolicy.{field} must be integer cents"
        assert data[field] >= 0, f"InsurancePolicy.{field} must not be negative"
    assert 0 <= data["oon_reimburse_pct"] <= 1, "oon_reimburse_pct lies between 0 and 1"
    assert isinstance(data["oon_fee_schedule"], dict)
    assert is_iso8601_timestamp(data["plan_year_start"])


def assert_store(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Store")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in _ENUM_VALUES(StoreStatus)
    assert isinstance(data["exam_chairs"], int) and data["exam_chairs"] >= 1
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["pickup_capacity_per_day"], int)


def assert_frame(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Frame")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str)
    assert isinstance(data["brand"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in _ENUM_VALUES(FrameStatus)
    assert isinstance(data["tryon_stock"], int) and data["tryon_stock"] >= 0
    assert isinstance(data["tryon_available"], int) and data["tryon_available"] >= 0
    assert isinstance(data["min_pd_mm"], (int, float))
    assert isinstance(data["max_pd_mm"], (int, float))


def assert_lens_option(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "LensOption")
    assert isinstance(data["code"], str) and data["code"]
    assert data["category"] in _ENUM_VALUES(LensCategory)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["status"] in _ENUM_VALUES(LensOptionStatus)
    assert isinstance(data["incompatible_with"], list)


def assert_customer(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Customer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_iso8601_timestamp(data["dob"])
    assert isinstance(data["fsa_balance_cents"], int) and data["fsa_balance_cents"] >= 0
    assert isinstance(data["lifetime_kit_count"], int) and data["lifetime_kit_count"] >= 0
    assert isinstance(data["return_risk_score"], int)
    assert 0 <= data["return_risk_score"] <= 100, (
        "PRD §3.4: the return-risk score is an integer between 0 and 100"
    )


def assert_prescription(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Prescription")
    assert is_valid_uuid(data["customer_id"])
    for field in ("od_sphere", "od_cylinder", "os_sphere", "os_cylinder", "pd_mm"):
        assert isinstance(data[field], (int, float)), f"Prescription.{field} must be numeric"
    assert 45.0 <= data["pd_mm"] <= 80.0, "PRD §3.2: pd_mm lies in the closed range [45.0, 80.0]"
    assert isinstance(data["prism_diopters"], (int, float)) and data["prism_diopters"] >= 0
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert parse_instant(data["expires_at"]) > parse_instant(data["issued_at"]), (
        "PRD §3.2: expires_at must be strictly after issued_at"
    )
    assert data["status"] in _ENUM_VALUES(PrescriptionStatus)
    assert isinstance(data["resubmit_count"], int) and data["resubmit_count"] >= 0


def assert_home_try_on_kit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "HomeTryOnKit")
    assert is_valid_uuid(data["customer_id"])
    assert is_iso8601_timestamp(data["ship_date"])
    assert is_iso8601_timestamp(data["due_date"])
    assert parse_instant(data["due_date"]) > parse_instant(data["ship_date"]), (
        "PRD §3.4: due_date must be strictly after ship_date"
    )
    assert data["status"] in _ENUM_VALUES(KitStatus)
    assert isinstance(data["was_overdue"], bool)
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0
    assert isinstance(data["kept_count"], int) and data["kept_count"] >= 0
    assert data["kept_count"] <= data["item_count"]
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert data["late_fee_cents"] <= 5000, "PRD §3.4: the late fee is clamped to 5,000 cents"


def assert_try_on_kit_item(data: Dict[str, Any]) -> None:
    """PRD §2.4: the item carries ONLY id and created_at on top of its own fields —
    it has no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "TryOnKitItem.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["kit_id"])
    assert is_valid_uuid(data["frame_id"])
    assert data["outcome"] in _ENUM_VALUES(KitItemOutcome)
    assert "version" not in data, (
        "PRD §2.4: a try-on kit item has NO version field — clients must not expect one"
    )
    assert "updated_at" not in data, (
        "PRD §2.4: a try-on kit item has NO updated_at field — clients must not expect one"
    )


def assert_exam_appointment(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ExamAppointment")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["store_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert parse_instant(data["end_at"]) > parse_instant(data["start_at"]), (
        "PRD §3.3: end_at must be strictly after start_at"
    )
    assert data["status"] in _ENUM_VALUES(AppointmentStatus)


def assert_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Order")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["prescription_id"])
    assert is_valid_uuid(data["frame_id"])
    assert is_valid_uuid(data["material_option_id"])
    assert isinstance(data["coating_option_ids"], list)
    assert data["delivery_method"] in _ENUM_VALUES(DeliveryMethod)
    assert data["fulfillment_status"] in _ENUM_VALUES(FulfillmentStatus)
    assert data["payment_status"] in _ENUM_VALUES(PaymentStatus)
    assert data["quote_variant"] in _ENUM_VALUES(QuoteVariant)
    for field in (
        "lens_upcharge_cents",
        "subtotal_cents",
        "discount_cents",
        "benefit_frame_cents",
        "benefit_lens_cents",
        "benefit_applied_cents",
        "fsa_applied_cents",
        "customer_due_cents",
    ):
        assert isinstance(data[field], int), (
            f"PRD §2.6: Order.{field} must be an integer number of cents, "
            f"got {data[field]!r}"
        )
    assert_order_money_invariants(data)


def assert_order_money_invariants(data: Dict[str, Any]) -> None:
    """PRD §3.6 — invariants that hold after any run of the money waterfall.

    The frame's `price_cents` is not echoed on the order, so the
    `subtotal = price + lens_upcharge` identity is asserted directly by the tests
    that know the frame's price; what holds unconditionally is the sign discipline.
    """
    assert data["subtotal_cents"] >= data["lens_upcharge_cents"], (
        "PRD §3.6: subtotal_cents is the frame's price_cents plus the order's "
        "lens_upcharge_cents, and price_cents is zero or greater"
    )
    assert data["discount_cents"] >= 0
    assert data["benefit_frame_cents"] >= 0
    assert data["benefit_lens_cents"] >= 0
    assert data["fsa_applied_cents"] >= 0
    assert data["customer_due_cents"] >= 0, (
        "PRD §3.6: the FSA bucket is the smallest of three numbers including the "
        "pre-FSA balance, so customer_due_cents can never go negative"
    )


def assert_lab_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "LabOrder")
    assert is_valid_uuid(data["order_id"])
    assert data["status"] in _ENUM_VALUES(LabOrderStatus)
    assert isinstance(data["remake_count"], int) and data["remake_count"] >= 0
    assert data["remake_count"] <= 2, (
        "PRD §3.7: a QC failure is only accepted while remake_count is strictly below two"
    )
    assert isinstance(data["is_remake"], bool)


def assert_insurance_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "InsuranceClaim")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["policy_id"])
    assert isinstance(data["service_lines"], list)
    assert data["status"] in _ENUM_VALUES(ClaimStatus)
    assert isinstance(data["reserved_frame_benefit_cents"], int)
    assert data["reserved_frame_benefit_cents"] >= 0
    assert isinstance(data["approved_amount_cents"], int)
    assert isinstance(data["reimbursed_amount_cents"], int)


def assert_warranty_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "WarrantyClaim")
    assert is_valid_uuid(data["lab_order_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["reason"] in _ENUM_VALUES(WarrantyReason)
    assert data["status"] in _ENUM_VALUES(WarrantyClaimStatus)
    assert isinstance(data["customer_charge_cents"], int)
    assert data["customer_charge_cents"] >= 0


# ─── Conserved-quantity invariants (PRD §2.8) ────────────────────────────────

def assert_frame_benefit_conserved(
    policy: Dict[str, Any], claims: List[Dict[str, Any]]
) -> None:
    """PRD §2.8: for any policy, `frame_allowance_remaining_cents` plus the sum of
    `reserved_frame_benefit_cents` across every non-VOID claim against that policy
    always equals `frame_allowance_cents`."""
    reserved = sum(
        c["reserved_frame_benefit_cents"]
        for c in claims
        if c["status"] != ClaimStatus.VOID.value
    )
    total = policy["frame_allowance_remaining_cents"] + reserved
    assert total == policy["frame_allowance_cents"], (
        "PRD §2.8: frame_allowance_remaining_cents "
        f"({policy['frame_allowance_remaining_cents']}) + reserved over non-VOID claims "
        f"({reserved}) must equal frame_allowance_cents "
        f"({policy['frame_allowance_cents']}), got {total}"
    )


def assert_tryon_units_conserved(frame: Dict[str, Any], items: List[Dict[str, Any]]) -> None:
    """PRD §2.8: for any frame, `tryon_available` plus the count of try-on kit items
    on that frame whose `outcome` is still PENDING always equals `tryon_stock`."""
    pending = sum(
        1 for i in items if i["outcome"] == KitItemOutcome.PENDING.value
    )
    total = frame["tryon_available"] + pending
    assert total == frame["tryon_stock"], (
        f"PRD §2.8: tryon_available ({frame['tryon_available']}) + PENDING items "
        f"({pending}) must equal tryon_stock ({frame['tryon_stock']}), got {total}"
    )


# ─── List helpers ────────────────────────────────────────────────────────────

def find_item_by_frame(
    items: List[Dict[str, Any]], frame_id: str
) -> Optional[Dict[str, Any]]:
    """Return the try-on kit item on the given frame, or None."""
    for item in items:
        if item["frame_id"] == frame_id:
            return item
    return None
