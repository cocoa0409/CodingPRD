"""Payload factories — one per entity, input fields only (PRD §3, §4).

Each factory emits only the fields a client supplies (source: input). Optional
fields with defaults are omitted unless overridden, so callers can exercise the
PRD-declared defaults.
"""


# ─── Community (PRD §3.1) ───────────────────────────────────────────────────

def create_community_payload(
    name: str = "Test Community",
    actuarial_discount_rate_bps: int = 0,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "actuarial_discount_rate_bps": actuarial_discount_rate_bps,
    }
    payload.update(overrides)
    return payload


# ─── Contract Plan (PRD §3.1) ───────────────────────────────────────────────

def create_contract_plan_payload(
    community_id: str,
    name: str = "Test Plan",
    contract_type: str = "TYPE_C",
    entrance_fee_cents: int = 5_000_000,
    refund_plan: str = "DECLINING",
    monthly_service_fee_cents: int = 300_000,
    second_person_fee_cents: int = 0,
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "name": name,
        "contract_type": contract_type,
        "entrance_fee_cents": entrance_fee_cents,
        "refund_plan": refund_plan,
        "monthly_service_fee_cents": monthly_service_fee_cents,
        "second_person_fee_cents": second_person_fee_cents,
    }
    payload.update(overrides)
    return payload


# ─── Unit (PRD §3.1) ────────────────────────────────────────────────────────

def create_unit_payload(
    community_id: str,
    unit_number: str = "U-1",
    care_level: str = "INDEPENDENT",
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "unit_number": unit_number,
        "care_level": care_level,
    }
    payload.update(overrides)
    return payload


# ─── Resident (PRD §3.1) ────────────────────────────────────────────────────

def create_resident_payload(
    community_id: str,
    full_name: str = "Test Resident",
    date_of_birth: str = "1930-01-01",
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    }
    payload.update(overrides)
    return payload


# ─── Residency (PRD §3.2) ───────────────────────────────────────────────────

def create_residency_payload(
    community_id: str,
    primary_resident_id: str,
    contract_plan_id: str,
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "primary_resident_id": primary_resident_id,
        "contract_plan_id": contract_plan_id,
    }
    payload.update(overrides)
    return payload


# ─── Second Person (PRD §3.4) ───────────────────────────────────────────────

def create_second_person_payload(
    full_name: str = "Test Second Person",
    date_of_birth: str = "1932-01-01",
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    }
    payload.update(overrides)
    return payload


# ─── Waitlist Entry (PRD §3.3) ──────────────────────────────────────────────

def create_waitlist_entry_payload(
    community_id: str,
    residency_id: str,
    target_care_level: str = "INDEPENDENT",
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "residency_id": residency_id,
        "target_care_level": target_care_level,
    }
    payload.update(overrides)
    return payload


# ─── Care Transition (PRD §3.4) ─────────────────────────────────────────────

def create_care_transition_payload(
    residency_id: str,
    to_level: str,
    **overrides,
) -> dict:
    payload = {
        "residency_id": residency_id,
        "to_level": to_level,
    }
    payload.update(overrides)
    return payload


# ─── Bed Reservation (PRD §3.5) ─────────────────────────────────────────────

def create_bed_reservation_payload(
    residency_id: str,
    unit_id: str,
    hold_expiry_period: int,
    **overrides,
) -> dict:
    payload = {
        "residency_id": residency_id,
        "unit_id": unit_id,
        "hold_expiry_period": hold_expiry_period,
    }
    payload.update(overrides)
    return payload


# ─── Council (PRD §3.8) ─────────────────────────────────────────────────────

def create_council_payload(
    community_id: str,
    name: str = "Test Council",
    **overrides,
) -> dict:
    payload = {
        "community_id": community_id,
        "name": name,
    }
    payload.update(overrides)
    return payload


# ─── Council Resolution (PRD §3.8) ──────────────────────────────────────────

def create_resolution_payload(
    council_id: str,
    title: str = "Test Resolution",
    **overrides,
) -> dict:
    payload = {
        "council_id": council_id,
        "title": title,
    }
    payload.update(overrides)
    return payload
