"""Payload factories — one per write endpoint, input fields only."""

DEFAULTS = {
    "PRACTICE_NAME": "Test Practice",
    "PANEL_TARGET": 50,
    "PANEL_HARD_CAP": 100,
    "MONTHLY_FEE_CENTS": 15000,
    "DPC_CODES": ["OFFICE_VISIT"],
    "PROVIDER_NAME": "Dr Test",
    "COMPANY_NAME": "Test Co",
    "SPONSORED_SEAT_LIMIT": 5,
    "MEMBER_NAME": "Test Member",
}

_npi_counter = [1000000000]


def _next_npi() -> str:
    _npi_counter[0] += 1
    return str(_npi_counter[0])


def create_practice_payload(**overrides) -> dict:
    """Required: name, panel_target, panel_hard_cap, monthly_fee_cents,
    dpc_covered_service_codes. Optional: annual_fee_discount_pct,
    insurance_coinsurance_pct, late_fee_cents, grace_period_days."""
    defaults = {
        "name": DEFAULTS["PRACTICE_NAME"],
        "panel_target": DEFAULTS["PANEL_TARGET"],
        "panel_hard_cap": DEFAULTS["PANEL_HARD_CAP"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "dpc_covered_service_codes": list(DEFAULTS["DPC_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(practice_id: str, **overrides) -> dict:
    """Required: practice_id, full_name, npi. Optional: panel_capacity,
    accepting_new_members."""
    defaults = {
        "practice_id": practice_id,
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "npi": _next_npi(),
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(practice_id: str, **overrides) -> dict:
    """Required: practice_id, company_name, sponsored_seat_limit.
    Optional: sponsorship_pct."""
    defaults = {
        "practice_id": practice_id,
        "company_name": DEFAULTS["COMPANY_NAME"],
        "sponsored_seat_limit": DEFAULTS["SPONSORED_SEAT_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def register_member_payload(practice_id: str, email: str, **overrides) -> dict:
    """Required: practice_id, email, full_name. Optional: plan_type, has_insurance."""
    defaults = {
        "practice_id": practice_id,
        "email": email,
        "full_name": DEFAULTS["MEMBER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def assign_pcp_payload(mode: str, provider_id: str = None, **overrides) -> dict:
    """Required: mode. Optional: provider_id (for MANUAL)."""
    payload = {"mode": mode}
    if provider_id is not None:
        payload["provider_id"] = provider_id
    payload.update(overrides)
    return payload


def create_visit_slot_payload(slot_type: str, starts_at: str, ends_at: str, **overrides) -> dict:
    """Required: slot_type, starts_at, ends_at. Optional: virtual_capacity."""
    defaults = {
        "slot_type": slot_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(member_id: str, slot_id: str, visit_type: str,
                         expected_slot_version: int, **overrides) -> dict:
    """Required: member_id, slot_id, visit_type, expected_slot_version."""
    defaults = {
        "member_id": member_id,
        "slot_id": slot_id,
        "visit_type": visit_type,
        "expected_slot_version": expected_slot_version,
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(service_lines: list, **overrides) -> dict:
    """Required: service_lines."""
    defaults = {"service_lines": list(service_lines)}
    defaults.update(overrides)
    return defaults


def occupy_seat_payload(member_id: str, expected_employer_version: int, **overrides) -> dict:
    """Required: member_id, expected_employer_version."""
    defaults = {
        "member_id": member_id,
        "expected_employer_version": expected_employer_version,
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(member_id: str, origin_visit_id: str, **overrides) -> dict:
    """Required: member_id, origin_visit_id. Optional: goal_count."""
    defaults = {
        "member_id": member_id,
        "origin_visit_id": origin_visit_id,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(member_id: str, origin_visit_id: str, specialty: str, **overrides) -> dict:
    """Required: member_id, origin_visit_id, specialty."""
    defaults = {
        "member_id": member_id,
        "origin_visit_id": origin_visit_id,
        "specialty": specialty,
    }
    defaults.update(overrides)
    return defaults


def charge_payload(charge_kind: str, amount_cents: int, outcome: str, **overrides) -> dict:
    """For membership charge. Required: charge_kind, amount_cents, outcome."""
    defaults = {
        "charge_kind": charge_kind,
        "amount_cents": amount_cents,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def invoice_charge_payload(amount_cents: int, outcome: str, **overrides) -> dict:
    """For invoice charge. Required: amount_cents, outcome."""
    defaults = {
        "amount_cents": amount_cents,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def message_thread_payload(body: str, **overrides) -> dict:
    """Required: body."""
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults
