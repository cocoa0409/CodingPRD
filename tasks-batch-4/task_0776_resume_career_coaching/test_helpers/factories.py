"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_BASE_PRICE": 20000,
    "TARGET_ROLE": "Product Manager",
    "TARGET_INDUSTRY": "Tech",
    "DELIVERY_DAYS": 7,
}


def create_package_plan_payload(**overrides) -> dict:
    payload = {
        "tier": "BASIC",
        "base_price_cents": DEFAULTS["PLAN_BASE_PRICE"],
        "included_deliverables": ["RESUME"],
        "included_revision_rounds": 1,
        "included_coaching_sessions": 0,
        "guarantee_type": "NONE",
    }
    payload.update(overrides)
    return payload


def create_client_payload(**overrides) -> dict:
    payload = {"name": "Test Client", "email": "client@example.com"}
    payload.update(overrides)
    return payload


def create_coach_payload(**overrides) -> dict:
    payload = {"name": "Test Coach", "email": "coach@example.com", "specialty": "GENERAL"}
    payload.update(overrides)
    return payload


def create_order_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "target_role": DEFAULTS["TARGET_ROLE"],
        "target_industry": DEFAULTS["TARGET_INDUSTRY"],
        "requested_delivery_days": DEFAULTS["DELIVERY_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_session_payload(coach_id, scheduled_start, scheduled_end,
                           expected_order_version, session_type="COACHING",
                           **overrides) -> dict:
    payload = {
        "coach_id": coach_id,
        "session_type": session_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def create_addon_payload(addon_type, **overrides) -> dict:
    payload = {"type": addon_type}
    payload.update(overrides)
    return payload


def create_revision_payload(reason="Please revise", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def create_guarantee_claim_payload(claim_type, evidence="justification", **overrides) -> dict:
    payload = {"claim_type": claim_type, "evidence": evidence}
    payload.update(overrides)
    return payload


def create_ats_scan_payload(sections, **overrides) -> dict:
    payload = {"sections": sections}
    payload.update(overrides)
    return payload


def create_draft_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload
