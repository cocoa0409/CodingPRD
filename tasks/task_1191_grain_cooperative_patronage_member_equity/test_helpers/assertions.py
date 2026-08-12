"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields per PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["patron_ref"], str) and data["patron_ref"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["member_class"] in [
        "INDIVIDUAL", "PARTNERSHIP", "CORPORATION", "LLC", "ESTATE",
    ]
    assert data["status"] in [
        "ACTIVE", "INACTIVE", "WITHDRAWN", "DECEASED", "EXPELLED",
    ]
    assert isinstance(data["is_producer_member"], bool)
    for field in (
        "capital_share_balance_cents", "qualified_equity_cents",
        "nonqualified_equity_cents", "per_unit_retains_cents",
        "total_patronage_volume_bu",
    ):
        assert isinstance(data[field], int), f"{field} must be integer"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_delegate_district(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["max_delegates"], int)
    assert data["status"] in ["ACTIVE", "MERGED", "RETIRED"]


def assert_delegate(data: dict):
    _assert_common(data)
    assert isinstance(data["district_id"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["is_seated"], bool)


def assert_fiscal_year(data: dict):
    _assert_common(data)
    assert isinstance(data["year_code"], str) and data["year_code"]
    assert data["status"] in [
        "OPEN", "CLOSED_PROVISIONAL", "UNDER_AUDIT", "CLOSED_FINAL", "REOPENED",
    ]
    assert isinstance(data["net_margin_cents"], int)


def assert_delivery(data: dict):
    _assert_common(data)
    assert data["commodity"] in ["CORN", "SOYBEAN", "WHEAT", "SORGHUM", "SUNFLOWER"]
    assert isinstance(data["gross_bushels"], int)
    assert data["status"] in ["BOOKED", "SETTLED", "CANCELLED"]
    assert isinstance(data["is_patron_sourced"], bool)


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "AMENDED", "REVERSED"]
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert data["tier_code"] in ["T1", "T2", "T3"]
    assert isinstance(data["allocated_volume_bu"], int)
    for field in (
        "qualified_allocation_cents", "nonqualified_allocation_cents",
        "cash_paid_cents", "qualified_equity_issued_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_certificate(data: dict):
    _assert_common(data)
    assert data["equity_class"] in ["QUALIFIED", "NONQUALIFIED"]
    assert data["status"] in [
        "ISSUED", "ACTIVE", "PARTIALLY_REDEEMED", "REDEEMED",
        "REVOKED", "ESCHEATED", "FROZEN",
    ]
    assert isinstance(data["face_value_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert 0 <= data["outstanding_cents"] <= data["face_value_cents"], (
        "outstanding_cents must lie in [0, face_value_cents]"
    )


def assert_cycle(data: dict):
    _assert_common(data)
    assert data["equity_class"] in ["QUALIFIED", "NONQUALIFIED"]
    assert data["status"] in ["PLANNED", "OPEN", "CLOSED", "CANCELLED"]
    assert isinstance(data["budget_cap_cents"], int)
    assert isinstance(data["redeemed_cents"], int)


def assert_resolution(data: dict):
    _assert_common(data)
    assert data["kind"] in [
        "OPEN_REVOLVEMENT", "APPROVE_ESTATE", "APPROVE_RETIREMENT",
        "APPROVE_SPECIAL_REDEMPTION", "AMEND_ALLOCATION", "AUTHORIZE_ESCHEAT",
    ]
    assert data["status"] in ["PROPOSED", "VOTING", "PASSED", "REJECTED", "TABLED"]
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["quorum_required"], int)


def assert_redemption_request(data: dict):
    _assert_common(data)
    assert data["kind"] in [
        "ESTATE", "RETIREMENT", "SPECIAL_HARDSHIP", "CYCLE_REDEMPTION",
    ]
    assert data["status"] in [
        "PENDING", "UNDER_REVIEW", "APPROVED", "REJECTED",
        "PAID", "APPEALED", "CANCELLED",
    ]
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["certificate_ids"], list)


def assert_estate_claim(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "FILED", "PROBATED", "APPROVED", "DENIED", "DISTRIBUTED", "LAPSED",
    ]
    assert isinstance(data["claim_window_days"], int)
    assert isinstance(data["claim_amount_cents"], int)


def assert_unclaimed_lot(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DORMANT", "NOTIFIED", "ESCHEAT_PENDING", "ESCHEATED", "RECOVERED",
    ]
    assert isinstance(data["dormancy_years"], int)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_tax_form(data: dict):
    _assert_common(data)
    assert data["form_type"] in [
        "FORM_1099_PATR", "FORM_1099_DIV", "CORRECTED_1099_PATR",
    ]
    assert data["status"] in ["DRAFT", "ISSUED", "CORRECTED", "VOID"]
    assert isinstance(data["is_corrected"], bool)


def assert_allocation_slice_identity(alloc: dict):
    """PRD §3.3: cash plus qualified equity reconstitutes the qualified slice."""
    assert (
        alloc["cash_paid_cents"] + alloc["qualified_equity_issued_cents"]
        == alloc["qualified_allocation_cents"]
    ), (
        "cash_paid_cents + qualified_equity_issued_cents must equal "
        "qualified_allocation_cents (rounding residual lands in equity)"
    )
