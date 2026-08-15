"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 p1/p2)."""

from flask import g, request

import errors

ROLES = {
    "Cardholder",
    "IntakeAgent",
    "DisputeInvestigator",
    "ChargebackAnalyst",
    "FinanceOfficer",
    "BankAdmin",
}

# Every role may read these resources (per-endpoint role lists in §1.5)
ALL_ROLES = frozenset(ROLES)


def authenticate():
    """Validate X-User-ID / X-User-Role headers. Priority tier 1."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.missing_auth()
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Validate the presented role is permitted on this endpoint. Tier 2."""
    if g.role not in roles:
        raise errors.forbidden(
            f"Role {g.role} is not permitted for this endpoint"
        )


def require_cardholder_owns(card_account_id):
    """Cardholder ownership check (tier 5): X-User-ID must equal the account id."""
    if g.role == "Cardholder" and g.user_id != card_account_id:
        raise errors.forbidden(
            "Cardholder may only access resources on their own card account"
        )
