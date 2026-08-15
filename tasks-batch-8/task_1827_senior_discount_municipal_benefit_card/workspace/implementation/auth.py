"""Authentication / authorization / ownership (PRD 2.1, 2.9, 2.10)."""
from flask import request

import store
from errors import (
    ERR_CARDHOLDER_OWNERSHIP_MISMATCH,
    ERR_FORBIDDEN,
    ERR_MERCHANT_OWNERSHIP_MISMATCH,
    ERR_UNAUTHENTICATED,
    raise_err,
)

ROLES = [
    "Applicant",
    "Cardholder",
    "EligibilitySpecialist",
    "ProgramAdministrator",
    "MerchantOperator",
    "FraudAnalyst",
]

# Roles whose X-User-ID must reference an existing persisted entity (PRD 2.1).
ENTITY_BACKED = {
    "Cardholder": ("cardholders", "Cardholder"),
    "MerchantOperator": ("merchants", "Merchant"),
}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present, role recognized, and
    entity-backed identity resolvable."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    backing = ENTITY_BACKED.get(role)
    if backing is not None:
        table_name, label = backing
        if uid not in getattr(store, table_name):
            raise_err(ERR_UNAUTHENTICATED,
                      "X-User-ID does not reference an existing %s" % label)
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role in the endpoint's roles list."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s is not authorized for this endpoint" % role)


def require_cardholder_self(uid, cardholder_id):
    if uid != cardholder_id:
        raise_err(ERR_CARDHOLDER_OWNERSHIP_MISMATCH,
                  "Cardholder may act only on their own record")


def require_merchant_self(uid, merchant_id):
    if uid != merchant_id:
        raise_err(ERR_MERCHANT_OWNERSHIP_MISMATCH,
                  "MerchantOperator may act only for their own merchant")
