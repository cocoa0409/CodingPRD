"""Shared club-cascade helpers (PRD §3.6, §3.7).

Used by member and membership lifecycle transitions so the cascade chain
member -> membership -> shipment -> release stays consistent."""
from db import db, touch
from domain import recompute_release_available


def cancel_scheduled_shipments(membership):
    """Cancel every SCHEDULED shipment of a membership, each freeing the bottles
    it had reserved on its allocation release."""
    for s in db.shipments.values():
        if s["membership_id"] == membership["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
            release = db.releases.get(s["release_id"])
            if release is not None:
                release["reserved_bottles"] = release["reserved_bottles"] - s["requested_bottles"]
                recompute_release_available(release)
                touch(release)
