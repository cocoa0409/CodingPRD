"""Payload factories — one per write endpoint, request-input fields only."""

DEFAULTS = {
    "GALLERY_NAME": "Orlando Sales Gallery",
    "GALLERY_SITE_CODE": "ORLGAL",
    "CONCURRENT_TOUR_CAPACITY": 4,
    "PRESENTATION_MINUTES": 120,
    "BUFFER_MINUTES": 30,
    "CHANNEL_NAME": "Off-Property Contact",
    "CHANNEL_CODE": "OFF_PROPERTY_CONTACT",
    "INCENTIVE_GIFT_VALUE_CENTS": 12500,
    "MIN_AGE": 30,
    "MIN_HOUSEHOLD_INCOME_CENTS": 5_000_000,
    "MIN_QUALIFICATION_SCORE": 55,
    "REP_NAME": "Dana Reyes",
    "REP_LICENSE_NUMBER": "FL-SL-410077",
    "ROTATION_POSITION": 1,
    "HOUSEHOLD_NAME": "Alvarez Household",
    "PRIMARY_AGE": 45,
    "HOUSEHOLD_INCOME_CENTS": 10_000_000,
    "MARITAL_STATUS": "MARRIED",
    "BOOKING_START_UTC": "2026-08-14T07:00:00Z",
    "RECORDED_ACK_REFERENCE": "REC-0001",
    "PRODUCT_TYPE": "DEEDED_INTEREST",
    "STATE_CODE": "FL",
    "PURCHASE_PRICE_CENTS": 3_200_000,
    "DOWN_PAYMENT_CENTS": 320_000,
    "POS_DELIVERED_AT": "2026-08-10T10:00:00Z",
    "REQUESTED_AMOUNT_CENTS": 3_019_980,
    "APPLICANT_FICO": 760,
    "TERM_MONTHS": 120,
    "FUNDING_REFERENCE": "WIRE-77120",
    "RECORDING_REFERENCE": "OR-BK-2026-114455",
    "RECORDING_JURISDICTION": "Orange County, FL",
    "SETTLEMENT_REFERENCE": "ACH-88231",
    "REQUIRED_MODULE_COUNT": 4,
}


def create_tour_channel_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CHANNEL_NAME"],
        "channel_code": DEFAULTS["CHANNEL_CODE"],
        "incentive_gift_value_cents": DEFAULTS["INCENTIVE_GIFT_VALUE_CENTS"],
        "min_age": DEFAULTS["MIN_AGE"],
        "min_household_income_cents": DEFAULTS["MIN_HOUSEHOLD_INCOME_CENTS"],
        "min_qualification_score": DEFAULTS["MIN_QUALIFICATION_SCORE"],
    }
    payload.update(overrides)
    return payload


def create_sales_gallery_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["GALLERY_NAME"],
        "site_code": DEFAULTS["GALLERY_SITE_CODE"],
        "concurrent_tour_capacity": DEFAULTS["CONCURRENT_TOUR_CAPACITY"],
        "presentation_minutes": DEFAULTS["PRESENTATION_MINUTES"],
        "buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_sales_representative_payload(gallery_id: str, **overrides) -> dict:
    payload = {
        "gallery_id": gallery_id,
        "full_name": DEFAULTS["REP_NAME"],
        "license_number": DEFAULTS["REP_LICENSE_NUMBER"],
        "rotation_position": DEFAULTS["ROTATION_POSITION"],
    }
    payload.update(overrides)
    return payload


def create_prospect_payload(**overrides) -> dict:
    payload = {
        "household_name": DEFAULTS["HOUSEHOLD_NAME"],
        "primary_age": DEFAULTS["PRIMARY_AGE"],
        "household_income_cents": DEFAULTS["HOUSEHOLD_INCOME_CENTS"],
        "marital_status": DEFAULTS["MARITAL_STATUS"],
    }
    payload.update(overrides)
    return payload


def create_tour_booking_payload(
    channel_id: str, prospect_id: str, gallery_id: str, **overrides
) -> dict:
    payload = {
        "channel_id": channel_id,
        "prospect_id": prospect_id,
        "gallery_id": gallery_id,
        "scheduled_start_utc": DEFAULTS["BOOKING_START_UTC"],
    }
    payload.update(overrides)
    return payload


def check_in_payload(issue_incentive_gift: bool = False) -> dict:
    return {"issue_incentive_gift": issue_incentive_gift}


