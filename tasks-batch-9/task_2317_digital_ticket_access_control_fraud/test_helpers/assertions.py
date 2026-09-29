"""Entity-shape assertions and domain invariant checkers.

The shape assertions check that a response body carries every declared field of
its entity with the declared type, including the common properties. The scan
event and the audit log entry are append-only, so their checkers assert the
absence of ``updated_at`` and ``version``.
"""

import math
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BARCODE_ROTATION_SECONDS,
    CATEGORY_WEIGHTS,
    DEVICE_CHURN_WEIGHT,
    FROZEN_RATIO,
    GOODWILL_TIER1_CENTS,
    GOODWILL_TIER1_PCT,
    GOODWILL_TIER2_CENTS,
    GOODWILL_TIER2_PCT,
    GOODWILL_TIER3_PCT,
    MAX_ABS_MARKUP_CENTS,
    PLATFORM_FEE_PCT,
    PROCESSING_FEE_PCT,
    PROCESSING_FIXED_CENTS,
    RESTRICTED_RATIO,
    SCORE_CAP,
    STATUTORY_CAP_PCT,
    STRIKE_PENALTY_CAP_CENTS,
    STRIKE_PENALTY_CENTS,
    VENUE_POLICY_CAP_PCT,
    VENUE_ROYALTY_PCT,
)
from .types import (
    AdmissionStatus,
    DeviceBindingStatus,
    EventStatus,
    GateStatus,
    IncidentStatus,
    LifecycleStatus,
    ListingStatus,
    PriceCapRegime,
    ReportStatus,
    ScanResult,
    ScanSource,
    SessionStatus,
    TicketType,
    ZonePosture,
)

# ─── Common property helpers ──────────────────────────────────────────────────


def assert_common_fields(entity: Dict[str, Any]) -> None:
    """Assert a versioned resource's id, timestamps and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_append_only_fields(entity: Dict[str, Any]) -> None:
    """Assert an append-only record exposes only id and created_at."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "append-only record must not carry updated_at"
    assert "version" not in entity, "append-only record must not carry version"


def _assert_keys(entity: Dict[str, Any], keys: List[str], label: str) -> None:
    missing = [key for key in keys if key not in entity]
    assert not missing, f"{label} is missing fields {missing}"


# ─── Entity shape assertions ──────────────────────────────────────────────────


def assert_event(event: Dict[str, Any]) -> None:
    assert_common_fields(event)
    _assert_keys(
        event,
        [
            "name",
            "venue_name",
            "fire_code_capacity",
            "barcode_anchor_at",
            "doors_open_at",
            "event_start_at",
            "transfer_window_closes_at",
            "price_cap_regime",
            "transfer_limit_per_ticket",
            "status",
            "live_occupancy",
            "peak_live_occupancy",
            "entitlements_outstanding",
            "settlement_pool_cents",
        ],
        "event",
    )
    assert event["status"] in {
        EventStatus.DRAFT,
        EventStatus.ON_SALE,
        EventStatus.DOORS_OPEN,
        EventStatus.IN_PROGRESS,
        EventStatus.CLOSED,
        EventStatus.RECONCILED,
    }
    assert event["price_cap_regime"] in {
        PriceCapRegime.STATUTORY,
        PriceCapRegime.VENUE_POLICY,
        PriceCapRegime.NONE,
    }
    assert event["fire_code_capacity"] >= 1
    assert event["transfer_limit_per_ticket"] >= 0
    for money in ("settlement_pool_cents",):
        assert isinstance(event[money], int), f"{money} must be integer cents"


def assert_access_zone(zone: Dict[str, Any]) -> None:
    assert_common_fields(zone)
    _assert_keys(
        zone,
        [
            "event_id",
            "zone_code",
            "required_entitlement_level",
            "fire_code_capacity",
            "credential_capacity",
            "face_value_reference_cents",
            "comp_discount_pct",
            "occupancy_count",
            "issued_entitlement_count",
            "posture",
            "comp_forgone_cents",
        ],
        "access zone",
    )
    assert zone["posture"] in {ZonePosture.OPEN, ZonePosture.RESTRICTED, ZonePosture.FROZEN}
    assert isinstance(zone["comp_forgone_cents"], int)
    assert zone["fire_code_capacity"] >= 1
    assert zone["credential_capacity"] >= 0


def assert_gate(gate: Dict[str, Any]) -> None:
    assert_common_fields(gate)
    _assert_keys(
        gate,
        [
            "event_id",
            "access_zone_id",
            "gate_code",
            "throughput_per_minute",
            "lanes_open",
            "status",
            "last_session_closed_at",
            "admitted_scan_count",
        ],
        "gate",
    )
    assert gate["status"] in {GateStatus.IDLE, GateStatus.SCANNING}
    assert gate["throughput_per_minute"] >= 1
    assert gate["lanes_open"] >= 1


