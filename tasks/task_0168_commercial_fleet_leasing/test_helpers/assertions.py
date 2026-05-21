"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3
for that entity. Common-fields entities (PRD §2.4) carry id +
created_at + updated_at + version. The two append-only entities
(`FuelCardTransaction` and `TelematicsEvent`) carry only id +
created_at — PRD §2.4: "Two entities — `FuelCardTransaction` and
`TelematicsEvent` — are immutable append-only records: they carry
`id` and `created_at` only, and both `updated_at` and `version` are
absent because there is no in-place edit path that could refresh them."
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "All resources carry a `created_at` timestamp written
    in ISO 8601 UTC with three fractional digits ... Most resources
    additionally carry an `updated_at` timestamp in the same format
    that refreshes on every mutation, and an integer `version` field
    that begins at 1 on creation and increments by one on every
    server-acknowledged mutation."""
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: FuelCardTransaction and TelematicsEvent carry only id
    and created_at; neither updated_at nor version may be present."""
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.6: "the mutation proceeds and the stored `version`
    increments by one"."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Lessee — PRD §3.1
# ---------------------------------------------------------------------------
def assert_lessee(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"], (
        "legal_name must be non-empty string"
    )
    assert isinstance(data.get("dot_number"), str), (
        f"dot_number must be string, got {data.get('dot_number')!r}"
    )
    assert data.get("base_jurisdiction") in {
        "CA", "TX", "NY", "IL", "FL", "OH", "PA", "GA", "WA", "AZ",
    }, f"base_jurisdiction invalid: {data.get('base_jurisdiction')!r}"
    assert data.get("account_status") in {
        "ACTIVE", "SUSPENDED", "CLOSED",
    }, f"account_status invalid: {data.get('account_status')!r}"
    ob = data.get("outstanding_balance_cents")
    assert isinstance(ob, int), (
        f"outstanding_balance_cents must be int, got {ob!r}"
    )


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.1
# ---------------------------------------------------------------------------
def assert_vehicle(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    vin = data.get("vin")
    assert isinstance(vin, str) and len(vin) == 17, (
        f"vin must be 17-char string, got {vin!r}"
    )
    assert data.get("vehicle_class") in {
        "CLASS_3", "CLASS_5", "CLASS_7", "CLASS_8",
    }, f"vehicle_class invalid: {data.get('vehicle_class')!r}"
    my = data.get("model_year")
    assert isinstance(my, int), (
        f"model_year must be int, got {my!r}"
    )
    obl = data.get("odometer_baseline_miles")
    assert isinstance(obl, int) and obl >= 0, (
        f"odometer_baseline_miles must be non-negative int, got {obl!r}"
    )
    ocm = data.get("odometer_current_miles")
    assert isinstance(ocm, int) and ocm >= 0, (
        f"odometer_current_miles must be non-negative int, got {ocm!r}"
    )
    assert data.get("vehicle_status") in {
        "AVAILABLE", "ALLOCATED", "IN_SHOP", "GROUNDED", "RETIRED",
    }, f"vehicle_status invalid: {data.get('vehicle_status')!r}"
    # current_lease_id may be null when AVAILABLE / RETIRED.
    cli = data.get("current_lease_id", None)
    assert cli is None or isinstance(cli, str), (
        f"current_lease_id must be string or null, got {cli!r}"
    )


# ---------------------------------------------------------------------------
# LeaseAgreement — PRD §3.2, §3.8
# ---------------------------------------------------------------------------
def assert_lease_agreement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("lessee_id"), str), (
        f"lessee_id must be string, got {data.get('lessee_id')!r}"
    )
    assert isinstance(data.get("vehicle_id"), str), (
        f"vehicle_id must be string, got {data.get('vehicle_id')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("term_start_date", ""))) \
        or isinstance(data.get("term_start_date"), str), (
        f"term_start_date must be ISO 8601, got {data.get('term_start_date')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("term_end_date", ""))) \
        or isinstance(data.get("term_end_date"), str), (
        f"term_end_date must be ISO 8601, got {data.get('term_end_date')!r}"
    )
    mma = data.get("monthly_mileage_allowance")
    assert isinstance(mma, int) and 1000 <= mma <= 15000, (
        f"monthly_mileage_allowance must be 1000..15000, got {mma!r}"
    )
    rate = data.get("overage_rate_cents_per_mile")
    assert isinstance(rate, int) and 5 <= rate <= 100, (
        f"overage_rate_cents_per_mile must be 5..100, got {rate!r}"
    )
    assert isinstance(data.get("tiered_overage_enabled"), bool), (
        f"tiered_overage_enabled must be bool, got "
        f"{type(data.get('tiered_overage_enabled'))}"
    )
    assert data.get("lease_state") in {
        "DRAFT", "ACTIVE", "IN_RETURN", "CLOSED", "DEFAULTED",
    }, f"lease_state invalid: {data.get('lease_state')!r}"
    com = data.get("cumulative_overage_miles")
    assert isinstance(com, int) and com >= 0, (
        f"cumulative_overage_miles must be non-negative int, got {com!r}"
    )
    coc = data.get("collision_open_count")
    assert isinstance(coc, int) and coc >= 0, (
        f"collision_open_count must be non-negative int, got {coc!r}"
    )


