"""Entity assertions, semantic date/instant comparison and domain invariants."""

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ==========================================================================
# Semantic temporal comparison
#
# Every datetime the API emits is ISO 8601 UTC with three fractional digits
# (PRD §2.4).  Callers, however, often supply the same instant without the
# fractional part.  Comparing the two forms as strings would report a spurious
# mismatch, so both sides are parsed and the resulting instants compared.
# ==========================================================================


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC datetime, with or without fractional digits."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_day(value: str) -> date:
    """Parse a bare `YYYY-MM-DD` calendar date."""
    assert isinstance(value, str) and value, f"Expected a YYYY-MM-DD string, got {value!r}"
    return date.fromisoformat(value.strip()[:10])


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant"):
    """Compare two datetimes as instants, never as rendered strings."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_date_equals(actual: Optional[str], expected: str, label: str = "date"):
    """Compare two calendar dates as dates, never as rendered strings."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert parse_day(actual) == parse_day(expected), (
        f"{label}: expected date {expected}, got {actual}"
    )


def assert_emitted_datetime(value: Optional[str], label: str = "datetime"):
    """The field must be a parseable ISO 8601 UTC instant."""
    assert value is not None, f"{label} must not be null"
    assert is_iso8601_timestamp(value) or parse_instant(value), (
        f"{label} must be an ISO 8601 UTC datetime, got {value!r}"
    )


def assert_emitted_date(value: Optional[str], label: str = "date"):
    """The field must be a bare `YYYY-MM-DD` calendar date with no time part."""
    assert value is not None, f"{label} must not be null"
    assert isinstance(value, str) and len(value.strip()) == 10, (
        f"{label} must be rendered as bare YYYY-MM-DD with no time part, got {value!r}"
    )
    parse_day(value)


