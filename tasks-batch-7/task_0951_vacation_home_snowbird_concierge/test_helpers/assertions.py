"""Entity assertions, semantic timestamp comparison and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, accepting 'Z', '+00:00' and optional
    fractional seconds. Returns a timezone-aware datetime in UTC."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label: str = "timestamp"):
    """Compare two ISO 8601 instants semantically, never as strings.

    '2026-03-01T00:00:00Z', '2026-03-01T00:00:00.000Z' and
    '2026-03-01T00:00:00+00:00' all name the same instant.
    """
    assert actual is not None, f"{label}: expected {expected}, got None"
    a = parse_instant(actual)
    b = parse_instant(expected)
    assert a == b, f"{label}: expected instant {expected} ({b.isoformat()}), got {actual} ({a.isoformat()})"


def instants_equal(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return parse_instant(a) == parse_instant(b)


def assert_utc_millis_format(value: str, label: str = "timestamp"):
    """The PRD requires ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"


# --------------------------------------------------------------------------
# Generic shape helpers
# --------------------------------------------------------------------------

def assert_common_fields(data: dict, entity: str = "resource"):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_enum(data: dict, field: str, allowed, entity: str = "resource"):
    assert data.get(field) in allowed, (
        f"{entity}.{field} must be one of {list(allowed)}, got {data.get(field)!r}"
    )


def assert_money(data: dict, field: str, entity: str = "resource"):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{entity}.{field} must be an integer number of cents, got {value!r}"
    )


def assert_one_decimal_place(value, label: str = "value"):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    assert round(float(value), 1) == float(value), (
        f"{label} must carry one decimal place, got {value!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_owner(data: dict):
    assert_common_fields(data, "Owner")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert "@" in data["email"], "Owner.email must contain an at-sign"
    assert_enum(data, "status", ["ACTIVE", "INACTIVE"], "Owner")
    assert_enum(data, "notification_preference", ["EMAIL", "SMS", "BOTH"], "Owner")
    assert isinstance(data["snowbird_flag"], bool)
    assert_money(data, "lifetime_credit_balance_cents", "Owner")


def assert_property(data: dict):
    assert_common_fields(data, "Property")
    assert_enum(data, "travel_zone", ["Z1", "Z2", "Z3", "OUT_OF_AREA"], "Property")
    assert_enum(data, "seasonal_state", ["OPEN", "CLOSING", "WINTERIZED", "OPENING"], "Property")
    assert_enum(
        data, "occupancy_state",
        ["VACANT", "OWNER_IN_RESIDENCE", "RENTAL_OCCUPIED", "CONTRACTOR_ONSITE"], "Property",
    )
    assert_enum(data, "risk_posture", ["NORMAL", "ELEVATED", "CRITICAL"], "Property")
    assert isinstance(data["storm_hold_flag"], bool)
    assert 0.0 <= float(data["freeze_risk_score"]) <= 100.0
    assert_one_decimal_place(data["freeze_risk_score"], "Property.freeze_risk_score")


def assert_service_plan(data: dict):
    assert_common_fields(data, "ServicePlan")
    assert_enum(data, "tier", ["BASIC", "STANDARD", "PREMIUM"], "ServicePlan")
    assert_enum(data, "status", ["ACTIVE", "RETIRED"], "ServicePlan")
    assert_enum(data, "entitlement_rollover_policy", ["EXPIRE", "CARRY_CAPPED"], "ServicePlan")
    assert isinstance(data["covered_visit_types"], list) and data["covered_visit_types"]
    assert_money(data, "monthly_fee_cents", "ServicePlan")


def assert_subscription(data: dict):
    assert_common_fields(data, "Subscription")
    assert_enum(
        data, "status",
        ["PENDING_ACTIVATION", "ACTIVE", "PAUSED", "DELINQUENT", "CANCELLED"], "Subscription",
    )


def assert_billing_cycle(data: dict):
    assert_common_fields(data, "BillingCycle")
    assert_enum(data, "status", ["OPEN", "CLOSING", "CLOSED"], "BillingCycle")
    assert_entitlement_conservation(data)


def assert_visit(data: dict):
    assert_common_fields(data, "Visit")
    assert_enum(
        data, "status",
        ["SCHEDULED", "EN_ROUTE", "IN_PROGRESS", "COMPLETED", "DEFERRED", "CONVERTED", "ABORTED"],
        "Visit",
    )
    assert isinstance(data["entitlement_applied"], bool)
    assert isinstance(data["after_hours_flag"], bool)
    assert_money(data, "billable_amount_cents", "Visit")


def assert_finding(data: dict):
    assert_common_fields(data, "Finding")
    assert_enum(data, "severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"], "Finding")
    assert_enum(
        data, "status",
        ["OPEN", "TRIAGED", "MONITORING", "WORK_ORDERED", "DISMISSED"], "Finding",
    )
    assert 0.0 <= float(data["escalation_score"]) <= 100.0


