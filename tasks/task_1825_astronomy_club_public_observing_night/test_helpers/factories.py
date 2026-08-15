"""Payload factories — one per entity, input fields only.

Every factory takes keyword overrides so tests control exactly the inputs
they need while sensible defaults keep setup terse. Field names follow the
PRD exactly.
"""
import itertools

_counter = itertools.count(1)


def _unique_email(prefix="member"):
    return f"{prefix}-{next(_counter)}@example.com"


def create_membership_tier_payload(**overrides) -> dict:
    defaults = {
        "code": "INDIVIDUAL",
        "annual_dues_cents": 120000,
        "observatory_access_level": 2,
        "loan_privilege": True,
        "max_concurrent_loans": 2,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(tier_id, **overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": _unique_email(),
        "tier_id": tier_id,
    }
    defaults.update(overrides)
    return defaults


def create_dues_invoice_payload(member_id, period_start, period_end, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_dues_payment_payload(invoice_id, member_id, amount_cents, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "member_id": member_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_telescope_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Telescope",
        "equipment_class": "REFRACTOR",
    }
    defaults.update(overrides)
    return defaults


def update_telescope_payload(name, expected_telescope_version, **overrides) -> dict:
    defaults = {
        "name": name,
        "expected_telescope_version": expected_telescope_version,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_ticket_payload(telescope_id, **overrides) -> dict:
    defaults = {
        "telescope_id": telescope_id,
        "kind": "REPAIR",
        "severity": "MEDIUM",
        "condition_delta": 0,
    }
    defaults.update(overrides)
    return defaults


def create_training_certification_payload(member_id, equipment_class,
                                          expires_at, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "equipment_class": equipment_class,
        "expires_at": expires_at,
    }
    defaults.update(overrides)
    return defaults


def create_loan_reservation_payload(member_id, telescope_id,
                                    window_start, window_end, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "telescope_id": telescope_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_observing_event_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Event",
        "event_kind": "PUBLIC_NIGHT",
        "window_start": "2026-08-10T01:00:00Z",
        "window_end": "2026-08-10T05:00:00Z",
        "moon_illumination_pct": 20,
        "min_operators": 1,
    }
    defaults.update(overrides)
    return defaults


def create_operator_assignment_payload(event_id, member_id, telescope_id,
                                       **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "member_id": member_id,
        "telescope_id": telescope_id,
    }
    defaults.update(overrides)
    return defaults


def create_group_visit_booking_payload(event_id, contact_member_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "group_name": "Test Group",
        "party_size": 5,
        "contact_member_id": contact_member_id,
    }
    defaults.update(overrides)
    return defaults


def create_sky_quality_reading_payload(taken_by_member_id, event_id, sqm_value,
                                       **overrides) -> dict:
    defaults = {
        "taken_by_member_id": taken_by_member_id,
        "event_id": event_id,
        "sqm_value": sqm_value,
    }
    defaults.update(overrides)
    return defaults


def create_dark_sky_report_payload(period_start, period_end, **overrides) -> dict:
    defaults = {
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
