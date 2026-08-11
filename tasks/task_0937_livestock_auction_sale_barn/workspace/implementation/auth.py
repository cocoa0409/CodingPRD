"""Ladder rungs 1 and 2 (PRD 2.1, 2.7)."""
from flask import request

import config
from errors import fail


def actor(allowed_roles):
    """Rung 1 then rung 2. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # Rung 1: role present and one of the nine; X-User-ID present whenever the
    # role is one of the three party-backed roles.
    if not role or role not in config.ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role in config.PARTY_BACKED_ROLES and not user_id:
        fail("ERR_UNAUTHENTICATED")

    # Rung 2: the acting role appears in the endpoint's authorized-role list.
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    return role, user_id


def ownership(role, user_id, owning_party_id, party_roles=("Consignor", "Buyer", "Carrier")):
    """Rung 9: a party-backed actor must own the resource it acts on."""
    if role in party_roles and role in config.PARTY_BACKED_ROLES:
        if owning_party_id is not None and user_id != owning_party_id:
            fail("ERR_OWNERSHIP_VIOLATION")
