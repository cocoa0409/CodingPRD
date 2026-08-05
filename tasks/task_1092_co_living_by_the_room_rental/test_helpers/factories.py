"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HOST_LEGAL_NAME": "Peachtree Holdings LLC",
    "HOST_ACCOUNT": "acct_pt_001",
    "HOST_EMAIL": "ops@peachtree.example",
    "HOUSE_LABEL": "Peachtree A",
    "ADDRESS": "12 Peachtree St",
    "CITY": "Atlanta",
    "STATE": "GA",
    "UTILITY_BUDGET": 60000,
    "WEEKLY_RATE": 25000,
    "MONTHLY_RATE": 100000,
    "MEMBER_NAME": "Ada Reyes",
    "MEMBER_EMAIL": "ada@resident.example",
    "MEMBER_INCOME": 400000,
    "REPORT_REF": "SCR-001",
}


def create_host_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["HOST_LEGAL_NAME"],
        "payout_account_ref": DEFAULTS["HOST_ACCOUNT"],
        "contact_email": DEFAULTS["HOST_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_house_payload(host_id, **overrides) -> dict:
    payload = {
        "host_id": host_id,
        "label": DEFAULTS["HOUSE_LABEL"],
        "address_line1": DEFAULTS["ADDRESS"],
        "city": DEFAULTS["CITY"],
        "state_code": DEFAULTS["STATE"],
        "monthly_utility_budget_cents": DEFAULTS["UTILITY_BUDGET"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(house_id, room_number="101", **overrides) -> dict:
    payload = {
        "house_id": house_id,
        "room_number": room_number,
        "weekly_rate_cents": DEFAULTS["WEEKLY_RATE"],
        "monthly_rate_cents": DEFAULTS["MONTHLY_RATE"],
        "private_bath": True,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["MEMBER_NAME"],
        "email": DEFAULTS["MEMBER_EMAIL"],
        "declared_monthly_income_cents": DEFAULTS["MEMBER_INCOME"],
    }
    payload.update(overrides)
    return payload


def create_application_payload(member_id, room_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "room_id": room_id,
        "requested_move_in_date": "2026-06-01",
        "billing_cycle": "WEEKLY",
    }
    payload.update(overrides)
    return payload


def create_screening_report_payload(**overrides) -> dict:
    payload = {
        "background_result": "CLEAR",
        "verified_monthly_income_cents": DEFAULTS["MEMBER_INCOME"],
        "report_reference": DEFAULTS["REPORT_REF"],
    }
    payload.update(overrides)
    return payload


def create_membership_payload(application_id, move_in_date="2026-06-01", **overrides) -> dict:
    payload = {"application_id": application_id, "move_in_date": move_in_date}
    payload.update(overrides)
    return payload


def create_invoice_payload(membership_id, period_start, period_end, **overrides) -> dict:
    payload = {
        "membership_id": membership_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents, method="ACH", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "method": method}
    payload.update(overrides)
    return payload


def create_incident_payload(membership_id, **overrides) -> dict:
    payload = {
        "membership_id": membership_id,
        "rule_code": "QUIET_HOURS",
        "severity": "MAJOR",
        "description": "Amplified music after 23:00",
        "occurred_at": "2026-06-02T23:30:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(house_id, **overrides) -> dict:
    payload = {
        "house_id": house_id,
        "area": "COMMON_AREA",
        "severity": "NORMAL",
        "description": "Hallway light flickers",
    }
    payload.update(overrides)
    return payload


def create_payout_payload(house_id, cycle_start, cycle_end, **overrides) -> dict:
    payload = {"house_id": house_id, "cycle_start": cycle_start, "cycle_end": cycle_end}
    payload.update(overrides)
    return payload
