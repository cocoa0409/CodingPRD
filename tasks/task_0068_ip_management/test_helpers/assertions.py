"""Entity assertions and domain invariant checkers for the IP Management API.

Every assertion walks the exact PRD-named fields. Append-only entities
(ContractTemplate, Evidence, Cost, AuditEntry) MUST NOT have updated_at /
version asserted — PRD §2.4 explicitly excludes those.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─────────────────────── Shared helpers ──────────────────────


def round_half_up(value: float) -> int:
    """Round-half-up to integer cents per PRD §2.5."""
    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def round_half_up_to_decimals(value: float, decimals: int = 2) -> float:
    """Round-half-up to N decimal places per PRD §2.5 (workload/perf rating)."""
    quantizer = Decimal("1").scaleb(-decimals)
    return float(
        Decimal(str(value)).quantize(quantizer, rounding=ROUND_HALF_UP)
    )


def _assert_common_versioned(data: Dict[str, Any]) -> None:
    """Shared invariant for entities that carry id, created_at, updated_at,
    version per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at not ISO8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at not ISO8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1, got {data.get('version')!r}"
    )


def _assert_common_append_only(data: Dict[str, Any]) -> None:
    """Shared invariant for entities that carry ONLY id + created_at
    (ContractTemplate, Evidence, Cost, AuditEntry per PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at not ISO8601: {data.get('created_at')!r}"


# ─────────────────── Entity-level assertions ──────────────────


def assert_business_unit(data: Dict[str, Any]) -> None:
    """PRD §3.1 BusinessUnit shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("code"), str) and len(data["code"]) >= 2
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("annual_budget_cents"), int)
    assert data["annual_budget_cents"] >= 0
    assert isinstance(data.get("actual_spend_cents"), int)
    assert data["actual_spend_cents"] >= 0
    assert data.get("status") in ("ACTIVE", "ARCHIVED")


def assert_agent(data: Dict[str, Any]) -> None:
    """PRD §3.1 Agent shape."""
    _assert_common_versioned(data)
    assert data.get("kind") in ("INTERNAL", "EXTERNAL")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("qualification_number"), str)
    assert isinstance(data.get("qualification_verified"), bool)
    assert isinstance(data.get("jurisdictions"), list)
    assert isinstance(data.get("hourly_rate_cents"), int)
    assert data["hourly_rate_cents"] >= 0
    assert data.get("status") in ("ACTIVE", "SUSPENDED")
    # Computed counts are non-negative ints (PRD §3.1).
    for field in (
        "active_case_count",
        "pending_action_count",
        "upcoming_deadline_count",
    ):
        assert isinstance(data.get(field), int)
        assert data[field] >= 0
    # Computed scores are numeric (PRD §3.1).
    for field in ("workload_score", "performance_rating"):
        assert isinstance(data.get(field), (int, float))


def assert_ip_right(data: Dict[str, Any]) -> None:
    """PRD §3.2 IPRight shape."""
    _assert_common_versioned(data)
    assert data.get("ip_type") in ("PATENT", "TRADEMARK", "COPYRIGHT")
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("handling_mode") in ("AGENCY", "SELF")
    assert isinstance(data.get("business_unit_id"), str)
    assert isinstance(data.get("primary_jurisdiction"), str)
    assert data.get("status") in (
        "DRAFT",
        "MATERIALS_READY",
        "FILED",
        "OFFICE_ACTION",
        "REGISTERED",
        "ABANDONED",
        "TRANSFERRED",
    )


def assert_jurisdiction_filing(data: Dict[str, Any]) -> None:
    """PRD §3.2 JurisdictionFiling shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("ip_right_id"), str)
    assert isinstance(data.get("jurisdiction"), str)
    assert isinstance(data.get("filing_number"), str)
    assert data.get("status") in ("FILED", "OFFICE_ACTION", "REGISTERED", "ABANDONED")


def assert_office_action(data: Dict[str, Any]) -> None:
    """PRD §3.2 ApplicationOfficeAction shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("ip_right_id"), str)
    assert isinstance(data.get("jurisdiction_filing_id"), str)
    assert isinstance(data.get("assigned_agent_id"), str)
    assert is_iso8601_timestamp(data.get("response_due_at", ""))
    assert data.get("status") in (
        "PENDING",
        "RESPONDED",
        "CLOSED_GRANTED",
        "CLOSED_ABANDONED",
    )


