"""Auth header extraction, role checks, and entity-backed scoping (PRD 2.1, 2.10 tiers 1-3)."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_APPLICANT_ACCESS_DENIED,
    ERR_PROVIDER_ACCESS_DENIED,
)

# Nine operational roles recognized by the program (PRD 2.1). "Any" is a
# designation on read endpoints, not a presentable role value.
ALL_ROLES = [
    "ProgramAdmin",
    "ApplicantCoordinator",
    "ApplicantCertifier",
    "VendorRepresentative",
    "PIAReviewer",
    "CommitmentOfficer",
    "InvoiceProcessor",
    "AppealOfficer",
    "Auditor",
]

APPLICANT_ROLES = ("ApplicantCoordinator", "ApplicantCertifier")


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role
        # Entity-backed resolution (PRD 2.1):
        #   ApplicantCoordinator/ApplicantCertifier -> ApplicantUser -> applicant_id
        #   VendorRepresentative -> ServiceProvider id
        # Opaque roles never resolve to an entity.
        self.applicant_id = None
        self.provider_id = None


def get_caller() -> Caller:
    """Tier 1: header presence and form. An unrecognized role is malformed."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and well-formed",
        )
    caller = Caller(user_id, role)
    if role in APPLICANT_ROLES:
        user = db["applicant_users"].get(user_id)
        if user is not None:
            caller.applicant_id = user["applicant_id"]
    elif role == "VendorRepresentative":
        if user_id in db["service_providers"]:
            caller.provider_id = user_id
    return caller


def check_role(caller: Caller, allowed_roles):
    """Tier 2: caller role must appear in the endpoint's authorized list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def check_applicant_scope(caller: Caller, target_applicant_id):
    """Tier 3 (applicant side): the caller's applicant_id must match the target
    resource's applicant chain. An unresolvable ApplicantUser identity cannot
    match anything and is denied."""
    if caller.applicant_id is None or caller.applicant_id != target_applicant_id:
        raise_error(
            ERR_APPLICANT_ACCESS_DENIED,
            "caller's applicant does not match the target resource's applicant chain",
        )


def check_provider_identity(caller: Caller):
    """VendorRepresentative identity must resolve to a registered ServiceProvider."""
    if caller.provider_id is None:
        raise_error(
            ERR_PROVIDER_ACCESS_DENIED,
            "X-User-ID does not resolve to a registered service provider",
        )


def check_provider_scope(caller: Caller, provider_id):
    """Tier 3 (provider side): caller's provider must match the target provider."""
    if caller.provider_id is None or caller.provider_id != provider_id:
        raise_error(
            ERR_PROVIDER_ACCESS_DENIED,
            "caller's service provider does not match the target resource's provider",
        )
