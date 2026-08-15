"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AbsorptionMethod,
    AgreementStatus,
    BondStatus,
    ClosingStatus,
    ConnectionStatus,
    DrawStatus,
    HOAStatus,
    LoanStatus,
    LotLienStatus,
    LotSalesStatus,
    LotType,
    ParcelStatus,
    PhaseStatus,
    UtilityType,
)


def assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_money(value, field):
    assert isinstance(value, int), f"{field} must be integer cents, got {value!r}"


def assert_parcel(data: dict):
    assert_common_fields(data)
    assert isinstance(data["parcel_name"], str) and data["parcel_name"]
    assert isinstance(data["county"], str) and data["county"]
    _assert_money(data["earnest_money_cents"], "earnest_money_cents")
    assert isinstance(data["planned_sellout_months"], int)
    assert data["absorption_method"] in [m.value for m in AbsorptionMethod]
    assert data["status"] in [s.value for s in ParcelStatus]
    assert isinstance(data["earnest_money_refunded"], bool)
    for field in ("total_lots_planned", "lots_closed_count", "lots_available_count"):
        assert isinstance(data[field], int) and data[field] >= 0, field
    for field in ("closed_pct", "straight_line_pace_pm",
                  "trailing_weighted_pace_pm", "selected_pace_pm"):
        assert isinstance(data[field], (int, float)), field
    assert isinstance(data["next_phase_release_eligible"], bool)
    # §3.1: acquisition_close_date is stamped at ACQUIRED and null otherwise.
    if data["status"] in (ParcelStatus.ACQUIRED.value, ParcelStatus.SOLD_OUT.value):
        assert is_iso8601_timestamp(data.get("acquisition_close_date") or "")
    else:
        assert data.get("acquisition_close_date") is None


def assert_phase(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["parcel_id"])
    assert isinstance(data["phase_name"], str) and data["phase_name"]
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["planned_lot_count"], int) and data["planned_lot_count"] >= 1
    assert is_iso8601_timestamp(data["selling_window_start"])
    assert is_iso8601_timestamp(data["selling_window_end"])
    assert isinstance(data["recorded_lot_count"], int) and data["recorded_lot_count"] >= 0
    assert data["status"] in [s.value for s in PhaseStatus]


def assert_bond(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["phase_id"])
    _assert_money(data["engineer_estimate_cents"], "engineer_estimate_cents")
    _assert_money(data["required_bond_cents"], "required_bond_cents")
    _assert_money(data["posted_bond_cents"], "posted_bond_cents")
    assert isinstance(data["work_accepted"], bool)
    assert data["status"] in [s.value for s in BondStatus]


def assert_builder(data: dict):
    assert_common_fields(data)
    assert isinstance(data["builder_name"], str) and data["builder_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["builder_id"])
    assert is_iso8601_timestamp(data["effective_date"])
    _assert_money(data["base_lot_price_cents"], "base_lot_price_cents")
    assert isinstance(data["escalator_rate_bp_per_quarter"], int)
    assert isinstance(data["price_cap_bp"], int) and data["price_cap_bp"] >= 10000
    assert isinstance(data["min_lots_per_quarter"], int)
    assert isinstance(data["scheduled_lot_count"], int)
    assert isinstance(data["closed_lot_count"], int) and data["closed_lot_count"] >= 0
    assert data["status"] in [s.value for s in AgreementStatus]


def assert_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["phase_id"])
    assert isinstance(data["lot_number"], int) and data["lot_number"] >= 1
    assert data["lot_type"] in [t.value for t in LotType]
    assert data["sales_status"] in [s.value for s in LotSalesStatus]
    assert data["lien_status"] in [s.value for s in LotLienStatus]
    # §3.2: reserved_agreement_id is null whenever the lot sits unreserved in PLATTED.
    if data["sales_status"] == LotSalesStatus.PLATTED.value:
        assert data.get("reserved_agreement_id") is None


