"""Entity assertions and domain invariant checkers for the Domestic Service Dispatch API.

Per-entity `assert_<entity>(data)` validates required fields per PRD §2.4 and
the entity-specific PRD §3 field list. Append-only entities (PRD §2.4:
ServiceExecution, AbnormalEvent, OrderRating, SettlementLedgerEntry,
AuditLogEntry) carry only `id` and `created_at` — they MUST NOT carry
`updated_at` or `version`.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─────────────────────────────────────────────────────────────
# Rounding helpers — PRD §2.10 (round_half_up).
# ─────────────────────────────────────────────────────────────


def round_half_up(value: float, decimals: int) -> float:
    """Bankers' rounding is wrong here — PRD §2.10 pins round_half_up explicitly."""
    quant = Decimal(10) ** -decimals
    return float(
        Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    )


def round_half_up_cents(value: float) -> int:
    """Round a non-integer cents value to integer cents using round_half_up."""
    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


# ─────────────────────────────────────────────────────────────
# Common-field helpers
# ─────────────────────────────────────────────────────────────


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: entities carry id (UUID) + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be positive int: {data.get('version')}"
    )


def _assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only entities carry ONLY id and created_at — no
    updated_at, no version. Reading those keys is forbidden because the
    implementer is correctly told not to expose them."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"


# ─────────────────────────────────────────────────────────────
# ServicePersonnel (PRD §3.1)
# ─────────────────────────────────────────────────────────────


def assert_personnel(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["gender"] in ("MALE", "FEMALE")
    assert isinstance(data["age"], int) and 18 <= data["age"] <= 70
    assert isinstance(data["languages"], list)
    assert isinstance(data["skill_tags"], list)
    assert isinstance(data["service_lat"], (int, float))
    assert isinstance(data["service_lng"], (int, float))
    assert isinstance(data["service_radius_km"], (int, float))
    assert isinstance(data["identity_verified"], bool)
    assert is_iso8601_timestamp(data["health_cert_expires_at"])
    assert data["status"] in (
        "PENDING_VERIFICATION",
        "ACTIVE",
        "SUSPENDED",
        "DISQUALIFIED",
    )
    assert isinstance(data["rating_score"], (int, float))
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert (
        isinstance(data["workload_active_orders"], int)
        and data["workload_active_orders"] >= 0
    )
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")


# ─────────────────────────────────────────────────────────────
# SkillCertification (PRD §3.2)
# ─────────────────────────────────────────────────────────────


def assert_certification(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["personnel_id"])
    assert data["skill_tag"] in ("CLEANING", "COOKING", "CHILDCARE", "ELDERCARE")
    assert isinstance(data["training_hours"], (int, float))
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("PENDING", "ACTIVE", "EXPIRED", "REVOKED")


# ─────────────────────────────────────────────────────────────
# ServiceItem (PRD §3.3)
# ─────────────────────────────────────────────────────────────


def assert_service_item(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["required_skill_tag"] in (
        "CLEANING",
        "COOKING",
        "CHILDCARE",
        "ELDERCARE",
    )
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["min_duration_hours"], (int, float))
    assert isinstance(data["service_areas"], list)
    assert isinstance(data["active"], bool)


# ─────────────────────────────────────────────────────────────
# Customer (PRD §3.3)
# ─────────────────────────────────────────────────────────────


def assert_customer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["area_code"], str)
    assert isinstance(data["address_lat"], (int, float))
    assert isinstance(data["address_lng"], (int, float))
    # pref_* may be null
    if data.get("pref_gender") is not None:
        assert data["pref_gender"] in ("MALE", "FEMALE")
    assert (
        isinstance(data["wallet_credit_cents"], int)
        and data["wallet_credit_cents"] >= 0
    )


# ─────────────────────────────────────────────────────────────
# Order (PRD §3.4)
# ─────────────────────────────────────────────────────────────


_ORDER_STATES = {
    "DRAFT",
    "PENDING_DISPATCH",
    "DISPATCHED",
    "ACCEPTED",
    "IN_PROGRESS",
    "COMPLETED",
    "ACCEPTED_BY_CUSTOMER",
    "CANCELLED",
    "REFUNDED",
}


