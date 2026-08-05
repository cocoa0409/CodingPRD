"""Entity assertions, instant comparison, and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ANALYTE_UNIT,
    CLINIC_OPTIMAL_BAND,
    CRITICAL_HIGH,
    LAB_REFERENCE_INTERVAL,
    PELLET_PRICE_CENTS_PER_MG,
)


# ── Instants ─────────────────────────────────────────────────────────────────
# Datetimes are compared as instants, never as raw strings: an implementation
# may legitimately render the same moment with or without fractional digits.


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, field: str = "timestamp") -> None:
    """Assert two ISO 8601 strings denote the same instant."""
    assert actual is not None, f"{field} is null; expected {expected}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field}: expected the instant {expected}, got {actual}"
    )


def assert_instant_shape(value: str, field: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 UTC instant: {value!r}"


def days_between(earlier: str, later: str) -> int:
    """Whole 24-hour periods between two instants, floored (PRD 2.4)."""
    delta = (parse_instant(later) - parse_instant(earlier)).total_seconds()
    return int(delta // 86400)


def hours_between(earlier: str, later: str) -> float:
    """Exact, unfloored hours between two instants (PRD 2.4)."""
    return (parse_instant(later) - parse_instant(earlier)).total_seconds() / 3600.0


def shift_iso(instant: str, *, days: int = 0, hours: int = 0, minutes: int = 0) -> str:
    """Offset an instant and render it back as an ISO 8601 UTC string."""
    from datetime import timedelta

    moved = parse_instant(instant) + timedelta(days=days, hours=hours, minutes=minutes)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Common record shape ──────────────────────────────────────────────────────
def assert_common_fields(data: dict, entity: str = "record") -> None:
    """id / created_at / updated_at / version, carried by every record but Protocol."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID: {data.get('id')!r}"
    assert_instant_shape(data.get("created_at", ""), f"{entity}.created_at")
    assert_instant_shape(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# ── Per-entity assertions ────────────────────────────────────────────────────
def assert_patient(data: dict) -> None:
    assert_common_fields(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["sex_at_birth"] in ("MALE", "FEMALE")
    assert isinstance(data["clinical_hold"], bool)
    assert isinstance(data["financial_hold"], bool)
    assert data["eligibility_status"] in (
        "CLEAR", "CLINICAL_HOLD", "FINANCIAL_HOLD", "DUAL_HOLD"
    )
    assert data["cumulative_mg_testosterone"] >= 0
    assert data["cumulative_mg_estradiol"] >= 0
    assert isinstance(data["open_notification_count"], int)
    assert data["open_notification_count"] >= 0
    assert_patient_eligibility_projection(data)


def assert_patient_eligibility_projection(data: dict) -> None:
    """eligibility_status is a pure projection over the two hold booleans (PRD 3.1)."""
    clinical, financial = data["clinical_hold"], data["financial_hold"]
    if clinical and financial:
        expected = "DUAL_HOLD"
    elif clinical:
        expected = "CLINICAL_HOLD"
    elif financial:
        expected = "FINANCIAL_HOLD"
    else:
        expected = "CLEAR"
    assert data["eligibility_status"] == expected, (
        f"eligibility_status {data['eligibility_status']} does not project "
        f"clinical_hold={clinical}, financial_hold={financial} (expected {expected})"
    )


def assert_provider(data: dict) -> None:
    assert_common_fields(data, "Provider")
    assert data["provider_type"] in ("PHYSICIAN", "NURSE_INJECTOR")
    assert isinstance(data["npi"], str) and data["npi"]


def assert_protocol(data: dict) -> None:
    """A published Protocol is immutable: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "Protocol.id must be a bare UUID"
    assert_instant_shape(data.get("created_at", ""), "Protocol.created_at")
    assert data["hormone_type"] in ("TESTOSTERONE", "ESTRADIOL")
    assert isinstance(data["protocol_version"], int) and data["protocol_version"] >= 1
    assert_instant_shape(data.get("effective_at", ""), "Protocol.effective_at")
    assert "updated_at" not in data, "A published Protocol must carry no updated_at"
    assert "version" not in data, "A published Protocol must carry no version"


def assert_consent(data: dict) -> None:
    assert_common_fields(data, "ConsentRecord")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert data["hormone_type"] in ("TESTOSTERONE", "ESTRADIOL")
    assert isinstance(data["protocol_version"], int)
    assert_instant_shape(data.get("signed_at", ""), "ConsentRecord.signed_at")


def assert_consult(data: dict) -> None:
    assert_common_fields(data, "Consult")
    assert data["hormone_type"] in ("TESTOSTERONE", "ESTRADIOL")
    assert data["prescribed_dose_mg"] > 0
    assert 0 <= data["symptom_score"] <= 100
    assert data["planned_large_count"] >= 0
    assert data["planned_small_count"] >= 0
    assert data["planned_pellet_count"] == data["planned_large_count"] + data["planned_small_count"]
    assert data["planned_total_mg"] >= data["prescribed_dose_mg"], (
        "The plan never under-delivers: planned_total_mg must be >= prescribed_dose_mg"
    )


def assert_lab_panel(data: dict) -> None:
    assert_common_fields(data, "LabPanel")
    analyte = data["analyte"]
    assert analyte in ("TOTAL_TESTOSTERONE", "ESTRADIOL", "HEMATOCRIT")
    assert data["unit"] == ANALYTE_UNIT[analyte], (
        f"unit for {analyte} must be {ANALYTE_UNIT[analyte]}, got {data['unit']}"
    )
    assert data["lab_reference_band"] in ("BELOW_REF", "IN_REF", "ABOVE_REF")
    assert data["clinic_optimal_band"] in ("BELOW_OPTIMAL", "IN_OPTIMAL", "ABOVE_OPTIMAL")
    assert isinstance(data["critical_flag"], bool)
    assert data["status"] in ("RECORDED", "CRITICAL_FLAGGED", "ACKNOWLEDGED", "SUPERSEDED")
    assert isinstance(data["is_trough_draw"], bool)
    assert_instant_shape(data.get("drawn_at", ""), "LabPanel.drawn_at")
    assert_instant_shape(data.get("resulted_at", ""), "LabPanel.resulted_at")
    assert_lab_band_classification(data)


def assert_lab_band_classification(data: dict) -> None:
    """Both rulers and the critical ceiling read the raw value with no rounding."""
    analyte, value = data["analyte"], data["value"]
    ref_low, ref_high = LAB_REFERENCE_INTERVAL[analyte]
    opt_low, opt_high = CLINIC_OPTIMAL_BAND[analyte]
    expected_ref = "BELOW_REF" if value < ref_low else "ABOVE_REF" if value > ref_high else "IN_REF"
    expected_opt = (
        "BELOW_OPTIMAL" if value < opt_low
        else "ABOVE_OPTIMAL" if value > opt_high
        else "IN_OPTIMAL"
    )
    assert data["lab_reference_band"] == expected_ref, (
        f"{analyte} {value} should read {expected_ref}, got {data['lab_reference_band']}"
    )
    assert data["clinic_optimal_band"] == expected_opt, (
        f"{analyte} {value} should read {expected_opt}, got {data['clinic_optimal_band']}"
    )
    assert data["critical_flag"] is (value > CRITICAL_HIGH[analyte]), (
        f"{analyte} {value} critical_flag should be {value > CRITICAL_HIGH[analyte]}"
    )


def assert_pellet_lot(data: dict) -> None:
    assert_common_fields(data, "PelletLot")
    assert data["sterility_status"] in ("QUARANTINED", "RELEASED", "RECALLED")
    assert data["hormone_type"] in ("TESTOSTERONE", "ESTRADIOL")
    assert_lot_pellet_conservation(data)


def assert_lot_pellet_conservation(lot: dict) -> None:
    """qty_received == on_hand + reserved + consumed + wasted + returned (PRD 2.10)."""
    buckets = (
        lot["qty_on_hand"], lot["qty_reserved"], lot["qty_consumed"],
        lot["qty_wasted"], lot["qty_returned"],
    )
    assert all(b >= 0 for b in buckets), f"Every lot bucket must be non-negative: {buckets}"
    assert lot["qty_received"] == sum(buckets), (
        f"Pellet conservation broken on lot {lot.get('lot_code')}: "
        f"qty_received {lot['qty_received']} != on_hand {lot['qty_on_hand']} "
        f"+ reserved {lot['qty_reserved']} + consumed {lot['qty_consumed']} "
        f"+ wasted {lot['qty_wasted']} + returned {lot['qty_returned']}"
    )


def assert_lot_buckets(
    lot: dict, *, on_hand: int, reserved: int, consumed: int, wasted: int, returned: int
) -> None:
    assert lot["qty_on_hand"] == on_hand, f"qty_on_hand: expected {on_hand}, got {lot['qty_on_hand']}"
    assert lot["qty_reserved"] == reserved, (
        f"qty_reserved: expected {reserved}, got {lot['qty_reserved']}"
    )
    assert lot["qty_consumed"] == consumed, (
        f"qty_consumed: expected {consumed}, got {lot['qty_consumed']}"
    )
    assert lot["qty_wasted"] == wasted, f"qty_wasted: expected {wasted}, got {lot['qty_wasted']}"
    assert lot["qty_returned"] == returned, (
        f"qty_returned: expected {returned}, got {lot['qty_returned']}"
    )
    assert_lot_pellet_conservation(lot)


def assert_standing_order(data: dict) -> None:
    assert_common_fields(data, "StandingOrder")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")
    assert isinstance(data["scope_hormone_types"], list)
    assert isinstance(data["scope_injection_types"], list)
    assert data["max_dose_mg"] > 0
    assert_instant_shape(data.get("valid_from", ""), "StandingOrder.valid_from")
    assert_instant_shape(data.get("valid_until", ""), "StandingOrder.valid_until")


def assert_procedure(data: dict) -> None:
    assert_common_fields(data, "Procedure")
    assert data["status"] in (
        "SCHEDULED", "CONSENTED", "SUPPLY_OPENED", "COMPLETED",
        "CANCELLED", "VOIDED", "SUPPLY_HOLD",
    )
    assert data["recall_status"] in ("NONE", "RECALL_AFFECTED", "NOTIFIED")
    assert data["procedure_type"] in ("INITIAL", "REDOSE")
    assert data["hormone_type"] in ("TESTOSTERONE", "ESTRADIOL")
    assert_instant_shape(data.get("scheduled_start", ""), "Procedure.scheduled_start")
    assert_instant_shape(data.get("scheduled_end", ""), "Procedure.scheduled_end")
    for counter in ("pellets_allocated", "pellets_opened", "pellets_inserted", "pellets_wasted"):
        assert data[counter] >= 0, f"{counter} must be non-negative"
    assert data["delivered_total_mg"] >= 0
    assert data["charge_cents"] >= 0
    assert data["cancel_fee_cents"] >= 0


def assert_pellet_allocation(data: dict) -> None:
    assert_common_fields(data, "PelletAllocation")
    assert data["status"] in (
        "RESERVED", "OPENED", "CONSUMED", "WASTED",
        "RELEASED", "RECALL_RELEASED", "RECALL_FLAGGED",
    )
    assert data["quantity"] >= 0
    assert data["allocation_rank"] >= 1
    assert data["strength_mg"] > 0


def assert_membership(data: dict) -> None:
    assert_common_fields(data, "Membership")
    assert data["tier"] in ("BASIC", "PLUS", "ELITE")
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert data["included_visits_used"] >= 0
    assert data["pause_days_used"] >= 0
    assert data["pause_credit_cents"] >= 0
    assert_instant_shape(data.get("period_start", ""), "Membership.period_start")
    assert_instant_shape(data.get("period_end", ""), "Membership.period_end")


def assert_series_pack(data: dict) -> None:
    assert_common_fields(data, "SeriesPack")
    assert data["series_type"] in ("B12", "LIPOTROPIC", "VITAMIN_D", "GLUTATHIONE")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "REFUNDED")
    assert_instant_shape(data.get("purchased_at", ""), "SeriesPack.purchased_at")
    assert_instant_shape(data.get("expires_at", ""), "SeriesPack.expires_at")
    assert_series_entitlement_conservation(data)


def assert_series_entitlement_conservation(pack: dict) -> None:
    """purchased == remaining + redeemed + refunded + forfeited (PRD 2.10)."""
    buckets = (
        pack["remaining_visits"], pack["redeemed_visits"],
        pack["refunded_visits"], pack["forfeited_visits"],
    )
    assert all(b >= 0 for b in buckets), f"Every entitlement bucket must be non-negative: {buckets}"
    assert pack["purchased_visits"] == sum(buckets), (
        f"Entitlement conservation broken: purchased_visits {pack['purchased_visits']} "
        f"!= remaining {pack['remaining_visits']} + redeemed {pack['redeemed_visits']} "
        f"+ refunded {pack['refunded_visits']} + forfeited {pack['forfeited_visits']}"
    )


def assert_injection_visit(data: dict) -> None:
    assert_common_fields(data, "InjectionVisit")
    assert data["status"] in ("SCHEDULED", "ADMINISTERED", "CANCELLED", "VOIDED")
    assert data["injection_type"] in ("B12", "LIPOTROPIC", "VITAMIN_D", "GLUTATHIONE")
    if data.get("payment_source") is not None:
        assert data["payment_source"] in ("SERIES", "MEMBERSHIP_INCLUDED", "SELF_PAY")
    assert data["charge_cents"] >= 0
    assert data["series_debit_cents"] >= 0
    assert_instant_shape(data.get("scheduled_start", ""), "InjectionVisit.scheduled_start")
    assert_instant_shape(data.get("scheduled_end", ""), "InjectionVisit.scheduled_end")


def assert_adverse_event(data: dict) -> None:
    assert_common_fields(data, "AdverseEvent")
    assert data["severity"] in ("MILD", "MODERATE", "SEVERE", "SURVEILLANCE")
    assert data["source"] in ("CLINICAL_REPORT", "RECALL_SURVEILLANCE")
    assert data["status"] in ("OPEN", "CLOSED", "ESCALATED")
    assert_instant_shape(data.get("onset_at", ""), "AdverseEvent.onset_at")


def assert_financing_plan(data: dict) -> None:
    assert_common_fields(data, "FinancingPlan")
    assert data["status"] in (
        "DRAFT", "ACTIVE", "DELINQUENT", "DEFAULTED", "PAID_OFF", "CANCELLED"
    )
    assert isinstance(data["schedule"], list) and data["schedule"]
    for entry in data["schedule"]:
        assert entry["status"] in ("PENDING", "PAID", "MISSED", "WAIVED")
        assert isinstance(entry["index"], int) and entry["index"] >= 1
        assert isinstance(entry["amount_cents"], int)
        assert_instant_shape(entry.get("due_date", ""), "schedule[].due_date")
    assert_financing_money_conservation(data)


def assert_financing_money_conservation(plan: dict) -> None:
    """Both legs of the cents identity (PRD 2.10)."""
    schedule_sum = sum(entry["amount_cents"] for entry in plan["schedule"])
    assert plan["principal_cents"] == plan["down_payment_cents"] + schedule_sum, (
        f"Leg A broken: principal {plan['principal_cents']} != down "
        f"{plan['down_payment_cents']} + schedule {schedule_sum}"
    )
    leg_b = plan["paid_installment_cents"] + plan["outstanding_cents"] + plan["waived_cents"]
    assert schedule_sum == leg_b, (
        f"Leg B broken: schedule {schedule_sum} != paid {plan['paid_installment_cents']} "
        f"+ outstanding {plan['outstanding_cents']} + waived {plan['waived_cents']}"
    )


def assert_notification(data: dict) -> None:
    assert_common_fields(data, "PatientNotification")
    assert data["notification_type"] in ("RECALL", "ADVERSE_EVENT", "CONSENT_REQUIRED")
    assert data["status"] in ("PENDING", "ACKNOWLEDGED", "OVERDUE")
    if data.get("severity_class") is not None:
        assert data["severity_class"] in ("CLASS_I", "CLASS_II")
    assert_instant_shape(data.get("due_at", ""), "PatientNotification.due_at")


def assert_schedule_entry(plan: dict, index: int, *, amount_cents=None, status=None) -> dict:
    """Fetch one installment by its 1-based index and check it."""
    matches = [e for e in plan["schedule"] if e["index"] == index]
    assert len(matches) == 1, f"Expected exactly one schedule entry at index {index}"
    entry = matches[0]
    if amount_cents is not None:
        assert entry["amount_cents"] == amount_cents, (
            f"Installment {index}: expected {amount_cents} cents, got {entry['amount_cents']}"
        )
    if status is not None:
        assert entry["status"] == status, (
            f"Installment {index}: expected status {status}, got {entry['status']}"
        )
    return entry


def wasted_pellet_charge_cents(rows, hormone_type: str) -> int:
    """Sum of quantity * strength_mg * price, rounded half up per allocation row."""
    from decimal import ROUND_HALF_UP, Decimal

    price = Decimal(str(PELLET_PRICE_CENTS_PER_MG[hormone_type]))
    total = 0
    for row in rows:
        raw = Decimal(row["quantity"]) * Decimal(str(row["strength_mg"])) * price
        total += int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def assert_envelope_meta(body: dict) -> None:
    """Every response carries a server-generated request id prefixed `req_`."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_instant_shape(meta.get("api_request_timestamp", ""), "meta.api_request_timestamp")


def find_one(rows, **predicates) -> Optional[dict]:
    """Return the single row matching every predicate, or None."""
    matches = [r for r in rows if all(r.get(k) == v for k, v in predicates.items())]
    assert len(matches) <= 1, f"Expected at most one row matching {predicates}, got {len(matches)}"
    return matches[0] if matches else None


def filter_rows(rows, **predicates):
    return [r for r in rows if all(r.get(k) == v for k, v in predicates.items())]
