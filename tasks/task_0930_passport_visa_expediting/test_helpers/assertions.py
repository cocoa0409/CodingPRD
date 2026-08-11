"""Entity assertions, instant comparison and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


# ---------------------------------------------------------------------------
# Instants are compared SEMANTICALLY — parse both sides, compare the point in
# time. The PRD's rendering rule is a separate concern from the contract that
# two instants denote the same moment.
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


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same point in time."""
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected the instant {expected}, got {actual}"


def assert_instant_before(earlier: str, later: str, label: str = "instant") -> None:
    assert parse_instant(earlier) < parse_instant(later), (
        f"{label}: expected {earlier} to precede {later}"
    )


def assert_is_instant(value: Any, label: str = "instant") -> None:
    assert isinstance(value, str) and value, f"{label} must be a non-empty string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 timestamp, got {value!r}"
    parse_instant(value)


def assert_is_calendar_date(value: Any, label: str = "date") -> None:
    """Calendar dates are plain YYYY-MM-DD with no time component or zone."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a plain YYYY-MM-DD date, got {value!r}"
    )
    datetime.strptime(value, "%Y-%m-%d")


# ---------------------------------------------------------------------------
# Common-field shape
# ---------------------------------------------------------------------------
def assert_versioned_common_fields(data: dict, label: str = "row") -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_is_instant(data.get("created_at"), f"{label}.created_at")
    assert_is_instant(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_append_only_common_fields(data: dict, label: str = "row") -> None:
    """Append-only rows expose only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert_is_instant(data.get("created_at"), f"{label}.created_at")
    assert "version" not in data, f"{label} is append-only and must not expose version"
    assert "updated_at" not in data, f"{label} is append-only and must not expose updated_at"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_catalog_item(data: dict) -> None:
    assert_versioned_common_fields(data, "ServiceCatalogItem")
    assert isinstance(data["nationality_code"], str) and len(data["nationality_code"]) == 2
    assert isinstance(data["destination_country"], str) and len(data["destination_country"]) == 2
    assert data["visa_type"] in (
        "TOURIST",
        "BUSINESS",
        "STUDENT",
        "PASSPORT_RENEWAL",
        "PASSPORT_FIRST_TIME",
    )
    assert isinstance(data["government_fee_cents"], int) and data["government_fee_cents"] >= 0
    assert data["government_fee_basis"] in ("PER_APPLICANT", "PER_ORDER")
    assert isinstance(data["base_service_fee_cents"], int) and data["base_service_fee_cents"] >= 0
    assert isinstance(data["form_code"], str) and data["form_code"]
    assert isinstance(data["requires_appointment"], bool)


def assert_document_requirement(data: dict) -> None:
    assert_append_only_common_fields(data, "DocumentRequirement")
    assert is_valid_uuid(data["catalog_item_id"])
    assert isinstance(data["is_required"], bool)
    assert data["validity_rule"] in ("NONE", "EXPIRES_AFTER_ISSUE_DAYS", "VALID_BEYOND_RETURN_MONTHS")


def assert_agency_form(data: dict) -> None:
    assert_versioned_common_fields(data, "AgencyForm")
    assert isinstance(data["form_code"], str) and data["form_code"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["required_field_count"], int) and data["required_field_count"] >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_consulate(data: dict) -> None:
    assert_versioned_common_fields(data, "Consulate")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["destination_country"], str) and len(data["destination_country"]) == 2
    assert isinstance(data["jurisdiction_region_codes"], list)
    assert len(data["jurisdiction_region_codes"]) >= 1
    assert isinstance(data["closure_dates"], list)


def assert_appointment_slot(data: dict) -> None:
    assert_versioned_common_fields(data, "AppointmentSlot")
    assert is_valid_uuid(data["consulate_id"])
    assert_is_instant(data["starts_at"], "AppointmentSlot.starts_at")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert data["status"] in ("OPEN", "FULL", "CLOSED")


