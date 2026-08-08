"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_university(data: dict):
    _common(data)
    assert data["partner_tier"] in ("STANDARD", "PREFERRED")
    assert isinstance(data["partner_discount_bps"], int)
    assert isinstance(data["verification_required"], bool)
    assert isinstance(data["verified_student_count"], int)


def assert_property(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "LISTED", "FULLY_COMMITTED", "SUSPENDED")
    assert isinstance(data["unit_count"], int)
    assert isinstance(data["total_bed_count"], int)
    assert isinstance(data["available_bed_count"], int)
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["maintenance_reserve_cents"], int)
    assert isinstance(data["payout_eligible"], bool)


def assert_unit(data: dict):
    _common(data)
    assert data["occupancy_status"] in ("AVAILABLE", "PARTIALLY_LEASED", "FULLY_LEASED")
    assert isinstance(data["bed_labels"], list) and len(data["bed_labels"]) > 0
    assert_unit_partition(data)


def assert_unit_partition(data: dict):
    """PRD §2.8 conserved invariant: bed labels == leased + available."""
    assert len(data["bed_labels"]) == data["leased_bed_count"] + data["available_bed_count"], (
        f"partition broken: {len(data['bed_labels'])} != "
        f"{data['leased_bed_count']} + {data['available_bed_count']}"
    )
    assert data["available_bed_count"] >= 0
    assert data["leased_bed_count"] >= 0


def assert_student(data: dict):
    _common(data)
    assert data["verification_status"] in ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED")
    assert data["credit_score_band"] in ("THIN", "LOW", "FAIR", "GOOD", "EXCELLENT")


def assert_lease(data: dict):
    _common(data)
    assert data["lease_status"] in (
        "DRAFT", "PENDING_GUARANTOR", "PENDING_SIGNATURE", "ACTIVE",
        "ENDED", "CANCELLED", "TERMINATED",
    )
    assert data["funding_status"] in (
        "UNFUNDED", "PARTIAL", "CURRENT", "DELINQUENT", "SETTLED",
    )
    assert isinstance(data["monthly_rent_cents"], int)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["guarantor_required"], bool)


def assert_guarantor_application(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DECLINED")
    assert isinstance(data["income_multiple_bps"], int)
    assert isinstance(data["round_count"], int)


def assert_installment(data: dict):
    _common(data)
    assert data["kind"] in ("RENT", "AMENITY", "SUBLET_FEE")
    assert data["status"] in ("SCHEDULED", "LATE", "PAID", "VOID")
    assert isinstance(data["amount_cents"], int)


def assert_sublet(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DECLINED", "ACTIVE", "COMPLETED")


def assert_amenity(data: dict):
    _common(data)
    assert data["amenity_type"] in ("PARKING", "STORAGE", "GYM", "STUDY_ROOM", "LAUNDRY")


def assert_amenity_assignment(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_payout(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "PAID", "REVERSED")


def assert_escrow_conservation(prop: dict, paid_payout_gross_sum: int, collected_paid_sum: int):
    """PRD §3.9 conserved invariant: escrow_balance + SUM(gross over PAID payouts)
    == SUM collected from PAID installments."""
    assert prop["escrow_balance_cents"] + paid_payout_gross_sum == collected_paid_sum, (
        f"escrow conservation broken: {prop['escrow_balance_cents']} + "
        f"{paid_payout_gross_sum} != {collected_paid_sum}"
    )
