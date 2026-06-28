"""Lazy permit-expiry evaluation (PRD §2.9, §3.4).

An APPROVED permit lapses to EXPIRED when the logical clock reaches or passes
its expires_at while the project is still PERMITTING or APPROVED_TO_BUILD and no
manufacture order has yet been created. Evaluated lazily on read/transition.
Carries no effect beyond the status flip.
"""
from db import db


def project_has_manufacture_order(project_id):
    for mo in db.manufacture_orders.values():
        if mo["project_id"] == project_id:
            return True
    return False


def evaluate_expiry(permit):
    """Mutate the permit to EXPIRED if its approval has lapsed. Returns the permit."""
    if permit["status"] != "APPROVED":
        return permit
    expires_at = permit.get("expires_at")
    if expires_at is None:
        return permit
    project = db.projects.get(permit["project_id"])
    if project is None:
        return permit
    if project["status"] not in ("PERMITTING", "APPROVED_TO_BUILD"):
        return permit
    if project_has_manufacture_order(permit["project_id"]):
        return permit
    if db.now() >= expires_at:
        # status flip only; no version/updated_at bump (permit has its own version
        # but PRD says "carries no effect beyond the status flip itself").
        permit["status"] = "EXPIRED"
    return permit
