"""Ladder rungs 12-16: the five ordered custody gates (PRD 2.6).

The gates are coarse postures that pre-empt every ordinary rule below them
within their own declared scope, and the order between them is fixed.  An
animal carrying an active legal AND medical AND behavioural hold whose adoption
someone tries to finalize is rejected with ERR_LEGAL_HOLD_ACTIVE and nothing
else; peeling gates one at a time is the intended operator experience.
"""

from errors import ApiError
from store import DB
import derive

GATE_ERRORS = (
    "ERR_RECORDS_FROZEN",
    "ERR_ANIMAL_OUTCOME_CLOSED",
    "ERR_LEGAL_HOLD_ACTIVE",
    "ERR_MEDICAL_HOLD_ACTIVE",
    "ERR_BEHAVIORAL_HOLD_ACTIVE",
)


def org_of_animal(animal):
    return animal.get("current_organization_id") if animal else None


def gate1_org_id(target=None, animal=None, organization_id=None):
    """Resolve the organization that Gate 1 keys on for a write's target.

    # Adjudication of friction 1: Reading B -- the freeze gate applies to its
    # full declared scope ("every create, update and delete under /rescue"
    # except the freeze toggle and the clock setter), resolving the owning
    # organization through whatever organization-bearing field the target
    # carries, and treating a target with no organization at all as ungated.
    # Reading A (fire only where an organization is reachable THROUGH an animal)
    # would leave a large part of the gate's own declared scope permanently
    # unreachable -- registering a partner commitment, planning a transport run
    # and every run/leg action could never observe ERR_RECORDS_FROZEN even
    # though the organization that owns them is plainly frozen.  Reading B is a
    # strict superset of Reading A's firings and strands nothing, so it keeps
    # the larger number of PRD-declared behaviours reachable.
    #
    # Resolution order: an Animal's own current_organization_id; else the
    # target's animal_id -> that animal's organization; else the target's own
    # organization_id; else origin_organization_id (directly or through the
    # target's parent run).
    """
    if organization_id is not None:
        return organization_id
    if animal is not None:
        return animal.get("current_organization_id")
    if target is None:
        return None
    entity = target.get("_entity")
    if entity == "Animal":
        return target.get("current_organization_id")
    if target.get("animal_id"):
        a = DB.get("Animal", target["animal_id"])
        return a.get("current_organization_id") if a else None
    if target.get("organization_id"):
        return target["organization_id"]
    if target.get("origin_organization_id"):
        return target["origin_organization_id"]
    if entity == "TransportLeg":
        run = DB.get("TransportRun", target.get("transport_run_id"))
        return run.get("origin_organization_id") if run else None
    if entity == "ManifestEntry":
        leg = DB.get("TransportLeg", target.get("transport_leg_id"))
        if leg:
            run = DB.get("TransportRun", leg.get("transport_run_id"))
            return run.get("origin_organization_id") if run else None
    return None


def check_gate1(org_id):
    """Gate 1 -- records freeze.  PRD 2.6: reads are never gated."""
    if not org_id:
        return
    org = DB.get("Organization", org_id)
    if org is not None and org.get("records_freeze_active"):
        raise ApiError("ERR_RECORDS_FROZEN",
                       "The owning organization is under a records freeze.")


def _outcome_closed(animal):
    return animal is not None and animal.get("lifecycle_status") == "OUTCOME_CLOSED"


def check_gate2(animal):
    if _outcome_closed(animal):
        raise ApiError("ERR_ANIMAL_OUTCOME_CLOSED",
                       "The animal's custody is already closed by a standing outcome.")


def check_gate3(animals):
    for a in animals:
        if a is not None and derive.active_holds(a["id"], "LEGAL"):
            raise ApiError("ERR_LEGAL_HOLD_ACTIVE", "An active legal hold restrains this animal.")


def check_gate4(animal):
    if animal is not None and derive.active_holds(animal["id"], "MEDICAL"):
        raise ApiError("ERR_MEDICAL_HOLD_ACTIVE", "An active medical hold restrains this animal.")


def check_gate5(animal):
    if animal is not None and derive.active_holds(animal["id"], "BEHAVIORAL"):
        raise ApiError("ERR_BEHAVIORAL_HOLD_ACTIVE",
                       "An active behavioural hold restrains this animal.")


def run_gates(org_id, animal=None, gate2=False, gate3=False, gate4=False, gate5=False,
              gate3_animals=None):
    """Evaluate the gates in their fixed order, each within its declared scope."""
    check_gate1(org_id)
    if gate2:
        check_gate2(animal)
    if gate3:
        check_gate3(gate3_animals if gate3_animals is not None else [animal])
    if gate4:
        check_gate4(animal)
    if gate5:
        check_gate5(animal)


# ---------------------------------------------------------------------------
#  The eligibility view roll-ups (PRD 3.1)
# ---------------------------------------------------------------------------

def gate_flags(animal):
    org = DB.get("Organization", animal.get("current_organization_id"))
    return {
        "records_freeze_active": bool(org.get("records_freeze_active")) if org else False,
        "outcome_closed": _outcome_closed(animal),
        "legal_hold_active": bool(derive.active_holds(animal["id"], "LEGAL")),
        "medical_hold_active": bool(derive.active_holds(animal["id"], "MEDICAL")),
        "behavioral_hold_active": bool(derive.active_holds(animal["id"], "BEHAVIORAL")),
    }


def _first_firing(flags, scope):
    """The highest-precedence gate in `scope` that is currently firing, following
    the gate order of PRD 2.6; null when nothing blocks."""
    keys = ("records_freeze_active", "outcome_closed", "legal_hold_active",
            "medical_hold_active", "behavioral_hold_active")
    for index, key in enumerate(keys):
        if index in scope and flags[key]:
            return GATE_ERRORS[index]
    return None


def blocked_by(animal):
    flags = gate_flags(animal)
    out = dict(flags)
    # POST /rescue/adoptions is the only operation inside every gate's scope.
    out["adoption_blocked_by"] = _first_firing(flags, (0, 1, 2, 3, 4))
    # Transport writes: freeze, outcome-closed (manifesting) and the legal hold.
    out["transport_blocked_by"] = _first_firing(flags, (0, 1, 2))
    # A foster transfer is outside gate 2's scope but inside gates 1, 3 and 4.
    out["foster_transfer_blocked_by"] = _first_firing(flags, (0, 2, 3))
    return out