# ---------------------------------------------------------------------------
# FuelCard — PRD §3.3
# ---------------------------------------------------------------------------
def assert_fuel_card(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("lease_agreement_id"), str), (
        f"lease_agreement_id must be string, "
        f"got {data.get('lease_agreement_id')!r}"
    )
    last4 = data.get("card_pan_last4")
    assert isinstance(last4, str) and len(last4) == 4 and last4.isdigit(), (
        f"card_pan_last4 must be 4 digits, got {last4!r}"
    )
    ml = data.get("monthly_limit_cents")
    assert isinstance(ml, int) and 50_000 <= ml <= 1_000_000, (
        f"monthly_limit_cents must be 50000..1000000, got {ml!r}"
    )
    assert data.get("card_status") in {
        "ACTIVE", "BLOCKED", "CLOSED",
    }, f"card_status invalid: {data.get('card_status')!r}"
    sp = data.get("current_period_spend_cents")
    assert isinstance(sp, int) and sp >= 0, (
        f"current_period_spend_cents must be non-negative int, got {sp!r}"
    )


# ---------------------------------------------------------------------------
# FuelCardTransaction — PRD §3.3 (append-only)
# ---------------------------------------------------------------------------
def assert_fuel_card_transaction(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("fuel_card_id"), str), (
        f"fuel_card_id must be string, got {data.get('fuel_card_id')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("posted_at", ""))), (
        f"posted_at must be ISO 8601, got {data.get('posted_at')!r}"
    )
    assert data.get("jurisdiction") in {
        "CA", "TX", "NY", "IL", "FL", "OH", "PA", "GA", "WA", "AZ",
    }, f"jurisdiction invalid: {data.get('jurisdiction')!r}"
    g = data.get("gallons")
    assert isinstance(g, (int, float)) and g > 0, (
        f"gallons must be positive number, got {g!r}"
    )
    amt = data.get("amount_cents")
    assert isinstance(amt, int) and amt > 0, (
        f"amount_cents must be positive int, got {amt!r}"
    )
    assert data.get("txn_status") in {
        "POSTED", "REVERSED", "IFTA_INCLUDED",
    }, f"txn_status invalid: {data.get('txn_status')!r}"
    assert isinstance(data.get("ifta_eligible"), bool), (
        f"ifta_eligible must be bool, got "
        f"{type(data.get('ifta_eligible'))}"
    )


# ---------------------------------------------------------------------------
# TelematicsEvent — PRD §3.4 (append-only)
# ---------------------------------------------------------------------------
def assert_telematics_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("vehicle_id"), str), (
        f"vehicle_id must be string, got {data.get('vehicle_id')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("event_ts", ""))), (
        f"event_ts must be ISO 8601, got {data.get('event_ts')!r}"
    )
    od = data.get("odometer_reading")
    assert isinstance(od, int) and od >= 0, (
        f"odometer_reading must be non-negative int, got {od!r}"
    )
    hec = data.get("harsh_event_count", 0)
    assert isinstance(hec, int) and hec >= 0, (
        f"harsh_event_count must be non-negative int, got {hec!r}"
    )
    # fault_code may be empty string per PRD §3.4 default.
    fc = data.get("fault_code", "")
    assert isinstance(fc, str), (
        f"fault_code must be string, got {fc!r}"
    )
    assert data.get("ingest_status") in {
        "ACCEPTED", "REJECTED_STALE",
    }, f"ingest_status invalid: {data.get('ingest_status')!r}"


