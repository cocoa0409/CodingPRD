"""Cross-entity cascades that walk a license's attached server permits when the
license leaves ACTIVE (suspend / revoke / expire). Each touched permit gets its
own version bump + updated_at refresh; active_server_count drives to 0."""
from db import db, touch


def expire_active_permits(license_id):
    """Set every ACTIVE permit of this license to EXPIRED; zero the count."""
    for permit in db.server_permits.values():
        if permit["license_id"] == license_id and permit["status"] == "ACTIVE":
            permit["status"] = "EXPIRED"
            touch(permit)
    lic = db.licenses.get(license_id)
    if lic is not None:
        lic["active_server_count"] = 0


def revoke_active_permits(license_id):
    """Set every ACTIVE permit of this license to REVOKED; zero the count."""
    for permit in db.server_permits.values():
        if permit["license_id"] == license_id and permit["status"] == "ACTIVE":
            permit["status"] = "REVOKED"
            touch(permit)
    lic = db.licenses.get(license_id)
    if lic is not None:
        lic["active_server_count"] = 0
