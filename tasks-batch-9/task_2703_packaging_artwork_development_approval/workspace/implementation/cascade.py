"""The three cascades of PRD 2.9 plus the compliance recomputation shared by
verification runs and element waivers."""
import calc
from calc import ELEMENT_INDEX, compliance_score, derive_proof_state
from core import db, now_iso, rows, touch


# ---------------------------------------------------------------- element helpers
def version_checks(version_id):
    return [r for r in rows("element_checks") if r["artwork_version_id"] == version_id]


def current_run_checks(version):
    return [
        r
        for r in version_checks(version["id"])
        if r["check_run_no"] == version["check_run_no"]
    ]


def element_sort_key(row):
    return (ELEMENT_INDEX.get(row["element_code"], 99), row["created_at"], row["_seq"])


def recompute_compliance(version):
    """PRD 3.4: score, failed and waived counts always read the current run only."""
    asset = db.assets[version["artwork_asset_id"]]
    brief = db.briefs[asset["brief_id"]]
    run_rows = current_run_checks(version)
    version["compliance_score"] = compliance_score(run_rows, brief, asset)
    version["failed_element_count"] = len([r for r in run_rows if r["result"] == "FAIL"])
    version["waived_element_count"] = len([r for r in run_rows if r["result"] == "WAIVED"])


# ---------------------------------------------------------------- approval cascade
def cancel_orders_for_version(version_id):
    """Auto-cancellation link of the approval cascade (PRD 3.5)."""
    stamp = now_iso()
    for order in rows("plate_orders"):
        if order["artwork_version_id"] != version_id:
            continue
        if order["status"] != "ORDERED":
            continue
        order["status"] = "CANCELLED"
        order["auto_cancelled"] = True
        order["cancel_reason"] = "SUPERSEDED_BY_NEW_ARTWORK"
        order["cancelled_at"] = stamp
        touch(order)


def approve_version(version, route):
    """Links 3 and 4 of the approval cascade (PRD 3.5)."""
    version["state"] = "APPROVED"
    version["approved_at"] = now_iso()
    snapshot = []
    for claim_id in version["claim_ids"]:
        claim = db.claims.get(claim_id)
        if claim is None:
            continue
        snapshot.append(
            {
                "marketing_claim_id": claim["id"],
                "claim_code": claim["claim_code"],
                "cleared_until_utc": claim.get("cleared_until_utc"),
            }
        )
    version["pinned_claim_snapshot"] = snapshot
    version["requires_reverification"] = route["conditional_count"] > 0
    touch(version)

    asset = db.assets[version["artwork_asset_id"]]
    predecessor_id = asset.get("current_approved_version_id")
    asset["current_approved_version_id"] = version["id"]
    if predecessor_id is None:
        touch(asset)
        return
    asset["obsolescence_state"] = "SUPERSEDE_PENDING"
    touch(asset)
    predecessor = db.versions.get(predecessor_id)
    if predecessor is None:
        return
    predecessor["state"] = "OBSOLETE_PENDING"
    touch(predecessor)
    cancel_orders_for_version(predecessor["id"])


def reject_version(version):
    version["state"] = "REVISION_REQUESTED"
    version["revision_cycle_count"] = version["revision_cycle_count"] + 1
    touch(version)


# ---------------------------------------------------------------- obsolescence completion
def complete_obsolescence(runout):
    """PRD 3.8: a terminal disposition completes the obsolescence chain."""
    version = db.versions.get(runout["obsolete_version_id"])
    if version is not None and version["state"] == "OBSOLETE_PENDING":
        version["state"] = "OBSOLETE"
        version["obsoleted_at"] = now_iso()
        touch(version)
    asset = db.assets.get(runout["artwork_asset_id"])
    if asset is not None and asset["obsolescence_state"] == "SUPERSEDE_PENDING":
        asset["obsolescence_state"] = "SUPERSEDED"
        touch(asset)
    return asset


def unwind_obsolescence(runout):
    """PRD 3.8: a scrap reversal unwinds the obsolescence chain by one step."""
    version = db.versions.get(runout["obsolete_version_id"])
    if version is not None and version["state"] == "OBSOLETE":
        version["state"] = "OBSOLETE_PENDING"
        version["obsoleted_at"] = None
        touch(version)
    asset = db.assets.get(runout["artwork_asset_id"])
    if asset is not None and asset["obsolescence_state"] == "SUPERSEDED":
        asset["obsolescence_state"] = "SUPERSEDE_PENDING"
        touch(asset)
    return asset


# ---------------------------------------------------------------- probation cascade
def flag_proofs_for_recheck(printer_id):
    """Link 4 of the probation cascade (PRD 3.9): already-approved proofs are left alone."""
    for proof in rows("proofs"):
        if proof["printer_id"] != printer_id:
            continue
        if proof["proof_state"] == "PROOF_APPROVED":
            continue
        proof["requires_recheck"] = True
        touch(proof)


def apply_settlement_penalty(printer, escape):
    """Links 2 to 4 of the probation cascade (PRD 3.9)."""
    penalty = calc.performance_penalty(escape["units_affected"], escape["discovered_stage"])
    printer["performance_score"] = calc.apply_penalty(printer["performance_score"], penalty)
    if (
        printer["performance_score"] < calc.PRINTER_PROBATION_SCORE
        and printer["certification_status"] == "CERTIFIED"
    ):
        printer["certification_status"] = "PROBATION"
        touch(printer)
        flag_proofs_for_recheck(printer["id"])
    else:
        touch(printer)
    return penalty


# ---------------------------------------------------------------- proof state
def refresh_proof_state(proof):
    proof["proof_state"] = derive_proof_state(proof)
    touch(proof)
    return proof