def cancel_booking_payload(reason: str = "prospect withdrew") -> dict:
    return {"reason": reason}


def reschedule_request_payload(reason: str = "Rental car unavailable") -> dict:
    return {"reason": reason}


def reschedule_commit_payload(new_scheduled_start_utc: str) -> dict:
    return {"new_scheduled_start_utc": new_scheduled_start_utc}


def set_gallery_status_payload(status: str) -> dict:
    return {"status": status}


def create_sales_presentation_payload(booking_id: str, **overrides) -> dict:
    payload = {
        "booking_id": booking_id,
        "recorded_ack_reference": DEFAULTS["RECORDED_ACK_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def create_disclosure_acknowledgment_payload(
    presentation_id: str,
    disclosure_code: str,
    acknowledged_by_prospect: bool = True,
    recording_timestamp_offset_seconds: int = 120,
    **overrides,
) -> dict:
    payload = {
        "presentation_id": presentation_id,
        "disclosure_code": disclosure_code,
        "acknowledged_by_prospect": acknowledged_by_prospect,
        "recording_timestamp_offset_seconds": recording_timestamp_offset_seconds,
    }
    payload.update(overrides)
    return payload


def create_prohibited_claim_finding_payload(
    presentation_id: str,
    severity: str,
    expected_presentation_version: int,
    claim_code: str = "RENTAL_INCOME_PROMISE",
    **overrides,
) -> dict:
    payload = {
        "presentation_id": presentation_id,
        "claim_code": claim_code,
        "severity": severity,
        "expected_presentation_version": expected_presentation_version,
    }
    payload.update(overrides)
    return payload


def review_payload(decision: str = "CLEAR") -> dict:
    return {"decision": decision}


def create_purchase_agreement_payload(presentation_id: str, **overrides) -> dict:
    payload = {
        "presentation_id": presentation_id,
        "product_type": DEFAULTS["PRODUCT_TYPE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "down_payment_cents": DEFAULTS["DOWN_PAYMENT_CENTS"],
        "pos_delivered_at": DEFAULTS["POS_DELIVERED_AT"],
    }
    payload.update(overrides)
    return payload


def fund_payload(collected_amount_cents: int, **overrides) -> dict:
    payload = {
        "funding_reference": DEFAULTS["FUNDING_REFERENCE"],
        "collected_amount_cents": collected_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_financing_application_payload(
    agreement_id: str, expected_agreement_version: int, **overrides
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "requested_amount_cents": DEFAULTS["REQUESTED_AMOUNT_CENTS"],
        "applicant_fico": DEFAULTS["APPLICANT_FICO"],
        "term_months": DEFAULTS["TERM_MONTHS"],
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def financing_decision_payload(decision: str = "APPROVE") -> dict:
    return {"decision": decision}


def create_rescission_request_payload(
    agreement_id: str, delivery_method: str = "HAND_DELIVERED", **overrides
) -> dict:
    payload = {"agreement_id": agreement_id, "delivery_method": delivery_method}
    payload.update(overrides)
    return payload


def create_refund_disbursement_payload(
    rescission_request_id: str, method: str = "ACH"
) -> dict:
    return {"rescission_request_id": rescission_request_id, "method": method}


def settle_payload(settlement_reference: str = DEFAULTS["SETTLEMENT_REFERENCE"]) -> dict:
    return {"settlement_reference": settlement_reference}


def record_closing_package_payload(**overrides) -> dict:
    payload = {
        "recording_reference": DEFAULTS["RECORDING_REFERENCE"],
        "recording_jurisdiction": DEFAULTS["RECORDING_JURISDICTION"],
    }
    payload.update(overrides)
    return payload


def deliver_closing_package_payload(delivery_method: str = "COURIER") -> dict:
    return {"delivery_method": delivery_method}


def create_retraining_assignment_payload(
    rep_id: str,
    expected_representative_version: int,
    trigger_reason: str = "DISCLOSURE_GAP",
    **overrides,
) -> dict:
    payload = {
        "rep_id": rep_id,
        "trigger_reason": trigger_reason,
        "required_module_count": DEFAULTS["REQUIRED_MODULE_COUNT"],
        "expected_representative_version": expected_representative_version,
    }
    payload.update(overrides)
    return payload


def close_retraining_payload(outcome: str, modules_completed: int) -> dict:
    return {"outcome": outcome, "modules_completed": modules_completed}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