def assert_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["service_item_id"])
    assert data["mode"] in ("SINGLE", "RECURRING")
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert isinstance(data["duration_hours"], (int, float))
    assert isinstance(data["gross_price_cents"], int) and data["gross_price_cents"] >= 0
    assert data["status"] in _ORDER_STATES, f"unexpected status {data['status']}"
    assert (
        isinstance(data["dispatch_round"], int) and data["dispatch_round"] >= 0
    )
    assert isinstance(data["rated"], bool)


# ─────────────────────────────────────────────────────────────
# RecurringOrder (PRD §3.4)
# ─────────────────────────────────────────────────────────────


def assert_recurring_order(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["service_item_id"])
    assert data["cadence_days"] in (1, 7, 14, 30)
    assert is_iso8601_timestamp(data["first_start_at"])
    assert data["status"] in ("ACTIVE", "PAUSED", "TERMINATED")


# ─────────────────────────────────────────────────────────────
# InsuranceClaim (PRD §3.7)
# ─────────────────────────────────────────────────────────────


def assert_claim(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["claim_type"] in ("ON_JOB_INJURY", "PROPERTY_DAMAGE")
    assert data["status"] in (
        "REPORTED",
        "EVIDENCE_PENDING",
        "FILED",
        "APPROVED",
        "REJECTED",
        "PAID",
        "ARCHIVED",
    )
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["evidence_count"], int) and data["evidence_count"] >= 0


# ─────────────────────────────────────────────────────────────
# Append-only entities (PRD §2.4) — id + created_at only
# ─────────────────────────────────────────────────────────────


def assert_service_execution(data: Dict[str, Any]) -> None:
    """PRD §2.4: ServiceExecution is append-only — id + created_at only."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["checkin_face_passed"], bool)
    assert isinstance(data["procedure_checklist"], list)
    assert isinstance(data["abnormal_reported"], bool)


def assert_abnormal_event(data: Dict[str, Any]) -> None:
    """PRD §2.4: AbnormalEvent is append-only — id + created_at only."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert data["reporter_role"] in ("PERSONNEL", "CUSTOMER", "OPERATOR")
    assert data["category"] in ("INJURY", "PROPERTY_DAMAGE", "NO_SHOW", "OTHER")
    assert isinstance(data["triggers_claim"], bool)


def assert_order_rating(data: Dict[str, Any]) -> None:
    """PRD §2.4: OrderRating is append-only — id + created_at only."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["order_id"])
    for k in ("quality_score", "punctuality_score", "attitude_score"):
        assert isinstance(data[k], int) and 1 <= data[k] <= 5, (
            f"{k} must be int in [1,5]: {data[k]}"
        )
    assert isinstance(data["composite_score"], (int, float))
    assert data["investigation_status"] in ("NONE", "OPEN", "CLOSED")


def assert_ledger_entry(data: Dict[str, Any]) -> None:
    """PRD §2.4: SettlementLedgerEntry is append-only — id + created_at only."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["personnel_id"])
    assert data["kind"] in ("COMMISSION", "BONUS", "REVERSAL", "TAX", "PAYOUT")
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["posted_at"])
    assert isinstance(data["cycle_id"], str)


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    """PRD §2.4: AuditLogEntry is append-only — id + created_at only."""
    _assert_append_only_fields(data)
    assert data["action_type"] in (
        "DISPATCH",
        "REASSIGN",
        "DISPATCH_EXPIRED",
        "CLAIM_REPORTED",
        "CLAIM_FILED",
        "CLAIM_APPROVED",
        "CLAIM_REJECTED",
        "CLAIM_PAID",
    )
    assert data["subject_type"] in ("Order", "InsuranceClaim")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_role"], str)


# ─────────────────────────────────────────────────────────────
# Domain invariants
# ─────────────────────────────────────────────────────────────


def expected_gross_price_cents(base_price_cents: int, duration_hours: float) -> int:
    """PRD §3.4: gross_price_cents = base_price_cents * duration_hours (integer cents)."""
    # base is integer cents, duration is multiple of 0.5 — product is exact integer.
    val = base_price_cents * duration_hours
    # Defensive round to absorb float-multiplication crumbs.
    return round_half_up_cents(val)


