"""Auth header extraction and role checking per PRD section 2.1."""
from flask import request

import db
import errors

ROLES = ("MasterServicer", "SpecialServicer", "Borrower", "Inspector")
ENTITY_BACKED = {"Borrower": db.borrowers, "Inspector": db.inspectors}


def authenticate():
    """Priority 1: headers present, role declared, entity-backed ids resolvable."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise errors.unauthenticated("X-User-Role header missing or not a declared role")
    if not user_id:
        raise errors.unauthenticated("X-User-ID header missing or empty")
    if role in ENTITY_BACKED:
        if user_id not in ENTITY_BACKED[role]:
            raise errors.unauthenticated("X-User-ID does not correspond to an existing entity")
    return {"role": role, "user_id": user_id}


def authorize(actor, allowed_roles):
    """Priority 2: acting role must be in endpoint's roles list."""
    if actor["role"] not in allowed_roles:
        raise errors.unauthorized("Role %s is not authorized for this endpoint" % actor["role"])


def loan_of_resource(kind, obj):
    """Resolve the owning loan for any resource in a loan chain."""
    if obj is None:
        return None
    if kind == "loan":
        return obj
    if kind == "property":
        return db.loans.get(obj["loan_id"])
    if kind == "statement":
        return db.loans.get(obj["loan_id"])
    if kind == "assessment":
        return db.loans.get(obj["loan_id"])
    if kind == "reserve":
        return db.loans.get(obj["loan_id"])
    if kind == "disbursement":
        reserve = db.reserve_accounts.get(obj["reserve_account_id"])
        return db.loans.get(reserve["loan_id"]) if reserve else None
    if kind == "lease":
        prop = db.properties.get(obj["property_id"])
        return db.loans.get(prop["loan_id"]) if prop else None
    if kind == "estoppel":
        lease = db.leases.get(obj["lease_id"])
        if not lease:
            return None
        prop = db.properties.get(lease["property_id"])
        return db.loans.get(prop["loan_id"]) if prop else None
    if kind == "inspection":
        prop = db.properties.get(obj["property_id"])
        return db.loans.get(prop["loan_id"]) if prop else None
    if kind == "policy":
        prop = db.properties.get(obj["property_id"])
        return db.loans.get(prop["loan_id"]) if prop else None
    if kind == "assumption":
        return db.loans.get(obj["loan_id"])
    if kind == "option":
        return db.loans.get(obj["loan_id"])
    if kind == "watchlist":
        return db.loans.get(obj["loan_id"])
    return None


def borrower_owns(actor, kind, obj):
    """Priority 3: borrower loan-chain ownership on writes."""
    if actor["role"] != "Borrower":
        return True
    loan = loan_of_resource(kind, obj)
    if loan is None:
        return False
    return loan["borrower_id"] == actor["user_id"]


def require_borrower_ownership(actor, kind, obj):
    if not borrower_owns(actor, kind, obj):
        raise errors.ownership("Acting borrower does not own this resource's loan chain")


def read_scope_allows(actor, kind, obj):
    """Out-of-scope reads by entity-backed roles surface as ERR_NOT_FOUND."""
    if obj is None:
        return False
    if actor["role"] == "Borrower":
        return borrower_owns(actor, kind, obj)
    if actor["role"] == "Inspector":
        if kind == "inspector":
            return obj["id"] == actor["user_id"]
        if kind == "inspection":
            return obj["inspector_id"] == actor["user_id"]
        return False
    return True
