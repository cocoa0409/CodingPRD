"""IdentityVerification logic per PRD §3.5."""

from db import DB, new_id
from clock import now
from errors import validation_failed, not_found
from services.calculations import compute_identity_strength


def create_identity_verification(payload: dict, *, actor_user_id: str) -> dict:
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    subject = payload.get("subject_user_id")
    if not isinstance(subject, str) or not subject:
        raise validation_failed("subject_user_id required")
    contract_id = payload.get("contract_id")
    factors_attempted = payload.get("factors_attempted")
    if not isinstance(factors_attempted, list):
        raise validation_failed("factors_attempted must be a list")
    for fa in factors_attempted:
        if not isinstance(fa, dict):
            raise validation_failed("factors_attempted entries must be objects")
        if fa.get("outcome") not in ("PASS", "FAIL"):
            raise validation_failed("factor outcome must be PASS or FAIL")

    # Determine real_name_match: prefer explicit body field, then look up OrgUser
    if "real_name_match" in payload:
        real_name_match = bool(payload["real_name_match"])
    elif "real_name" in payload:
        org_user = DB.org_users.get(subject)
        if org_user is not None:
            real_name_match = (payload["real_name"] == org_user.get("legal_name"))
        else:
            real_name_match = True
    else:
        real_name_match = True
    org_binding_verified = bool(payload.get("org_binding_verified", False))

    factors_passed, identity_strength, result = compute_identity_strength(
        factors_attempted, real_name_match
    )

    n = now()
    iv_id = new_id()
    iv = {
        "id": iv_id,
        "subject_user_id": subject,
        "contract_id": contract_id,
        "signing_party_id": None,
        "factors_attempted": factors_attempted,
        "factors_passed": factors_passed,
        "real_name_match": real_name_match,
        "org_binding_verified": org_binding_verified,
        "identity_strength": identity_strength,
        "result": result,
        "archived_at": n,
        "created_at": n,
    }
    DB.identity_verifications[iv_id] = iv
    return iv


def get_identity_verification(iv_id: str) -> dict:
    iv = DB.identity_verifications.get(iv_id)
    if not iv:
        raise not_found("IdentityVerification not found")
    return iv
