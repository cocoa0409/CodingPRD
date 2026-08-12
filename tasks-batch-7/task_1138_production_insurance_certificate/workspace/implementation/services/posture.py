"""Coverage posture derivation (PRD section 3.4 / scaffold production_posture_derive).

Runs after every mutation on Production, Policy, CastEndorsement,
ClearanceItem, Claim, CompletionBond, or CastMember. Evaluation order is
fixed by the spec.
"""

from flask import g

from db import db
from util import now, touch

BOUND_STATUSES = ("BOUND", "ENDORSED_PENDING", "ACTIVE")
MANDATORY_CLEARANCE_KINDS = ("SCRIPT", "TITLE", "PERSONAL_RIGHTS")
OPEN_CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "ADJUSTED")


def derive_posture(prod, assume_bond_issued=False):
    """Compute (coverage_posture, posture_reasons) for a production.

    assume_bond_issued: evaluate the ladder as if the production's bond were
    already ISSUED. Used by the bond-issuance gate (PRD section 3.7) so a
    required-but-not-yet-issued bond cannot self-block its own issuance —
    otherwise ISSUED would be unreachable and ERR_BOND_NOT_ISSUED at
    activation unsatisfiable. Other restrictions (open injury claims,
    uncleared mandatory clearances) still gate normally.
    """
    prod_id = prod["id"]

    # step 1: bound lines
    bound_lines = set()
    for pol in db.policies.values():
        if pol["production_id"] == prod_id and pol["status"] in BOUND_STATUSES:
            bound_lines.add(pol["coverage_line"])

    # step 2: required lines
    required_lines = {"GENERAL_LIABILITY", "EQUIPMENT"}
    if prod["production_type"] in ("FEATURE", "EPISODIC"):
        required_lines.add("CAST")

    # step 3: missing lines
    missing_lines = required_lines - bound_lines

    # step 4: open injury claims
    open_injury = 0
    for cl in db.claims.values():
        if (cl["production_id"] == prod_id and cl["claim_type"] == "INJURY"
                and cl["status"] in OPEN_CLAIM_STATUSES):
            open_injury += 1

    # step 5: uncleared mandatory clearances (per kind)
    uncleared_kinds = set()
    for ci in db.clearance_items.values():
        if (ci["production_id"] == prod_id
                and ci["clearance_kind"] in MANDATORY_CLEARANCE_KINDS
                and ci["status"] in ("PENDING", "FLAGGED")):
            uncleared_kinds.add(ci["clearance_kind"])

    # step 6: failed cast exams (endorsement-required members not in good standing)
    failed_members = []
    for cm in db.cast_members.values():
        if (cm["production_id"] == prod_id and cm["endorsement_required"]
                and cm["physical_exam_status"] in ("PENDING", "FAILED", "EXPIRED")):
            failed_members.append(cm["id"])

    # step 7: bond status
    bond_status = None
    if prod["requires_completion_bond"]:
        bond_id = db.bond_by_production.get(prod_id)
        if bond_id is not None:
            bond_status = db.completion_bonds[bond_id]["status"]

    # step 8: the ladder
    bond_not_issued = (
        prod["requires_completion_bond"] and bond_status != "ISSUED"
        and not assume_bond_issued
    )
    if prod["status"] == "CANCELLED":
        posture = "SUSPENDED"
    elif open_injury > 0:
        posture = "RESTRICTED"
    elif len(uncleared_kinds) > 0:
        posture = "RESTRICTED"
    elif bond_not_issued:
        posture = "RESTRICTED"
    elif not missing_lines and len(failed_members) == 0:
        posture = "BOUND_FULL"
    elif not missing_lines and len(failed_members) > 0:
        posture = "BOUND_PARTIAL"
    elif not bound_lines:
        posture = "UNBOUND"
    else:
        posture = "BOUND_PARTIAL"

    # step 9: reasons, sorted lexicographically
    reasons = []
    for line in missing_lines:
        reasons.append("MISSING_LINE_" + line)
    if open_injury > 0:
        reasons.append("OPEN_INJURY_CLAIM")
    for kind in uncleared_kinds:
        reasons.append("MANDATORY_CLEARANCE_OPEN_" + kind)
    for mid in failed_members:
        reasons.append("CAST_EXAM_FAILED_" + mid)
    if bond_not_issued:
        reasons.append("BOND_NOT_ISSUED")
    reasons.sort()

    return posture, reasons


def _touched_set():
    """Per-request set of production ids already version-bumped."""
    if not hasattr(g, "touched_productions"):
        g.touched_productions = set()
    return g.touched_productions


def touch_production_once(prod):
    """Bump the production version at most once per request."""
    seen = _touched_set()
    if prod["id"] not in seen:
        seen.add(prod["id"])
        touch(prod)


def recompute_posture(prod):
    """Recompute posture after a mutation; bump production version if changed."""
    posture, reasons = derive_posture(prod)
    if prod["coverage_posture"] != posture or prod["posture_reasons"] != reasons:
        prod["coverage_posture"] = posture
        prod["posture_reasons"] = reasons
        touch_production_once(prod)


def recompute_all_postures():
    for prod in db.productions.values():
        recompute_posture(prod)
