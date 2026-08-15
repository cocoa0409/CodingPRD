"""Auth middleware — validates X-User-Role / X-User-ID headers and RBAC."""

from flask import request
from errors import (
    APIError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_SCOPE,
)
from db import store


VALID_ROLES = {
    "PlatformAdmin",
    "LandlordPM",
    "LandlordApprover",
    "TenantRep",
    "ContractorRep",
    "BuildingEngineer",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise APIError(ERR_UNAUTHENTICATED, 401, "X-User-ID and X-User-Role headers required")
    return user_id, role


def require_roles(*allowed_roles):
    """Validate the caller's role is in the allowed list. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise APIError(ERR_UNAUTHORIZED_ROLE, 403, f"Role {role} not authorized for this endpoint")
    return user_id, role


def check_tenant_ownership(user_id, lease_id):
    """TenantRep scope: X-User-ID must equal Lease.tenant_id."""
    lease = store.leases.get(lease_id)
    if not lease:
        return  # existence check handles 404 elsewhere
    if lease["tenant_id"] != user_id:
        raise APIError(ERR_FORBIDDEN_SCOPE, 403, "TenantRep does not own this lease")


def check_contractor_ownership(user_id, engagement_id):
    """ContractorRep scope: X-User-ID must equal the engagement's contractor_id."""
    eng = store.contractor_engagements.get(engagement_id)
    if not eng:
        return
    if eng["contractor_id"] != user_id:
        raise APIError(ERR_FORBIDDEN_SCOPE, 403, "ContractorRep does not own this engagement")


def check_contractor_ownership_by_contractor(user_id, contractor_id):
    """ContractorRep scope: X-User-ID must equal contractor_id."""
    if contractor_id != user_id:
        raise APIError(ERR_FORBIDDEN_SCOPE, 403, "ContractorRep does not own this contractor")


def get_project_tenant_ownership(user_id, project_id):
    """For TenantRep scoped endpoints that go through a project, resolve lease and check."""
    proj = store.ti_projects.get(project_id)
    if not proj:
        return
    check_tenant_ownership(user_id, proj["lease_id"])