def assert_patron(patron: Dict[str, Any]) -> None:
    assert_common_fields(patron)
    _assert_keys(
        patron,
        [
            "email",
            "display_name",
            "identity_verified",
            "device_rebind_count",
            "strike_count",
            "fraud_risk_score",
            "fraud_risk_basis",
            "remediation_credit_cents",
            "payout_balance_cents",
        ],
        "patron",
    )
    assert isinstance(patron["identity_verified"], bool)
    assert 0 <= patron["fraud_risk_score"] <= SCORE_CAP
    assert isinstance(patron["remediation_credit_cents"], int)
    assert isinstance(patron["payout_balance_cents"], int)


def assert_ticket(ticket: Dict[str, Any]) -> None:
    assert_common_fields(ticket)
    _assert_keys(
        ticket,
        [
            "event_id",
            "access_zone_id",
            "holder_patron_id",
            "credential_request_id",
            "ticket_type",
            "face_value_cents",
            "barcode_seed",
            "lifecycle_status",
            "admission_status",
            "transfer_count",
            "bound_device_fingerprint",
            "device_binding_status",
            "last_admitted_at",
            "last_exited_at",
            "admitted_scan_count",
        ],
        "ticket",
    )
    assert ticket["ticket_type"] in {
        TicketType.PAID,
        TicketType.COMP,
        TicketType.WILL_CALL,
        TicketType.CREDENTIAL,
    }
    assert ticket["lifecycle_status"] in {
        LifecycleStatus.ISSUED,
        LifecycleStatus.LISTED,
        LifecycleStatus.TRANSFERRED,
        LifecycleStatus.RESOLD,
        LifecycleStatus.VOIDED,
    }
    assert ticket["admission_status"] in {
        AdmissionStatus.NOT_ADMITTED,
        AdmissionStatus.INSIDE,
        AdmissionStatus.EXITED,
        AdmissionStatus.DENIED_FLAGGED,
    }
    assert ticket["device_binding_status"] in {
        DeviceBindingStatus.UNBOUND,
        DeviceBindingStatus.BOUND,
        DeviceBindingStatus.RELEASED,
    }
    assert isinstance(ticket["face_value_cents"], int)
    assert ticket["barcode_seed"], "a ticket must carry a minted barcode seed"


def assert_ticket_barcode(barcode: Dict[str, Any]) -> None:
    _assert_keys(
        barcode,
        [
            "ticket_id",
            "barcode_seed",
            "barcode_epoch_index",
            "current_barcode",
            "accepted_epoch_floor",
        ],
        "barcode read",
    )
    assert isinstance(barcode["barcode_epoch_index"], int)
    assert isinstance(barcode["accepted_epoch_floor"], int)
    assert barcode["current_barcode"] == (
        f"{barcode['barcode_seed']}-{barcode['barcode_epoch_index']}"
    )
    assert barcode["accepted_epoch_floor"] == barcode["barcode_epoch_index"] - 1


def assert_transfer_request(transfer: Dict[str, Any]) -> None:
    assert_common_fields(transfer)
    _assert_keys(
        transfer,
        ["ticket_id", "from_patron_id", "to_patron_id", "status", "decided_at"],
        "transfer request",
    )


def assert_resale_listing(listing: Dict[str, Any]) -> None:
    assert_common_fields(listing)
    _assert_keys(
        listing,
        [
            "ticket_id",
            "seller_patron_id",
            "buyer_patron_id",
            "superseded_listing_id",
            "marketplace",
            "ask_price_cents",
            "cap_price_cents",
            "status",
            "platform_fee_cents",
            "venue_royalty_cents",
            "processing_fee_cents",
            "seller_payout_cents",
        ],
        "resale listing",
    )
    assert listing["status"] in {
        ListingStatus.LISTED,
        ListingStatus.SOLD,
        ListingStatus.DELISTED,
        ListingStatus.SUSPENDED,
    }
    assert isinstance(listing["ask_price_cents"], int)


def assert_scan_session(session: Dict[str, Any]) -> None:
    assert_common_fields(session)
    _assert_keys(
        session,
        [
            "gate_id",
            "operator_device_id",
            "mode",
            "status",
            "opened_at",
            "closed_at",
            "online_scan_count",
            "offline_uploaded_count",
            "duplicate_suppressed_count",
        ],
        "scan session",
    )
    assert session["status"] in {SessionStatus.OPEN, SessionStatus.SYNCING, SessionStatus.CLOSED}


