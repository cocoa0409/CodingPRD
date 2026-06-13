"""Payload factories — one per entity, input fields only (PRD §3).

Each factory builds the minimal valid create body and accepts **overrides for
fields a test needs to control.
"""
import itertools

# Monotonic counter so independently-created entities get unique emails /
# system codes within a single test (the server starts empty before each test).
_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


# --------------------------------------------------------------------------
# Entitlement — input: name, system_code, is_privileged?, risk_weight?
# --------------------------------------------------------------------------
def create_entitlement_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Entitlement {n}",
        "system_code": f"SYS_{n}",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Role — input: name, entitlement_ids
# --------------------------------------------------------------------------
def create_role_payload(entitlement_ids, **overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Role {n}",
        "entitlement_ids": list(entitlement_ids),
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# SodPolicy — input: name, entitlement_a_id, entitlement_b_id, severity?
# --------------------------------------------------------------------------
def create_sod_policy_payload(entitlement_a_id, entitlement_b_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"SodPolicy {n}",
        "entitlement_a_id": entitlement_a_id,
        "entitlement_b_id": entitlement_b_id,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Identity — input: display_name, email, is_human?
# --------------------------------------------------------------------------
def create_identity_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "display_name": f"Identity {n}",
        "email": f"identity{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Grant (direct) — input: entitlement_id, expected_identity_version,
#   is_just_in_time?, effective_from?, effective_until?
# --------------------------------------------------------------------------
def create_grant_payload(entitlement_id, expected_identity_version, **overrides) -> dict:
    defaults = {
        "entitlement_id": entitlement_id,
        "expected_identity_version": expected_identity_version,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# AccessRequest — input: identity_id, role_id, justification,
#   sod_override_justification?
# --------------------------------------------------------------------------
def create_access_request_payload(identity_id, role_id, **overrides) -> dict:
    defaults = {
        "identity_id": identity_id,
        "role_id": role_id,
        "justification": "Business justification for access",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# CertificationCampaign — input: name, scope_role_id, review_window_start,
#   review_window_end
# --------------------------------------------------------------------------
def create_campaign_payload(scope_role_id,
                            review_window_start="2026-06-01T00:00:00Z",
                            review_window_end="2026-06-30T00:00:00Z",
                            **overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Campaign {n}",
        "scope_role_id": scope_role_id,
        "review_window_start": review_window_start,
        "review_window_end": review_window_end,
    }
    defaults.update(overrides)
    return defaults
