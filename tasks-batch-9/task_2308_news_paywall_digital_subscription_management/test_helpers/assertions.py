"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    BILLING_RUN_ARRAYS,
    AccessClass,
    AccessDecision,
    BundleType,
    CancellationRequestStatus,
    CardStatus,
    CardUpdaterStatus,
    ChurnRiskBand,
    ContentType,
    DunningStatus,
    EntitlementSource,
    GrandfatherPolicy,
    GroupAccountStatus,
    HoldStatus,
    HoldType,
    InvoiceStatus,
    LifecycleStatus,
    OfferPlanStatus,
    PaymentOutcome,
    PaywallAction,
    PaywallRuleStatus,
    PriceChangeState,
    PriceSource,
    PrintFulfillmentStatus,
    PropensityBand,
    ReaderEventType,
    SaveOfferStatus,
    SaveOfferTier,
    SaveOfferType,
    SeatStatus,
)


def _values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------
# Envelope / common property assertions
# --------------------------------------------------------------------------


def assert_response_envelope(response, expected_response_type: str = "object") -> Dict[str, Any]:
    """Assert the standard success envelope on a raw response and return the body."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp"
    )
    assert body["response_type"] == expected_response_type, (
        f"Expected response_type {expected_response_type!r}, got {body['response_type']!r}"
    )
    return body


def assert_common_fields(data: Dict[str, Any]) -> None:
    """id, created_at, updated_at and version — the full system-managed set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """Append-only records carry only id and created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, (
        "append-only records must not carry updated_at"
    )
    assert "version" not in data, "append-only records must not carry version"


def assert_iso_date(value: Any, field: str) -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} must be an ISO calendar date in YYYY-MM-DD form, got {value!r}"
    )


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------


def assert_offer_plan(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["bundle_type"] in _values(BundleType)
    assert data["status"] in _values(OfferPlanStatus)
    for field in (
        "intro_price_cents",
        "intro_cycles",
        "standard_from_cycle",
        "standard_price_cents",
        "cycle_days",
        "print_component_cents",
        "print_deliveries_per_cycle",
        "per_seat_price_cents",
        "active_subscription_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)!r}"
        )
    assert 1 <= data["cycle_days"] <= 92, "cycle_days must be between 1 and 92 inclusive"
    assert isinstance(data["step_up_schedule"], list)
    assert isinstance(data["print_delivery_days"], list)
    assert data["price_change_state"] in _values(PriceChangeState)
    assert data["grandfather_policy"] in _values(GrandfatherPolicy)


def assert_paywall_rule(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["status"] in _values(PaywallRuleStatus)
    assert data["content_type_match"] in _values(ContentType)
    assert data["propensity_band_match"] in _values(PropensityBand)
    assert isinstance(data["section_match"], str)
    assert data["action"] in _values(PaywallAction)
    assert isinstance(data["priority"], int) and 1 <= data["priority"] <= 999
    assert isinstance(data["specificity_score"], int) and 0 <= data["specificity_score"] <= 111


def assert_article(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["headline"], str) and 1 <= len(data["headline"]) <= 240
    assert data["content_type"] in ["NEWS", "OPINION", "INVESTIGATION", "LIVE_BLOG"]
    assert isinstance(data["section"], str) and data["section"] == data["section"].lower()
    assert data["access_class"] in _values(AccessClass)
    assert is_iso8601_timestamp(data["published_at"]), "published_at must be RFC 3339"


def assert_reader(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["is_registered"], bool)
    assert data["propensity_band"] in ["HIGH", "MEDIUM", "LOW"]
    assert isinstance(data["engagement_score"], (int, float))
    assert data["churn_risk_band"] in _values(ChurnRiskBand)
    assert isinstance(data["metered_article_ids"], list)
    assert isinstance(data["metered_distinct_article_count"], int)
    assert data["metered_distinct_article_count"] == len(data["metered_article_ids"]), (
        "metered_distinct_article_count must equal the length of metered_article_ids"
    )
    assert_iso_date(data["meter_period_started_on"], "meter_period_started_on")
    assert data["entitlement_source"] in _values(EntitlementSource)
    assert data["card_status"] in _values(CardStatus)
    assert isinstance(data["card_updater_registered"], bool)
    assert data["card_updater_status"] in _values(CardUpdaterStatus)
    assert isinstance(data["intervention_count_in_period"], int)


def assert_subscription(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["reader_id"])
    assert is_valid_uuid(data["offer_plan_id"])
    assert data["lifecycle_status"] in _values(LifecycleStatus)
    assert data["dunning_status"] in _values(DunningStatus)
    assert data["print_fulfillment_status"] in _values(PrintFulfillmentStatus)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert_iso_date(data["cycle_start_on"], "cycle_start_on")
    for field in (
        "next_cycle_price_cents",
        "pending_credit_cents",
        "lifetime_credit_cents",
        "payment_attempt_count",
        "max_payment_attempts",
        "vacation_days_used_365",
        "tenure_cycles",
        "retention_discount_cycles_remaining",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer, got {data.get(field)!r}"
        )
    assert 0 <= data["retention_discount_pct"] <= 0.40, (
        "retention_discount_pct must be a fraction between 0 and 0.40 inclusive"
    )


def assert_invoice(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["status"] in _values(InvoiceStatus)
    assert data["price_source"] in _values(PriceSource)
    for field in (
        "base_line_cents",
        "seat_line_cents",
        "discount_line_cents",
        "credit_line_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer of cents, got {data.get(field)!r}"
        )
    assert_iso_date(data["due_on"], "due_on")
    assert data["total_cents"] >= 0, "total_cents is floored at zero"


def assert_invoice_waterfall(data: Dict[str, Any]) -> None:
    """total_cents is subtotal minus discount minus credit, floored at zero."""
    subtotal = data["base_line_cents"] + data["seat_line_cents"]
    expected = max(
        0, subtotal - data["discount_line_cents"] - data["credit_line_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} must equal subtotal {subtotal} less "
        f"discount {data['discount_line_cents']} less credit "
        f"{data['credit_line_cents']}, floored at zero ({expected})"
    )


def assert_payment_attempt(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert data["outcome"] in _values(PaymentOutcome)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["is_final"], bool)
    assert_iso_date(data["attempted_on"], "attempted_on")


def assert_reader_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["reader_id"])
    assert data["event_type"] in _values(ReaderEventType)
    assert isinstance(data["weight"], int)
    assert is_iso8601_timestamp(data["occurred_at"]), "occurred_at must be RFC 3339"
    if data.get("decision") is not None:
        assert data["decision"] in _values(AccessDecision)


def assert_cancellation_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["status"] in _values(CancellationRequestStatus)
    assert data["reason_code"] in ["PRICE", "CONTENT", "TECHNICAL", "LIFE_CHANGE", "OTHER"]
    assert isinstance(data["save_offer_count"], int) and data["save_offer_count"] >= 0
    assert isinstance(data["projected_engagement_score"], (int, float))
    assert data["eligible_save_offer_tier"] in _values(SaveOfferTier)
    assert isinstance(data["retained"], bool)


def assert_save_offer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cancellation_request_id"])
    assert data["offer_type"] in _values(SaveOfferType)
    assert 0 <= data["discount_pct"] <= 0.40, (
        "discount_pct must be a fraction between 0 and 0.40 inclusive"
    )
    assert isinstance(data["duration_cycles"], int) and data["duration_cycles"] >= 0
    assert isinstance(data["pause_days"], int) and data["pause_days"] >= 0
    assert data["status"] in _values(SaveOfferStatus)
    assert_iso_date(data["presented_on"], "presented_on")


def assert_hold(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["subscription_id"])
    assert data["hold_type"] in _values(HoldType)
    assert_iso_date(data["start_date"], "start_date")
    assert_iso_date(data["end_date"], "end_date")
    assert data["end_date"] >= data["start_date"], (
        "end_date must be on or after start_date"
    )
    assert data["status"] in _values(HoldStatus)
    assert isinstance(data["delivery_days_credited"], int) and data["delivery_days_credited"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert isinstance(data["credit_applied"], bool)


def assert_group_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert isinstance(data["admin_email"], str) and "@" in data["admin_email"]
    assert isinstance(data["allowed_email_domain"], str)
    assert data["allowed_email_domain"] == data["allowed_email_domain"].lower()
    assert isinstance(data["seat_capacity"], int) and 1 <= data["seat_capacity"] <= 10000
    assert is_valid_uuid(data["offer_plan_id"])
    assert data["status"] in _values(GroupAccountStatus)
    assert_seat_capacity_conserved(data)


def assert_seat(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["group_account_id"])
    assert is_valid_uuid(data["reader_id"])
    assert data["status"] in _values(SeatStatus)
    assert_iso_date(data["starts_on"], "starts_on")
    assert_iso_date(data["invited_on"], "invited_on")
    assert_iso_date(data["invite_expires_on"], "invite_expires_on")
    if data.get("ends_on") is not None:
        assert data["ends_on"] > data["starts_on"], (
            "a seat whose ends_on equals its starts_on is a zero-length occupancy"
        )


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------


def assert_seat_capacity_conserved(group: Dict[str, Any]) -> None:
    """seat_capacity equals seats_assigned_count plus seats_available_count."""
    assigned = group["seats_assigned_count"]
    available = group["seats_available_count"]
    assert isinstance(assigned, int) and assigned >= 0
    assert isinstance(available, int) and available >= 0
    assert group["seat_capacity"] == assigned + available, (
        f"seat_capacity {group['seat_capacity']} must equal seats_assigned_count "
        f"{assigned} plus seats_available_count {available}"
    )


def assert_billing_run_report(
    report: Dict[str, Any], scope: str, non_empty: Optional[Iterable[str]] = None
) -> None:
    """Every one of the ten arrays is present; out-of-scope passes are empty."""
    assert isinstance(report.get("run_id"), str) and report["run_id"], "run_id must be present"
    assert report["scope"] == scope, f"scope must be echoed as {scope}, got {report.get('scope')}"
    non_empty = set(non_empty or ())
    for key in BILLING_RUN_ARRAYS:
        assert key in report, f"{key} must be present rather than absent"
        assert isinstance(report[key], list), f"{key} must be an array"
        if key not in non_empty:
            assert report[key] == [], (
                f"{key} must be an empty array for this run, got {report[key]}"
            )


def assert_hold_credit_bookkeeping(subscription: Dict[str, Any], holds: List[Dict[str, Any]]) -> None:
    """pending_credit_cents and lifetime_credit_cents follow the holds' credit flags."""
    pending = sum(
        h["credit_cents"]
        for h in holds
        if h["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED") and not h["credit_applied"]
    )
    lifetime = sum(h["credit_cents"] for h in holds if h["credit_applied"])
    assert subscription["pending_credit_cents"] == pending, (
        f"pending_credit_cents {subscription['pending_credit_cents']} must equal the sum "
        f"of unapplied SCHEDULED/ACTIVE/COMPLETED hold credit ({pending})"
    )
    assert subscription["lifetime_credit_cents"] == lifetime, (
        f"lifetime_credit_cents {subscription['lifetime_credit_cents']} must equal the sum "
        f"of credit over holds whose credit_applied is true ({lifetime})"
    )


def assert_no_version_regression(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    assert after["version"] >= before["version"], (
        f"version must never move backwards: {before['version']} -> {after['version']}"
    )