def assert_scan_event(scan_event: Dict[str, Any]) -> None:
    assert_append_only_fields(scan_event)
    _assert_keys(
        scan_event,
        [
            "scan_session_id",
            "ticket_id",
            "presented_barcode",
            "device_fingerprint",
            "direction",
            "scanned_at",
            "recorded_at",
            "source",
            "result",
            "dedupe_key",
            "denied_reason_code",
        ],
        "scan event",
    )
    assert scan_event["source"] in {ScanSource.ONLINE, ScanSource.OFFLINE_BATCH}
    assert scan_event["result"] in {
        ScanResult.ADMITTED,
        ScanResult.EXIT_RECORDED,
        ScanResult.DENIED_DUPLICATE,
        ScanResult.DENIED_COUNTERFEIT,
        ScanResult.DENIED_DEVICE_MISMATCH,
        ScanResult.DENIED_ZONE,
        ScanResult.DENIED_CAPACITY,
        ScanResult.DENIED_VOIDED,
        ScanResult.DENIED_STALE_BARCODE,
        ScanResult.DENIED_REENTRY_LOCKOUT,
    }
    if scan_event["result"] in (ScanResult.ADMITTED, ScanResult.EXIT_RECORDED):
        assert scan_event["denied_reason_code"] is None


def assert_offline_batch_receipt(receipt: Dict[str, Any]) -> None:
    _assert_keys(
        receipt,
        ["accepted_count", "duplicate_suppressed_count", "denied_count", "scan_event_ids"],
        "offline batch receipt",
    )
    assert isinstance(receipt["scan_event_ids"], list)
    assert receipt["accepted_count"] + receipt["denied_count"] == len(receipt["scan_event_ids"])


def assert_credential_request(request: Dict[str, Any]) -> None:
    assert_common_fields(request)
    _assert_keys(
        request,
        [
            "event_id",
            "access_zone_id",
            "recipient_patron_id",
            "distribution_type",
            "quantity",
            "valid_from",
            "valid_until",
            "justification",
            "requested_by_user_id",
            "approved_by_user_id",
            "status",
            "revision_count",
            "issued_ticket_count",
            "forgone_revenue_cents",
        ],
        "credential request",
    )
    assert 1 <= request["quantity"] <= 50
    assert isinstance(request["forgone_revenue_cents"], int)


def assert_denied_entry_incident(incident: Dict[str, Any]) -> None:
    assert_common_fields(incident)
    _assert_keys(
        incident,
        [
            "scan_event_id",
            "ticket_id",
            "patron_id",
            "category",
            "status",
            "reviewer_user_id",
            "resolution_note",
            "remediation_credit_cents",
        ],
        "denied-entry incident",
    )
    assert incident["status"] in {
        IncidentStatus.OPEN,
        IncidentStatus.UNDER_REVIEW,
        IncidentStatus.REMEDIATED,
        IncidentStatus.DISMISSED,
    }
    assert incident["category"] in CATEGORY_WEIGHTS


def assert_reconciliation_report(report: Dict[str, Any]) -> None:
    assert_common_fields(report)
    _assert_keys(
        report,
        [
            "event_id",
            "reported_attendance",
            "scan_derived_attendance",
            "variance_count",
            "variance_pct",
            "fire_code_breach",
            "override_reason",
            "status",
            "finalized_by_user_id",
        ],
        "reconciliation report",
    )
    assert report["status"] in {ReportStatus.DRAFT, ReportStatus.FINAL, ReportStatus.REOPENED}
    assert isinstance(report["fire_code_breach"], bool)


def assert_audit_log_entry(entry: Dict[str, Any]) -> None:
    assert_append_only_fields(entry)
    _assert_keys(
        entry,
        [
            "event_id",
            "subject_type",
            "subject_id",
            "action",
            "actor_role",
            "actor_user_id",
            "occurred_at",
            "detail",
        ],
        "audit log entry",
    )


def assert_event_occupancy(occupancy: Dict[str, Any]) -> None:
    _assert_keys(
        occupancy,
        [
            "event_id",
            "live_occupancy",
            "peak_live_occupancy",
            "reconciled_attendance",
            "fire_code_capacity",
            "headroom",
            "projected_clearance_minutes",
            "zone_occupancy",
        ],
        "occupancy read",
    )
    assert occupancy["headroom"] == occupancy["fire_code_capacity"] - occupancy["live_occupancy"]
    assert isinstance(occupancy["zone_occupancy"], list)
    for zone in occupancy["zone_occupancy"]:
        _assert_keys(
            zone, ["id", "zone_code", "occupancy_count", "fire_code_capacity"], "zone occupancy"
        )


# ─── Domain arithmetic ────────────────────────────────────────────────────────


