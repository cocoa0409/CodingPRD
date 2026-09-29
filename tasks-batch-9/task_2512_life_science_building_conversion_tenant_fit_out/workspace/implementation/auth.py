"""Role gate and tenant ownership (PRD 2.1).

The role gate is coarse and runs after ERR_VALIDATION but before path resolution
(PRD 2.8). `Tenant` is the one entity-backed role: its X-User-ID is the acting
Tenant record's id, and ownership is reached through the lease that owns the
project, phase, permit, reservation, allocation or commissioning record.
"""
from flask import request

import constants
import db
import queries
from errors import fail

TENANT = constants.ROLE_TENANT


def identity():
    """(X-User-ID, X-User-Role) or ERR_UNAUTHORIZED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in constants.ROLE_SET:
        fail("ERR_UNAUTHORIZED", "Missing or unrecognised X-User-ID / X-User-Role headers")
    return user_id, role


def require(*allowed):
    user_id, role = identity()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    return user_id, role


def party(role):
    return "LANDLORD" if role == constants.ROLE_LANDLORD else "TENANT"


# --------------------------------------------------------------- ownership scope
def guard_tenant(tenant_id, user_id, role):
    if role == TENANT and tenant_id != user_id:
        fail("ERR_UNAUTHORIZED", "This tenant may not reach another tenant's records")


def guard_lease(lease, user_id, role):
    guard_tenant(lease["tenant_id"], user_id, role)


def guard_project(project, user_id, role):
    if role != TENANT:
        return
    lease = queries.lease_of_project(project)
    if lease is None or lease["tenant_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "This tenant may not reach another tenant's records")


def guard_by_project_id(project_id, user_id, role):
    if role != TENANT:
        return
    project = db.projects.get(project_id)
    if project is None:
        fail("ERR_UNAUTHORIZED", "This tenant may not reach another tenant's records")
    guard_project(project, user_id, role)


def guard_by_lease_id(lease_id, user_id, role):
    if role != TENANT:
        return
    lease = db.leases.get(lease_id)
    if lease is None or lease["tenant_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "This tenant may not reach another tenant's records")
