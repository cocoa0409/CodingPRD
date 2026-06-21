"""Shared cascade / bubble-up state transitions (PRD §3.2, §3.3, §3.5, §3.6, §3.8)."""
import db
from services import ledger
from services import calculations as calc
from services.common import touch


def unit_has_open_claim(unit_id, exclude_loss_id=None, exclude_pp_id=None):
    """A unit has an open claim if any loss/pp claim on it is DRAFT or UNDER_REVIEW."""
    for c in ledger.loss_claims_of_unit(unit_id):
        if c["id"] == exclude_loss_id:
            continue
        if c["status"] in ("DRAFT", "UNDER_REVIEW"):
            return True
    for c in ledger.pp_claims_of_unit(unit_id):
        if c["id"] == exclude_pp_id:
            continue
        if c["status"] in ("DRAFT", "UNDER_REVIEW"):
            return True
    return False


def settle_unit_if_no_open_claim(unit, exclude_loss_id=None, exclude_pp_id=None):
    """ACTIVE -> SETTLED when no other claim on the unit is DRAFT/UNDER_REVIEW
    (PRD §3.5, §3.6, §3.8)."""
    if unit["status"] != "ACTIVE":
        return
    if not unit_has_open_claim(unit["id"], exclude_loss_id, exclude_pp_id):
        unit["status"] = "SETTLED"
        touch(unit)


def bubble_election_to_reported(election):
    """ELECTED -> REPORTED when every unit under the election is REPORTED (PRD §3.5)."""
    if election["status"] != "ELECTED":
        return
    units = ledger.units_of_election(election["id"])
    if not units:
        return
    if all(u["status"] == "REPORTED" for u in units):
        election["status"] = "REPORTED"
        touch(election)


def cascade_election_to_indemnified(election):
    """REPORTED -> INDEMNIFIED on an approved claim (PRD §3.6, §3.8)."""
    if election["status"] == "REPORTED":
        election["status"] = "INDEMNIFIED"
        touch(election)


def void_election(election, cascade=True):
    """Void one election and run its two-hop cascade (PRD §3.3).

    Hop 1: PENDING units under the election -> VOID.
    Hop 2: the election's EARNED AgentCommission -> CLAWED_BACK
           (clawback_cents = commission_cents).
    Then recompute the owning policy ledger and bump the policy version.
    """
    election["status"] = "VOID"
    touch(election)

    # Hop 1: units PENDING -> VOID
    for u in ledger.units_of_election(election["id"]):
        if u["status"] == "PENDING":
            u["status"] = "VOID"
            touch(u)

    # Hop 2: commission clawback
    for c in ledger.commissions_of_election(election["id"]):
        if c["status"] == "EARNED":
            c["status"] = "CLAWED_BACK"
            c["clawback_cents"] = c["commission_cents"]
            touch(c)

    if cascade:
        policy = ledger.policy_of_election(election)
        if policy is not None:
            ledger.recompute_policy_premium(policy, bump=False)
            ledger.recompute_policy_insured_acres(policy, bump=False)
            touch(policy)