def round_half_up(value: float) -> int:
    """Round a cent amount half up to a whole cent."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def round_half_up_2dp(value: float) -> float:
    """Round a percentage to two decimals, half up."""
    if value >= 0:
        return math.floor(value * 100 + 0.5) / 100
    return -(math.floor(-value * 100 + 0.5) / 100)


def expected_epoch_index(anchor_epoch_seconds: int, instant_epoch_seconds: int) -> int:
    """The epoch index of an instant, rounded down toward negative infinity."""
    return math.floor(
        (instant_epoch_seconds - anchor_epoch_seconds) / BARCODE_ROTATION_SECONDS
    )


def expected_zone_posture(issued_entitlement_count: int, fire_code_capacity: int) -> str:
    """The posture derived from the exact issued-to-capacity ratio."""
    ratio = issued_entitlement_count / fire_code_capacity
    if ratio >= FROZEN_RATIO:
        return ZonePosture.FROZEN
    if ratio >= RESTRICTED_RATIO:
        return ZonePosture.RESTRICTED
    return ZonePosture.OPEN


def expected_price_cap(
    face_value_cents: int,
    ticket_type: str,
    price_cap_regime: str,
    seller_identity_verified: bool,
) -> Optional[int]:
    """The listing cap, or None when the regime imposes none."""
    if ticket_type in (TicketType.COMP, TicketType.CREDENTIAL):
        return 0
    if price_cap_regime == PriceCapRegime.NONE:
        return None
    pct = (
        STATUTORY_CAP_PCT
        if price_cap_regime == PriceCapRegime.STATUTORY
        else VENUE_POLICY_CAP_PCT
    )
    markup = min(round_half_up(face_value_cents * pct), MAX_ABS_MARKUP_CENTS)
    cap = face_value_cents + markup
    if price_cap_regime == PriceCapRegime.STATUTORY and not seller_identity_verified:
        return face_value_cents
    return cap


def expected_settlement_split(sale_price_cents: int) -> Dict[str, int]:
    """The four settlement components, each rounded before anything is summed."""
    platform = round_half_up(sale_price_cents * PLATFORM_FEE_PCT)
    royalty = round_half_up(sale_price_cents * VENUE_ROYALTY_PCT)
    processing = round_half_up(sale_price_cents * PROCESSING_FEE_PCT) + PROCESSING_FIXED_CENTS
    return {
        "platform_fee_cents": platform,
        "venue_royalty_cents": royalty,
        "processing_fee_cents": processing,
        "seller_payout_cents": sale_price_cents - (platform + royalty + processing),
    }


def expected_forgone_revenue(
    face_value_reference_cents: int, comp_discount_pct: float, quantity: int
) -> int:
    """Per-ticket forgone revenue rounded first, then multiplied by the quantity."""
    per_ticket = round_half_up(face_value_reference_cents * (1 - comp_discount_pct))
    return per_ticket * quantity


def expected_remediation_credit(
    face_value_cents: int, ticket_type: str, strike_count: int
) -> int:
    """The goodwill credit computed in the pinned five-step order."""
    base = face_value_cents if ticket_type == TicketType.PAID else 0
    if base <= GOODWILL_TIER1_CENTS:
        pct = GOODWILL_TIER1_PCT
    elif base <= GOODWILL_TIER2_CENTS:
        pct = GOODWILL_TIER2_PCT
    else:
        pct = GOODWILL_TIER3_PCT
    goodwill = round_half_up(base * pct)
    penalty = min(STRIKE_PENALTY_CENTS * strike_count, STRIKE_PENALTY_CAP_CENTS)
    return max(base + goodwill - penalty, 0)


def expected_fraud_score(
    device_rebind_count: int,
    open_or_under_review: List[str],
    remediated: List[str],
    basis: str,
) -> int:
    """The capped risk score under either reading of the incident history."""
    churn = DEVICE_CHURN_WEIGHT * max(device_rebind_count - 1, 0)
    total = churn + sum(CATEGORY_WEIGHTS[category] for category in open_or_under_review)
    for category in remediated:
        weight = CATEGORY_WEIGHTS[category]
        total += weight if basis == "PROVISIONAL" else round_half_up(weight * 0.5)
    return min(total, SCORE_CAP)


def expected_clearance_minutes(waiting: int, capacity_per_minute: int) -> Optional[int]:
    """Waiting population over per-minute capacity, rounded up; null at zero capacity."""
    if capacity_per_minute == 0:
        return None
    return math.ceil(waiting / capacity_per_minute)


# ─── Invariant checkers ───────────────────────────────────────────────────────


def assert_money_conserved(
    pool_before: int, pool_after: int, credit_before: int, credit_after: int
) -> None:
    """Whatever leaves the settlement pool must arrive in the holder's credit."""
    assert pool_before - pool_after == credit_after - credit_before, (
        f"pool moved by {pool_before - pool_after} while credit moved by "
        f"{credit_after - credit_before}"
    )


def assert_integer_cents(entity: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        value = entity[field]
        if value is not None:
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{field} must be integer cents, got {value!r}"
            )
