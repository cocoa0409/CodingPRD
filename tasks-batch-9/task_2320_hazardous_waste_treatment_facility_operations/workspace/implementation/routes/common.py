"""Shared route helpers: path/FK resolution, generator scoping, list plumbing."""

from flask import g

from db import db
from errors import fail
from response import ok_list
from schema import paginate
from services import derive

API = "/tsdf"

NOT_FOUND = {
    "facilities": "ERR_FACILITY_NOT_FOUND",
    "generators": "ERR_GENERATOR_NOT_FOUND",
    "profiles": "ERR_WASTE_PROFILE_NOT_FOUND",
    "manifests": "ERR_MANIFEST_NOT_FOUND",
    "units": "ERR_STORAGE_UNIT_NOT_FOUND",
    "containers": "ERR_CONTAINER_NOT_FOUND",
    "batches": "ERR_TREATMENT_BATCH_NOT_FOUND",
    "instruments": "ERR_RESOURCE_NOT_FOUND",
    "samples": "ERR_RESOURCE_NOT_FOUND",
    "inspections": "ERR_RESOURCE_NOT_FOUND",
    "repair_orders": "ERR_RESOURCE_NOT_FOUND",
    "findings": "ERR_RESOURCE_NOT_FOUND",
    "lines": "ERR_RESOURCE_NOT_FOUND",
}


def load(collection, row_id):
    """Priority 5: a path id that resolves to nothing."""
    row = db.collection(collection).get(row_id)
    if row is None:
        fail(NOT_FOUND[collection])
    return row


def reference(collection, row_id):
    """Priority 6: a foreign key in a request body that resolves to nothing."""
    if row_id is None:
        return None
    row = db.collection(collection).get(row_id)
    if row is None:
        fail("ERR_REFERENCE_NOT_FOUND")
    return row


def check_generator_scope(owner_generator_id):
    """Priority 3: Generator callers may only address their own rows."""
    if getattr(g, "role", None) == "Generator" and owner_generator_id != g.user_id:
        fail("ERR_GENERATOR_SCOPE_VIOLATION")


def scope_filter_generator(filters):
    """A Generator caller's collection reads are narrowed to its own rows."""
    if getattr(g, "role", None) != "Generator":
        return filters.get("generator_id")
    requested = filters.get("generator_id")
    if requested is not None and requested != g.user_id:
        fail("ERR_GENERATOR_SCOPE_VIOLATION")
    return g.user_id


def by_created_at(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def respond_list(rows, projector, limit, offset):
    page, total = paginate(rows, limit, offset)
    return ok_list([projector(row) for row in page], limit, offset, total)


def check_expected_version(row, expected):
    """Priority 7 optimistic concurrency."""
    if expected is None:
        return
    if int(expected) != int(row["version"]):
        fail("ERR_STALE_VERSION")


def check_permit_active(f):
    """Priority 11: permit_status must be ACTIVE or RENEWAL_PENDING."""
    if derive.permit_status(f) not in ("ACTIVE", "RENEWAL_PENDING"):
        fail("ERR_PERMIT_NOT_ACTIVE")


def check_generator_active(gen):
    """Priority 12."""
    if gen["status"] != "ACTIVE":
        fail("ERR_GENERATOR_SUSPENDED")


def check_profile_acceptable(p):
    """Priorities 14 and 15."""
    status = derive.profile_status(p)
    if status not in ("APPROVED", "EXPIRED"):
        fail("ERR_PROFILE_NOT_APPROVED")
    if status == "EXPIRED" or derive.profile_recertification_lapsed(p):
        fail("ERR_PROFILE_EXPIRED")


def check_assurance(f):
    """Priority 35."""
    if derive.facility_shortfall(f) > 0:
        fail("ERR_FINANCIAL_ASSURANCE_SHORTFALL")
