"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive int, got {data.get('version')!r}"
        )
    else:
        assert "updated_at" not in data, "immutable log must not carry updated_at"
        assert "version" not in data, "immutable log must not carry version"


def assert_compliance_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["epa_registration_id"], str) and data["epa_registration_id"]
    assert isinstance(data["escrow_reserved_cents"], int)
    assert isinstance(data["spent_cents"], int)


def assert_obligation_year(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["projected_volume_gal"], int)
    assert data["status"] in ("OPEN", "VOLUME_CLOSED", "FINALIZED")
    assert data["compliance_posture"] in ("ON_TRACK", "SHORTFALL", "SATISFIED")
    for k in ("cellulosic", "biomass_diesel", "advanced", "total"):
        assert isinstance(data[f"provisional_rvo_{k}_rins"], int)
        assert isinstance(data[f"retired_{k}_rins"], int)
        assert isinstance(data[f"retired_prior_{k}_rins"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["qap_audited"], bool)
    assert data["diligence_status"] in ("UNVETTED", "APPROVED", "REJECTED", "REVOKED")


def assert_rin_lot(data: dict):
    _assert_common(data)
    assert data["origin"] in ("GENERATED", "PURCHASED")
    assert data["d_code"] in ("D3", "D4", "D5", "D6")
    assert isinstance(data["vintage_year"], int)
    assert isinstance(data["rin_qty"], int)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "INVALIDATED")
    for k in ("attached_qty", "separated_qty", "pending_retired_qty",
              "retired_qty", "invalidated_qty", "expired_qty", "available_qty"):
        assert isinstance(data[k], int), f"{k} must be int"


def assert_blending_record(data: dict):
    # Immutable event log: id + created_at only (PRD §2.4).
    _assert_common(data, with_version=False)
    assert isinstance(data["blended_gallons"], int)
    assert isinstance(data["rin_lot_id"], str)


def assert_rin_trade(data: dict):
    _assert_common(data)
    assert data["d_code"] in ("D3", "D4", "D5", "D6")
    assert isinstance(data["rin_qty"], int)
    assert isinstance(data["price_per_rin_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["transfer_status"] in (
        "PENDING", "DELIVERED", "VERIFIED", "INVALIDATED", "CANCELLED",
    )


def assert_retirement_batch(data: dict):
    _assert_common(data)
    assert data["category"] in (
        "CELLULOSIC", "BIOMASS_DIESEL", "ADVANCED", "TOTAL_RENEWABLE",
    )
    assert data["d_code"] in ("D3", "D4", "D5", "D6")
    assert isinstance(data["rin_qty"], int)
    assert isinstance(data["allocations"], list)
    assert isinstance(data["prior_vintage_qty"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_compliance_report(data: dict):
    _assert_common(data)
    assert data["report_type"] in ("QUARTERLY", "ANNUAL")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["amendment_required"], bool)


def assert_attest_engagement(data: dict):
    _assert_common(data)
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert data["status"] in (
        "ENGAGED", "FIELDWORK", "FINDINGS_ISSUED", "REMEDIATION", "CLOSED_CLEAN",
    )


def assert_state_program(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["program_type"] == "LCFS"


def assert_state_credit_report(data: dict):
    _assert_common(data)
    assert isinstance(data["fuel_gallons"], int)
    assert data["status"] in ("PROVISIONAL", "VERIFIED")


def assert_price_quote(data: dict):
    _assert_common(data)
    assert data["d_code"] in ("D3", "D4", "D5", "D6")
    assert isinstance(data["price_cents"], int)


def assert_lot_rin_conservation(lot: dict):
    """Per-lot RIN conservation invariant (PRD §3.2): rin_qty fully accounted
    for as the sum of the six buckets."""
    total = (
        lot["attached_qty"] + lot["separated_qty"] + lot["pending_retired_qty"]
        + lot["retired_qty"] + lot["invalidated_qty"] + lot["expired_qty"]
    )
    assert total == lot["rin_qty"], (
        f"lot conservation broken: buckets sum to {total}, rin_qty {lot['rin_qty']}"
    )
