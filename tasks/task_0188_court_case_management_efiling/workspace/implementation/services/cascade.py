"""Cross-entity cascades (PRD Section 3 side-effects)."""
import db
from services import domain


def vacate_pending_deadlines(case, deadline_type=None):
    """Move every PENDING deadline under the case to VACATED.

    If deadline_type is given, only vacate deadlines of that type.
    Each vacated deadline gets its own version bump. The caller is
    responsible for the final case recompute / version bump.
    """
    for d in domain.deadlines_for_case(case["id"]):
        if d["status"] != "PENDING":
            continue
        if deadline_type is not None and d["deadline_type"] != deadline_type:
            continue
        d["status"] = "VACATED"
        db.touch(d)


def stay_case(case):
    """System transition OPEN -> STAYED (stay cascade hops 1-3).

    Hop 1: case status OPEN -> STAYED.
    Hop 2: every PENDING deadline -> VACATED.
    Hop 3: posture recomputed to FROZEN (done by bump_case while STAYED).
    Caller bumps the case version once via domain.bump_case afterwards if it
    has not already; here we perform the full stay and bump the case itself.
    """
    case["status"] = "STAYED"
    vacate_pending_deadlines(case)
    domain.bump_case(case)
