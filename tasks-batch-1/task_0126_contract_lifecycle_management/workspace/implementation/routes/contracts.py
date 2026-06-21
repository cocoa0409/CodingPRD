"""Contract endpoints and contract-scoped sub-resource lists
(PRD §3.2, §3.5, §3.7, §3.8)."""

from flask import Blueprint, g, request

from common import (bump, get_json_body, optional_bool, optional_int,
                    parse_pagination, paginate, require_field, require_int,
                    serialize, stamp_new)
from db import db
from errors import (contract_not_found, deviation_required, invalid_request,
                    invalid_state, no_version, open_breach, reference_not_found,
                    renewal_not_due, signers_incomplete, stale_version,
                    validation_range)
from middleware import require_roles
from response import success_list, success_object
from services.audit import append_audit
from services.calc import compute_risk_score, review_cost_cents
from services.clock import renew_contract
from services.contract_logic import (current_version, open_workflow,
                                      recompute_risk, supersede_on_new_version)

bp = Blueprint("contracts", __name__)

PARTY_ENUM = {"INTERNAL", "COUNTERPARTY"}


# --- Helpers -----------------------------------------------------------------
def _get_contract_or_404(cid):
    contract = db.contracts.get(cid)
    if not contract:
        raise contract_not_found("Contract not found.")
    return contract


def _require_occ_field(body):
    """Presence + type of expected_contract_version (priority 5 shape check).

    A missing/wrong-typed guard is an ERR_INVALID_REQUEST, which sorts before the
    value-mismatch OCC check (ERR_STALE_VERSION, priority 16). Returns the value.
    """
    if "expected_contract_version" not in body or body["expected_contract_version"] is None:
        raise invalid_request("expected_contract_version is required.")
    expected = body["expected_contract_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_contract_version must be an integer.")
    return expected


def _verify_occ(contract, expected):
    """Value-mismatch OCC check (priority 16, ERR_STALE_VERSION / 412)."""
    if expected != contract.get("version"):
        raise stale_version("expected_contract_version does not match the contract version.")


def _check_occ(contract, body):
    """Combined presence+value OCC check (PRD §2.7), for write paths where no
    other priority-7..15 check interleaves between them."""
    _verify_occ(contract, _require_occ_field(body))


# --- Create / read / list ----------------------------------------------------
@bp.route("/contracts", methods=["POST"])
@require_roles("ContractManager")
def create_contract():
    body = get_json_body()
    org_id = require_field(body, "organization_id", types=str)
    template_id = require_field(body, "contract_template_id", types=str)
    counterparty_name = require_field(body, "counterparty_name", types=str)
    title = require_field(body, "title", types=str)
    term_months = optional_int(body, "term_months", default=None)
    auto_renew = optional_bool(body, "auto_renew", default=None)

    # FK existence + same-organization (priority 4).
    if org_id not in db.organizations:
        raise reference_not_found("organization_id does not reference an organization.")
    template = db.contract_templates.get(template_id)
    if not template or template.get("organization_id") != org_id:
        raise reference_not_found(
            "contract_template_id does not reference a template of this organization.")

    # Range check (priority 5): term_months > 0 when supplied.
    if term_months is not None and term_months <= 0:
        raise validation_range("term_months must be > 0.")

    # Default term_months / auto_renew from the template when omitted.
    if term_months is None:
        term_months = int(template.get("default_term_months", 12))
    if auto_renew is None:
        auto_renew = bool(template.get("auto_renew_default", False))

    contract = {
        "organization_id": org_id,
        "contract_template_id": template_id,
        "counterparty_name": counterparty_name,
        "title": title,
        "term_months": term_months,
        "auto_renew": auto_renew,
        "effective_date": None,
        "expiry_date": None,
        "current_version_id": None,
        "drafter_user_id": g.user_id,
        "risk_score": 0,
        "renewal_cycle_index": 0,
        "status": "DRAFT",
    }
    stamp_new(contract)
    db.contracts[contract["id"]] = contract
    append_audit(contract["id"], "CONTRACT_CREATED", actor_user_id=g.user_id,
                 detail="Contract created in DRAFT.")
    return success_object(serialize(contract), status=201)