def assert_annual_fee(data: Dict[str, Any]) -> None:
    """PRD §3.3 AnnualFeeSchedule shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("ip_right_id"), str)
    assert isinstance(data.get("jurisdiction"), str)
    assert isinstance(data.get("fee_year"), int) and data["fee_year"] >= 1
    assert isinstance(data.get("base_fee_cents"), int) and data["base_fee_cents"] >= 0
    assert is_iso8601_timestamp(data.get("due_date", ""))
    assert is_iso8601_timestamp(data.get("grace_end_date", ""))
    assert isinstance(data.get("total_paid_cents"), int)
    assert isinstance(data.get("surcharge_cents"), int)
    assert data.get("status") in ("PENDING", "PAID", "LATE", "ABANDONED")


def assert_contract(data: Dict[str, Any]) -> None:
    """PRD §3.4 Contract shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("ip_right_id"), str)
    assert isinstance(data.get("template_id"), str)
    assert data.get("contract_type") in (
        "TRANSFER",
        "EXCLUSIVE_LICENSE",
        "NON_EXCLUSIVE_LICENSE",
    )
    assert isinstance(data.get("parties"), list) and len(data["parties"]) >= 2
    assert isinstance(data.get("filed_with_authority"), bool)
    assert data.get("status") in (
        "DRAFT",
        "SIGNING",
        "SIGNED",
        "FILED",
        "AMENDED",
        "TERMINATED",
    )


def assert_contract_template(data: Dict[str, Any]) -> None:
    """PRD §3.1 ContractTemplate shape — append-only per PRD §2.4."""
    _assert_common_append_only(data)
    assert isinstance(data.get("code"), str)
    assert data.get("contract_type") in (
        "TRANSFER",
        "EXCLUSIVE_LICENSE",
        "NON_EXCLUSIVE_LICENSE",
    )


