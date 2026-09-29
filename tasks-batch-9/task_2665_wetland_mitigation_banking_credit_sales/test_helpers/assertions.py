"""Entity assertions and domain invariant checkers."""

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

CREDIT_TOLERANCE = 0.005


def assert_common_resource_fields(data: dict) -> None:
    """Every resource carries id, created_at, updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_append_only_event_fields(data: dict) -> None:
    """Immutable events carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only events carry no updated_at"
    assert "version" not in data, "append-only events carry no version"


def assert_sponsor(data: dict) -> None:
    assert_common_resource_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["legal_entity_type"] in ("PRIVATE_ENTREPRENEURIAL", "PUBLIC_AGENCY", "NGO")
    assert isinstance(data["performance_bond_cents"], int)
    assert data["performance_bond_cents"] >= 0
    assert isinstance(data["banks_count"], int) and data["banks_count"] >= 0
    assert isinstance(data["good_standing"], bool)


def assert_permittee(data: dict) -> None:
    assert_common_resource_fields(data)
    assert isinstance(data["organization_name"], str) and data["organization_name"]
    assert isinstance(data["permit_number"], str)
    assert isinstance(data["impact_huc8_code"], str) and len(data["impact_huc8_code"]) == 8
    assert data["required_credits"] > 0
    assert isinstance(data["deposited_cents"], int) and data["deposited_cents"] >= 0
    assert isinstance(data["escrow_balance_cents"], int)
    assert data["assigned_credits"] >= 0
    assert data["unmet_requirement_credits"] >= 0


def assert_irt_member(data: dict) -> None:
    assert_common_resource_fields(data)
    assert isinstance(data["member_name"], str) and data["member_name"]
    assert data["agency"] in ("USACE", "EPA", "USFWS", "STATE_DEQ", "TRIBAL")
    assert isinstance(data["veto_authority"], bool)
    assert data["roster_status"] in ("SEATED", "RECUSED")


def assert_bank(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["sponsor_id"])
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["site_huc8_code"], str) and len(data["site_huc8_code"]) == 8
    assert isinstance(data["service_area_huc8_codes"], list)
    assert 1 <= len(data["service_area_huc8_codes"]) <= 8
    assert data["site_huc8_code"] in data["service_area_huc8_codes"]
    assert data["hgm_class"] in ("RIVERINE", "DEPRESSIONAL", "SLOPE", "FLATS", "ESTUARINE")
    assert data["annual_stewardship_cost_cents"] > 0
    assert data["status"] in (
        "DRAFT",
        "PROSPECTUS_REVIEW",
        "INSTRUMENT_EXECUTED",
        "MONITORING",
        "SUSPENDED",
        "CLOSED",
    )
    assert data["sales_posture"] in ("OPEN", "RESTRICTED", "SOLD_OUT", "FROZEN")
    assert isinstance(data["easement_recorded"], bool)
    assert isinstance(data["stewardship_required_cents"], int)
    assert isinstance(data["stewardship_funded_cents"], int)
    assert isinstance(data["deferral_count"], int)
    assert isinstance(data["open_quote_count"], int)
    assert_credit_conservation(data)


def assert_credit_conservation(bank: dict) -> None:
    """Released credits equal the sum of sold, on-hold and available credits
    (PRD §2.11)."""
    released = bank["credits_released"]
    total = bank["credits_sold"] + bank["credits_on_hold"] + bank["credits_available"]
    assert released == pytest.approx(total, abs=CREDIT_TOLERANCE), (
        f"conservation broken: credits_released {released} != "
        f"credits_sold {bank['credits_sold']} + credits_on_hold "
        f"{bank['credits_on_hold']} + credits_available {bank['credits_available']}"
    )
    assert bank["credits_on_hold"] >= -CREDIT_TOLERANCE, "credits_on_hold may not go negative"
    assert bank["credits_available"] >= -CREDIT_TOLERANCE, (
        "credits_available may not go negative"
    )


def assert_prospectus(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "REVISION_REQUESTED",
        "APPROVED",
        "REJECTED",
    )
    assert data["revision_round"] in (1, 2)
    for tally in ("concur_count", "object_count", "abstain_count"):
        assert isinstance(data[tally], int) and data[tally] >= 0
    assert isinstance(data["veto_recorded"], bool)


def assert_prospectus_vote(data: dict) -> None:
    assert_append_only_event_fields(data)
    assert is_valid_uuid(data["prospectus_id"])
    assert is_valid_uuid(data["irt_member_id"])
    assert data["position"] in ("CONCUR", "OBJECT", "ABSTAIN")
    assert isinstance(data["is_veto"], bool)
    assert isinstance(data["revision_round"], int)


def assert_work_plan(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "RETURNED")
    assert data["invasive_control_protocol"] in ("MECHANICAL", "HERBICIDE", "INTEGRATED")
    assert isinstance(data["credit_strata"], list) and 1 <= len(data["credit_strata"]) <= 6
    assert data["total_planned_credits"] >= 0