def assert_vendor(data: dict):
    assert_common_fields(data, "Vendor")
    assert_enum(data, "status", ["ONBOARDING", "ELIGIBLE", "SUSPENDED", "LAPSED"], "Vendor")
    assert_enum(data, "billing_mode", ["MANAGED", "PASS_THROUGH"], "Vendor")
    assert 0 <= float(data["rating"]) <= 5


def assert_work_order(data: dict):
    assert_common_fields(data, "WorkOrder")
    assert_enum(data, "pipeline", ["ROUTINE", "STORM"], "WorkOrder")
    assert_enum(
        data, "status",
        ["DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "DISPATCHED",
         "IN_PROGRESS", "COMPLETED", "INVOICED", "VOID"],
        "WorkOrder",
    )
    assert_work_order_cost_conservation(data)


def assert_vendor_assignment(data: dict):
    assert_common_fields(data, "VendorAssignment")
    assert_enum(
        data, "status",
        ["OFFERED", "ACCEPTED", "DECLINED", "WORKING", "FINISHED", "WITHDRAWN"],
        "VendorAssignment",
    )


def assert_key_asset(data: dict):
    assert_common_fields(data, "KeyAsset")
    assert_enum(data, "key_type", ["PHYSICAL", "LOCKBOX"], "KeyAsset")
    assert_key_copy_conservation(data)


def assert_key_issuance(data: dict):
    assert_common_fields(data, "KeyIssuance")
    assert_enum(
        data, "status",
        ["ISSUED", "RETURNED", "OVERDUE", "RETURNED_LATE", "LOST", "REKEY_ORDERED"],
        "KeyIssuance",
    )


def assert_access_grant(data: dict):
    assert_common_fields(data, "AccessGrant")
    assert_enum(
        data, "status", ["PENDING", "ACTIVE", "REVOKED", "EXPIRED", "INVALIDATED"], "AccessGrant"
    )


def assert_winterization_record(data: dict):
    assert_common_fields(data, "WinterizationRecord")
    assert_enum(
        data, "status", ["NOT_STARTED", "PARTIAL", "COMPLETE", "REOPENED"], "WinterizationRecord"
    )
    assert 0 <= data["completed_step_count"] <= 4


def assert_rental_turnover(data: dict):
    assert_common_fields(data, "RentalTurnover")
    assert_enum(
        data, "status",
        ["BOOKED", "CHECKOUT", "CLEANING", "INSPECTION", "READY", "CHECKIN", "CANCELLED"],
        "RentalTurnover",
    )


def assert_mail_hold(data: dict):
    assert_common_fields(data, "MailHold")
    assert_enum(
        data, "status", ["REQUESTED", "ACTIVE", "OVERFLOW", "FORWARDED", "RELEASED"], "MailHold"
    )
    assert data["package_count"] >= 0, "MailHold.package_count is floored at zero"


def assert_security_incident(data: dict):
    assert_common_fields(data, "SecurityIncident")
    assert_enum(
        data, "incident_type",
        ["ALARM_INTRUSION", "ALARM_SMOKE", "FREEZE_ALARM", "WATER_LEAK", "VANDALISM",
         "UNAUTHORIZED_ACCESS"],
        "SecurityIncident",
    )
    assert_enum(
        data, "status",
        ["REPORTED", "ACKNOWLEDGED", "INVESTIGATING", "ESCALATED", "RESOLVED", "FALSE_ALARM"],
        "SecurityIncident",
    )


def assert_storm_event(data: dict):
    assert_common_fields(data, "StormEvent")
    assert_enum(
        data, "status",
        ["FORECAST", "WATCH", "WARNING", "IMMINENT", "LANDFALL", "ALL_CLEAR", "CLOSED"],
        "StormEvent",
    )
    assert_enum(data, "derived_tier", ["FORECAST", "WATCH", "WARNING", "IMMINENT"], "StormEvent")


def assert_storm_response(data: dict):
    assert_common_fields(data, "StormResponse")
    assert_enum(
        data, "status",
        ["PENDING", "SECURE_SWEEP_SCHEDULED", "SECURED", "SECURED_LATE", "MISSED_DEADLINE",
         "AWAITING_ALL_CLEAR", "ASSESSMENT_DUE", "ASSESSED", "CLOSED"],
        "StormResponse",
    )


