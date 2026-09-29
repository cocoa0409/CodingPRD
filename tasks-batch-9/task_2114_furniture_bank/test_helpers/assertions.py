"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import CATEGORY_BASE_CENTS
from .types import (
    AgencyStanding,
    BedBugStatus,
    ClientStatus,
    ConditionGrade,
    County,
    CrewAssignmentStatus,
    CrewRole,
    DeliveryRunStatus,
    DeliveryStopStatus,
    DonationItemDecision,
    DonationOfferStatus,
    FeeBasis,
    GoodsCategory,
    InventoryItemStatus,
    ReferralStatus,
    ReferralUrgency,
    RejectReason,
    VoucherFeeStatus,
    VoucherLineStatus,
    VoucherStatus,
    WaitlistEntryStatus,
)

_COUNTIES = [c.value for c in County]
_CATEGORIES = [c.value for c in GoodsCategory]


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_nullable_timestamp(value, field_name: str):
    if value is not None:
        assert is_iso8601_timestamp(value), (
            f"{field_name} must be null or an ISO 8601 UTC timestamp, got {value!r}"
        )


# ─── Per-entity assertions ─────────────────────────────────────────────

def assert_partner_agency(data: dict):
    assert_common_fields(data, "PartnerAgency")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["county"] in _COUNTIES
    assert isinstance(data["quarterly_voucher_quota"], int)
    assert data["quarterly_voucher_quota"] >= 1
    assert isinstance(data["quota_used"], int) and data["quota_used"] >= 0
    assert isinstance(data["quota_epoch"], int) and data["quota_epoch"] >= 1
    assert data["standing"] in _values(AgencyStanding)
    assert isinstance(data["no_show_credits_owed_cents"], int)
    assert data["no_show_credits_owed_cents"] >= 0


def assert_client(data: dict):
    assert_common_fields(data, "Client")
    assert is_valid_uuid(data["agency_id"])
    assert isinstance(data["household_size"], int)
    assert 1 <= data["household_size"] <= 12
    assert data["county"] in _COUNTIES
    assert isinstance(data["has_infant"], bool)
    assert data["bed_bug_status"] in _values(BedBugStatus)
    assert_nullable_timestamp(data["bed_bug_confirmed_at"], "Client.bed_bug_confirmed_at")
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert_nullable_timestamp(data["delivery_ban_until"], "Client.delivery_ban_until")
    assert isinstance(data["lifetime_vouchers_delivered"], int)
    assert data["status"] in _values(ClientStatus)


def assert_referral(data: dict):
    assert_common_fields(data, "Referral")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["agency_id"])
    assert isinstance(data["requested_categories"], list)
    assert len(data["requested_categories"]) >= 1
    for category in data["requested_categories"]:
        assert category in _CATEGORIES
    assert data["urgency"] in _values(ReferralUrgency)
    assert isinstance(data["home_visit_completed"], bool)
    assert isinstance(data["bed_bug_attestation"], bool)
    assert data["status"] in _values(ReferralStatus)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["priority_score"], (int, float))
    assert data["priority_score"] >= 0.0
    assert_nullable_timestamp(data["approved_at"], "Referral.approved_at")
    assert_nullable_timestamp(data["expires_at"], "Referral.expires_at")


def assert_voucher(data: dict):
    assert_common_fields(data, "Voucher")
    assert is_valid_uuid(data["referral_id"])
    assert data["status"] in _values(VoucherStatus)
    assert data["fee_status"] in _values(VoucherFeeStatus)
    for money_field in ("gross_fee_cents", "subsidy_cents",
                        "client_due_cents", "amount_paid_cents"):
        assert isinstance(data[money_field], int), (
            f"Voucher.{money_field} must be integer cents, got {data[money_field]!r}"
        )
        assert data[money_field] >= 0
    assert data["fee_basis"] is None or data["fee_basis"] in _values(FeeBasis)
    assert isinstance(data["fill_ratio"], (int, float))
    assert 0.0 <= data["fill_ratio"] <= 1.0


