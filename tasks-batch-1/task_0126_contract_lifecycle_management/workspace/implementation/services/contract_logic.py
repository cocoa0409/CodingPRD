"""Contract state-machine transitions, cascades, and bubble-up logic
(PRD §2.5, §3.2–§3.7 / SCAFFOLD §1.2)."""

from common import bump
from db import db
from services.audit import append_audit
from services.calc import compute_risk_score
from util import add_calendar_months, format_iso_millis


# --- Helpers -----------------------------------------------------------------
def current_version(contract):
    vid = contract.get("current_version_id")
    if not vid:
        return None
    return db.contract_versions.get(vid)


def open_workflow(contract):
    """The single PENDING ApprovalWorkflow for the contract, if any."""
    for wf in db.approval_workflows.values():
        if wf.get("contract_id") == contract.get("id") and wf.get("status") == "PENDING":
            return wf
    return None


def recompute_risk(contract, final=False):
    version = current_version(contract)
    contract["risk_score"] = compute_risk_score(contract, version, final=final)


# --- Bubble-up: workflow reaches a decision ----------------------------------
def workflow_reached_approved(workflow, contract):
    """ApprovalWorkflow PENDING -> APPROVED bubbles Contract UNDER_REVIEW -> APPROVED
    (PRD §3.3). Current version -> ACCEPTED; risk_score final; APPROVED audit."""
    workflow["status"] = "APPROVED"
    bump(workflow)

    version = current_version(contract)
    if version is not None:
        version["status"] = "ACCEPTED"
        bump(version)

    contract["status"] = "APPROVED"
    recompute_risk(contract, final=True)
    append_audit(contract["id"], "APPROVED", actor_user_id=None,
                 detail="Approval quorum reached.")
    bump(contract)


def workflow_reached_rejected(workflow, contract):
    """ApprovalWorkflow PENDING -> REJECTED bubbles Contract UNDER_REVIEW -> REDLINING
    (PRD §3.3)."""
    workflow["status"] = "REJECTED"
    bump(workflow)

    contract["status"] = "REDLINING"
    append_audit(contract["id"], "REJECTED", actor_user_id=None,
                 detail="Approval workflow rejected.")
    bump(contract)


# --- Activation (signature join) ---------------------------------------------
def activate_contract(contract):
    """OUT_FOR_SIGNATURE -> ACTIVE when all signatures land (PRD §3.5, §3.6)."""
    now = db.clock
    contract["status"] = "ACTIVE"
    contract["effective_date"] = format_iso_millis(now)
    expiry = add_calendar_months(now, int(contract["term_months"]))
    contract["expiry_date"] = format_iso_millis(expiry)

    _create_renewal_alert(contract, expiry)

    append_audit(contract["id"], "ACTIVATED", actor_user_id=None,
                 detail="All signatures received; contract activated.")
    bump(contract)


def _create_renewal_alert(contract, expiry_dt):
    """Create a SCHEDULED RenewalAlert with trigger_date = expiry - lead_days
    (PRD §3.6, §1.3 renewal_alert_window)."""
    from datetime import timedelta

    from common import stamp_new

    org = db.organizations.get(contract.get("organization_id"))
    lead_days = int(org.get("auto_renew_lead_days")) if org else 30
    trigger = expiry_dt - timedelta(days=lead_days)
    alert = {
        "contract_id": contract["id"],
        "trigger_date": format_iso_millis(trigger),
        "resolution": None,
        "status": "SCHEDULED",
    }
    stamp_new(alert)
    db.renewal_alerts[alert["id"]] = alert
    return alert


# --- Signature decline cascade -----------------------------------------------
def decline_cascade(declined_request, contract):
    """A signer declines: bounce OUT_FOR_SIGNATURE -> REDLINING and void siblings
    still SENT (PRD §3.5)."""
    for sr in db.signature_requests.values():
        if (
            sr.get("contract_id") == contract.get("id")
            and sr.get("id") != declined_request.get("id")
            and sr.get("status") == "SENT"
        ):
            sr["status"] = "VOIDED"
            bump(sr)

    contract["status"] = "REDLINING"
    append_audit(contract["id"], "REJECTED", actor_user_id=None,
                 detail="A signer declined; contract returned to redlining.")
    bump(contract)


# --- Redline open (new version while UNDER_REVIEW) ---------------------------
def supersede_on_new_version(contract, prior_version_id):
    """When a new version is created while UNDER_REVIEW, supersede prior version,
    void the open workflow, and deny stale PENDING deviation approvals (PRD §3.2)."""
    prior = db.contract_versions.get(prior_version_id) if prior_version_id else None
    if prior is not None and prior.get("status") == "PROPOSED":
        prior["status"] = "SUPERSEDED"
        bump(prior)

    wf = open_workflow(contract)
    if wf is not None:
        wf["status"] = "VOIDED"
        bump(wf)

    # Any PENDING deviation approval covering the now-superseded version -> DENIED.
    for dev in db.deviation_approvals.values():
        if (
            dev.get("contract_id") == contract.get("id")
            and dev.get("status") == "PENDING"
            and dev.get("contract_version_id") == prior_version_id
        ):
            dev["status"] = "DENIED"
            append_audit(contract["id"], "DEVIATION_DENIED", actor_user_id=None,
                         detail="Deviation denied: covered version superseded.")
            bump(dev)