def assert_invoice(data: dict):
    assert_common_fields(data, "Invoice")
    assert_enum(
        data, "status",
        ["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "VOID"], "Invoice"
    )
    assert_invoice_total_conservation(data)


def assert_invoice_line(data: dict):
    assert_common_fields(data, "InvoiceLine")
    assert_enum(data, "status", ["ACTIVE", "VOID"], "InvoiceLine")
    assert_enum(
        data, "line_type",
        ["SUBSCRIPTION_FEE", "VISIT_OVERAGE", "TRAVEL_SURCHARGE", "WORK_ORDER", "FALSE_ALARM_FEE",
         "MAIL_DISPOSITION", "REKEY_FEE", "ENTITLEMENT_OFFSET", "GUARANTEE_CREDIT"],
        "InvoiceLine",
    )
    assert data["sequence_index"] >= 1, "InvoiceLine.sequence_index is one-based"


# --------------------------------------------------------------------------
# Conservation invariants (PRD 2.11)
# --------------------------------------------------------------------------

def assert_entitlement_conservation(cycle: dict):
    """granted + carried_in - consumed - remaining == 0."""
    total = (
        cycle["entitlement_granted_units"]
        + cycle["entitlement_carried_in_units"]
        - cycle["entitlement_consumed_units"]
        - cycle["entitlement_remaining_units"]
    )
    assert total == 0, (
        "entitlement conservation broken: granted "
        f"{cycle['entitlement_granted_units']} + carried_in {cycle['entitlement_carried_in_units']}"
        f" - consumed {cycle['entitlement_consumed_units']}"
        f" - remaining {cycle['entitlement_remaining_units']} != 0"
    )


def assert_entitlement_rollover_conservation(cycle: dict):
    """Once CLOSED, remaining == carried_out + expired."""
    assert cycle["status"] == "CLOSED", "rollover conservation only holds once the cycle is CLOSED"
    assert cycle["entitlement_remaining_units"] == (
        cycle["entitlement_carried_out_units"] + cycle["entitlement_expired_units"]
    ), (
        f"rollover conservation broken: remaining {cycle['entitlement_remaining_units']} != "
        f"carried_out {cycle['entitlement_carried_out_units']} + "
        f"expired {cycle['entitlement_expired_units']}"
    )


def assert_key_copy_conservation(key_asset: dict):
    """copies_total == copies_on_hand + copies_issued_outstanding + copies_lost."""
    expected = (
        key_asset["copies_on_hand"]
        + key_asset["copies_issued_outstanding"]
        + key_asset["copies_lost"]
    )
    assert key_asset["copies_total"] == expected, (
        f"key copy conservation broken: copies_total {key_asset['copies_total']} != "
        f"on_hand {key_asset['copies_on_hand']} + outstanding "
        f"{key_asset['copies_issued_outstanding']} + lost {key_asset['copies_lost']}"
    )


def assert_work_order_cost_conservation(work_order: dict):
    """total_cents == labour + parts + markup + storm surcharge."""
    expected = (
        work_order["labour_cost_cents"]
        + work_order["parts_cost_cents"]
        + work_order["markup_cents"]
        + work_order["storm_surcharge_cents"]
    )
    assert work_order["total_cents"] == expected, (
        f"work-order cost conservation broken: total {work_order['total_cents']} != "
        f"labour {work_order['labour_cost_cents']} + parts {work_order['parts_cost_cents']}"
        f" + markup {work_order['markup_cents']}"
        f" + surcharge {work_order['storm_surcharge_cents']}"
    )


def assert_invoice_total_conservation(invoice: dict):
    """subtotal == net service + storm surcharge + guarantee credit, and
    total == subtotal + tax + late fee, and balance == total - paid."""
    net = invoice["gross_service_cents"] + invoice["entitlement_offset_cents"]
    expected_subtotal = net + invoice["storm_surcharge_cents"] + invoice["guarantee_credit_cents"]
    assert invoice["subtotal_cents"] == expected_subtotal, (
        f"invoice subtotal conservation broken: subtotal {invoice['subtotal_cents']} != "
        f"net {net} + storm {invoice['storm_surcharge_cents']} + "
        f"guarantee {invoice['guarantee_credit_cents']}"
    )
    expected_total = invoice["subtotal_cents"] + invoice["tax_cents"] + invoice["late_fee_cents"]
    assert invoice["total_cents"] == expected_total, (
        f"invoice total conservation broken: total {invoice['total_cents']} != "
        f"subtotal {invoice['subtotal_cents']} + tax {invoice['tax_cents']} + "
        f"late fee {invoice['late_fee_cents']}"
    )
    assert invoice["balance_due_cents"] == invoice["total_cents"] - invoice["amount_paid_cents"], (
        f"balance_due_cents {invoice['balance_due_cents']} != total {invoice['total_cents']} - "
        f"paid {invoice['amount_paid_cents']}"
    )


def assert_invoice_money(invoice: dict, gross: Optional[int] = None, subtotal: Optional[int] = None,
                         tax: Optional[int] = None, total: Optional[int] = None):
    """Convenience: assert the named invoice money fields together with the
    line-sum conservation identity."""
    if gross is not None:
        assert invoice["gross_service_cents"] == gross, (
            f"gross_service_cents expected {gross}, got {invoice['gross_service_cents']}"
        )
    if subtotal is not None:
        assert invoice["subtotal_cents"] == subtotal, (
            f"subtotal_cents expected {subtotal}, got {invoice['subtotal_cents']}"
        )
    if tax is not None:
        assert invoice["tax_cents"] == tax, (
            f"tax_cents expected {tax}, got {invoice['tax_cents']}"
        )
    if total is not None:
        assert invoice["total_cents"] == total, (
            f"total_cents expected {total}, got {invoice['total_cents']}"
        )
    assert_invoice_total_conservation(invoice)