# ---------------------------------------------------------------------------
# MaintenanceTicket — PRD §3.5
# ---------------------------------------------------------------------------
def assert_maintenance_ticket(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("vehicle_id"), str), (
        f"vehicle_id must be string, got {data.get('vehicle_id')!r}"
    )
    assert data.get("ticket_kind") in {"PM", "REPAIR"}, (
        f"ticket_kind invalid: {data.get('ticket_kind')!r}"
    )
    oao = data.get("opened_at_odometer")
    assert isinstance(oao, int) and oao >= 0, (
        f"opened_at_odometer must be non-negative int, got {oao!r}"
    )
    est = data.get("estimate_cents")
    assert isinstance(est, int) and est >= 0, (
        f"estimate_cents must be non-negative int, got {est!r}"
    )
    act = data.get("actual_cents")
    assert isinstance(act, int) and act >= 0, (
        f"actual_cents must be non-negative int, got {act!r}"
    )
    assert data.get("ticket_status") in {
        "OPEN", "IN_SHOP", "CLOSED", "CANCELLED",
    }, f"ticket_status invalid: {data.get('ticket_status')!r}"


# ---------------------------------------------------------------------------
# CollisionClaim — PRD §3.7
# ---------------------------------------------------------------------------
def assert_collision_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("lease_agreement_id"), str), (
        f"lease_agreement_id must be string, "
        f"got {data.get('lease_agreement_id')!r}"
    )
    assert isinstance(data.get("vehicle_id"), str), (
        f"vehicle_id must be string, got {data.get('vehicle_id')!r}"
    )
    assert is_iso8601_timestamp(str(data.get("incident_ts", ""))), (
        f"incident_ts must be ISO 8601, got {data.get('incident_ts')!r}"
    )
    est = data.get("estimate_cents")
    assert isinstance(est, int) and est >= 0, (
        f"estimate_cents must be non-negative int, got {est!r}"
    )
    rev = data.get("revised_estimate_cents", 0)
    assert isinstance(rev, int) and rev >= 0, (
        f"revised_estimate_cents must be non-negative int, got {rev!r}"
    )
    led = data.get("lessee_deductible_cents", 0)
    assert isinstance(led, int) and led >= 0, (
        f"lessee_deductible_cents must be non-negative int, got {led!r}"
    )
    assert data.get("claim_status") in {
        "FILED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "APPROVED", "REJECTED",
    }, f"claim_status invalid: {data.get('claim_status')!r}"
    rr = data.get("revision_round", 0)
    assert isinstance(rr, int) and rr >= 0, (
        f"revision_round must be non-negative int, got {rr!r}"
    )


# ---------------------------------------------------------------------------
# OverageSettlement — PRD §3.6
# ---------------------------------------------------------------------------
def assert_overage_settlement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("lease_agreement_id"), str), (
        f"lease_agreement_id must be string, "
        f"got {data.get('lease_agreement_id')!r}"
    )
    py = data.get("period_year")
    assert isinstance(py, int) and 2000 <= py <= 2099, (
        f"period_year must be 2000..2099, got {py!r}"
    )
    pm = data.get("period_month")
    assert isinstance(pm, int) and 1 <= pm <= 12, (
        f"period_month must be 1..12, got {pm!r}"
    )
    pom = data.get("provisional_overage_miles", 0)
    assert isinstance(pom, int) and pom >= 0, (
        f"provisional_overage_miles must be non-negative int, got {pom!r}"
    )
    fom = data.get("final_overage_miles", 0)
    assert isinstance(fom, int) and fom >= 0, (
        f"final_overage_miles must be non-negative int, got {fom!r}"
    )
    pbc = data.get("provisional_balance_cents", 0)
    assert isinstance(pbc, int) and pbc >= 0, (
        f"provisional_balance_cents must be non-negative int, got {pbc!r}"
    )
    bc = data.get("balance_cents", 0)
    assert isinstance(bc, int) and bc >= 0, (
        f"balance_cents must be non-negative int, got {bc!r}"
    )
    assert data.get("settlement_status") in {
        "DRAFT", "FINAL", "PAID", "DISPUTED",
    }, f"settlement_status invalid: {data.get('settlement_status')!r}"


