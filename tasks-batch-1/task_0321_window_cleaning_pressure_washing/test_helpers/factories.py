"""Payload factories — one per entity, input fields only (PRD §3 / §4).

Each factory provides sensible defaults and accepts **overrides for the fields a
test needs to control. Only source: input fields are emitted; computed and
system fields (balances, charges, statuses, derived flags) are never sent.
"""
import itertools

# A monotonic counter so default contact_email is unique across Account creates
# (PRD §3.1: contact_email must be unique across all accounts).
_email_counter = itertools.count(1)


def create_account_payload(**overrides) -> dict:
    n = next(_email_counter)
    defaults = {
        "company_name": "Test Cleaning Co",
        "contact_email": f"acct{n}@example.com",
        "region_code": "NORTH",
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "address_line": "1 Test Lane",
        "pane_count": 60,
        "glass_sqft": 100.0,
        "stories": 2,
        "soft_wash_sqft": 0,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(account_id: str, property_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "property_id": property_id,
        "pricing_basis": "PANE_COUNT",
        "addon_codes": ["GUTTER"],
        "valid_until": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_service_agreement_payload(quote_id: str, schedule_kind: str = "ONE_TIME",
                                     **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "schedule_kind": schedule_kind,
    }
    if schedule_kind == "RECURRING":
        defaults["recurrence_interval_days"] = 14
    defaults.update(overrides)
    return defaults


def activate_agreement_payload(planned_date: str = "2026-07-01",
                               window_start_min: int = 540,
                               window_end_min: int = 660, **overrides) -> dict:
    defaults = {
        "first_visit_planned_date": planned_date,
        "first_visit_window_start_min": window_start_min,
        "first_visit_window_end_min": window_end_min,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(account_id: str, agreement_id: str,
                           amount_cents: int = 9000, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "agreement_id": agreement_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_name": "Test Crew",
        "region_code": "NORTH",
        "skill_codes": [],
        "daily_capacity_minutes": 600,
    }
    defaults.update(overrides)
    return defaults


def set_crew_status_payload(status: str, **overrides) -> dict:
    defaults = {"status": status}
    defaults.update(overrides)
    return defaults


def create_route_payload(crew_id: str, region_code: str = "NORTH",
                         service_date: str = "2026-07-01", **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "region_code": region_code,
        "service_date": service_date,
    }
    defaults.update(overrides)
    return defaults


def commit_visit_payload(visit_id: str, expected_route_version: int, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def attach_add_on_payload(addon_code: str, **overrides) -> dict:
    defaults = {"addon_code": addon_code}
    defaults.update(overrides)
    return defaults


def upload_photo_payload(phase: str, image_uri: str = "s3://photo.jpg", **overrides) -> dict:
    defaults = {"phase": phase, "image_uri": image_uri}
    defaults.update(overrides)
    return defaults


def weather_reschedule_payload(new_planned_date: str, **overrides) -> dict:
    defaults = {"new_planned_date": new_planned_date}
    defaults.update(overrides)
    return defaults


def create_weather_advisory_payload(region_code: str = "NORTH",
                                    advisory_date: str = "2026-07-01",
                                    severity: str = "SUSPEND", **overrides) -> dict:
    defaults = {
        "region_code": region_code,
        "advisory_date": advisory_date,
        "severity": severity,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(visit_id: str, **overrides) -> dict:
    defaults = {"visit_id": visit_id}
    defaults.update(overrides)
    return defaults


def create_reclean_request_payload(visit_id: str, reason: str = "streaks left", **overrides) -> dict:
    defaults = {"visit_id": visit_id, "reason": reason}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