def expected_provisional_commission(gross_price_cents: int) -> int:
    """PRD §3.10: provisional = round_half_up(gross_price_cents * 0.70, 0)."""
    return round_half_up_cents(gross_price_cents * 0.70)


def tier_bonus_rate(tier: str) -> float:
    """PRD §3.10: PLATINUM=0.20, GOLD=0.10, SILVER=0.05, BRONZE=0.00."""
    return {
        "PLATINUM": 0.20,
        "GOLD": 0.10,
        "SILVER": 0.05,
        "BRONZE": 0.00,
    }[tier]


def expected_final_commission(gross_price_cents: int, tier_at_acceptance: str) -> int:
    """PRD §3.10: final = round_half_up(gross * 0.70 * (1 + bonus_rate), 0)."""
    rate = tier_bonus_rate(tier_at_acceptance)
    return round_half_up_cents(gross_price_cents * 0.70 * (1 + rate))


def expected_composite_score(
    quality: int, punctuality: int, attitude: int
) -> float:
    """PRD §3.9: 0.5*quality + 0.3*punctuality + 0.2*attitude, 4 decimals round_half_up."""
    return round_half_up(
        0.5 * quality + 0.3 * punctuality + 0.2 * attitude, 4
    )


def expected_new_rating_score(
    old_score: float, old_count: int, new_composite: float
) -> float:
    """PRD §3.9: incremental running average to 4 decimal places round_half_up."""
    new_count = old_count + 1
    raw = (old_score * old_count + new_composite) / new_count
    return round_half_up(raw, 4)


def expected_tier(rating_score: float, rating_count: int) -> str:
    """PRD §3.9: tier from (rating_count, rating_score). Inclusive floors."""
    if rating_count < 5:
        return "BRONZE"
    if rating_score >= 4.8:
        return "PLATINUM"
    if rating_score >= 4.5:
        return "GOLD"
    if rating_score >= 4.0:
        return "SILVER"
    return "BRONZE"


def expected_payout_components(
    eligible_amounts_cents: Iterable[int],
) -> Dict[str, int]:
    """PRD §3.10: sum-then-round tax. Returns dict with pre_tax_sum, payout_base,
    tax_cents (positive magnitude), payout_cents (positive magnitude)."""
    pre = sum(eligible_amounts_cents)
    payout_base = max(0, pre)
    tax = round_half_up_cents(payout_base * 0.10)
    payout = payout_base - tax
    return {
        "pre_tax_sum": pre,
        "payout_base": payout_base,
        "tax_cents": tax,
        "payout_cents": payout,
    }


def assert_commission_plus_reversal_zero(
    entries: List[Dict[str, Any]], order_id: str
) -> None:
    """PRD §3.8: sum of COMMISSION + BONUS + REVERSAL ledger entries for the
    refunded order equals exactly zero cents."""
    sub = [
        e
        for e in entries
        if e.get("order_id") == order_id
        and e.get("kind") in ("COMMISSION", "BONUS", "REVERSAL")
    ]
    total = sum(e["amount_cents"] for e in sub)
    assert total == 0, (
        f"PRD §3.8 invariant violated: COMMISSION+BONUS+REVERSAL for order "
        f"{order_id} summed to {total}, expected 0. Entries={sub}"
    )


def assert_version_incremented(
    before: Dict[str, Any], after: Dict[str, Any]
) -> None:
    """PRD §2.4: every mutating write increments version by exactly 1."""
    b, a = before.get("version"), after.get("version")
    assert isinstance(b, int) and isinstance(a, int), (
        f"version must be int both sides: before={b!r} after={a!r}"
    )
    assert a == b + 1, f"version must increment by 1: before={b} after={a}"


def assert_response_envelope_meta(envelope: Dict[str, Any]) -> None:
    """PRD §2.2: meta carries api_request_id (req_…) and api_request_timestamp."""
    meta = envelope["meta"]
    rid = meta.get("api_request_id", "")
    assert isinstance(rid, str) and rid.startswith("req_"), (
        f"api_request_id must start with req_: {rid!r}"
    )
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), f"api_request_timestamp must be ISO 8601: {meta.get('api_request_timestamp')}"
