"""ComplianceCase endpoints + sanctions-hit reads (PRD §3.5).

Deciding a case bubbles its outcome onto the transfer's compliance_status; a
REJECT of a funded+pending transfer additionally fires the compensating refund
chain to REFUNDED.
"""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import get_user_context, require_role
from services.common import touch, public, get_json, paginate, require_fields
from services import calculations
from services.ledger import execute_refund

bp = Blueprint("compliance", __name__)


def _case_or_404(case_id):
    case = db.compliance_cases.get(case_id)
    if case is None:
        raise err("ERR_NOT_FOUND", "Compliance case not found")
    return case


@bp.route("/compliance-cases/<case_id>", methods=["GET"])
def get_case(case_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer", "RemittanceAgent"})
    return success(public(_case_or_404(case_id)), 200)


@bp.route("/compliance-cases", methods=["GET"])
def list_cases():
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer", "RemittanceAgent"})
    items = list(db.compliance_cases.values())
    tid = request.args.get("transfer_id")
    st = request.args.get("status")
    if tid is not None:
        items = [c for c in items if c["transfer_id"] == tid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, meta = paginate(items)
    return success([public(c) for c in page], 200, pagination=meta)


@bp.route("/compliance-cases/<case_id>/request-info", methods=["POST"])
def request_info(case_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    case = _case_or_404(case_id)
    if case["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "request-info only allowed from OPEN")
    case["status"] = "AWAITING_INFO"
    case["info_request_count"] += 1
    touch(case)
    return success(public(case), 200)


@bp.route("/compliance-cases/<case_id>/provide-info", methods=["POST"])
def provide_info(case_id):
    _, role = get_user_context()
    require_role(role, {"RemittanceAgent"})
    case = _case_or_404(case_id)
    get_json()  # optional note; not persisted on the case
    if case["status"] != "AWAITING_INFO":
        raise err("ERR_INVALID_STATE", "provide-info only allowed from AWAITING_INFO")
    case["status"] = "OPEN"
    touch(case)
    return success(public(case), 200)


@bp.route("/compliance-cases/<case_id>/escalate", methods=["POST"])
def escalate(case_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    case = _case_or_404(case_id)
    if case["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "escalate only allowed from OPEN")
    transfer = db.transfers[case["transfer_id"]]
    if (transfer["sanctions_score"] or 0) < calculations.SANCTIONS_ESCALATE_THRESHOLD:
        raise err("ERR_ESCALATION_NOT_WARRANTED",
                  "Sanctions score is below the escalation threshold")
    case["status"] = "ESCALATED"
    touch(case)
    return success(public(case), 200)


@bp.route("/compliance-cases/<case_id>/decide", methods=["POST"])
def decide(case_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    case = _case_or_404(case_id)
    body = get_json()
    require_fields(body, ["decision", "expected_case_version"])
    decision = body["decision"]
    if decision not in ("CLEAR", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "decision must be CLEAR or REJECT")
    expected = body["expected_case_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_case_version must be an integer")

    # OCC (priority 5) precedes the state-transition check (priority 6).
    if case["version"] != expected:
        raise err("ERR_STALE_VERSION", "Case version has advanced; re-read before deciding")

    # Decision allowed only from OPEN or ESCALATED (priority 6).
    if case["status"] not in ("OPEN", "ESCALATED"):
        raise err("ERR_INVALID_STATE", "decide only allowed from OPEN or ESCALATED")

    transfer = db.transfers[case["transfer_id"]]

    if decision == "CLEAR":
        case["status"] = "CLEARED"
        touch(case)
        transfer["compliance_status"] = "CLEARED"
        touch(transfer)
    else:
        case["status"] = "REJECTED"
        touch(case)
        transfer["compliance_status"] = "REJECTED"
        touch(transfer)
        # Confirmed sanctions match on the SENDER blocks the sender (PRD §3.2:
        # BLOCKED is reached only through a confirmed sanctions match).
        _block_sender_if_sender_hit(transfer)
        # Compensating refund chain: funded + pending delivery -> REFUNDED.
        if (transfer["funding_status"] == "FUNDED"
                and transfer["delivery_status"] == "PENDING"):
            corridor = db.corridors[transfer["corridor_id"]]
            execute_refund(transfer, corridor, "COMPLIANCE_REJECT")

    return success(public(case), 200)


def _block_sender_if_sender_hit(transfer):
    """If the rejected transfer screened a SanctionsHit against its SENDER, the
    confirmed match blocks the sender (Sender.status -> BLOCKED)."""
    for hit in db.sanctions_hits.values():
        if hit["transfer_id"] == transfer["id"] and hit["subject_kind"] == "SENDER":
            sender = db.senders.get(transfer["sender_id"])
            if sender is not None and sender["status"] != "BLOCKED":
                sender["status"] = "BLOCKED"
                touch(sender)
            break


# ---------------------------------------------------------------------------
# SanctionsHit (read-only discovery)
# ---------------------------------------------------------------------------
@bp.route("/sanctions-hits/<hit_id>", methods=["GET"])
def get_hit(hit_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    hit = db.sanctions_hits.get(hit_id)
    if hit is None:
        raise err("ERR_NOT_FOUND", "Sanctions hit not found")
    return success(public(hit), 200)


@bp.route("/sanctions-hits", methods=["GET"])
def list_hits():
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    items = list(db.sanctions_hits.values())
    tid = request.args.get("transfer_id")
    leid = request.args.get("list_entry_id")
    if tid is not None:
        items = [h for h in items if h["transfer_id"] == tid]
    if leid is not None:
        items = [h for h in items if h["list_entry_id"] == leid]
    page, meta = paginate(items)
    return success([public(h) for h in page], 200, pagination=meta)
