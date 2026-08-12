"""Entity assertions, semantic instant comparison and domain invariant checks."""

from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
CONFIG_COMMON_FIELDS = ("id", "created_at")


# ---------------------------------------------------------------------------
# Instants are compared SEMANTICALLY. Two renderings of the same point in time
# ("...Z", "...+00:00", any fractional-second precision) must compare equal;
# nothing here asserts a literal rendered form.
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse any legal ISO 8601 instant into an aware UTC datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(a: Any, b: Any, label: str = "instant") -> None:
    """Assert two ISO 8601 renderings denote the same point in time."""
    got = parse_instant(a)
    want = parse_instant(b)
    assert got == want, f"{label}: expected the instant {b}, got {a}"


def assert_instant_before(earlier: Any, later: Any, label: str = "instant") -> None:
    assert parse_instant(earlier) < parse_instant(later), (
        f"{label}: expected {earlier} to precede {later}"
    )


def assert_is_instant(value: Any, label: str = "instant") -> None:
    assert isinstance(value, str) and value, f"{label} must be a non-empty string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 timestamp, got {value!r}"
    parse_instant(value)


def assert_is_null(data: dict, field: str, label: str = "row") -> None:
    """A field the PRD says is null. Absence and an explicit null both satisfy it."""
    assert data.get(field) is None, (
        f"{label}.{field} must be null, got {data.get(field)!r}"
    )


# ---------------------------------------------------------------------------
# Common-field shape
# ---------------------------------------------------------------------------
def assert_versioned_row(data: dict, label: str = "row") -> None:
    """Rows that carry id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_is_instant(data.get("created_at"), f"{label}.created_at")
    assert_is_instant(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_config_row(data: dict, label: str = "row") -> None:
    """Configuration rows carry only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_is_instant(data.get("created_at"), f"{label}.created_at")
    assert "version" not in data, f"{label} must not return a version key"
    assert "updated_at" not in data, f"{label} must not return an updated_at key"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_household(data: dict) -> None:
    assert_versioned_row(data, "Household")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 3
    assert data["region_code"].isupper() and data["region_code"].isalpha()
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["entitled_device_count"], int) and data["entitled_device_count"] >= 0
    assert isinstance(data["active_device_count"], int) and data["active_device_count"] >= 0
    assert data["active_device_count"] <= data["entitled_device_count"], (
        "active_device_count counts a subset of the entitled lifecycle states"
    )


def assert_household_member(data: dict) -> None:
    assert_versioned_row(data, "HouseholdMember")
    assert data["member_role"] in ("OWNER", "MEMBER", "BILLING_ADMIN")
    assert isinstance(data["is_active"], bool)


def assert_subscription_plan(data: dict) -> None:
    assert_config_row(data, "SubscriptionPlan")
    assert data["tier"] in ("BASIC", "PLUS", "PRO")
    assert data["coverage_mode"] in ("BUSINESS_HOURS", "TWENTY_FOUR_SEVEN")
    assert data["monthly_fee_cents"] >= 0
    assert data["included_device_count"] >= 1


def assert_subscription(data: dict) -> None:
    assert_versioned_row(data, "Subscription")
    assert data["status"] in (
        "ACTIVE",
        "PAST_DUE",
        "SUSPENDED",
        "CANCEL_PENDING",
        "CANCELLED",
    )
    assert isinstance(data["allow_overage"], bool)
    assert data["cycle_index"] >= 1
    assert_is_instant(data["cycle_start_at"], "Subscription.cycle_start_at")
    assert_is_instant(data["cycle_end_at"], "Subscription.cycle_end_at")
    assert_install_credit_conservation(data)
    assert data["install_credits_remaining"] >= 0
    assert data["overage_charges_cents_this_cycle"] >= 0
    assert data["credits_issued_cents_this_cycle"] >= 0


def assert_catalog_entry(data: dict) -> None:
    assert_config_row(data, "DeviceCatalogEntry")
    assert data["device_class"] in ("HUB", "CAMERA", "SENSOR", "THERMOSTAT", "LOCK")
    assert isinstance(data["requires_install"], bool)
    assert isinstance(data["manufacturer_service_only"], bool)
    assert data["msrp_cents"] >= 0


def assert_device(data: dict) -> None:
    assert_versioned_row(data, "Device")
    assert data["lifecycle_status"] in (
        "CLAIMED",
        "ACTIVE",
        "RECLAIMABLE",
        "SERVICE_HOLD",
        "SUSPENDED_RMA",
        "TRANSFER_PENDING",
        "DECOMMISSIONED",
    )
    assert data["firmware_status"] in (
        "CURRENT",
        "UPDATE_PENDING",
        "ROLLED_BACK",
        "DEFERRED",
        "BLOCKED",
    )
    assert data["warranty_basis"] in ("BASE_ONLY", "TIER_EXTENDED")
    assert isinstance(data["is_overage"], bool)
    assert isinstance(data["activation_attempts"], int) and data["activation_attempts"] >= 0
    assert_is_instant(data["warranty_expires_at"], "Device.warranty_expires_at")


