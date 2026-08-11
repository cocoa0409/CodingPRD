"""Entity assertions, instant comparison helpers and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import POSITION_CODES


# ---------------------------------------------------------------------------
# Instant comparison
#
# The API renders every datetime it returns as ISO 8601 UTC with exactly three
# fractional-second digits and a trailing Z, regardless of the format the value
# arrived in (PRD 2.4).  Comparing rendered output to an input literal as a raw
# string is therefore always wrong; parse both sides and compare the instants.
# Date-only fields (YYYY-MM-DD) are never widened, so those stay plain strings.
# ---------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 instant (with or without fractional digits) to UTC."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def same_instant(actual: str, expected: str) -> bool:
    return parse_instant(actual) == parse_instant(expected)


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    assert same_instant(actual, expected), (
        f"{label}: expected the instant {expected}, got {actual}"
    )


def assert_rendered_instant(value: str, label: str = "instant") -> None:
    """The rendered form carries three fractional digits and a trailing Z."""
    assert isinstance(value, str) and value, f"{label} must be a non-empty string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601, got {value!r}"


def assert_date_string(value: str, expected: str, label: str = "date") -> None:
    """Date-only fields stay plain YYYY-MM-DD strings and are compared as such."""
    assert value == expected, f"{label}: expected {expected!r}, got {value!r}"


# ---------------------------------------------------------------------------
# Common-field assertions
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict, label: str = "resource") -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert_rendered_instant(data.get("created_at", ""), f"{label}.created_at")
    assert_rendered_instant(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_agency(data: dict) -> None:
    assert_common_fields(data, "agency")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "SUSPENDED")
    assert data["payer_regime_default"] in ("APPLICANT_PAID", "AGENCY_BILLED", "FEE_WAIVED")
    assert isinstance(data["invoice_terms_days"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["max_aging_days"], int)
    assert isinstance(data["mtd_billed_cents"], int)


def assert_ori(data: dict) -> None:
    assert_common_fields(data, "ori")
    assert len(data["ori_code"]) == 9, "ori_code is exactly nine characters"
    assert data["statutory_authority"] in (
        "CRIMINAL_JUSTICE",
        "NONCRIMINAL_STATUTORY",
        "NONCRIMINAL_NOFED",
    )
    assert data["destination_requirement"] in ("STATE_ONLY", "STATE_AND_FBI")
    assert data["dissemination_tier"] in ("FULL_CHR", "FITNESS_CODE_ONLY")
    assert isinstance(data["retention_permitted"], bool)
    assert isinstance(data["rapback_authority"], bool)
    assert data["authority_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["tcn_consumed_count"], int)
    assert isinstance(data["tcn_released_count"], int)


def assert_authority_profile(ori: dict) -> None:
    """The complete statutory_authority mapping (PRD 3.1); no other combination exists."""
    expected = {
        "CRIMINAL_JUSTICE": ("STATE_AND_FBI", "FULL_CHR", True, True),
        "NONCRIMINAL_STATUTORY": ("STATE_AND_FBI", "FITNESS_CODE_ONLY", True, True),
        "NONCRIMINAL_NOFED": ("STATE_ONLY", "FITNESS_CODE_ONLY", False, False),
    }[ori["statutory_authority"]]
    actual = (
        ori["destination_requirement"],
        ori["dissemination_tier"],
        ori["retention_permitted"],
        ori["rapback_authority"],
    )
    assert actual == expected, (
        f"{ori['statutory_authority']} must derive {expected}, got {actual}"
    )


def assert_service_type(data: dict) -> None:
    assert_common_fields(data, "service_type")
    assert data["slot_duration_minutes"] in (15, 30, 45)
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["required_document_codes"], list) and data["required_document_codes"]
    assert isinstance(data["accepted_id_document_types"], list) and data["accepted_id_document_types"]
    assert 0 <= data["state_fee_cents"] <= 20000
    assert 0 <= data["federal_fee_cents"] <= 20000


def assert_capture_site(data: dict) -> None:
    assert_common_fields(data, "site")
    assert data["site_kind"] in ("FIXED", "MOBILE_EVENT")
    assert 1 <= data["concurrent_capacity"] <= 50
    assert isinstance(data["walkin_usable_capacity"], int)
    assert data["reconciliation_status"] in ("NOT_APPLICABLE", "PENDING", "RECONCILED")
    assert isinstance(data["billable_print_count"], int)
    assert isinstance(data["shortfall_charge_cents"], int)


def assert_device(data: dict) -> None:
    assert_common_fields(data, "device")
    assert data["calibration_status"] in ("CALIBRATED", "EXPIRED", "QUARANTINED")
    assert_rendered_instant(data["last_calibrated_at"], "device.last_calibrated_at")
    assert_rendered_instant(data["calibration_expires_at"], "device.calibration_expires_at")
    assert isinstance(data["capture_count"], int)
    assert isinstance(data["tainted_card_count"], int)


def assert_device_assignment(data: dict) -> None:
    assert_common_fields(data, "device_assignment")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "RELEASED", "REVOKED_TAINTED")
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])
    assert isinstance(data["billable_print_count"], int)
    assert isinstance(data["tainted_print_count"], int)


def assert_applicant(data: dict) -> None:
    assert_common_fields(data, "applicant")
    assert data["sex"] in ("M", "F", "X")
    assert data["id_document_type"] in ("DRIVER_LICENSE", "PASSPORT", "STATE_ID", "MILITARY_ID")
    assert isinstance(data["demographics_complete"], bool)
    assert len(data["date_of_birth"]) == 10, "date_of_birth stays a plain YYYY-MM-DD string"
    assert len(data["id_document_expires_on"]) == 10


def assert_appointment(data: dict) -> None:
    assert_common_fields(data, "appointment")
    assert data["status"] in (
        "BOOKED",
        "CHECKED_IN",
        "IN_CAPTURE",
        "COMPLETED",
        "NO_SHOW",
        "CANCELLED",
    )
    assert data["booking_channel"] in ("BOOKED", "WALK_IN")
    assert isinstance(data["reschedule_count"], int)
    assert isinstance(data["no_show_fee_assessed"], bool)
    assert_rendered_instant(data["scheduled_start"], "appointment.scheduled_start")
    assert_rendered_instant(data["scheduled_end"], "appointment.scheduled_end")


def assert_fingerprint_card(data: dict) -> None:
    assert_common_fields(data, "card")
    assert data["status"] in (
        "OPEN",
        "CAPTURING",
        "READY_FOR_SUBMISSION",
        "SUBMITTED",
        "CLOSED",
        "REJECTED_CLOSED",
        "SUPERSEDED",
    )
    assert isinstance(data["positions_passed_count"], int)
    assert isinstance(data["positions_exception_count"], int)
    assert isinstance(data["submittable"], bool)
    assert isinstance(data["free_reprint_granted"], bool)
    assert data["taint_reason"] in (None, "CALIBRATION_LAPSE", "PURGED_RECORD")


def assert_position_capture(data: dict) -> None:
    assert_common_fields(data, "position")
    assert data["position_code"] in POSITION_CODES
    assert data["status"] in (
        "PENDING",
        "PASSED",
        "FAILED_RETRYABLE",
        "CEILING_REACHED",
        "EXCEPTION_CODED",
    )
    assert 0 <= data["attempt_count"] <= 3
    assert data["exception_code"] in (None, "AMPUTATED", "BANDAGED", "UNCLASSIFIABLE")


def assert_submission(data: dict) -> None:
    assert_common_fields(data, "submission")
    assert data["state_status"] in (
        "PENDING",
        "ACCEPTED",
        "REJECTED_TECHNICAL",
        "REJECTED_ADMIN",
    )
    assert data["fbi_status"] in (
        "NOT_REQUIRED",
        "PENDING",
        "ACCEPTED",
        "REJECTED_TECHNICAL",
        "REJECTED_ADMIN",
    )
    assert data["composite_disposition"] in (
        "INCOMPLETE",
        "CLEARED",
        "HIT",
        "REJECTED",
        "MIXED",
    )
    assert data["retention_status"] in (
        "NOT_REQUESTED",
        "GRANTED",
        "PURGE_REQUESTED",
        "PURGE_DENIED",
        "PURGED",
    )
    assert set(data["destinations"]) <= {"STATE", "FBI"}
    assert isinstance(data["tcn_suffix"], int)
    assert_rendered_instant(data["transmitted_at"], "submission.transmitted_at")


def assert_tcn_rendering(submission: dict) -> None:
    """tcn_full is the bare root at suffix 0, otherwise root + '-' + suffix (PRD 3.5)."""
    if submission["tcn_suffix"] == 0:
        assert submission["tcn_full"] == submission["tcn_root"], (
            f"tcn_full must equal tcn_root at suffix 0, got {submission['tcn_full']}"
        )
    else:
        assert submission["tcn_full"] == f"{submission['tcn_root']}-{submission['tcn_suffix']}"


def assert_fee_assessment(data: dict) -> None:
    assert_common_fields(data, "fee_assessment")
    assert data["assessment_kind"] in ("SUBMISSION", "REPRINT", "NO_SHOW", "ONSITE_SHORTFALL")
    assert data["payer_regime"] in ("APPLICANT_PAID", "AGENCY_BILLED", "FEE_WAIVED")
    assert data["status"] in ("ASSESSED", "INVOICED", "PAID", "CREDITED")
    for field in (
        "state_fee_cents",
        "federal_fee_cents",
        "processing_surcharge_cents",
        "vendor_convenience_fee_cents",
        "vendor_tax_cents",
        "trip_surcharge_cents",
        "reprint_fee_cents",
        "waived_cents",
        "discount_cents",
        "total_cents",
        "paid_cents",
        "credited_cents",
    ):
        assert isinstance(data[field], int), f"fee_assessment.{field} must be whole cents"


def assert_component_conservation(assessment: dict) -> None:
    """total_cents equals the seven components less waiver and discount (PRD 2.11).

    Scoped to the two kinds whose components the specification fills in; the
    specification does not resolve whether the equality reaches the two flat kinds.
    """
    assert assessment["assessment_kind"] in ("SUBMISSION", "REPRINT")
    components = (
        assessment["state_fee_cents"]
        + assessment["federal_fee_cents"]
        + assessment["processing_surcharge_cents"]
        + assessment["vendor_convenience_fee_cents"]
        + assessment["vendor_tax_cents"]
        + assessment["trip_surcharge_cents"]
        + assessment["reprint_fee_cents"]
        - assessment["waived_cents"]
        - assessment["discount_cents"]
    )
    assert assessment["total_cents"] == components, (
        f"total_cents {assessment['total_cents']} must equal the component sum {components}"
    )


def assert_invoice(data: dict) -> None:
    assert_common_fields(data, "invoice")
    assert data["status"] in ("DRAFT", "ISSUED", "PAST_DUE", "PAID", "WRITTEN_OFF")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["aging_days"], int)


def assert_chr_response(data: dict) -> None:
    assert_common_fields(data, "chr_response")
    assert data["destination"] in ("STATE", "FBI")
    assert data["routing_status"] in ("RECEIVED", "ROUTED", "VOIDED", "SUPERSEDED")


def assert_fitness_determination(data: dict) -> None:
    assert_common_fields(data, "determination")
    assert data["status"] in ("ISSUED", "CHALLENGED", "REAFFIRMED", "AMENDED", "VACATED")
    assert data["outcome"] in (None, "FIT", "NOT_FIT", "FIT_WITH_CONDITIONS")
    assert isinstance(data["challenge_count"], int)


def assert_rapback_subscription(data: dict) -> None:
    assert_common_fields(data, "subscription")
    assert data["status"] in ("ACTIVE", "RENEWAL_DUE", "LAPSED", "CANCELLED", "TERMINATED")
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["notifications_received_count"], int)
    assert isinstance(data["notifications_routed_count"], int)
    assert isinstance(data["notifications_voided_count"], int)


def assert_notification_routing_conservation(subscription: dict) -> None:
    """received == routed + voided for one subscription (PRD 2.11)."""
    assert subscription["notifications_received_count"] == (
        subscription["notifications_routed_count"] + subscription["notifications_voided_count"]
    ), (
        "notifications_received_count must equal routed + voided, got "
        f"{subscription['notifications_received_count']} vs "
        f"{subscription['notifications_routed_count']} + {subscription['notifications_voided_count']}"
    )


def assert_rapback_notification(data: dict) -> None:
    assert_common_fields(data, "notification")
    assert data["status"] in ("ROUTED", "ACKNOWLEDGED", "ORPHANED", "VOIDED")
    assert data["event_type"] in ("ARREST", "DISPOSITION", "WARRANT")
    assert len(data["event_date"]) == 10, "event_date stays a plain YYYY-MM-DD string"


def find_one(rows: list, **match) -> Optional[dict]:
    """Return the single row matching every key/value pair, or None."""
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) <= 1, f"Expected at most one row matching {match}, found {len(hits)}"
    return hits[0] if hits else None