@bp.route("/contracts/<cid>", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer", "ClauseLibrarian")
def get_contract(cid):
    contract = _get_contract_or_404(cid)
    return success_object(serialize(contract), status=200)


@bp.route("/contracts", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_contracts():
    limit, offset = parse_pagination()
    rows = list(db.contracts.values())

    org_id = request.args.get("organization_id")
    template_id = request.args.get("contract_template_id")
    current_version_id = request.args.get("current_version_id")
    status = request.args.get("status")

    if org_id is not None:
        rows = [r for r in rows if r.get("organization_id") == org_id]
    if template_id is not None:
        rows = [r for r in rows if r.get("contract_template_id") == template_id]
    if current_version_id is not None:
        rows = [r for r in rows if r.get("current_version_id") == current_version_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]

    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


# --- Versions ----------------------------------------------------------------
@bp.route("/contracts/<cid>/versions", methods=["POST"])
@require_roles("ContractManager")
def create_version(cid):
    contract = _get_contract_or_404(cid)
    body = get_json_body()

    authored_by_party = require_field(body, "authored_by_party", types=str,
                                      enum=PARTY_ENUM)
    clauses = require_field(body, "clauses", types=list)

    # Validate clause shapes (priority 5).
    for clause in clauses:
        if not isinstance(clause, dict):
            raise invalid_request("Each clause must be an object.")
        if not isinstance(clause.get("clause_template_id"), str):
            raise invalid_request("clause.clause_template_id must be a string.")
        if not isinstance(clause.get("text"), str):
            raise invalid_request("clause.text must be a string.")
        if not isinstance(clause.get("is_deviation"), bool):
            raise invalid_request("clause.is_deviation must be a boolean.")

    # Presence/type of the OCC guard is a shape check (priority 5); a missing
    # guard is ERR_INVALID_REQUEST. The value-mismatch (priority 16) runs later.
    expected_version = _require_occ_field(body)

    # State (priority 6): a new version is only defined from DRAFT/UNDER_REVIEW/REDLINING.
    if contract.get("status") not in ("DRAFT", "UNDER_REVIEW", "REDLINING"):
        raise invalid_state("Cannot create a version from this contract state.")

    # Business referential (priority 7): each clause_template_id must reference an
    # ACTIVE clause of the contract's organization.
    for clause in clauses:
        ct = db.clause_templates.get(clause["clause_template_id"])
        if (
            not ct
            or ct.get("organization_id") != contract.get("organization_id")
            or ct.get("status") != "ACTIVE"
        ):
            raise reference_not_found(
                "A clause references a non-ACTIVE or out-of-organization clause template.")

    # OCC value mismatch (priority 16).
    _verify_occ(contract, expected_version)

    was_under_review = contract.get("status") == "UNDER_REVIEW"
    prior_version_id = contract.get("current_version_id")

    # Assign version_number = max existing for this contract + 1.
    existing = [v for v in db.contract_versions.values()
                if v.get("contract_id") == cid]
    next_number = (max((v.get("version_number", 0) for v in existing), default=0)) + 1

    authored_by_user_id = g.user_id if authored_by_party == "INTERNAL" else None
    deviation_count = sum(1 for c in clauses if c.get("is_deviation"))

    version = {
        "contract_id": cid,
        "version_number": next_number,
        "authored_by_party": authored_by_party,
        "authored_by_user_id": authored_by_user_id,
        "clauses": [dict(c) for c in clauses],
        "deviation_count": deviation_count,
        "status": "PROPOSED",
    }
    stamp_new(version)
    db.contract_versions[version["id"]] = version

    # Redline cascade if the contract was UNDER_REVIEW (PRD §3.2).
    if was_under_review:
        supersede_on_new_version(contract, prior_version_id)
        contract["status"] = "REDLINING"

    contract["current_version_id"] = version["id"]
    recompute_risk(contract, final=False)  # provisional

    append_audit(cid, "VERSION_CREATED", actor_user_id=g.user_id,
                 detail="New contract version created.")
    if was_under_review:
        append_audit(cid, "REDLINE_OPENED", actor_user_id=g.user_id,
                     detail="Redline opened during review.")

    bump(contract)
    return success_object(serialize(version), status=201)


@bp.route("/contracts/<cid>/versions", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_versions(cid):
    _get_contract_or_404(cid)
    limit, offset = parse_pagination()
    rows = [v for v in db.contract_versions.values() if v.get("contract_id") == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


# --- Submit ------------------------------------------------------------------
@bp.route("/contracts/<cid>/submit", methods=["POST"])
@require_roles("ContractManager")
def submit_contract(cid):
    contract = _get_contract_or_404(cid)
    body = get_json_body()

    required_approver_count = optional_int(body, "required_approver_count", default=1)

    # State: submit is defined from DRAFT or REDLINING.
    if contract.get("status") not in ("DRAFT", "REDLINING"):
        raise invalid_state("Submit is only valid from DRAFT or REDLINING.")

    # ERR_NO_VERSION before OCC? Per §1.2 preconditions order: current_version
    # checked first, then OCC. (§3.2 lists no-version then expected_contract_version.)
    if not contract.get("current_version_id"):
        raise no_version("Contract has no current version to submit.")

    # OCC (priority 16).
    _check_occ(contract, body)

    if required_approver_count < 1:
        raise validation_range("required_approver_count must be >= 1.")

    workflow = {
        "contract_id": cid,
        "pinned_version_id": contract.get("current_version_id"),
        "required_approver_count": required_approver_count,
        "approvals_received": 0,
        "status": "PENDING",
    }
    stamp_new(workflow)
    db.approval_workflows[workflow["id"]] = workflow

    contract["status"] = "UNDER_REVIEW"
    recompute_risk(contract, final=False)  # provisional
    append_audit(cid, "SUBMITTED", actor_user_id=g.user_id,
                 detail="Contract submitted for review.")
    bump(contract)
    return success_object(serialize(contract), status=200)


# --- Send for signature ------------------------------------------------------
@bp.route("/contracts/<cid>/send-for-signature", methods=["POST"])
@require_roles("ContractManager")
def send_for_signature(cid):
    contract = _get_contract_or_404(cid)
    body = get_json_body()

    signers = require_field(body, "signers", types=list)
    for s in signers:
        if not isinstance(s, dict):
            raise invalid_request("Each signer must be an object.")
        if s.get("signer_party") not in PARTY_ENUM:
            raise invalid_request("signer.signer_party must be INTERNAL or COUNTERPARTY.")
        if not isinstance(s.get("signer_name"), str):
            raise invalid_request("signer.signer_name must be a string.")

    # State (priority 6): only from APPROVED.
    if contract.get("status") != "APPROVED":
        raise invalid_state("send-for-signature is only valid from APPROVED.")

    # Deviation gate (priority 12) before signer gate (priority 13) before OCC.
    org = db.organizations.get(contract.get("organization_id"))
    threshold = int(org.get("risk_appetite_threshold")) if org else 60
    if contract.get("risk_score", 0) >= threshold:
        if not _all_deviations_cleared(contract):
            raise deviation_required(
                "Risk score at/above threshold and a deviated clause is uncleared.")

    internal = [s for s in signers if s.get("signer_party") == "INTERNAL"]
    counterparty = [s for s in signers if s.get("signer_party") == "COUNTERPARTY"]
    if not internal or not counterparty:
        raise signers_incomplete(
            "Signer list must contain at least one INTERNAL and one COUNTERPARTY.")

    # OCC (priority 16).
    _check_occ(contract, body)

    for s in signers:
        sr = {
            "contract_id": cid,
            "signer_party": s["signer_party"],
            "signer_name": s["signer_name"],
            "signed_at": None,
            "status": "SENT",
        }
        stamp_new(sr)
        db.signature_requests[sr["id"]] = sr

    contract["status"] = "OUT_FOR_SIGNATURE"
    append_audit(cid, "SENT_FOR_SIGNATURE", actor_user_id=g.user_id,
                 detail="Contract sent for signature.")
    bump(contract)
    return success_object(serialize(contract), status=200)


def _all_deviations_cleared(contract):
    """Every clause template deviated in the current version has a GRANTED
    DeviationApproval pinned to current_version_id (PRD §3.5)."""
    version = current_version(contract)
    if version is None:
        return True
    deviated_ct_ids = {c.get("clause_template_id")
                       for c in (version.get("clauses") or [])
                       if c.get("is_deviation")}
    if not deviated_ct_ids:
        return True
    for ct_id in deviated_ct_ids:
        granted = any(
            d.get("contract_id") == contract.get("id")
            and d.get("status") == "GRANTED"
            and d.get("clause_template_id") == ct_id
            and d.get("contract_version_id") == contract.get("current_version_id")
            for d in db.deviation_approvals.values()
        )
        if not granted:
            return False
    return True


# --- Renew -------------------------------------------------------------------
@bp.route("/contracts/<cid>/renew", methods=["POST"])
@require_roles("ContractManager")
def renew(cid):
    contract = _get_contract_or_404(cid)
    body = get_json_body()

    # State (priority 6): renew self-loop is only defined from ACTIVE.
    if contract.get("status") != "ACTIVE":
        raise invalid_state("Renew is only valid for an ACTIVE contract.")

    # OCC (priority 16).
    _check_occ(contract, body)

    # Temporal (priority 11): a DUE renewal alert must exist.
    has_due = any(
        a.get("contract_id") == cid and a.get("status") == "DUE"
        for a in db.renewal_alerts.values()
    )
    if not has_due:
        raise renewal_not_due("No renewal alert is DUE for this contract.")

    # Business constraint (priority 14): no obligation may be BREACHED.
    for ob in db.obligations.values():
        if ob.get("contract_id") == cid and ob.get("status") == "BREACHED":
            raise open_breach("Contract has a breached obligation; cannot renew.")

    renew_contract(contract)
    return success_object(serialize(contract), status=200)


# --- Terminate ---------------------------------------------------------------
@bp.route("/contracts/<cid>/terminate", methods=["POST"])
@require_roles("ContractManager")
def terminate(cid):
    contract = _get_contract_or_404(cid)
    body = get_json_body()

    if contract.get("status") != "ACTIVE":
        raise invalid_state("Terminate is only valid for an ACTIVE contract.")

    _check_occ(contract, body)

    for ob in db.obligations.values():
        if ob.get("contract_id") == cid and ob.get("status") == "OPEN":
            ob["status"] = "WAIVED"
            bump(ob)

    for alert in db.renewal_alerts.values():
        if alert.get("contract_id") == cid and alert.get("status") in ("SCHEDULED", "DUE"):
            alert["status"] = "CANCELLED"
            bump(alert)

    contract["status"] = "TERMINATED"
    append_audit(cid, "TERMINATED", actor_user_id=g.user_id,
                 detail="Contract terminated.")
    bump(contract)
    return success_object(serialize(contract), status=200)


# --- Cancel ------------------------------------------------------------------
@bp.route("/contracts/<cid>/cancel", methods=["POST"])
@require_roles("ContractManager")
def cancel(cid):
    contract = _get_contract_or_404(cid)
    body = get_json_body()

    if contract.get("status") not in ("DRAFT", "REDLINING"):
        raise invalid_state("Cancel is only valid from DRAFT or REDLINING.")

    _check_occ(contract, body)

    was_redlining = contract.get("status") == "REDLINING"
    if was_redlining:
        wf = open_workflow(contract)
        if wf is not None:
            wf["status"] = "VOIDED"
            bump(wf)

    contract["status"] = "CANCELLED"
    bump(contract)
    return success_object(serialize(contract), status=200)


# --- Cost estimate -----------------------------------------------------------
@bp.route("/contracts/<cid>/cost-estimate", methods=["GET"])
@require_roles("ContractManager", "RiskOfficer")
def cost_estimate(cid):
    contract = _get_contract_or_404(cid)
    version = current_version(contract)
    deviation_count = int(version.get("deviation_count", 0)) if version else 0
    data = {
        "contract_id": cid,
        "deviation_count": deviation_count,
        "review_cost_cents": review_cost_cents(deviation_count),
    }
    return success_object(data, status=200)


# --- Contract-scoped sub-resource lists --------------------------------------
@bp.route("/contracts/<cid>/approval-workflows", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_contract_workflows(cid):
    _get_contract_or_404(cid)
    limit, offset = parse_pagination()
    rows = [w for w in db.approval_workflows.values() if w.get("contract_id") == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/contracts/<cid>/signature-requests", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_contract_signature_requests(cid):
    _get_contract_or_404(cid)
    limit, offset = parse_pagination()
    rows = [s for s in db.signature_requests.values() if s.get("contract_id") == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/contracts/<cid>/renewal-alerts", methods=["GET"])
@require_roles("ContractManager", "RiskOfficer")
def list_contract_renewal_alerts(cid):
    _get_contract_or_404(cid)
    limit, offset = parse_pagination()
    rows = [a for a in db.renewal_alerts.values() if a.get("contract_id") == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/contracts/<cid>/audit-events", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def list_contract_audit_events(cid):
    _get_contract_or_404(cid)
    limit, offset = parse_pagination()
    rows = [a for a in db.audit_events.values() if a.get("contract_id") == cid]
    event_type = request.args.get("event_type")
    if event_type is not None:
        rows = [r for r in rows if r.get("event_type") == event_type]
    page, total = paginate(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)