def assert_order(data: dict) -> None:
    assert_versioned_common_fields(data, "Order")
    assert is_valid_uuid(data["catalog_item_id"])
    assert data["service_level"] in ("STANDARD", "EXPEDITED", "RUSH")
    assert_is_calendar_date(data["travel_date"], "Order.travel_date")
    assert_is_calendar_date(data["return_date"], "Order.return_date")
    assert data["workflow_status"] in (
        "DRAFT",
        "QUOTED",
        "INTAKE",
        "READY_FOR_SUBMISSION",
        "SUBMITTED",
        "AT_AGENCY",
        "RFE_PENDING",
        "APPROVED",
        "REJECTED",
        "DELIVERING",
        "COMPLETED",
        "CANCELLED",
        "ABANDONED",
    )
    assert data["payment_status"] in (
        "UNPAID",
        "PARTIALLY_COLLECTED",
        "COLLECTED",
        "REFUND_PENDING",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
    )
    assert data["custody_holder"] in ("APPLICANT", "SERVICE", "COURIER", "AGENCY")
    assert data["feasibility_status"] in (
        "UNKNOWN",
        "FEASIBLE",
        "INFEASIBLE",
        "ACKNOWLEDGED_INFEASIBLE",
    )
    for money in (
        "government_fee_quoted_cents",
        "service_fee_quoted_cents",
        "total_quoted_cents",
        "collected_government_cents",
        "collected_service_cents",
        "collected_cents",
        "government_tendered_cents",
        "service_earned_cents",
        "refunded_cents",
        "refund_scheduled_cents",
        "outstanding_cents",
    ):
        assert isinstance(data[money], int), f"Order.{money} must be whole cents"
    assert isinstance(data["applicant_count"], int)
    assert isinstance(data["handling_fee_waived"], bool)
    assert isinstance(data["rfe_round_count"], int)


def assert_applicant(data: dict) -> None:
    assert_versioned_common_fields(data, "Applicant")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_is_calendar_date(data["date_of_birth"], "Applicant.date_of_birth")
    assert data["readiness_status"] in ("PENDING", "COMPLETE", "WITHDRAWN")
    assert isinstance(data["age_years"], int)
    assert isinstance(data["required_doc_count"], int)
    assert isinstance(data["accepted_doc_count"], int)


def assert_applicant_document(data: dict) -> None:
    assert_versioned_common_fields(data, "ApplicantDocument")
    assert is_valid_uuid(data["applicant_id"])
    assert data["review_status"] in ("MISSING", "RECEIVED", "ACCEPTED", "REJECTED")
    assert isinstance(data["is_required"], bool)
    assert isinstance(data["resubmission_count"], int)


def assert_photo_asset(data: dict) -> None:
    assert_versioned_common_fields(data, "PhotoAsset")
    assert is_valid_uuid(data["applicant_id"])
    assert_is_calendar_date(data["taken_on"], "PhotoAsset.taken_on")
    assert data["compliance_status"] in ("PENDING", "PASSED", "FAILED", "EXPIRED", "SUPERSEDED")
    assert isinstance(data["retake_count"], int)
    assert isinstance(data["failure_reasons"], list)


def assert_prepared_form(data: dict) -> None:
    assert_versioned_common_fields(data, "PreparedForm")
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["agency_form_id"])
    assert data["prep_status"] in ("PREPARED", "SIGNED", "STALE", "VOID")
    assert isinstance(data["revision_used"], int)
    assert isinstance(data["filled_field_count"], int)


def assert_appointment(data: dict) -> None:
    assert_versioned_common_fields(data, "Appointment")
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["slot_id"])
    assert data["booking_status"] in ("BOOKED", "ATTENDED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["reschedule_count"], int)
    assert isinstance(data["no_show_count"], int)


def assert_courier_leg(data: dict) -> None:
    assert_versioned_common_fields(data, "CourierLeg")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["leg_index"], int) and data["leg_index"] >= 1
    assert data["from_holder"] in ("APPLICANT", "SERVICE", "AGENCY")
    assert data["to_holder"] in ("SERVICE", "AGENCY", "APPLICANT")
    assert_is_calendar_date(data["scheduled_date"], "CourierLeg.scheduled_date")
    assert data["leg_status"] in ("CREATED", "DISPATCHED", "DELIVERED", "FAILED", "CANCELLED")
    assert isinstance(data["attempt_count"], int)


def assert_custody_event(data: dict) -> None:
    assert_append_only_common_fields(data, "CustodyEvent")
    assert is_valid_uuid(data["order_id"])
    assert data["holder_type"] in ("APPLICANT", "SERVICE", "COURIER", "AGENCY")
    assert_is_instant(data["acquired_at"], "CustodyEvent.acquired_at")
    assert data["reason"] in (
        "ORDER_CREATED",
        "LEG_DISPATCHED",
        "LEG_DELIVERED",
        "LEG_FAILED_RETURN",
        "DECISION_RETURNED",
        "SHIPMENT_DELIVERED",
        "SHIPMENT_PICKED_UP",
    )


def assert_rfe(data: dict) -> None:
    assert_versioned_common_fields(data, "RFE")
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["round_index"], int)
    assert_is_instant(data["issued_at"], "RFE.issued_at")
    assert_is_instant(data["deadline_at"], "RFE.deadline_at")
    assert data["rfe_status"] in ("OPEN", "RESPONDED", "CLEARED", "INSUFFICIENT", "EXPIRED")
    assert isinstance(data["response_count"], int)


