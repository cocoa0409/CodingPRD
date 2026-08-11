"""Cross-cutting cascades: the contribution ledger, the outcome cascade, the
foster-home recompute and the transport strand chain."""

import calc
import clock
import derive
from store import DB, ordered, touch


# =====================================================================
#  Contribution ledger (PRD 3.9)
# =====================================================================

def draw_contribution(contribution, amount):
    """Raise applied_cents and advance the contribution's own axis."""
    contribution["applied_cents"] += amount
    if contribution["applied_cents"] >= contribution["amount_cents"]:
        contribution["status"] = "FULLY_APPLIED"
    elif contribution["applied_cents"] > 0:
        contribution["status"] = "PARTIALLY_APPLIED"
    touch(contribution)


def restore_contribution(contribution, amount):
    """Return credit on a FEE_ASSESSED adopter return."""
    if amount <= 0:
        return
    contribution["applied_cents"] -= amount
    # PRD 3.9 declares exactly one recovery transition on this axis:
    # "possibly moving a contribution FULLY_APPLIED -> PARTIALLY_APPLIED".
    if contribution["status"] == "FULLY_APPLIED" and contribution["applied_cents"] < contribution["amount_cents"]:
        contribution["status"] = "PARTIALLY_APPLIED"
    touch(contribution)


def release_designated_contributions(animal_id):
    """"Every contribution designated to this animal that still carries
    available_cents greater than zero moves to RELEASED"."""
    for c in ordered(DB.where("Contribution", designated_animal_id=animal_id)):
        if c["status"] not in ("RECEIVED", "PARTIALLY_APPLIED"):
            continue
        residual = derive.available_cents(c)
        if residual <= 0:
            continue
        c["released_cents"] += residual
        c["status"] = "RELEASED"
        touch(c)


# =====================================================================
#  Foster home recompute
# =====================================================================

def recompute_home_and_version(home):
    """PRD 3.4: "each flip in either direction increments the home's version"."""
    if home is None:
        return
    if calc.recompute_home(home):
        touch(home)


# =====================================================================
#  The outcome cascade (PRD 3.9)
# =====================================================================

def write_outcome(animal, outcome_type, counterparty_person_id=None,
                  partner_commitment_id=None, adoption_id=None,
                  foster_to_adopt_placement=None):
    """Create the OutcomeRecord and fire the cascade across four entities."""
    episode = derive.open_episode(animal)
    outcome = DB.insert("OutcomeRecord", {
        "animal_id": animal["id"],
        "intake_record_id": episode["id"] if episode else None,
        "adoption_id": adoption_id,
        "partner_commitment_id": partner_commitment_id,
        "counterparty_person_id": counterparty_person_id,
        "outcome_type": outcome_type,
        "recorded_at": clock.stamp(),      # (c) clock-derived
        "reversed_at": None,
        "reversal_reason": None,
    })

    if episode is not None:
        episode["status"] = "CLOSED"
        touch(episode)

    # Any ACTIVE foster placement for this animal ends.
    for placement in ordered(DB.where("FosterPlacement", animal_id=animal["id"], status="ACTIVE")):
        home = DB.get("FosterHome", placement["foster_home_id"])
        if foster_to_adopt_placement is not None and placement["id"] == foster_to_adopt_placement["id"]:
            placement["status"] = "CONVERTED_TO_ADOPTION"
            placement["end_reason"] = "ADOPTED"
        else:
            placement["status"] = "ENDED"
            placement["end_reason"] = "ANIMAL_OUTCOME_CLOSED"
        placement["ended_at"] = clock.stamp()
        touch(placement)
        animal["current_foster_home_id"] = None
        recompute_home_and_version(home)

    release_designated_contributions(animal["id"])

    animal["lifecycle_status"] = "OUTCOME_CLOSED"
    touch(animal)
    return outcome


def standing_outcome(animal_id):
    """The animal's unreversed outcome record, if any."""
    for o in reversed(ordered(DB.all("OutcomeRecord"))):
        if o["animal_id"] == animal_id and o["reversed_at"] is None:
            return o
    return None


def active_placement_in_home_of(animal_id, person_id):
    """The animal's ACTIVE placement when the given person owns its home."""
    for placement in ordered(DB.where("FosterPlacement", animal_id=animal_id, status="ACTIVE")):
        home = DB.get("FosterHome", placement["foster_home_id"])
        if home is not None and home["person_id"] == person_id:
            return placement
    return None


# =====================================================================
#  Transport cascades (PRD 3.6 / 3.7)
# =====================================================================

def return_partner_slots(run):
    """Hops 5 and 6 of the leg-abort chain, and the same work on a run abort."""
    if run["purpose"] != "TRANSFER_OUT" or run["slots_drawn"] <= 0:
        return
    commitment = DB.get("PartnerCommitment", run.get("partner_commitment_id"))
    returned = run["slots_drawn"]
    run["slots_drawn"] = 0
    if commitment is None:
        return
    commitment["slots_drawn"] -= returned
    commitment["slots_open"] = (commitment["slots_total"] - commitment["slots_drawn"]
                                - commitment["slots_released"])
    if commitment["status"] in ("EXHAUSTED", "PARTIALLY_DRAWN"):
        commitment["status"] = "PARTIALLY_DRAWN" if commitment["slots_drawn"] > 0 else "OPEN"
    touch(commitment)
    # Hop 6: Organization.open_commitment_slots_total is a derived roll-up
    # (PRD 3.7), so it is recomputed on every read of the organization.


def invalidate_scheduled_legs(run):
    for leg in ordered(DB.where("TransportLeg", transport_run_id=run["id"])):
        if leg["status"] != "SCHEDULED":
            continue
        leg["status"] = "INVALIDATED"
        touch(leg)
        for entry in ordered(DB.where("ManifestEntry", transport_leg_id=leg["id"], status="ASSIGNED")):
            entry["status"] = "BUMPED"
            touch(entry)
        calc.recompute_leg(leg)


def abort_run(run, cascade_from_leg=False):
    """PLANNED -> CANCELLED (no slots were ever drawn) or IN_PROGRESS -> ABORTED."""
    if run["status"] == "PLANNED":
        run["status"] = "CANCELLED"
        invalidate_scheduled_legs(run)
        touch(run)
        return run
    run["status"] = "ABORTED"
    run["aborted_at"] = clock.stamp()
    invalidate_scheduled_legs(run)
    return_partner_slots(run)
    touch(run)
    return run


def strand_cascade(leg):
    """The six-hop chain fired by aborting a DEPARTED leg."""
    # Hop 1: the leg itself.
    leg["status"] = "ABORTED"
    touch(leg)
    hub = leg["origin_hub_code"]
    # Hop 2: every LOADED entry on the leg becomes STRANDED.
    for entry in ordered(DB.where("ManifestEntry", transport_leg_id=leg["id"], status="LOADED")):
        entry["status"] = "STRANDED"
        entry["stranded_at_hub_code"] = hub
        touch(entry)
        # Hop 3: the carried animal follows.
        animal = DB.get("Animal", entry["animal_id"])
        if animal is not None and animal["lifecycle_status"] == "IN_TRANSIT":
            animal["lifecycle_status"] = "STRANDED"
            animal["current_hub_code"] = hub
            touch(animal)
    calc.recompute_leg(leg)
    # Hop 4 (and through it hops 5 and 6): the parent run aborts.
    run = DB.get("TransportRun", leg["transport_run_id"])
    if run is not None and run["status"] == "IN_PROGRESS":
        abort_run(run, cascade_from_leg=True)
    return leg
