"""Credit blocks: minting, sign-off, verification, retirement (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import calc
import domain
import response
import store
import validate
from constants import VERIFICATION_VARIANCE_TOLERANCE
from errors import (
    ERR_BATCH_NOT_SHIPPED,
    ERR_INSUFFICIENT_CREDITS,
    ERR_INVALID_CREDIT_BLOCK_STATE,
    ERR_INVALID_PATHWAY_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_NOTHING_TO_REVERSE,
    ERR_PATHWAY_SCOPE_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    fail,
)
from routes.helpers import body_ref, find, listing
from store import bump, q

bp = Blueprint("credits", __name__)
ZERO = Decimal("0")


@bp.post("/credit-blocks")
def create_block():
    validate.auth("ComplianceOfficer")
    data = validate.body()
    batch = body_ref("batch", data, "batch_id")
    pathway = body_ref("pathway", data, "pathway_id")

    run = store.runs.get(batch["run_id"])
    dominant = domain.dominant_feedstock(run) if run is not None else None
    if run is None or pathway["unit_id"] != run["unit_id"] \
            or pathway["feedstock_type"] != dominant:
        fail(ERR_PATHWAY_SCOPE_MISMATCH,
             "The pathway must be scoped to the producing unit and the campaign's "
             "dominant feedstock (%s)." % dominant)

    if batch["distribution_status"] != "SHIPPED":
        fail(ERR_BATCH_NOT_SHIPPED,
             "Credits are minted on transfer; the batch is %s."
             % batch["distribution_status"])

    if pathway["status"] != "REGISTERED":
        fail(ERR_INVALID_PATHWAY_STATE,
             "The cited pathway is %s, not REGISTERED." % pathway["status"])

    provisional_ci = calc.provisional_ci(run["blend_ci_gco2e_per_mj"])
    row = store.new_row()
    row.update({
        "batch_id": batch["id"],
        "pathway_id": pathway["id"],
        "program": pathway["program"],
        "provisional_ci_gco2e_per_mj": provisional_ci,
        "verified_ci_gco2e_per_mj": None,
        "provisional_rin_credits": 0,
        "provisional_credits_mtco2e": q(ZERO, 3),
        "verified_credits_mtco2e": q(ZERO, 3),
        "verified_rin_credits": 0,
        "retired_credits_mtco2e": q(ZERO, 3),
        "verification_outcome": "NONE",
        "verification_findings": None,
        "signed_off_by_user_id": None,
        "status": "DRAFT",
    })
    if pathway["program"] == "RFS":
        row["provisional_rin_credits"] = calc.provisional_rin(
            batch["volume_gal"], batch["product_type"])
    else:
        row["provisional_credits_mtco2e"] = calc.provisional_lcfs(
            batch["volume_gal"], batch["product_type"], provisional_ci)
    store.blocks[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/credit-blocks/<block_id>")
def read_block(block_id):
    validate.auth("ComplianceOfficer", "IndependentVerifier")
    return response.ok(find("block", block_id))


@bp.get("/credit-blocks")
def list_blocks():
    validate.auth("ComplianceOfficer", "IndependentVerifier")
    rows, limit, offset = listing(store.table_rows(store.blocks), {
        "batch_id": "batch_id",
        "pathway_id": "pathway_id",
        "program": "program",
        "status": "status",
    })
    return response.page(rows, limit, offset)


@bp.post("/credit-blocks/<block_id>/internal-signoffs")
def sign_off_block(block_id):
    user_id, _role = validate.auth("ComplianceOfficer")
    block = find("block", block_id)
    if block["status"] != "DRAFT":
        fail(ERR_INVALID_CREDIT_BLOCK_STATE,
             "Only a DRAFT block may be signed off; this one is %s." % block["status"])

    pathway = store.pathways.get(block["pathway_id"])
    if pathway is not None and pathway["registered_by_user_id"] == user_id:
        fail(ERR_SEGREGATION_OF_DUTIES,
             "The officer who registered the pathway may not sign off its credit blocks.")
    if pathway is None or pathway["status"] != "REGISTERED":
        fail(ERR_INVALID_PATHWAY_STATE,
             "The cited pathway is %s, not REGISTERED."
             % (pathway["status"] if pathway else "missing"))

    block["signed_off_by_user_id"] = user_id
    block["status"] = "INTERNAL_SIGNED_OFF"
    bump(block)
    return response.ok(block)


@bp.post("/credit-blocks/<block_id>/verification-submissions")
def submit_block(block_id):
    validate.auth("ComplianceOfficer")
    block = find("block", block_id)
    if block["status"] != "INTERNAL_SIGNED_OFF":
        fail(ERR_INVALID_CREDIT_BLOCK_STATE,
             "Only an INTERNAL_SIGNED_OFF block may be submitted; this one is %s."
             % block["status"])

    batch = store.batches.get(block["batch_id"])
    run = store.runs.get(batch["run_id"]) if batch is not None else None
    if run is None or run["status"] != "RECONCILED":
        fail(ERR_INVALID_RUN_STATE,
             "Verification claims against frozen figures; the campaign is not RECONCILED.")

    block["status"] = "SUBMITTED_FOR_VERIFICATION"
    bump(block)
    return response.ok(block)


def _diverged(provisional, verified):
    if provisional == 0:
        return verified != 0
    relative = abs(Decimal(verified) - Decimal(provisional)) / Decimal(provisional)
    return relative > VERIFICATION_VARIANCE_TOLERANCE


@bp.post("/credit-blocks/<block_id>/verification-decisions")
def decide_verification(block_id):
    validate.auth("IndependentVerifier")
    block = find("block", block_id)
    data = validate.body()
    decision = validate.get_enum(data, "decision", ("VERIFY", "REJECT"))
    verified_ci = None
    findings = None
    if decision == "VERIFY":
        verified_ci = validate.get_num(data, "verified_ci", 0)
    else:
        findings = validate.get_str(data, "findings", 1, 500)

    if block["status"] != "SUBMITTED_FOR_VERIFICATION":
        fail(ERR_INVALID_CREDIT_BLOCK_STATE,
             "Only a SUBMITTED_FOR_VERIFICATION block may be decided; this one is %s."
             % block["status"])

    pathway = store.pathways.get(block["pathway_id"])

    if decision == "REJECT":
        block["verification_findings"] = findings
        block["verification_outcome"] = "REJECTED"
        block["verified_credits_mtco2e"] = q(ZERO, 3)
        block["verified_rin_credits"] = 0
        block["status"] = "VERIFICATION_REJECTED"
        bump(block)
        return response.ok(block)

    batch = store.batches.get(block["batch_id"])
    verified_ci = q(verified_ci, 2)
    block["verified_ci_gco2e_per_mj"] = verified_ci
    if block["program"] == "RFS":
        block["verified_rin_credits"] = calc.verified_rin(
            batch["volume_gal"], batch["product_type"],
            block["provisional_ci_gco2e_per_mj"], verified_ci)
        adjusted = _diverged(block["provisional_rin_credits"],
                             block["verified_rin_credits"])
    else:
        block["verified_credits_mtco2e"] = calc.verified_lcfs(
            batch["volume_gal"], batch["product_type"], verified_ci)
        adjusted = _diverged(block["provisional_credits_mtco2e"],
                             block["verified_credits_mtco2e"])

    outcome = "ADJUSTED" if adjusted else "VERIFIED"
    block["verification_outcome"] = outcome
    block["status"] = outcome
    bump(block)

    if pathway is not None:
        domain.recompute_pathway_credits(pathway)
        bump(pathway)
        if adjusted:
            domain.adjusted_cascade(block, pathway)
    return response.ok(block)


@bp.post("/credit-blocks/<block_id>/retirements")
def retire_credits(block_id):
    validate.auth("ComplianceOfficer")
    block = find("block", block_id)
    data = validate.body()
    credits = validate.get_num(data, "credits", None, None, 3)

    if block["status"] not in ("VERIFIED", "ADJUSTED"):
        fail(ERR_INVALID_CREDIT_BLOCK_STATE,
             "Only a VERIFIED or ADJUSTED block may be retired against; this one is %s."
             % block["status"])

    credits = q(credits, 3)
    remaining = block["verified_credits_mtco2e"] - block["retired_credits_mtco2e"]
    if credits <= ZERO or credits > remaining:
        fail(ERR_INSUFFICIENT_CREDITS,
             "Retirement must be greater than 0 and no greater than the remaining %s."
             % q(remaining, 3))

    block["retired_credits_mtco2e"] = q(block["retired_credits_mtco2e"] + credits, 3)
    if block["retired_credits_mtco2e"] == block["verified_credits_mtco2e"]:
        block["status"] = "RETIRED"
    bump(block)

    pathway = store.pathways.get(block["pathway_id"])
    if pathway is not None:
        domain.recompute_pathway_credits(pathway)
        bump(pathway)
    return response.ok(block)


@bp.post("/credit-blocks/<block_id>/retirement-reversals")
def reverse_retirement(block_id):
    validate.auth("ComplianceOfficer")
    block = find("block", block_id)
    data = validate.body()
    reason = validate.get_str(data, "reason", 1, 500)

    if block["status"] not in ("VERIFIED", "ADJUSTED", "RETIRED"):
        fail(ERR_INVALID_CREDIT_BLOCK_STATE,
             "A block at %s has no retirement to reverse." % block["status"])
    if block["retired_credits_mtco2e"] <= ZERO:
        fail(ERR_NOTHING_TO_REVERSE, "The block holds no retired balance.")

    block["retired_credits_mtco2e"] = q(ZERO, 3)
    block["verification_findings"] = reason
    if block["status"] == "RETIRED":
        block["status"] = block["verification_outcome"]
    bump(block)

    pathway = store.pathways.get(block["pathway_id"])
    if pathway is not None:
        domain.recompute_pathway_credits(pathway)
        bump(pathway)
    return response.ok(block)
