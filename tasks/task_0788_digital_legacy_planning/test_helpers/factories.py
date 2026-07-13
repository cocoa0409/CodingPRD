"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "OWNER_NAME": "Ada Owner",
    "OWNER_EMAIL": "ada@x.com",
    "AUTH_START": "2026-06-01T00:00:00Z",
    "AUTH_END": "2027-06-01T00:00:00Z",
}


def create_plan_payload(**overrides) -> dict:
    payload = {"owner_full_name": DEFAULTS["OWNER_NAME"], "owner_email": DEFAULTS["OWNER_EMAIL"]}
    payload.update(overrides)
    return payload


def create_vault_item_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "kind": "DOCUMENT",
        "category": "will",
        "title": "Will",
        "secret_ref": "vault://will",
    }
    payload.update(overrides)
    return payload


def create_deputy_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "full_name": "Dee One",
        "email": "d1@x.com",
        "deputy_role": "EXECUTOR",
        "access_scope": ["ASSET"],
        "release_trigger": "ON_DEATH",
        "authority_start_at": DEFAULTS["AUTH_START"],
        "authority_end_at": DEFAULTS["AUTH_END"],
    }
    payload.update(overrides)
    return payload


def create_beneficiary_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "full_name": "Ben One",
        "relationship": "child",
    }
    payload.update(overrides)
    return payload


def create_directive_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "directive_type": "MEDICAL",
        "content": "wishes",
    }
    payload.update(overrides)
    return payload


def create_release_request_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "trigger_type": "ON_DEATH",
        "scope_kinds": ["ASSET"],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(plan_id, **overrides) -> dict:
    payload = {"plan_id": plan_id, "tier": "PLUS"}
    payload.update(overrides)
    return payload


def create_share_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "shared_with_email": "bob@x.com",
        "scope": "ITEM",
        "effective_at": "2026-06-01T00:00:00Z",
        "expires_at": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_integration_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "provider_type": "WILL_REGISTRY",
        "provider_name": "StateReg",
        "external_ref": "WR-1",
    }
    payload.update(overrides)
    return payload


def create_review_reminder_payload(plan_id, **overrides) -> dict:
    payload = {
        "plan_id": plan_id,
        "subject_kind": "VAULT",
        "interval_days": 180,
        "last_reviewed_at": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