def assert_voucher_line(data: dict):
    assert_common_fields(data, "VoucherLine")
    assert is_valid_uuid(data["voucher_id"])
    assert data["category"] in _CATEGORIES
    assert isinstance(data["quantity_requested"], int)
    assert 1 <= data["quantity_requested"] <= 6
    assert data["min_condition"] in ["A", "B", "C"]
    assert isinstance(data["quantity_allocated"], int)
    assert data["quantity_allocated"] >= 0
    assert data["status"] in _values(VoucherLineStatus)


def assert_donation_offer(data: dict):
    assert_common_fields(data, "DonationOffer")
    assert isinstance(data["donor_name"], str) and len(data["donor_name"]) > 0
    assert isinstance(data["donor_phone"], str) and len(data["donor_phone"]) > 0
    assert data["pickup_county"] in _COUNTIES
    assert is_iso8601_timestamp(data["pickup_window_start"])
    assert is_iso8601_timestamp(data["pickup_window_end"])
    assert data["truck_id"] is None or is_valid_uuid(data["truck_id"])
    assert data["status"] in _values(DonationOfferStatus)
    assert isinstance(data["accepted_item_count"], int)
    assert isinstance(data["rejected_item_count"], int)
    assert isinstance(data["declared_soft_ratio"], (int, float))
    assert 0.0 <= data["declared_soft_ratio"] <= 1.0
    assert isinstance(data["bed_bug_risk_score"], (int, float))
    assert 0.0 <= data["bed_bug_risk_score"] <= 100.0
    assert_nullable_timestamp(data["quarantine_started_at"],
                              "DonationOffer.quarantine_started_at")
    assert_nullable_timestamp(data["quarantine_release_due_at"],
                              "DonationOffer.quarantine_release_due_at")


def assert_donation_item(data: dict):
    assert_common_fields(data, "DonationItem")
    assert is_valid_uuid(data["offer_id"])
    assert data["category"] in _CATEGORIES
    assert data["declared_condition"] in _values(ConditionGrade)
    assert isinstance(data["soft_surface"], bool)
    assert isinstance(data["cubic_feet"], (int, float))
    assert 0 < data["cubic_feet"] <= 200
    assert data["decision"] in _values(DonationItemDecision)
    assert data["reject_reason"] is None or data["reject_reason"] in _values(RejectReason)
    assert (data["graded_condition"] is None
            or data["graded_condition"] in _values(ConditionGrade))


def assert_inventory_item(data: dict):
    assert_common_fields(data, "InventoryItem")
    assert is_valid_uuid(data["donation_item_id"])
    assert data["category"] in _CATEGORIES
    assert data["condition"] in ["A", "B", "C"], (
        "A stock unit's condition is always one of A, B or C: "
        f"got {data['condition']!r}"
    )
    assert isinstance(data["cubic_feet"], (int, float)) and data["cubic_feet"] > 0
    assert data["status"] in _values(InventoryItemStatus)
    assert (data["reserved_for_voucher_line_id"] is None
            or is_valid_uuid(data["reserved_for_voucher_line_id"]))
    assert_nullable_timestamp(data["available_since"], "InventoryItem.available_since")


def assert_truck(data: dict):
    assert_common_fields(data, "Truck")
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["capacity_cubic_feet"], (int, float))
    assert data["capacity_cubic_feet"] > 0
    assert data["home_county"] in _COUNTIES
    assert isinstance(data["crew_minimum"], int)
    assert 1 <= data["crew_minimum"] <= 4
    assert_nullable_timestamp(data["bed_bug_lockout_until"], "Truck.bed_bug_lockout_until")


def assert_delivery_run(data: dict):
    assert_common_fields(data, "DeliveryRun")
    assert is_valid_uuid(data["truck_id"])
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["county"] in _COUNTIES
    assert (data["rescheduled_from_run_id"] is None
            or is_valid_uuid(data["rescheduled_from_run_id"]))
    assert data["status"] in _values(DeliveryRunStatus)
    assert isinstance(data["load_cubic_feet"], (int, float))
    assert data["load_cubic_feet"] >= 0
    assert isinstance(data["confirmed_crew_count"], int)
    assert data["confirmed_crew_count"] >= 0
    assert isinstance(data["has_confirmed_driver"], bool)
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0


