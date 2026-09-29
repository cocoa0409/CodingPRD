"""Entity assertions and domain invariant checkers for the auction platform."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AuctionStatus,
    BidStatus,
    ConditionReportStatus,
    ConsignmentStatus,
    ConsignorSettlementStatus,
    CountryTier,
    ExportPacketStatus,
    GradeBand,
    InvoicePaymentStatus,
    InvoiceReleaseStatus,
    LoadoutSlotStatus,
    LotLifecycleStatus,
    LotTitleStatus,
    PaymentStatus,
    RefurbishmentOrderStatus,
    RegistrationStatus,
    SaleStatus,
    SettlementVariant,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# ---------------------------------------------------------------------------
# Envelope-level shape
# ---------------------------------------------------------------------------

def assert_identified_record(data: dict):
    """Every stored record is addressable by a UUID `id` and stamped `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"


def assert_versioned_record(data: dict):
    """Records other than a bid or a payment also carry `updated_at` and `version`."""
    assert_identified_record(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_append_only_record(data: dict):
    """A bid and a payment carry only `id` and `created_at` — no `updated_at`, no `version`."""
    assert_identified_record(data)
    assert "updated_at" not in data, "an append-only record must not carry updated_at"
    assert "version" not in data, "an append-only record must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_yard(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["teardown_buffer_minutes"], int)
    assert isinstance(data["loadout_deadline_days"], int)
    assert isinstance(data["currency_code"], str) and data["currency_code"]


def assert_loadout_bay(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["yard_id"])
    assert isinstance(data["bay_number"], int)
    assert isinstance(data["crane_capacity_kg"], int) and data["crane_capacity_kg"] > 0
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["reserved_tonnage_kg"], int)
    assert data["reserved_tonnage_kg"] >= 0, "reserved tonnage never drifts negative"


def assert_consignor(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["seller_type"] in ["DEALER", "FLEET_OWNER", "BANK_REPO", "GOVERNMENT"]
    assert isinstance(data["unreserved_policy_ack"], bool)


def assert_consignment(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["consignor_id"])
    assert data["agreement_type"] in ["RESERVE", "UNRESERVED"]
    assert data["commission_schedule_code"] in ["RESERVE_STD", "UNRESERVED_STD"]
    assert isinstance(data["refurb_authorization_cap_cents"], int)
    assert data["status"] in _values(ConsignmentStatus)


def assert_lot(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["consignment_id"])
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["model_year"], int)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["hour_meter_reading"], int)
    assert isinstance(data["weight_kg"], int) and data["weight_kg"] > 0
    assert isinstance(data["title_required"], bool)
    assert data["lifecycle_status"] in _values(LotLifecycleStatus)
    assert data["title_status"] in _values(LotTitleStatus)


def assert_condition_report(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["lot_id"])
    for field in (
        "structural_score",
        "powertrain_score",
        "hydraulics_score",
        "tires_score",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert 0 <= data[field] <= 100, f"{field} must fall between 0 and 100"
    assert isinstance(data["observed_hour_meter_reading"], int)
    assert isinstance(data["hour_meter_verified"], bool)
    assert data["status"] in _values(ConditionReportStatus)
    assert 0.0 <= data["grade_score"] <= 100.0
    assert data["grade_band"] in _values(GradeBand)


def assert_refurbishment_order(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["rework_round"], int) and data["rework_round"] >= 0
    assert data["status"] in _values(RefurbishmentOrderStatus)


def assert_auction(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["yard_id"])
    assert data["kind"] in ["LIVE_ONSITE", "TIMED_ONLINE"]
    assert data["reserve_policy"] in ["UNRESERVED", "RESERVE_ALLOWED"]
    assert data["premium_schedule_code"] in ["STANDARD", "LOW_VALUE_FLAT"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"]
    assert data["status"] in _values(AuctionStatus)


def assert_bidder(data: dict):
    assert_versioned_record(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert data["country_tier"] in _values(CountryTier)
    assert_deposit_ledger_conserved(data)


def assert_bidder_registration(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["bidder_id"])
    assert is_valid_uuid(data["auction_id"])
    assert isinstance(data["deposit_hold_cents"], int)
    assert isinstance(data["paddle_number"], int)
    assert data["status"] in _values(RegistrationStatus)


def assert_bid(data: dict):
    assert_append_only_record(data)
    assert is_valid_uuid(data["registration_id"])
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["placed_at"])
    assert data["status"] in _values(BidStatus)


def assert_sale(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["lot_id"])
    assert isinstance(data["hammer_price_cents"], int)
    assert isinstance(data["reserve_met"], bool)
    assert is_iso8601_timestamp(data["hammered_at"])
    assert isinstance(data["counter_round"], int) and data["counter_round"] >= 0
    assert data["status"] in _values(SaleStatus)


def assert_invoice(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["sale_id"])
    assert data["settlement_variant"] in _values(SettlementVariant)
    assert data["payment_status"] in _values(InvoicePaymentStatus)
    assert data["release_status"] in _values(InvoiceReleaseStatus)
    assert isinstance(data["is_cross_border"], bool)
    assert is_iso8601_timestamp(data["grace_end_at"])
    assert is_iso8601_timestamp(data["payment_due_at"])
    assert_invoice_arithmetic(data)


def assert_payment(data: dict):
    assert_append_only_record(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ["WIRE", "CARD", "FINANCED_DRAW"]
    assert data["status"] in _values(PaymentStatus)
    assert is_iso8601_timestamp(data["received_at"])


def assert_export_packet(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["destination_country_code"], str)
    assert len(data["destination_country_code"]) == 2
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in _values(ExportPacketStatus)


def assert_loadout_slot(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["bay_id"])
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])
    assert data["slot_end"] > data["slot_start"]
    assert isinstance(data["tonnage_kg"], int) and data["tonnage_kg"] > 0
    assert data["transport_mode"] in [
        "BUYER_ARRANGED",
        "HOUSE_BROKERED",
        "RAIL",
        "OCEAN_CONTAINER",
    ]
    assert data["status"] in _values(LoadoutSlotStatus)


def assert_consignor_settlement(data: dict):
    assert_versioned_record(data)
    assert is_valid_uuid(data["sale_id"])
    assert isinstance(data["gross_proceeds_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["net_proceeds_cents"], int)
    assert data["status"] in _values(ConsignorSettlementStatus)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_deposit_ledger_conserved(bidder: dict):
    """`deposit_total_cents` always equals held + available + forfeited."""
    total = bidder["deposit_total_cents"]
    parts = (
        bidder["deposit_held_cents"]
        + bidder["deposit_available_cents"]
        + bidder["deposit_forfeited_cents"]
    )
    assert total == parts, (
        "deposit_total_cents must equal deposit_held_cents + deposit_available_cents "
        f"+ deposit_forfeited_cents; got {total} != {parts}"
    )
    for field in (
        "deposit_total_cents",
        "deposit_held_cents",
        "deposit_available_cents",
        "deposit_forfeited_cents",
    ):
        assert bidder[field] >= 0, f"{field} must never go negative, got {bidder[field]}"


def assert_invoice_arithmetic(invoice: dict):
    """The invoice's own totals must be internally consistent."""
    expected_subtotal = (
        invoice["hammer_price_cents"]
        + invoice["buyer_premium_cents"]
        + invoice["documentation_fee_cents"]
        + invoice["title_transfer_fee_cents"]
        + invoice["financing_fee_cents"]
    )
    assert invoice["subtotal_cents"] == expected_subtotal, (
        "subtotal_cents must be the hammer price plus buyer premium, documentation fee, "
        f"title transfer fee and financing fee; got {invoice['subtotal_cents']} != "
        f"{expected_subtotal}"
    )
    expected_total = (
        invoice["subtotal_cents"]
        + invoice["tax_cents"]
        + invoice["storage_fee_cents"]
        - invoice["credit_memo_cents"]
        - invoice["deposit_applied_cents"]
    )
    assert invoice["total_due_cents"] == expected_total, (
        "total_due_cents must be subtotal + tax + storage - credit memo - deposit "
        f"applied; got {invoice['total_due_cents']} != {expected_total}"
    )
    assert invoice["outstanding_cents"] == max(
        0, invoice["total_due_cents"] - invoice["amount_paid_cents"]
    ), (
        "outstanding_cents must be the larger of 0 and total_due_cents less "
        f"amount_paid_cents; got {invoice['outstanding_cents']}"
    )


def assert_tax_rate_precision(invoice: dict):
    """`tax_rate_applied` is carried to four decimal places."""
    rate = invoice["tax_rate_applied"]
    assert isinstance(rate, (int, float)), "tax_rate_applied must be numeric"
    assert round(float(rate), 4) == float(rate), (
        f"tax_rate_applied must be expressed to four decimal places, got {rate}"
    )


def assert_grade_score_precision(report: dict):
    """`grade_score` is carried to two decimal places."""
    score = report["grade_score"]
    assert round(float(score), 2) == float(score), (
        f"grade_score must be expressed to two decimal places, got {score}"
    )


def assert_auction_lot_counts_consistent(auction: dict):
    """Sold plus unsold lots can never exceed the assigned lot count."""
    assert (
        auction["sold_lot_count"] + auction["unsold_lot_count"]
        <= auction["assigned_lot_count"]
    ), (
        "sold_lot_count + unsold_lot_count must not exceed assigned_lot_count; got "
        f"{auction['sold_lot_count']} + {auction['unsold_lot_count']} > "
        f"{auction['assigned_lot_count']}"
    )