def assert_royalty_schedule(data: Dict[str, Any]) -> None:
    """PRD §3.5 RoyaltySchedule shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("period_index"), int) and data["period_index"] >= 1
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data.get("forecast_revenue_cents"), int)
    assert data.get("status") in ("FORECAST", "SETTLED")


def assert_protection_case(data: Dict[str, Any]) -> None:
    """PRD §3.6 ProtectionCase shape."""
    _assert_common_versioned(data)
    assert isinstance(data.get("ip_right_id"), str)
    assert isinstance(data.get("assigned_agent_id"), str)
    assert isinstance(data.get("business_unit_id"), str)
    assert data.get("status") in ("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED")
    assert data.get("route") in (
        "NONE",
        "DEMAND_LETTER",
        "LITIGATION",
        "MEDIATION",
        "ARBITRATION",
    )


def assert_evidence(data: Dict[str, Any]) -> None:
    """PRD §3.6 Evidence shape — append-only per PRD §2.4."""
    _assert_common_append_only(data)
    assert data.get("kind") in ("WITNESS", "DOCUMENT", "SAMPLE", "DIGITAL")
    assert is_iso8601_timestamp(data.get("collected_at", ""))
    assert isinstance(data.get("storage_uri"), str)


def assert_cost(data: Dict[str, Any]) -> None:
    """PRD §3.7 Cost shape — append-only per PRD §2.4."""
    _assert_common_append_only(data)
    assert data.get("category") in (
        "APPLICATION",
        "ANNUAL_FEE",
        "LITIGATION",
        "AGENT_FEE",
    )
    assert isinstance(data.get("currency"), str)
    assert isinstance(data.get("amount_native_cents"), int)
    assert isinstance(data.get("fx_rate_to_usd"), (int, float))
    assert isinstance(data.get("amount_usd_cents"), int)
    assert isinstance(data.get("allocations"), list)


def assert_audit_entry(data: Dict[str, Any]) -> None:
    """PRD §2.9 AuditEntry shape — append-only per PRD §2.4."""
    _assert_common_append_only(data)
    assert isinstance(data.get("subject_entity"), str)
    assert isinstance(data.get("subject_id"), str)
    assert data.get("event_type") in (
        "STATUS_CHANGE",
        "CONTRACT_RECORD",
        "PAYMENT_SETTLED",
        "EVIDENCE_ADDED",
        "EXTERNAL_SYNC",
    )


# ─────────────────────── Domain invariants ───────────────────


def assert_allocations_sum_equals_amount_usd_cents(cost: Dict[str, Any]) -> None:
    """PRD §3.7: "the sum of all `allocated_cents` equals `amount_usd_cents`
    exactly". Tested directly because it is a load-bearing invariant of the
    cost-allocation algorithm and the conservation property §1.8 names."""
    total = cost.get("amount_usd_cents")
    allocations = cost.get("allocations") or []
    s = sum(int(a["allocated_cents"]) for a in allocations)
    assert s == total, (
        f"sum(allocated_cents) {s} != amount_usd_cents {total} — "
        f"PRD §3.7 invariant violated"
    )


def assert_damages_waterfall_invariant(case: Dict[str, Any]) -> None:
    """PRD §3.6: "their sum is exactly equal to `recovered_amount_cents`."

    Asserts the conservation property of the damages waterfall.
    """
    dist = case.get("distributed") or {}
    total = (
        int(dist.get("legal_paid", 0))
        + int(dist.get("agent_paid", 0))
        + int(dist.get("punitive_paid", 0))
        + int(dist.get("rights_holder_paid", 0))
    )
    expected = int(case.get("recovered_amount_cents", 0))
    assert total == expected, (
        f"distributed sum {total} != recovered_amount_cents {expected} — "
        f"PRD §3.6 waterfall invariant violated"
    )


def assert_version_increased(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """PRD §2.4: "version ... increments by 1 on every mutation"."""
    assert after["version"] > before["version"], (
        f"version did not increment: before={before['version']} "
        f"after={after['version']}"
    )


def assert_no_field(data: Dict[str, Any], field: str) -> None:
    """For append-only entities (PRD §2.4) — assert updated_at / version absent."""
    assert field not in data, (
        f"append-only entity must not carry {field!r}; got {data.get(field)!r}"
    )


def expected_surcharge_cents(base_fee_cents: int, days_late: int) -> int:
    """Reproduce PRD §3.3 surcharge tiers for boundary assertions."""
    if days_late <= 0:
        rate = 0.0
    elif 1 <= days_late <= 30:
        rate = 0.10
    elif 31 <= days_late <= 90:
        rate = 0.25
    elif 91 <= days_late <= 180:
        rate = 0.50
    else:
        return 0  # days_late > 180 → ABANDONED, no surcharge
    return round_half_up(base_fee_cents * rate)


def expected_cost_allocations(
    amount_usd_cents: int, allocation_rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Reproduce PRD §3.7 round-per-allocation-then-remainder rule for tests."""
    allocations: List[Dict[str, Any]] = []
    running_sum = 0
    n = len(allocation_rules)
    for i in range(n - 1):
        rule = allocation_rules[i]
        portion = round_half_up(
            amount_usd_cents * int(rule["percent_bps"]) / 10000
        )
        allocations.append(
            {
                "business_unit_id": rule["business_unit_id"],
                "percent_bps": int(rule["percent_bps"]),
                "allocated_cents": portion,
            }
        )
        running_sum += portion
    last = allocation_rules[-1]
    allocations.append(
        {
            "business_unit_id": last["business_unit_id"],
            "percent_bps": int(last["percent_bps"]),
            "allocated_cents": amount_usd_cents - running_sum,
        }
    )
    return allocations


def expected_waterfall(
    recovered: int, legal: int, agent: int, punitive_cap: int
) -> Dict[str, int]:
    """Reproduce PRD §3.6 damages waterfall for tests."""
    remaining = recovered
    legal_paid = min(remaining, legal)
    remaining -= legal_paid
    agent_paid = min(remaining, agent)
    remaining -= agent_paid
    punitive_paid = min(remaining, punitive_cap)
    remaining -= punitive_paid
    rights_holder_paid = remaining
    return {
        "legal_paid": legal_paid,
        "agent_paid": agent_paid,
        "punitive_paid": punitive_paid,
        "rights_holder_paid": rights_holder_paid,
    }
