"""ConversionProject intake defaults, the derived aggregates of PRD 2.9, the
first-match posture derivation of 3.1 and the explicit recalculation sweep."""

from decimal import Decimal

import clock
import store
from rounding import pct2

ZERO_PCT = pct2(0)


def new_project(fields):
    record = {
        "_type": "ConversionProject",
        "building_address": fields["building_address"],
        "year_built": fields["year_built"],
        "total_unit_count": fields["total_unit_count"],
        "sponsor_user_id": fields["sponsor_user_id"],
        "max_overlapping_remediations": fields["max_overlapping_remediations"],
        "status": "FEASIBILITY",
        "posture": "RESTRICTED",
        "suitability_gate": "UNEVALUATED",
        "suitability_score": ZERO_PCT,
        "included_unit_count": 0,
        "escrow_deposits_received_cents": 0,
        "escrow_balance_cents": 0,
        "escrow_refunded_cents": 0,
        "escrow_disbursed_cents": 0,
        "relocation_obligation_accrued_cents": 0,
        "relocation_paid_cents": 0,
        "relocation_reversed_cents": 0,
        "warranty_reserve_charge_cents": 0,
        "relocation_outstanding_cents": 0,
        "escrow_reconciliation_delta_cents": 0,
        "relocation_reconciliation_delta_cents": 0,
        "bp_conservation_total": 0,
        "warrantability_verdict": "UNEVALUATED",
        "warrantability_verdict_closed_basis": "UNEVALUATED",
        "owner_occupancy_pct_contract_basis": ZERO_PCT,
        "investor_concentration_pct_contract_basis": ZERO_PCT,
        "owner_occupancy_pct_closed_basis": ZERO_PCT,
        "investor_concentration_pct_closed_basis": ZERO_PCT,
        "single_investor_max_pct": ZERO_PCT,
        "presale_sold_pct": ZERO_PCT,
        "declaration_recorded_at": None,
        "warranty_start_at": None,
        "last_posture_recalculated_at": None,
    }
    return store.new_record(store.projects, record)


def sync(project):
    """Recompute every derived aggregate from the current graph.  The three
    conserved identities of section 2.9 are computed by integer subtraction and
    therefore read exactly 0 at the end of every request."""
    project_id = project["id"]
    units = store.project_units(project_id)
    included = [u for u in units if u["declaration_status"] == "INCLUDED"]
    agreements = store.project_agreements(project_id)
    households = store.project_households(project_id)
    claims = store.project_claims(project_id)

    balance = sum(a["deposit_cents"] for a in agreements
                  if a["escrow_status"] == "FUNDED")
    refunded = sum(a["deposit_cents"] for a in agreements
                   if a["escrow_status"] == "REFUNDED")
    disbursed = sum(a["deposit_cents"] for a in agreements
                    if a["escrow_status"] == "DISBURSED")
    paid = sum(h["relocation_paid_cents"] for h in households)
    reversed_cents = sum(h["relocation_reversed_cents"] for h in households)
    outstanding = sum(h["relocation_assistance_cents"] for h in households
                      if h["relocation_status"] == "ACCRUED")

    computed = {
        "included_unit_count": len(included),
        "bp_conservation_total": sum(u["percentage_interest_bp"]
                                     for u in included),
        "escrow_balance_cents": balance,
        "escrow_refunded_cents": refunded,
        "escrow_disbursed_cents": disbursed,
        "escrow_reconciliation_delta_cents":
            project["escrow_deposits_received_cents"]
            - (balance + refunded + disbursed),
        "relocation_paid_cents": paid,
        "relocation_reversed_cents": reversed_cents,
        "relocation_outstanding_cents": outstanding,
        "relocation_reconciliation_delta_cents":
            project["relocation_obligation_accrued_cents"]
            - (paid + reversed_cents + outstanding),
        "warranty_reserve_charge_cents":
            sum(c["accrued_charge_cents"] for c in claims),
    }
    changed = any(project[key] != value for key, value in computed.items())
    project.update(computed)
    if changed:
        store.touch(project)
    return changed


def derive_posture(project):
    """First-match, top-down: the first branch that matches wins outright."""
    project_id = project["id"]
    reports = store.project_reports(project_id)
    if project["suitability_gate"] == "FAILED":
        return "FROZEN"
    if any(r["status"] == "REVISION_REQUESTED" for r in reports):
        return "FROZEN"

    package = store.project_package(project_id)
    statement = store.project_statement(project_id)
    households = store.project_households(project_id)
    batches = store.project_batches(project_id)
    if project["suitability_gate"] == "UNEVALUATED":
        return "RESTRICTED"
    if package is None or package["status"] != "RECORDED":
        return "RESTRICTED"
    if statement is None or statement["status"] != "EFFECTIVE":
        return "RESTRICTED"
    if any(b["status"] == "THRESHOLD_SHORT" for b in batches):
        return "RESTRICTED"
    if any(h["notice_status"] == "HOLDOVER" for h in households):
        return "RESTRICTED"
    for household in households:
        if (household["relocation_status"] == "ACCRUED"
                and household["rofr_status"] in ("WAIVED", "EXPIRED")):
            return "RESTRICTED"
    if project["escrow_reconciliation_delta_cents"] != 0:
        return "RESTRICTED"
    if project["relocation_reconciliation_delta_cents"] != 0:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(project, force=False):
    """Fire whichever of the five posture transitions the derivation selects.
    Each writes `posture`, stamps `last_posture_recalculated_at` and bumps the
    project's version; an explicit recalculation stamps unconditionally."""
    derived = derive_posture(project)
    if derived != project["posture"]:
        project["posture"] = derived
        project["last_posture_recalculated_at"] = clock.now()
        store.touch(project)
    elif force:
        project["last_posture_recalculated_at"] = clock.now()
        store.touch(project)
    return project["posture"]


def posture_recalculation(project):
    """The four pinned steps of the posture recalculation sweep (PRD 3.1).

    Advancing the clock fires nothing by itself; the expiries below are only
    realised when this sweep runs, and each swept child bumps its own version.
    """
    now = clock.now()
    project_id = project["id"]

    # Step one: vacate deadlines that have been reached, inclusively.
    for household in store.project_households(project_id):
        if (household["notice_status"] == "NOTICE_SERVED"
                and household["vacate_deadline_at"] is not None
                and now >= household["vacate_deadline_at"]):
            household["notice_status"] = "VACATE_DUE"
            store.touch(household)

    # Step two: right-of-first-refusal offers strictly past their expiry.
    for household in store.project_households(project_id):
        if (household["rofr_status"] == "OFFERED"
                and household["rofr_expires_at"] is not None
                and now > household["rofr_expires_at"]):
            household["rofr_status"] = "EXPIRED"
            store.touch(household)

    # Step three: remediated claims whose warranty has strictly expired.
    for claim in store.project_claims(project_id):
        if (claim["status"] == "REMEDIATED"
                and claim["warranty_expires_at"] is not None
                and now > claim["warranty_expires_at"]):
            claim["status"] = "CLOSED"
            store.touch(claim)

    # Step four: the first-match posture evaluation itself.
    sync(project)
    recompute_posture(project, force=True)
    return project