def assert_ledger_entry(data: dict) -> None:
    assert_append_only_common_fields(data, "LedgerEntry")
    assert is_valid_uuid(data["order_id"])
    assert data["stream"] in ("GOVERNMENT", "SERVICE")
    assert data["kind"] in ("COLLECTION", "TENDER", "EARN", "REFUND", "TRANSFER_OUT", "TRANSFER_IN")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1, (
        "a LedgerEntry carries a strictly positive amount_cents"
    )
    assert data["reason"] in (
        "CUSTOMER_PAYMENT",
        "AGENCY_TENDER",
        "SERVICE_RECOGNITION",
        "CANCELLATION_REFUND",
        "REJECTION_REFUND",
        "SPLIT_PARTITION",
    )
    assert_is_instant(data["recorded_at"], "LedgerEntry.recorded_at")


def assert_shipment(data: dict) -> None:
    assert_versioned_common_fields(data, "Shipment")
    assert is_valid_uuid(data["order_id"])
    assert data["method"] in ("GROUND", "OVERNIGHT", "COURIER_SAME_DAY")
    assert data["delivery_status"] in (
        "CREATED",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
        "HELD_FOR_PICKUP",
        "PICKED_UP",
    )
    assert isinstance(data["attempt_count"], int)
    assert isinstance(data["escalation_fee_cents"], int)
    assert isinstance(data["signature_required"], bool)


def assert_sla_segment(data: dict) -> None:
    assert_append_only_common_fields(data, "SlaSegment")
    assert is_valid_uuid(data["order_id"])
    assert data["segment_kind"] in ("RUNNING", "PAUSED")
    assert_is_instant(data["started_at"], "SlaSegment.started_at")


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_money_conservation(order: dict) -> None:
    """collected == tendered + earned + refunded + outstanding, in whole cents."""
    left = order["collected_cents"]
    right = (
        order["government_tendered_cents"]
        + order["service_earned_cents"]
        + order["refunded_cents"]
        + order["outstanding_cents"]
    )
    assert left == right, (
        "money conservation broken: collected_cents "
        f"{left} != government_tendered_cents {order['government_tendered_cents']} + "
        f"service_earned_cents {order['service_earned_cents']} + refunded_cents "
        f"{order['refunded_cents']} + outstanding_cents {order['outstanding_cents']}"
    )
    assert (
        order["collected_cents"]
        == order["collected_government_cents"] + order["collected_service_cents"]
    ), "collected_cents must be the sum of the two per-stream collected figures"


def assert_government_allocation_ceiling(order: dict) -> None:
    """The two GOVERNMENT-stream inequalities of the per-stream ceiling."""
    assert order["collected_government_cents"] >= order["government_tendered_cents"]
    assert order["collected_government_cents"] <= order["government_fee_quoted_cents"]


def assert_single_open_custody(events: Iterable[dict], expected_holder: Optional[str] = None) -> dict:
    """Exactly one CustodyEvent has released_at null; return that row."""
    open_rows = [e for e in events if e.get("released_at") is None]
    assert len(open_rows) == 1, (
        f"exactly one custody event must have released_at null, found {len(open_rows)}"
    )
    if expected_holder is not None:
        assert open_rows[0]["holder_type"] == expected_holder, (
            f"the open custody event should be held by {expected_holder}, "
            f"got {open_rows[0]['holder_type']}"
        )
    return open_rows[0]


def assert_custody_events_ordered(events: List[dict]) -> None:
    """Custody events come back sorted by acquired_at ascending."""
    stamps = [parse_instant(e["acquired_at"]) for e in events]
    assert stamps == sorted(stamps), "custody events must be sorted by acquired_at ascending"


def assert_sla_partition(segments: List[dict], submitted_at: str) -> None:
    """Segments tile the interval from submitted_at forward with no gaps."""
    assert segments, "an order that has been submitted carries at least one SLA segment"
    assert_same_instant(segments[0]["started_at"], submitted_at, "first SLA segment started_at")
    for earlier, later in zip(segments, segments[1:]):
        assert earlier["ended_at"] is not None, "only the last SLA segment may be open"
        assert_same_instant(
            earlier["ended_at"], later["started_at"], "adjacent SLA segment boundary"
        )


def assert_ledger_rows(entries: List[dict], stream: str, kind: str) -> List[dict]:
    return [e for e in entries if e["stream"] == stream and e["kind"] == kind]