def assert_ticket(data: dict) -> None:
    assert_versioned_row(data, "Ticket")
    assert data["severity"] in ("P1", "P2", "P3")
    assert data["workflow_status"] in (
        "NEW",
        "TRIAGED",
        "REMOTE_DIAG",
        "AWAITING_CUSTOMER",
        "DISPATCH_PENDING",
        "ONSITE",
        "RESOLVED",
        "REOPENED",
        "CLOSED",
    )
    assert data["sla_status"] in (
        "WITHIN",
        "AT_RISK",
        "PAUSED",
        "BREACHED_FIRST_RESPONSE",
        "BREACHED_ONSITE",
        "MET",
        "CREDITED",
    )
    assert data["dispatch_status"] in (
        "NOT_REQUIRED",
        "REQUIRED",
        "SCHEDULED",
        "RESCHEDULING",
        "NO_SHOW",
        "COMPLETED",
    )
    for field in ("sla_counted_minutes", "sla_paused_minutes", "sla_uncovered_minutes"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Ticket.{field} must be a non-negative integer, got {data[field]!r}"
        )


def assert_remote_session(data: dict) -> None:
    assert_versioned_row(data, "RemoteSession")
    assert data["status"] in ("IN_PROGRESS", "COMPLETED")
    assert data["outcome"] in (None, "RESOLVED", "FAILED", "HARDWARE_FAULT")
    assert isinstance(data["session_index"], int) and data["session_index"] >= 1


def assert_technician(data: dict) -> None:
    assert_versioned_row(data, "Technician")
    assert isinstance(data["skills"], list) and data["skills"]
    assert_slot_capacity_conservation(data)


def assert_visit_slot(data: dict) -> None:
    assert_versioned_row(data, "VisitSlot")
    assert data["status"] in ("OPEN", "BOOKED", "BLOCKED")
    assert_instant_before(data["start_at"], data["end_at"], "VisitSlot window")


def assert_visit(data: dict) -> None:
    assert_versioned_row(data, "Visit")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["fee_kind"] in ("NONE", "LATE_CANCEL", "NO_SHOW")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["fee_waived"], bool)


def assert_campaign(data: dict) -> None:
    assert_versioned_row(data, "FirmwareCampaign")
    assert data["kind"] in ("SECURITY_MANDATORY", "FEATURE_OPTIONAL")
    assert data["status"] in ("DRAFT", "RING_ACTIVE", "HALTED", "COMPLETED")
    assert data["ring_device_count"] >= 0
    assert data["ring_failed_count"] >= 0
    assert data["ring_failed_count"] <= data["ring_device_count"]


def assert_rollout(data: dict) -> None:
    assert_versioned_row(data, "FirmwareRollout")
    assert data["status"] in (
        "PENDING",
        "APPLIED",
        "ROLLED_BACK",
        "DEFERRED",
        "BLOCKED_BY_HALT",
        "BLOCKED_BY_SERVICE",
    )
    assert data["last_result"] in (None, "SUCCESS", "FAILURE")
    assert 0 <= data["retry_count"] <= 2


def assert_addon_order(data: dict) -> None:
    assert_versioned_row(data, "AddOnOrder")
    assert data["status"] in ("PLACED", "FULFILLED")
    assert data["proration_mode"] in ("MID_CYCLE_PRORATED", "NEXT_CYCLE_FULL")
    for field in (
        "subtotal_cents",
        "bundle_discount_cents",
        "discounted_subtotal_cents",
        "install_credits_applied",
        "install_charge_cents",
        "monthly_delta_cents",
        "proration_cents",
        "order_total_cents",
    ):
        assert isinstance(data[field], int), f"AddOnOrder.{field} must be integer cents/count"
    assert data["discounted_subtotal_cents"] == (
        data["subtotal_cents"] - data["bundle_discount_cents"]
    ), "discounted_subtotal_cents is subtotal_cents less bundle_discount_cents"
    assert data["order_total_cents"] == (
        data["discounted_subtotal_cents"]
        + data["install_charge_cents"]
        + data["proration_cents"]
    ), "order_total_cents is the sum of its three declared components"


