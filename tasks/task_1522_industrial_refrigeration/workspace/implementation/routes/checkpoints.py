"""The global compliance checkpoint (PRD 2.5): four marking passes against
the logical clock, then every facility's posture fields are recomputed --
which in this implementation happens continuously at read time, so the sweep
only needs the marking passes."""
from flask import Blueprint

import envelope
from guards import endpoint
from store import db, touch

bp = Blueprint("checkpoints", __name__)

EMPTY_SCHEMA = (frozenset(), frozenset())


@bp.post("/psm/checkpoints/run")
@endpoint(["ComplianceOfficer"], schema=EMPTY_SCHEMA)
def run_checkpoint(ctx):
    now = db.now()

    # pass 1 -- SCHEDULED inspections whose due_at lies strictly before now
    inspections_marked_overdue = 0
    for inspection in db.inspections.values():
        if inspection["status"] == "SCHEDULED" and inspection["due_at"] < now:
            inspection["status"] = "OVERDUE"
            touch(inspection)
            inspections_marked_overdue += 1

    # pass 2 -- QUALIFIED contractors whose qualified_until lies strictly before now
    contractors_expired = 0
    for contractor in db.contractors.values():
        if (
            contractor["qualification_status"] == "QUALIFIED"
            and contractor["qualified_until"] is not None
            and contractor["qualified_until"] < now
        ):
            contractor["qualification_status"] = "EXPIRED"
            touch(contractor)
            contractors_expired += 1

    # pass 3 -- ISSUED permits whose valid_until has been reached (<= now)
    permits_expired = 0
    for permit in db.hot_work_permits.values():
        if permit["status"] == "ISSUED" and permit["valid_until"] <= now:
            permit["status"] = "EXPIRED"
            touch(permit)
            permits_expired += 1

    # pass 4 -- PENDING notifications whose deadline lies strictly before now
    notifications_marked_overdue = 0
    for leak in db.leak_events.values():
        if (
            leak["notification_status"] == "PENDING"
            and leak["notification_deadline_at"] is not None
            and leak["notification_deadline_at"] < now
        ):
            leak["notification_status"] = "OVERDUE"
            touch(leak)
            notifications_marked_overdue += 1

    return envelope.ok(
        {
            "inspections_marked_overdue": inspections_marked_overdue,
            "contractors_expired": contractors_expired,
            "permits_expired": permits_expired,
            "notifications_marked_overdue": notifications_marked_overdue,
        }
    )
