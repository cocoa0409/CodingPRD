"""Authentication, authorization and VendorUser scoping (PRD section 2.1)."""

from flask import request

from db import db
from errors import api_error

ROLES = (
    "PlatformAdmin",
    "VendorOpsAnalyst",
    "MerchandiseManager",
    "VendorUser",
    "CareAgent",
)


class Caller(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_vendor_user(self):
        return self.role == "VendorUser"


def authenticate(allowed_roles):
    """Validation ranks 1 and 2."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        api_error("ERR_UNAUTHENTICATED", "X-User-Role header is missing or invalid")
    if role == "VendorUser" and (user_id is None or user_id == ""):
        api_error("ERR_UNAUTHENTICATED", "X-User-ID header is required for VendorUser")
    if role not in allowed_roles:
        api_error("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return Caller(role, user_id)


def require_vendor_scope(caller, vendor_id):
    """Validation rank 11: a VendorUser may only reach its own vendor."""
    if caller.is_vendor_user and vendor_id != caller.user_id:
        api_error(
            "ERR_VENDOR_SCOPE_VIOLATION",
            "vendor user may only access its own vendor",
        )


def require_item_scope(caller, item):
    if caller.is_vendor_user:
        require_vendor_scope(caller, item["vendor_id"])


def require_line_scope(caller, line):
    if caller.is_vendor_user:
        item = db.items.get(line["item_id"])
        require_vendor_scope(caller, item["vendor_id"] if item else None)
