"""Payload factories — one per entity, input fields only (PRD section 4)."""

DEFAULTS = {
    "OPERATOR_NAME": "Op One",
    "OPERATOR_HOME_PORT": "Athens",
    "CA_DISPLAY_NAME": "CA One",
    "CA_LICENSE_NO": "LIC-CA-1",
    "CLIENT_FULL_NAME": "Cy Client",
    "CLIENT_EMAIL": "cy@example.com",
    "RESUME_CLASS": "OFFSHORE",
    "SKIPPERED_HOURS": 300,
    "GUESTS_COUNT": 4,
}


def create_operator_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["OPERATOR_NAME"],
        "home_port": DEFAULTS["OPERATOR_HOME_PORT"],
    }
    defaults.update(overrides)
    return defaults


def create_broker_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["CA_DISPLAY_NAME"],
        "broker_type": "CENTRAL_AGENT",
        "license_no": DEFAULTS["CA_LICENSE_NO"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CLIENT_FULL_NAME"],
        "email": DEFAULTS["CLIENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_resume_payload(**overrides) -> dict:
    defaults = {
        "resume_class": DEFAULTS["RESUME_CLASS"],
        "skippered_hours": DEFAULTS["SKIPPERED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_yacht_payload(listing_central_agent_id: str, **overrides) -> dict:
    """Yacht A preset: PRO_RATA, weekly 700000, capacity 8, min 3 days,
    required resume COASTAL, deposit 500000."""
    defaults = {
        "name": "Yacht A",
        "charter_type": "BAREBOAT",
        "home_port": "Athens",
        "capacity_berths": 8,
        "weekly_base_rate_cents": 700000,
        "min_charter_days": 3,
        "required_resume_class": "COASTAL",
        "security_deposit_cents": 500000,
        "pricing_mode": "PRO_RATA",
        "listing_central_agent_id": listing_central_agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_availability_block_payload(expected_yacht_version: int, **overrides) -> dict:
    defaults = {
        "block_type": "MAINTENANCE",
        "start_date": "2026-09-10",
        "end_date": "2026-09-20",
        "expected_yacht_version": expected_yacht_version,
    }
    defaults.update(overrides)
    return defaults


def create_charter_request_payload(client_id: str, yacht_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "yacht_id": yacht_id,
        "start_date": "2026-10-01",
        "end_date": "2026-10-11",
        "guests_count": DEFAULTS["GUESTS_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_counter_payload(expected_charter_request_version: int, **overrides) -> dict:
    defaults = {
        "expected_charter_request_version": expected_charter_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_accept_payload(expected_charter_request_version: int) -> dict:
    return {"expected_charter_request_version": expected_charter_request_version}


def create_rebook_payload(yacht_id: str, **overrides) -> dict:
    defaults = {
        "yacht_id": yacht_id,
        "start_date": "2026-12-01",
        "end_date": "2026-12-11",
        "guests_count": DEFAULTS["GUESTS_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(tranche: str, amount_cents: int) -> dict:
    return {"tranche": tranche, "amount_cents": amount_cents}


def create_expense_payload(**overrides) -> dict:
    defaults = {
        "bucket": "APA",
        "description": "provisioning",
        "amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(charter_fee_cents: int,
                                         start_date: str,
                                         end_date: str,
                                         **overrides) -> dict:
    """Window defaults generously contain the charter window on closed bounds."""
    defaults = {
        "insurer_name": "InsCo",
        "policy_no": "POL-1",
        "coverage_amount_cents": charter_fee_cents,
        "valid_from": _shift_date(start_date, -30),
        "valid_until": _shift_date(end_date, 30),
    }
    defaults.update(overrides)
    return defaults


def create_itinerary_leg_payload(**overrides) -> dict:
    defaults = {
        "port_name": "Mykonos",
        "arrival_date": "2026-11-03",
        "departure_date": "2026-11-05",
    }
    defaults.update(overrides)
    return defaults


def create_port_permit_payload(**overrides) -> dict:
    defaults = {
        "port_authority_ref": "PA-1",
        "valid_from": "2026-11-01",
        "valid_until": "2026-11-06",
    }
    defaults.update(overrides)
    return defaults


def _shift_date(yyyy_mm_dd: str, days: int) -> str:
    from datetime import date, timedelta
    d = date.fromisoformat(yyyy_mm_dd)
    return (d + timedelta(days=days)).isoformat()
