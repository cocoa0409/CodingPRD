"""Payload factories — one per creatable resource, input fields only (PRD §4)."""

from . import constants as C


def create_policyholder_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Holder",
        "policy_number": "POL-100",
        "contact_email": "pat@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_repair_shop_payload(**overrides) -> dict:
    defaults = {
        "shop_name": "Ace Auto Body",
        "shop_code": "SHOP-1",
    }
    defaults.update(overrides)
    return defaults


def create_rental_partner_payload(**overrides) -> dict:
    defaults = {
        "partner_name": "RentCo",
        "partner_code": "RC-1",
        "economy_rate_cents": C.BASE_ECONOMY_RATE_CENTS,
        "standard_rate_cents": C.BASE_STANDARD_RATE_CENTS,
        "premium_rate_cents": C.BASE_PREMIUM_RATE_CENTS,
        "economy_capacity": C.BASE_ECONOMY_CAPACITY,
        "standard_capacity": C.BASE_STANDARD_CAPACITY,
        "premium_capacity": C.BASE_PREMIUM_CAPACITY,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policyholder_id, **overrides) -> dict:
    defaults = {
        "policyholder_id": policyholder_id,
        "incident_date": "2026-07-28",
        "coverage_daily_limit_cents": C.BASE_DAILY_LIMIT_CENTS,
        "coverage_duration_cap_days": C.BASE_DURATION_CAP_DAYS,
        "loss_of_use_per_diem_cents": C.BASE_LOU_PER_DIEM_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_verification_payload(claim_id, expected_claim_version, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def decide_coverage_verification_payload(decision="VERIFIED", rental_eligible=True,
                                         loss_of_use_eligible=True, **overrides) -> dict:
    defaults = {
        "decision": decision,
        "rental_eligible": rental_eligible,
        "loss_of_use_eligible": loss_of_use_eligible,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(claim_id, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "estimated_completion_date": C.BASE_REPAIR_ESTIMATE,
        "labor_hours_estimate": 12,
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(milestone_type, **overrides) -> dict:
    defaults = {"milestone_type": milestone_type}
    defaults.update(overrides)
    return defaults


def create_rental_reservation_payload(claim_id, rental_partner_id, repair_order_id,
                                      expected_claim_version, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "rental_partner_id": rental_partner_id,
        "repair_order_id": repair_order_id,
        "vehicle_class": C.BASE_VEHICLE_CLASS,
        "pickup_date": C.BASE_PICKUP_DATE,
        "authorized_return_date": C.BASE_AUTHORIZED_RETURN_DATE,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_extension_request_payload(reservation_id, milestone_id,
                                     requested_additional_days,
                                     expected_reservation_version, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "milestone_id": milestone_id,
        "requested_additional_days": requested_additional_days,
        "expected_reservation_version": expected_reservation_version,
    }
    defaults.update(overrides)
    return defaults


def create_class_change_payload(reservation_id, to_class, effective_date, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "to_class": to_class,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_loss_of_use_claim_payload(claim_id, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "vehicle_description": "Spare coupe",
        "period_start": "2026-08-05",
        "period_end": "2026-08-10",
        "claimed_amount_cents": 9000,
        "payout_method": "STANDARD_PER_DIEM",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(reservation_id, invoice_number, **overrides) -> dict:
    defaults = {
        "reservation_id": reservation_id,
        "invoice_number": invoice_number,
        "period_start": C.BASE_PICKUP_DATE,
        "period_end": C.BASE_AUTHORIZED_RETURN_DATE,
        "daily_rate_cents": C.BASE_STANDARD_RATE_CENTS,
        "tax_cents": 4800,
        "fees_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_communication_log_payload(claim_id, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "channel": "EMAIL",
        "template": "COVERAGE_EXPLAINED",
        "body_summary": "60/day, 20 days max",
    }
    defaults.update(overrides)
    return defaults


def record_recovery_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
