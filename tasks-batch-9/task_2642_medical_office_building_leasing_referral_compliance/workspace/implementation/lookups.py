"""Existence resolution (PRD Section 2.8 rungs 4-8) and list paging."""

from db import db
from errors import ApiError
from response import array_response
from validators import pagination


def get_building(building_id):
    row = db.buildings.get(building_id)
    if row is None:
        raise ApiError("ERR_BUILDING_NOT_FOUND", "Building '%s' does not exist." % building_id)
    return row


def get_suite(suite_id, building=None):
    row = db.suites.get(suite_id)
    if row is None:
        raise ApiError("ERR_SUITE_NOT_FOUND", "Suite '%s' does not exist." % suite_id)
    if building is not None and row["building_id"] != building["id"]:
        raise ApiError(
            "ERR_SUITE_NOT_FOUND",
            "Suite '%s' does not belong to building '%s'." % (suite_id, building["id"]),
        )
    return row


def get_tenant(tenant_id):
    row = db.tenants.get(tenant_id)
    if row is None:
        raise ApiError("ERR_TENANT_NOT_FOUND", "Tenant '%s' does not exist." % tenant_id)
    return row


def get_lease(lease_id):
    row = db.leases.get(lease_id)
    if row is None:
        raise ApiError("ERR_LEASE_NOT_FOUND", "Lease '%s' does not exist." % lease_id)
    return row


def get_resource(store, resource_id, label="Resource"):
    row = store.get(resource_id)
    if row is None:
        raise ApiError(
            "ERR_RESOURCE_NOT_FOUND", "%s '%s' does not exist." % (label, resource_id)
        )
    return row


def paged(rows, serializer, limit=None, offset=None):
    """Pagination bounds are a rung-3 concern, so callers that also resolve
    existence must parse them first and pass them in."""
    if limit is None or offset is None:
        limit, offset = pagination()
    total = len(rows)
    window = rows[offset : offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)
