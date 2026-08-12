"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_consignor(data: dict):
    _assert_common(data)
    assert data["split_mode"] in ("GROSS_SPLIT", "NET_SPLIT")
    assert data["payout_method"] in ("CHECK", "ACH", "WIRE")
    assert isinstance(data["outstanding_payout_cents"], int)


def assert_customer(data: dict):
    _assert_common(data)
    assert data["customer_type"] in ("INDIVIDUAL", "INSTITUTIONAL")
    assert isinstance(data["risk_score"], int)


def assert_instrument(data: dict):
    _assert_common(data)
    assert data["category"] in ("GRAND", "UPRIGHT", "DIGITAL", "HYBRID")
    assert data["condition_grade"] in ("EXCELLENT", "GOOD", "FAIR", "POOR")
    assert data["acquisition_type"] in ("NEW", "USED", "CONSIGNMENT")
    assert data["status"] in (
        "IN_PREP", "AVAILABLE", "RESERVED", "SOLD", "DELIVERED",
        "RESTORATION_HOLD", "REPOSSESSION_HOLD", "RETURNED_TO_CONSIGNOR",
    )


def assert_appraisal(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "OFFERED", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED")
    assert isinstance(data["provisional_value_cents"], int)


def assert_bid_package(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "AWARDED", "LOST", "WITHDRAWN")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["revision_number"], int)


def assert_sales_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in (
        "UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "FINANCED_ACTIVE", "COLLECTIONS", "REFUNDED",
    )
    assert data["fulfillment_status"] in (
        "AWAITING_SCHEDULING", "DELIVERY_SCHEDULED", "OUT_FOR_DELIVERY",
        "DELIVERED", "INSTALLED", "RETURNED", "CANCELLED",
    )
    assert data["balance_cents"] == data["total_cents"] - data["amount_paid_cents"], (
        "balance_cents must equal total_cents - amount_paid_cents"
    )


def assert_delivery_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["climate_certified"], bool)


def assert_delivery_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "EN_ROUTE", "COMPLETED", "FAILED")


def assert_technician(data: dict):
    _assert_common(data)
    assert data["certification_level"] in ("STANDARD", "MASTER")


def assert_service_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXHAUSTED", "CANCELLED")
    assert data["tier"] in ("BASIC", "STANDARD", "PREMIUM")
    assert_plan_credit_invariant(data)


def assert_plan_credit_invariant(data: dict):
    """PRD §3.7: used plus booked plus available always equals visits_total."""
    assert (
        data["visits_used"] + data["visits_booked"] + data["visits_available"]
        == data["visits_total"]
    ), (
        f"visit credit invariant broken: {data['visits_used']} + {data['visits_booked']} "
        f"+ {data['visits_available']} != {data['visits_total']}"
    )


def assert_service_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")


def assert_financing_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "APPLIED", "ACTIVE", "PAID_OFF", "DEFAULTED", "CONVERTED_TO_PURCHASE", "CANCELLED",
    )
    assert data["program"] in ("STANDARD", "RENT_TO_OWN")
    assert isinstance(data["monthly_amount_cents"], int)


def assert_warranty(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "REGISTERED", "VOID", "EXPIRED")


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("REFERRED", "ASSESSED", "QUOTED", "COMMISSIONED", "DECLINED")


def assert_showroom_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "RSVP_OPEN", "SETTLED", "CANCELLED")
    assert data["room"] in ("MAIN_SHOWROOM", "RECITAL_HALL")
    assert isinstance(data["rsvp_count"], int)