def assert_closing(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["loan_id"])
    _assert_money(data["contract_price_cents"], "contract_price_cents")
    _assert_money(data["release_price_cents"], "release_price_cents")
    _assert_money(data["payment_applied_cents"], "payment_applied_cents")
    assert data["status"] in [s.value for s in ClosingStatus]
    # §3.5: the closing starts PENDING with payment_applied_cents zero and
    # finalized_at null; finalized_at is stamped with the current clock at finalize.
    if data["status"] == ClosingStatus.CLOSED.value:
        assert is_iso8601_timestamp(data.get("finalized_at") or "")
    else:
        assert data.get("finalized_at") is None
    if data["status"] == ClosingStatus.PENDING.value:
        assert data["payment_applied_cents"] == 0


def assert_loan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["parcel_id"])
    _assert_money(data["commitment_amount_cents"], "commitment_amount_cents")
    assert isinstance(data["release_price_floor_bp"], int)
    for field in ("outstanding_balance_cents", "total_drawn_cents",
                  "total_release_paid_cents"):
        _assert_money(data[field], field)
    # §3.5: the finalize clamp keeps the balance from ever going negative.
    assert data["outstanding_balance_cents"] >= 0
    assert data["status"] in [s.value for s in LoanStatus]


def assert_draw(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["requested_by_user_id"], str)
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    for item in data["line_items"]:
        assert isinstance(item["description"], str)
        _assert_money(item["amount_cents"], "line_items.amount_cents")
    for field in ("gross_amount_cents", "retainage_cents", "draw_fee_cents",
                  "net_disbursed_cents"):
        _assert_money(data[field], field)
    # §3.6: net is gross minus retainage minus fee.
    assert (data["gross_amount_cents"] - data["retainage_cents"]
            - data["draw_fee_cents"]) == data["net_disbursed_cents"]
    assert data["status"] in [s.value for s in DrawStatus]


def assert_hoa(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["parcel_id"])
    assert isinstance(data["hoa_name"], str) and data["hoa_name"]
    assert isinstance(data["control_transfer_pct_bp"], int)
    assert is_iso8601_timestamp(data["statutory_control_end"])
    # §3.8: board_seated_count is null until complete-transition records it.
    if data["status"] == HOAStatus.HOMEOWNER_CONTROL.value:
        assert isinstance(data["board_seated_count"], int)
    else:
        assert data.get("board_seated_count") is None
    assert data["status"] in [s.value for s in HOAStatus]


def assert_provider(data: dict):
    assert_common_fields(data)
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert data["utility_type"] in [t.value for t in UtilityType]
    assert isinstance(data["max_connections_per_day"], int)
    assert data["max_connections_per_day"] >= 1


def assert_connection(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["lot_id"])
    assert is_valid_uuid(data["provider_id"])
    assert is_iso8601_timestamp(data["scheduled_date"])
    _assert_money(data["impact_fee_cents"], "impact_fee_cents")
    assert data["status"] in [s.value for s in ConnectionStatus]


# ---------------------------------------------------------------------------
# Domain invariant checkers (PRD §2.9)
# ---------------------------------------------------------------------------

def assert_lot_inventory_conserved(phase: dict, lots: list):
    """PRD §2.9: recorded_lot_count always equals the sum of the phase's lots
    across the four sales statuses (PLATTED + RESERVED + UNDER_CONTRACT + CLOSED)."""
    buckets = {s.value: 0 for s in LotSalesStatus}
    for lot in lots:
        buckets[lot["sales_status"]] += 1
    total = sum(buckets.values())
    assert phase["recorded_lot_count"] == total, (
        f"recorded_lot_count {phase['recorded_lot_count']} != lot-status sum {total} "
        f"({buckets})")


def assert_loan_balance_conserved(loan: dict):
    """PRD §2.9 / §3.5: balances are integer cents and never negative."""
    _assert_money(loan["outstanding_balance_cents"], "outstanding_balance_cents")
    _assert_money(loan["total_drawn_cents"], "total_drawn_cents")
    _assert_money(loan["total_release_paid_cents"], "total_release_paid_cents")
    assert loan["outstanding_balance_cents"] >= 0