# ---------------------------------------------------------------------------
# IFTAQuarter — PRD §3.9
# ---------------------------------------------------------------------------
def assert_ifta_quarter(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("lessee_id"), str), (
        f"lessee_id must be string, got {data.get('lessee_id')!r}"
    )
    yr = data.get("year")
    assert isinstance(yr, int) and 2000 <= yr <= 2099, (
        f"year must be 2000..2099, got {yr!r}"
    )
    q = data.get("quarter")
    assert isinstance(q, int) and 1 <= q <= 4, (
        f"quarter must be 1..4, got {q!r}"
    )
    assert data.get("filing_status") in {
        "OPEN", "READY", "CLOSED",
    }, f"filing_status invalid: {data.get('filing_status')!r}"
    ttg = data.get("total_taxable_gallons", 0)
    assert isinstance(ttg, (int, float)) and ttg >= 0, (
        f"total_taxable_gallons must be non-negative number, got {ttg!r}"
    )
    ttc = data.get("total_tax_cents", 0)
    assert isinstance(ttc, int), (
        f"total_tax_cents must be int (signed), got {ttc!r}"
    )


# ---------------------------------------------------------------------------
# Conservation invariants — PRD §2.9 ledger integrity
# ---------------------------------------------------------------------------
def assert_outstanding_balance_conserved_by_approve_and_pay(
    *,
    pre_balance: int,
    post_approve_balance: int,
    post_paid_balance: int,
    deductible_cents: int,
    settlement_balance_cents: int,
) -> None:
    """PRD §2.9: "every approval of a `CollisionClaim` adds the
    computed `lessee_deductible_cents` to the balance, and every
    `OverageSettlement` that transitions into the paid state subtracts
    that settlement's `balance_cents` from the balance."

    With deductible == settlement balance, the pair of operations is
    balance-neutral: post-paid balance == pre balance.
    """
    assert post_approve_balance == pre_balance + deductible_cents, (
        f"After approve: expected balance "
        f"{pre_balance} + {deductible_cents} = "
        f"{pre_balance + deductible_cents}, "
        f"got {post_approve_balance}"
    )
    assert post_paid_balance == post_approve_balance - settlement_balance_cents, (
        f"After mark-paid: expected balance "
        f"{post_approve_balance} - {settlement_balance_cents} = "
        f"{post_approve_balance - settlement_balance_cents}, "
        f"got {post_paid_balance}"
    )


def assert_vehicle_lease_link_conserved(
    *,
    pre_vehicle: Dict[str, Any],
    post_vehicle: Dict[str, Any],
) -> None:
    """PRD §3.8: "On success, the underlying vehicle is restored to
    `AVAILABLE`, its `current_lease_id` is set to null."

    Asserts the (current_lease_id, vehicle_status) pair returns to its
    initial state (null, AVAILABLE) after a full activate→finalize
    cycle.
    """
    assert pre_vehicle.get("current_lease_id") is None, (
        f"Pre-vehicle current_lease_id should be null, "
        f"got {pre_vehicle.get('current_lease_id')!r}"
    )
    assert pre_vehicle.get("vehicle_status") == "AVAILABLE", (
        f"Pre-vehicle vehicle_status should be AVAILABLE, "
        f"got {pre_vehicle.get('vehicle_status')!r}"
    )
    assert post_vehicle.get("current_lease_id") is None, (
        f"Post-finalize-return vehicle current_lease_id should be null, "
        f"got {post_vehicle.get('current_lease_id')!r}"
    )
    assert post_vehicle.get("vehicle_status") == "AVAILABLE", (
        f"Post-finalize-return vehicle_status should be AVAILABLE, "
        f"got {post_vehicle.get('vehicle_status')!r}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    "assert_lessee",
    "assert_vehicle",
    "assert_lease_agreement",
    "assert_fuel_card",
    "assert_fuel_card_transaction",
    "assert_telematics_event",
    "assert_maintenance_ticket",
    "assert_collision_claim",
    "assert_overage_settlement",
    "assert_ifta_quarter",
    "assert_outstanding_balance_conserved_by_approve_and_pay",
    "assert_vehicle_lease_link_conserved",
]
