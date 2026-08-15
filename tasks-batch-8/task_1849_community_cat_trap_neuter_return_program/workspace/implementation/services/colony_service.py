"""Colony derived fields (PRD §2.6, calculation colony_sterilization_rate).

sterilized_pct: fraction of resident cats whose status is RETURNED or
COLONY_STERILIZED, rounded half-up to 4 decimal places; 0 when the colony has
no resident cats. Residents are cats in AT_LARGE, TRAPPED, AT_CLINIC,
POST_SURGERY, RETURNED, COLONY_STERILIZED, IN_FOSTER or ADOPTION_PIPELINE;
ADOPTED and DECEASED cats leave the resident set entirely.

monitoring_status: STABLE when sterilized_pct >= 0.75 and no complaint stands
OPEN; WATCH at the same threshold with at least one OPEN complaint; ACTIVE
otherwise. Only OPEN complaints participate.

Recomputation is itself a mutation of the colony: updated_at is refreshed and
version increments even when the numbers do not change.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import touch

RESIDENT_STATUSES = {
    "AT_LARGE", "TRAPPED", "AT_CLINIC", "POST_SURGERY", "RETURNED",
    "COLONY_STERILIZED", "IN_FOSTER", "ADOPTION_PIPELINE",
}
STERILIZED_STATUSES = {"RETURNED", "COLONY_STERILIZED"}
STABLE_THRESHOLD = Decimal("0.75")


def compute_sterilized_pct(colony_id):
    residents = [c for c in db.cats.values()
                 if c["colony_id"] == colony_id and c["status"] in RESIDENT_STATUSES]
    if not residents:
        return Decimal("0")
    sterilized = sum(1 for c in residents if c["status"] in STERILIZED_STATUSES)
    pct = (Decimal(sterilized) / Decimal(len(residents))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return pct


def has_open_complaint(colony_id):
    return any(c["colony_id"] == colony_id and c["status"] == "OPEN"
               for c in db.complaints.values())


def recompute_colony(colony):
    """Recompute the derived fields and record the recomputation mutation."""
    pct = compute_sterilized_pct(colony["id"])
    colony["sterilized_pct"] = float(pct)
    if pct >= STABLE_THRESHOLD:
        colony["monitoring_status"] = ("WATCH" if has_open_complaint(colony["id"])
                                       else "STABLE")
    else:
        colony["monitoring_status"] = "ACTIVE"
    touch(colony)
