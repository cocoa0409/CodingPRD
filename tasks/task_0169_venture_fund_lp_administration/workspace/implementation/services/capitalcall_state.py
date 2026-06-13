"""Capital-call state re-evaluation after allocation status changes.

Used by allocation fund/default and by the commitment-default cascade. These
helpers transition the parent call and bump its version/updated_at.
"""
import db
from services import derive


def _allocations_of(call_id):
    return [a for a in db.capital_call_allocations.values() if a["capital_call_id"] == call_id]


def reevaluate_after_default(call):
    """Re-evaluate a call after one of its allocations became DEFAULTED.

    ISSUED -> PARTIALLY_DEFAULTED when >=1 DEFAULTED and >=1 in {PAID, PENDING}.
    ISSUED -> DEFAULTED when every allocation is DEFAULTED.
    """
    if call["status"] != "ISSUED":
        return
    allocs = _allocations_of(call["id"])
    if not allocs:
        return
    statuses = [a["status"] for a in allocs]
    if all(s == "DEFAULTED" for s in statuses):
        call["status"] = "DEFAULTED"
        db.touch(call)
    elif any(s == "DEFAULTED" for s in statuses) and any(
        s in ("PAID", "PENDING") for s in statuses
    ):
        call["status"] = "PARTIALLY_DEFAULTED"
        db.touch(call)


def reevaluate_after_fund(call):
    """Re-evaluate a call after one of its allocations became PAID.

    ISSUED -> SETTLED when every allocation is in {PAID, WAIVED}.
    PARTIALLY_DEFAULTED -> SETTLED when every non-DEFAULTED allocation is in
    {PAID, WAIVED}.
    On SETTLED, funded_amount_cents is recomputed (it is computed at read time,
    so the version bump is what matters here).
    """
    allocs = _allocations_of(call["id"])
    if not allocs:
        return
    statuses = [a["status"] for a in allocs]
    if call["status"] == "ISSUED":
        if all(s in ("PAID", "WAIVED") for s in statuses):
            call["status"] = "SETTLED"
            db.touch(call)
    elif call["status"] == "PARTIALLY_DEFAULTED":
        non_defaulted = [s for s in statuses if s != "DEFAULTED"]
        if non_defaulted and all(s in ("PAID", "WAIVED") for s in non_defaulted):
            call["status"] = "SETTLED"
            db.touch(call)