def assert_delivery_stop(data: dict):
    assert_common_fields(data, "DeliveryStop")
    assert is_valid_uuid(data["run_id"])
    assert is_valid_uuid(data["voucher_id"])
    assert isinstance(data["sequence"], int)
    assert 1 <= data["sequence"] <= 40
    assert data["status"] in _values(DeliveryStopStatus)
    assert isinstance(data["pest_observed_at_residence"], bool)
    assert isinstance(data["chargeback_cents"], int)
    assert data["chargeback_cents"] >= 0
    assert_nullable_timestamp(data["outcome_recorded_at"],
                              "DeliveryStop.outcome_recorded_at")


def assert_volunteer(data: dict):
    assert_common_fields(data, "Volunteer")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["county"] in _COUNTIES
    assert isinstance(data["lift_certified"], bool)
    assert isinstance(data["reliability_score"], (int, float))
    assert 0.0 <= data["reliability_score"] <= 100.0
    assert isinstance(data["assigned_hours_month"], (int, float))
    assert data["assigned_hours_month"] >= 0.0


def assert_crew_assignment(data: dict):
    assert_common_fields(data, "CrewAssignment")
    assert is_valid_uuid(data["run_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert data["role_on_crew"] in _values(CrewRole)
    assert data["status"] in _values(CrewAssignmentStatus)


def assert_waitlist_entry(data: dict):
    assert_common_fields(data, "WaitlistEntry")
    assert is_valid_uuid(data["voucher_line_id"])
    assert is_valid_uuid(data["client_id"])
    assert data["category"] in _CATEGORIES
    assert data["county"] in _COUNTIES
    assert isinstance(data["quantity_unmet"], int) and data["quantity_unmet"] >= 0
    assert isinstance(data["priority_score"], (int, float))
    assert data["priority_score"] >= 0.0
    assert is_iso8601_timestamp(data["waiting_since"])
    assert data["status"] in _values(WaitlistEntryStatus)


# ─── Domain invariant checkers ─────────────────────────────────────────

def assert_voucher_money_identity(voucher: dict):
    """`client_due_cents` is `gross_fee_cents` minus `subsidy_cents`, never
    re-rounded (PRD §3.9)."""
    assert voucher["client_due_cents"] == (
        voucher["gross_fee_cents"] - voucher["subsidy_cents"]
    ), (
        "client_due_cents must equal gross_fee_cents - subsidy_cents, got "
        f"{voucher['client_due_cents']} vs "
        f"{voucher['gross_fee_cents']} - {voucher['subsidy_cents']}"
    )


def assert_quota_conservation(agency: dict, referrals: list):
    """PartnerAgency.quota_used equals the count of that agency's referrals whose
    status is APPROVED or FULFILLED and whose approved_epoch equals the agency's
    current quota_epoch (PRD §2.10)."""
    counted = [
        r for r in referrals
        if r["status"] in ("APPROVED", "FULFILLED")
        and r.get("approved_epoch") == agency["quota_epoch"]
    ]
    assert agency["quota_used"] == len(counted), (
        f"quota_used {agency['quota_used']} must equal the {len(counted)} "
        f"APPROVED/FULFILLED referrals stamped with epoch {agency['quota_epoch']}"
    )


def assert_line_stock_conservation(line: dict, inventory_items: list):
    """VoucherLine.quantity_allocated equals the number of inventory units whose
    reserved_for_voucher_line_id points at that line and whose status is
    RESERVED, STAGED or DELIVERED (PRD §2.10)."""
    held = [
        item for item in inventory_items
        if item.get("reserved_for_voucher_line_id") == line["id"]
        and item["status"] in ("RESERVED", "STAGED", "DELIVERED")
    ]
    assert line["quantity_allocated"] == len(held), (
        f"quantity_allocated {line['quantity_allocated']} must equal the "
        f"{len(held)} units held for line {line['id']}"
    )


def expected_line_chargeback_cents(category: str, quantity_allocated: int,
                                   rate: float) -> int:
    """Round half up to whole cents at the line, exactly as PRD §3.8 pins it."""
    raw = CATEGORY_BASE_CENTS[category] * quantity_allocated * rate
    floor_value = int(raw)
    remainder = raw - floor_value
    if remainder > 0.5 or abs(remainder - 0.5) < 1e-9:
        return floor_value + 1
    return floor_value