def assert_rma_case(data: dict) -> None:
    assert_versioned_row(data, "RmaCase")
    assert data["warranty_state"] in ("IN_WARRANTY", "EXPIRED")
    assert data["routing_target"] in (
        "MANUFACTURER",
        "IN_HOUSE_DEPOT",
        "ADVANCE_REPLACEMENT",
        "CUSTOMER_PAID_DEPOT",
    )
    assert data["status"] in (
        "OPEN",
        "ROUTED",
        "ADVANCE_SHIPPED",
        "AWAITING_RETURN",
        "RETURN_RECEIVED",
        "RETURN_WINDOW_EXPIRED",
        "CHARGED",
        "CLOSED",
        "SUPERSEDED",
    )
    assert data["hold_state"] in ("NONE", "HELD", "RELEASED", "CHARGED")
    assert isinstance(data["hold_amount_cents"], int) and data["hold_amount_cents"] >= 0


def assert_survey(data: dict) -> None:
    assert_versioned_row(data, "SatisfactionSurvey")
    assert 1 <= data["score"] <= 5
    assert data["credit_variant"] in ("NONE", "BREACH_COMPOUNDED", "GOODWILL")
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0


def assert_service_credit(data: dict) -> None:
    assert_versioned_row(data, "ServiceCredit")
    assert data["reason"] in (
        "SLA_FIRST_RESPONSE_BREACH",
        "SLA_ONSITE_BREACH",
        "CSAT_BREACH_COMPOUNDED",
        "CSAT_GOODWILL",
    )
    assert data["breach_tier"] in (None, "MINOR", "MAJOR", "SEVERE")
    assert data["amount_cents"] > 0, "a ServiceCredit row exists only for a positive amount"
    assert data["amount_cents"] <= data["uncapped_amount_cents"]
    assert data["applied_to_cycle_index"] == data["cycle_index"] + 1, (
        "applied_to_cycle_index is always the issuing cycle_index plus one"
    )


# ---------------------------------------------------------------------------
# Conservation invariants
# ---------------------------------------------------------------------------
def assert_slot_capacity_conservation(technician: dict) -> None:
    total = technician["total_slot_count"]
    parts = (
        technician["open_slot_count"]
        + technician["booked_slot_count"]
        + technician["blocked_slot_count"]
    )
    assert parts == total, (
        "open + booked + blocked must equal total_slot_count; got "
        f"{technician['open_slot_count']} + {technician['booked_slot_count']} + "
        f"{technician['blocked_slot_count']} != {total}"
    )


def assert_install_credit_conservation(subscription: dict) -> None:
    assert (
        subscription["install_credits_remaining"] + subscription["install_credits_consumed"]
        == subscription["install_credits_granted"]
    ), (
        "install_credits_remaining + install_credits_consumed must equal "
        f"install_credits_granted; got {subscription['install_credits_remaining']} + "
        f"{subscription['install_credits_consumed']} != {subscription['install_credits_granted']}"
    )


def assert_ticket_minute_conservation(ticket: dict, total_elapsed_minutes: int) -> None:
    got = (
        ticket["sla_counted_minutes"]
        + ticket["sla_paused_minutes"]
        + ticket["sla_uncovered_minutes"]
    )
    assert got == total_elapsed_minutes, (
        "counted + paused + uncovered must equal the whole minutes elapsed; got "
        f"{got} against {total_elapsed_minutes}"
    )


def assert_slot_counts(
    technician: dict, total: int, open_count: int, booked: int, blocked: int
) -> None:
    assert technician["total_slot_count"] == total, (
        f"total_slot_count expected {total}, got {technician['total_slot_count']}"
    )
    assert technician["open_slot_count"] == open_count, (
        f"open_slot_count expected {open_count}, got {technician['open_slot_count']}"
    )
    assert technician["booked_slot_count"] == booked, (
        f"booked_slot_count expected {booked}, got {technician['booked_slot_count']}"
    )
    assert technician["blocked_slot_count"] == blocked, (
        f"blocked_slot_count expected {blocked}, got {technician['blocked_slot_count']}"
    )
    assert_slot_capacity_conservation(technician)


# ---------------------------------------------------------------------------
# Envelope / listing helpers
# ---------------------------------------------------------------------------
def assert_success_envelope(body: dict, response_type: str = "object") -> None:
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    assert_is_instant(meta.get("api_request_timestamp"), "meta.api_request_timestamp")
    assert body.get("response_type") == response_type, (
        f"response_type expected {response_type}, got {body.get('response_type')!r}"
    )


def find_one(rows: Iterable[dict], **match) -> dict:
    """Return the single row matching every key/value pair; fail if not exactly one."""
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, f"expected exactly one row matching {match}, found {len(hits)}"
    return hits[0]


def maybe_one(rows: Iterable[dict], **match) -> Optional[dict]:
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) <= 1, f"expected at most one row matching {match}, found {len(hits)}"
    return hits[0] if hits else None
