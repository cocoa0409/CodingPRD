"""Department-related computed values."""
from __future__ import annotations

import db


ACTIVE_OFFER_STATUSES = {"PENDING_APPROVAL", "APPROVED", "EXTENDED", "ACCEPTED"}


def compute_committed_offer_cents(department_id: str) -> int:
    """Sum base_salary_cents over active offers on this department's requisitions."""
    # Build set of requisition ids belonging to the department.
    req_ids = {r["id"] for r in db.requisitions.values() if r["department_id"] == department_id}
    total = 0
    for off in db.offers.values():
        if off["status"] not in ACTIVE_OFFER_STATUSES:
            continue
        app = db.applications.get(off["application_id"])
        if not app:
            continue
        if app["requisition_id"] in req_ids:
            total += off["base_salary_cents"]
    return total


def department_of_offer(offer: dict) -> dict | None:
    """Resolve offer -> application -> requisition -> department."""
    app = db.applications.get(offer["application_id"])
    if not app:
        return None
    req = db.requisitions.get(app["requisition_id"])
    if not req:
        return None
    return db.departments.get(req["department_id"])