def assert_performance_standard(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert data["standard_code"] in (
        "HYDROPERIOD_DAYS",
        "INVASIVE_COVER_PCT",
        "NATIVE_COVER_PCT",
        "STEM_DENSITY_PER_ACRE",
    )
    assert data["comparator"] in ("GTE", "LTE")
    assert data["threshold_value"] > 0
    assert data["weight"] > 0
    assert data["effective_from_year"] >= 1


def assert_milestone(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert data["milestone_code"] in (
        "INSTRUMENT_EXECUTION",
        "CONSTRUCTION_COMPLETE",
        "PERF_YEAR_3",
        "PERF_YEAR_5",
        "PERF_YEAR_10",
    )
    assert 0 < data["release_pct"] <= 1
    assert data["status"] in ("PENDING", "CLAIMED", "APPROVED", "DEFERRED")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"], "window_end must follow window_start"


def assert_monitoring_report(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert data["monitoring_year"] >= 1
    assert data["review_status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert data["compliance_status"] in ("UNEVALUATED", "PASS", "PARTIAL", "FAIL")
    assert isinstance(data["failed_standard_codes"], list)
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_remedial_action(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["monitoring_report_id"])
    assert data["status"] in ("OPEN", "WORK_SUBMITTED", "REINSPECTION", "CLEARED", "FAILED")
    assert data["round_number"] in (1, 2, 3)
    assert isinstance(data["corrective_scope"], str)
    assert data["corrective_scope"].startswith("REMEDIATE: ")
    assert data["held_credits"] >= 0
    assert is_iso8601_timestamp(data["due_at"])
    assert is_iso8601_timestamp(data["opened_at"])


def assert_credit_sale(data: dict) -> None:
    assert_common_resource_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert is_valid_uuid(data["permittee_id"])
    assert data["credits_requested"] > 0
    assert isinstance(data["impact_huc8_code"], str) and len(data["impact_huc8_code"]) == 8
    assert data["service_area_tier"] in ("PRIMARY", "SECONDARY")
    assert data["status"] in (
        "QUOTED",
        "RESERVED",
        "EXECUTED",
        "ASSIGNED",
        "CANCELLED",
        "EXPIRED",
    )
    assert isinstance(data["quoted_price_cents"], int)
    assert data["quoted_demand_index"] >= 0


def assert_ledger_entry(data: dict) -> None:
    assert_append_only_event_fields(data)
    assert is_valid_uuid(data["bank_id"])
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert data["entry_type"] in (
        "GENERATED",
        "RELEASED",
        "HOLD_PLACED",
        "HOLD_RELEASED",
        "SOLD",
        "SALE_REVERSED",
        "ASSIGNED",
    )
    assert data["source_entity_type"] in (
        "MITIGATION_BANK",
        "RELEASE_MILESTONE",
        "CREDIT_SALE",
        "REMEDIAL_ACTION",
    )
    assert is_valid_uuid(data["source_id"])
    assert isinstance(data["memo"], str)


def assert_ledger_sequence(entries: list) -> None:
    """The ledger is a per-bank sequence starting at 1 and rising by one, with
    balance_after the running accumulation of every delta_credits (PRD §2.11)."""
    running = 0.0
    for index, entry in enumerate(entries, start=1):
        assert_ledger_entry(entry)
        assert entry["sequence_number"] == index, (
            f"expected sequence_number {index}, got {entry['sequence_number']}"
        )
        running += entry["delta_credits"]
        assert entry["balance_after"] == pytest.approx(running, abs=CREDIT_TOLERANCE), (
            f"entry {index} ({entry['entry_type']}): balance_after "
            f"{entry['balance_after']} != running total {running}"
        )
        assert entry["balance_after"] >= -CREDIT_TOLERANCE, (
            f"entry {index} ({entry['entry_type']}) left a negative balance_after"
        )


def assert_ledger_shape(entries: list, expected) -> None:
    """Compare the ledger against a list of (entry_type, delta_credits,
    balance_after) triples in sequence order."""
    assert len(entries) == len(expected), (
        f"expected {len(expected)} ledger rows, got {len(entries)}: "
        f"{[e['entry_type'] for e in entries]}"
    )
    for index, (entry, (entry_type, delta, balance)) in enumerate(
        zip(entries, expected), start=1
    ):
        assert entry["entry_type"] == entry_type, (
            f"row {index}: expected {entry_type}, got {entry['entry_type']}"
        )
        assert entry["delta_credits"] == pytest.approx(delta, abs=CREDIT_TOLERANCE), (
            f"row {index} ({entry_type}): expected delta {delta}, "
            f"got {entry['delta_credits']}"
        )
        assert entry["balance_after"] == pytest.approx(balance, abs=CREDIT_TOLERANCE), (
            f"row {index} ({entry_type}): expected balance_after {balance}, "
            f"got {entry['balance_after']}"
        )


def assert_credits(actual, expected, label: str = "credits") -> None:
    """Credit quantities are decimal numbers carried to exactly 2 decimal
    places (PRD §2.5)."""
    assert actual == pytest.approx(expected, abs=CREDIT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_score(actual, expected, label: str = "attainment_score") -> None:
    """The attainment score and the demand index are held at 4 decimal places
    (PRD §2.5)."""
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual, expected, label: str = "cents") -> None:
    """Money is carried as integer cents throughout (PRD §2.5)."""
    assert isinstance(actual, int), f"{label} must be integer cents, got {actual!r}"
    assert actual == expected, f"{label}: expected {expected}, got {actual}"
