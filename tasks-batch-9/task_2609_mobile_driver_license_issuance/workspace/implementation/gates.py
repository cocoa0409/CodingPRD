"""Cross-cutting ladder gates shared by several route modules."""

from flask import g

from errors import ApiError
from store import now


def physical_credential_eligible(holder):
    """PRD 3.2: only VALID plastic, expiring strictly after today, confers eligibility."""
    if holder["physical_credential_status"] != "VALID":
        return False
    return holder["physical_credential_expires_on"] > now().date()


def require_physical_eligible(holder):
    if not physical_credential_eligible(holder):
        raise ApiError("ERR_PHYSICAL_CREDENTIAL_INELIGIBLE")


def require_holder_owner(holder_id):
    if g.user_role == "Holder" and g.user_id != holder_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_verifier_owner(verifier_id):
    if g.user_role == "VerifierOperator" and g.user_id != verifier_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
