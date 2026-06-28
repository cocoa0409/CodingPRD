"""Payload factories — one per entity, input fields only."""


def create_member_payload(**overrides) -> dict:
    defaults = {"email": "member@example.com", "full_name": "Test Member"}
    defaults.update(overrides)
    return defaults


def create_savings_account_payload(member_id, **overrides) -> dict:
    defaults = {"member_id": member_id, "nickname": "Rainy Day"}
    defaults.update(overrides)
    return defaults


def create_linked_account_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "institution_name": "Acme Bank",
        "account_type": "CHECKING",
    }
    defaults.update(overrides)
    return defaults


def create_recurring_charge_payload(linked_account_id, **overrides) -> dict:
    defaults = {
        "linked_account_id": linked_account_id,
        "merchant_name": "StreamCo",
        "amount_cents": 5000,
        "cadence": "MONTHLY",
        "category": "STREAMING",
        "first_seen_utc": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(member_id, recurring_charge_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "recurring_charge_id": recurring_charge_id,
        "plan_name": "Standard",
        "monthly_cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_concierge_agent_payload(**overrides) -> dict:
    defaults = {"display_name": "Agent A", "max_open_cases": 5}
    defaults.update(overrides)
    return defaults


def create_negotiation_case_payload(member_id, recurring_charge_id, assigned_agent_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "recurring_charge_id": recurring_charge_id,
        "assigned_agent_id": assigned_agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_refund_claim_payload(member_id, recurring_charge_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "recurring_charge_id": recurring_charge_id,
        "claim_type": "PRICE_DROP",
        "observed_old_amount_cents": 2000,
        "observed_new_amount_cents": 1500,
    }
    defaults.update(overrides)
    return defaults