def assert_common_fields(data: Dict[str, Any], label: str = "resource"):
    """id / created_at / updated_at / version, present on every resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a server-minted UUID with no type prefix, got {data.get('id')!r}"
    )
    assert_emitted_datetime(data.get("created_at"), f"{label}.created_at")
    assert_emitted_datetime(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_envelope_object(body: Dict[str, Any]):
    """The success envelope for a single resource (PRD §2.2)."""
    assert body.get("response_type") == "object", (
        f"response_type must be 'object' for a single resource, got {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got {meta.get('api_request_id')!r}"
    )
    assert_emitted_datetime(meta.get("api_request_timestamp"), "meta.api_request_timestamp")


# ==========================================================================
# Per-entity assertions
# ==========================================================================


def assert_membership_plan(data: Dict[str, Any]):
    assert_common_fields(data, "MembershipPlan")
    assert data["tier"] in ("ESSENTIAL", "PLUS", "PREMIER")
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] >= 0
    assert isinstance(data["included_lactation_consults"], int)
    assert isinstance(data["included_sleep_consults"], int)
    assert isinstance(data["form_sla_hours"], int) and data["form_sla_hours"] > 0
    assert isinstance(data["after_hours_surcharge_waived"], bool)
    assert isinstance(data["overage_consult_fee_cents"], int)


def assert_physician(data: Dict[str, Any]):
    assert_common_fields(data, "Physician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert float(data["panel_slot_cap"]) > 0
    assert isinstance(data["licensed_state_codes"], list) and data["licensed_state_codes"]
    assert float(data["weighted_occupancy"]) >= 0
    assert float(data["available_panel_weight"]) >= 0, (
        "available_panel_weight is floored at 0 and never reports a negative figure"
    )


def assert_family(data: Dict[str, Any]):
    assert_common_fields(data, "Family")
    assert isinstance(data["household_name"], str) and data["household_name"]
    assert isinstance(data["family_monthly_cap_cents"], int)
    assert data["family_monthly_cap_cents"] >= 0
    assert isinstance(data["active_membership_count"], int)
    assert data["active_membership_count"] >= 0


def assert_insurance_policy(data: Dict[str, Any]):
    assert_common_fields(data, "InsurancePolicy")
    assert is_valid_uuid(data["family_id"])
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["deductible_met_cents"], int)
    assert 0 <= float(data["coinsurance_rate"]) <= 1
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_child(data: Dict[str, Any]):
    assert_common_fields(data, "Child")
    assert is_valid_uuid(data["family_id"])
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert_emitted_date(data["date_of_birth"], "Child.date_of_birth")
    assert isinstance(data["age_days"], int) and data["age_days"] >= 0
    assert float(data["current_slot_weight"]) in (2.0, 1.5, 1.0)
    assert isinstance(data["immunization_complete_for_age"], bool)


def assert_membership(data: Dict[str, Any]):
    assert_common_fields(data, "Membership")
    assert is_valid_uuid(data["child_id"])
    assert is_valid_uuid(data["family_id"])
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["physician_id"])
    assert_emitted_date(data["start_date"], "Membership.start_date")
    assert data["status"] in (
        "PENDING_ACTIVATION",
        "ACTIVE",
        "SUSPENDED",
        "CANCELLED",
    )
    assert isinstance(data["enrollment_sequence"], int)
    assert float(data["discount_pct"]) in (0.0, 0.20, 0.35)
    assert isinstance(data["monthly_rate_cents"], int)
    assert float(data["slot_weight"]) >= 0


def assert_waitlist_entry(data: Dict[str, Any]):
    assert_common_fields(data, "PanelWaitlistEntry")
    assert is_valid_uuid(data["physician_id"])
    assert is_valid_uuid(data["child_id"])
    assert is_valid_uuid(data["requested_plan_id"])
    assert data["status"] in ("WAITING", "PROMOTED", "WITHDRAWN", "EXPIRED")
    assert float(data["candidate_slot_weight"]) in (2.0, 1.5, 1.0)


def assert_entitlement_grant(data: Dict[str, Any]):
    assert_common_fields(data, "EntitlementGrant")
    assert is_valid_uuid(data["membership_id"])
    assert data["benefit_type"] in ("LACTATION_CONSULT", "SLEEP_CONSULT")
    assert isinstance(data["membership_year_index"], int)
    assert data["membership_year_index"] >= 0
    assert data["status"] in ("OPEN", "EXHAUSTED", "EXPIRED")
    assert_grant_conservation(data)


def assert_grant_conservation(grant: Dict[str, Any]):
    """available_count + booked_count + consumed_count == granted_count (PRD §2.10)."""
    total = grant["available_count"] + grant["booked_count"] + grant["consumed_count"]
    assert total == grant["granted_count"], (
        "benefit-pool conservation broken: "
        f"available {grant['available_count']} + booked {grant['booked_count']} + "
        f"consumed {grant['consumed_count']} = {total}, granted {grant['granted_count']}"
    )
    assert grant["available_count"] >= 0, "available_count is never negative"


def assert_consult_booking(data: Dict[str, Any]):
    assert_common_fields(data, "ConsultBooking")
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["grant_id"])
    assert is_valid_uuid(data["consultant_physician_id"])
    assert data["consult_type"] in ("LACTATION_CONSULT", "SLEEP_CONSULT")
    assert_emitted_datetime(data["scheduled_start"], "ConsultBooking.scheduled_start")
    assert_emitted_datetime(data["scheduled_end"], "ConsultBooking.scheduled_end")
    assert parse_instant(data["scheduled_end"]) > parse_instant(data["scheduled_start"])
    assert data["modality"] in ("IN_PERSON", "TELEHEALTH")
    assert data["coverage_route"] in ("ENTITLEMENT", "OVERAGE")
    assert isinstance(data["reschedule_count"], int)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_well_visit(data: Dict[str, Any]):
    assert_common_fields(data, "WellVisit")
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["child_id"])
    assert data["milestone_code"] in (
        "NEWBORN", "M1", "M2", "M4", "M6", "M9", "M12", "M24", "M36", "M48", "M60",
    )
    assert_emitted_date(data["target_date"], "WellVisit.target_date")
    assert_emitted_date(data["window_open_date"], "WellVisit.window_open_date")
    assert_emitted_date(data["window_close_date"], "WellVisit.window_close_date")
    assert data["status"] in ("DUE", "SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")
    if data.get("punctuality") is not None:
        assert data["punctuality"] in ("EARLY", "ON_SCHEDULE", "DELAYED")


def assert_immunization_dose(data: Dict[str, Any]):
    assert_common_fields(data, "ImmunizationDose")
    assert is_valid_uuid(data["child_id"])
    assert data["vaccine_code"] in ("HEPB", "DTAP")
    assert_emitted_date(data["administered_date"], "ImmunizationDose.administered_date")
    assert isinstance(data["age_days_at_administration"], int)
    assert isinstance(data["effective_series_index"], int)
    assert data["effective_series_index"] >= 1
    assert data["validity"] in ("VALID", "INVALID")
    assert isinstance(data["manually_invalidated"], bool)
    if data["validity"] == "VALID":
        assert data["invalid_reason"] is None, (
            "a dose clearing both rungs is VALID with invalid_reason null"
        )
    else:
        assert data["invalid_reason"] in (
            "MIN_AGE_NOT_MET",
            "MIN_INTERVAL_NOT_MET",
            "SERIES_ALREADY_COMPLETE",
            "MANUALLY_INVALIDATED",
        )


def assert_encounter(data: Dict[str, Any]):
    assert_common_fields(data, "Encounter")
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["child_id"])
    assert data["encounter_type"] in (
        "SICK_VISIT", "AFTER_HOURS_CONTACT", "ROUTINE_QUESTION", "NEWBORN_WEIGHT_CHECK",
    )
    assert data["modality"] in ("IN_PERSON", "TELEHEALTH")
    assert_emitted_datetime(data["started_at"], "Encounter.started_at")
    assert_emitted_datetime(data["ends_at"], "Encounter.ends_at")
    assert isinstance(data["after_hours"], bool)
    if data["after_hours"]:
        assert data["after_hours_reason"] in (
            "WEEKEND", "HOLIDAY", "WEEKDAY_EVENING", "WEEKDAY_EARLY_MORNING",
        )
    else:
        assert data["after_hours_reason"] is None, (
            "after_hours_reason is null when after_hours is false"
        )
        assert data["surcharge_cents"] == 0
    assert data["clinical_status"] in ("SCHEDULED", "CLINICALLY_COMPLETE", "CANCELLED")
    assert data["billing_status"] in (
        "BILLING_PENDING", "BILLING_ROUTED", "BILLING_CLOSED", "BILLING_VOID",
    )


def assert_service_line(data: Dict[str, Any]):
    assert_common_fields(data, "ServiceLine")
    assert is_valid_uuid(data["membership_id"])
    assert data["service_code"] in (
        "WELL_VISIT", "SICK_VISIT", "TELEHEALTH_VISIT",
        "AFTER_HOURS_SURCHARGE", "LACTATION_CONSULT", "SLEEP_CONSULT",
    )
    assert data["route"] in (
        "COVERED_BY_MEMBERSHIP", "BILLED_TO_INSURANCE", "PATIENT_RESPONSIBILITY",
    )
    assert isinstance(data["billed_amount_cents"], int)
    assert data["status"] in ("ROUTED", "ADJUDICATED", "SETTLED", "VOID")
    if data["route"] != "BILLED_TO_INSURANCE":
        assert data["policy_id"] is None, (
            "policy_id is set only on the insurance route and is null otherwise"
        )


def assert_invoice(data: Dict[str, Any]):
    assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data["family_id"])
    assert_emitted_date(data["cycle_start_date"], "Invoice.cycle_start_date")
    assert_emitted_date(data["cycle_end_date"], "Invoice.cycle_end_date")
    assert isinstance(data["days_in_cycle"], int) and data["days_in_cycle"] > 0
    assert isinstance(data["lines"], list)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID")
    assert_invoice_conservation(data)


def assert_invoice_conservation(invoice: Dict[str, Any]):
    """total == subtotal - cap_adjustment == sum(line_total_cents) (PRD §2.10)."""
    assert invoice["total_cents"] == invoice["subtotal_cents"] - invoice["cap_adjustment_cents"], (
        f"total_cents {invoice['total_cents']} must equal subtotal_cents "
        f"{invoice['subtotal_cents']} minus cap_adjustment_cents {invoice['cap_adjustment_cents']}"
    )
    line_sum = sum(line["line_total_cents"] for line in invoice["lines"])
    assert invoice["total_cents"] == line_sum, (
        f"total_cents {invoice['total_cents']} must equal the sum of line_total_cents {line_sum}"
    )


def assert_form_request(data: Dict[str, Any]):
    assert_common_fields(data, "FormRequest")
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["child_id"])
    assert data["form_type"] in ("SCHOOL", "CAMP", "SPORTS")
    assert_emitted_date(data["needed_by_date"], "FormRequest.needed_by_date")
    assert_emitted_datetime(data["requested_at"], "FormRequest.requested_at")
    assert_emitted_datetime(data["due_at"], "FormRequest.due_at")
    assert data["status"] in ("PENDING", "BLOCKED", "ISSUED")
    if data["status"] == "BLOCKED":
        assert data["blocked_reason"] in (
            "MEMBERSHIP_NOT_ACTIVE", "IMMUNIZATION_INCOMPLETE", "WELL_VISIT_STALE",
        )
    else:
        assert data["blocked_reason"] is None


# ==========================================================================
# Collection helpers
# ==========================================================================


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def by_field(rows: Iterable[Dict[str, Any]], field: str, value: Any) -> Dict[str, Any]:
    """Return the single row whose `field` equals `value`."""
    matches = [row for row in rows if row.get(field) == value]
    assert len(matches) == 1, (
        f"Expected exactly one row with {field} == {value!r}, found {len(matches)}"
    )
    return matches[0]


def assert_created_at_ascending(rows: List[Dict[str, Any]]):
    """List results are ordered by creation timestamp, ascending (PRD §2.3)."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), (
        f"rows must be ordered by created_at ascending, got {[r['created_at'] for r in rows]}"
    )
