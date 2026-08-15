"""Payload factories — one per entity, input fields only (per PRD §3)."""

from .constants import TEST_DEFAULTS


def customer_payload(**overrides) -> dict:
    """PRD §3.1: ShopManager onboarding a Customer."""
    defaults = {
        "name": "AeroAir",
        "certificate_number": "AIR-001",
        "contract_tat_hours": TEST_DEFAULTS["CONTRACT_TAT_HOURS"],
        "tat_penalty_rate_cents_per_hour": TEST_DEFAULTS["TAT_PENALTY_RATE_CENTS_PER_HOUR"],
        "tat_penalty_cap_pct": TEST_DEFAULTS["TAT_PENALTY_CAP_PCT"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def part_payload(**overrides) -> dict:
    """PRD §3.1: catalog part."""
    defaults = {
        "part_number": TEST_DEFAULTS["PART_NUMBER"],
        "ata_chapter": TEST_DEFAULTS["ATA_CHAPTER"],
        "is_rotable": True,
        "cmm_reference": TEST_DEFAULTS["CMM_REFERENCE"],
        "replacement_value_cents": TEST_DEFAULTS["REPLACEMENT_VALUE_CENTS"],
        "warranty_cycle_limit": TEST_DEFAULTS["WARRANTY_CYCLE_LIMIT"],
        "warranty_month_limit": TEST_DEFAULTS["WARRANTY_MONTH_LIMIT"],
        "flat_overhaul_price_cents": TEST_DEFAULTS["FLAT_OVERHAUL_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def directive_payload(**overrides) -> dict:
    """PRD §3.1: AD/SB registration against a part."""
    defaults = {
        "directive_type": "AD",
        "directive_number": "AD-2026-32-01",
        "mandatory": True,
        "description": "Actuator inspection",
    }
    defaults.update(overrides)
    return defaults


def unit_payload(part_id: str, **overrides) -> dict:
    """PRD §3.2: unit registration (birth record)."""
    defaults = {
        "part_id": part_id,
        "serial_number": "SN-U1",
        "ownership": "CUSTOMER",
        "condition_status": "UNSERVICEABLE",
        "custody_status": "OFF_SITE",
        "total_cycles": 4800,
        "cycles_since_overhaul": 300,
        "manufactured_at": "2015-06-01",
    }
    defaults.update(overrides)
    return defaults


def work_order_payload(customer_id: str, unit_id: str, **overrides) -> dict:
    """PRD §3.2: work-order induction."""
    defaults = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "work_scope": "OVERHAUL",
    }
    defaults.update(overrides)
    return defaults


def discrepancy_payload(**overrides) -> dict:
    """PRD §3.3: discrepancy card."""
    defaults = {
        "finding_text": "Worn bearing",
        "severity": "MAJOR",
    }
    defaults.update(overrides)
    return defaults


def quote_payload(**overrides) -> dict:
    """PRD §3.3: quote submission."""
    defaults = {
        "labor_estimate_cents": TEST_DEFAULTS["LABOR_ESTIMATE_CENTS"],
        "parts_estimate_cents": TEST_DEFAULTS["PARTS_ESTIMATE_CENTS"],
        "scrap_option_ack": False,
    }
    defaults.update(overrides)
    return defaults


def quote_approval_payload(expected_work_order_version: int, **overrides) -> dict:
    """PRD §3.3 + §2.7: customer quote approval."""
    defaults = {"expected_work_order_version": expected_work_order_version}
    defaults.update(overrides)
    return defaults


def quote_decline_payload(disposition: str, **overrides) -> dict:
    """PRD §3.3: quote decline."""
    defaults = {"disposition": disposition}
    defaults.update(overrides)
    return defaults


def directive_compliance_payload(**overrides) -> dict:
    """PRD §3.4: record directive compliance."""
    defaults = {
        "directive_number": "AD-2026-32-01",
        "result": "COMPLIED",
    }
    defaults.update(overrides)
    return defaults


def parts_requisition_payload(**overrides) -> dict:
    """PRD §3.4: parts requisition."""
    defaults = {
        "part_number": "BRG-32-99",
        "quantity": 1,
        "requested_source": "OEM",
    }
    defaults.update(overrides)
    return defaults


def source_approval_payload(approved: bool, **overrides) -> dict:
    """PRD §3.4: buyer source approval."""
    defaults = {"approved": approved}
    defaults.update(overrides)
    return defaults


def pma_approval_payload(approved: bool, **overrides) -> dict:
    """PRD §3.4: customer PMA approval."""
    defaults = {"approved": approved}
    defaults.update(overrides)
    return defaults


def receive_payload(unit_cost_cents: int, **overrides) -> dict:
    """PRD §3.4: receive a requisition."""
    defaults = {"unit_cost_cents": unit_cost_cents}
    defaults.update(overrides)
    return defaults


def test_cell_payload(**overrides) -> dict:
    """PRD §3.5: configure a test cell."""
    defaults = {
        "name": "CELL-A",
        "supported_ata_chapters": [TEST_DEFAULTS["ATA_CHAPTER"]],
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def booking_payload(work_order_id: str, **overrides) -> dict:
    """PRD §3.5: book a test-cell window."""
    defaults = {
        "work_order_id": work_order_id,
        "start_time": "2026-08-02T01:00:00Z",
        "end_time": "2026-08-02T05:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def test_results_payload(result: str = "PASS", **overrides) -> dict:
    """PRD §3.5: record ATP result."""
    defaults = {
        "result": result,
        "atp_reference": "ATP-1",
    }
    defaults.update(overrides)
    return defaults


def exchange_agreement_payload(customer_id: str, part_id: str, **overrides) -> dict:
    """PRD §3.7: open an exchange agreement."""
    defaults = {
        "customer_id": customer_id,
        "part_id": part_id,
    }
    defaults.update(overrides)
    return defaults


def core_return_payload(core_unit_id: str, core_teardown_estimate_cents: int, **overrides) -> dict:
    """PRD §3.7: core return."""
    defaults = {
        "core_unit_id": core_unit_id,
        "core_teardown_estimate_cents": core_teardown_estimate_cents,
    }
    defaults.update(overrides)
    return defaults


def lease_agreement_payload(customer_id: str, unit_id: str, expected_unit_version: int, **overrides) -> dict:
    """PRD §3.8 + §2.7: lease create."""
    defaults = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "start_date": "2026-08-10",
        "end_date": "2026-08-14",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def warranty_claim_payload(original_work_order_id: str, **overrides) -> dict:
    """PRD §3.9: file a warranty claim."""
    defaults = {
        "original_work_order_id": original_work_order_id,
        "claim_cycles_used": 100,
        "claim_months_used": 5,
        "failure_description": "Premature failure",
    }
    defaults.update(overrides)
    return defaults


def warranty_review_payload(decision: str, **overrides) -> dict:
    """PRD §3.9: review a warranty claim."""
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents: int, **overrides) -> dict:
    """PRD §3.6: invoice payment."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    """PRD §2.5: advance the logical clock."""
    return {"to_iso8601": to_iso8601}
