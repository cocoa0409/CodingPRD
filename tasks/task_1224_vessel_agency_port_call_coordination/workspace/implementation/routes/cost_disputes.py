"""CostDispute endpoints: raise, review ladder, escalation, resolution."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import is_int, new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("cost_disputes", __name__)


def _get_or_404(did):
    ent = domain.get("cost_disputes", did)
    if ent is None:
        not_found("cost dispute")
    return ent


def _apply_credit(dispute):
    """Credit mechanics shared by uphold and resolve-ACCEPT."""
    da = domain.get("disbursement_accounts", dispute["da_id"])
    if da is None:
        return
    if dispute["da_line_id"]:
        line = domain.get("da_lines", dispute["da_line_id"])
        if line is not None:
            line["actual_cents"] = max(0, (line["actual_cents"] or 0) - dispute["amount_cents"])
            line["status"] = "ACTUALIZED"
            touch(line)
    else:
        new_entity("da_lines", {
            "da_id": da["id"],
            "category": "SUNDRY",
            "description": "Dispute credit %s" % dispute["id"],
            "estimated_cents": 0,
            "actual_cents": -dispute["amount_cents"],
            "status": "ACTUALIZED",
            "source_type": "MANUAL",
            "source_ref": None,
            "tariff_id": None,
        })
    domain.recompute_da_totals(da)


def _restore_line(dispute):
    if dispute["da_line_id"]:
        line = domain.get("da_lines", dispute["da_line_id"])
        if line is not None and line["status"] == "DISPUTED":
            line["status"] = "ACTUALIZED"
            touch(line)


@bp.post("/cost-disputes")
def create_cost_dispute():
    user_id, _ = require_roles(["PrincipalRep"])
    body = request.get_json(silent=True) or {}
    da = None
    da_id = body.get("da_id")
    if isinstance(da_id, str):
        da = domain.get("disbursement_accounts", da_id)
        if da is None:
            not_found("disbursement account")
    line = None
    line_id = body.get("da_line_id")
    if line_id is not None:
        if isinstance(line_id, str):
            line = domain.get("da_lines", line_id)
            if line is None:
                not_found("DA line")
        else:
            invalid_request("da_line_id must be a string")
    # Entity-backed ownership over the account's principal
    if da is not None:
        call = domain.get("port_calls", da["port_call_id"])
        if call is None or call["principal_id"] != user_id:
            raise_err("ERR_NOT_RESOURCE_OWNER", "The account does not belong to the caller's principal")
    if da is not None and da["status"] not in ("FINAL", "DISPUTED"):
        invalid_state("Disputes may only be raised against a FINAL or DISPUTED account")
    amount = body.get("amount_cents")
    if (da is None or not is_int(amount) or amount <= 0
            or not isinstance(body.get("reason"), str) or not body.get("reason")):
        invalid_request("da_id, a positive amount_cents and reason are required")
    ent = new_entity("cost_disputes", {
        "da_id": da_id,
        "da_line_id": line_id,
        "principal_id": user_id,
        "amount_cents": amount,
        "reason": body["reason"],
        "status": "RAISED",
        "resolution_note": None,
    })
    if da["status"] == "FINAL":
        da["status"] = "DISPUTED"
        touch(da)
    if line is not None and line["status"] == "ACTUALIZED":
        line["status"] = "DISPUTED"
        touch(line)
    return ok_object(serialize(ent), status=201)


@bp.get("/cost-disputes")
def list_cost_disputes():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("cost_disputes"))
    for param in ("da_id", "da_line_id", "principal_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [d for d in items if d[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/cost-disputes/<did>")
def get_cost_dispute(did):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(did)))


@bp.post("/cost-disputes/<did>/start-review")
def start_review(did):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] != "RAISED":
        invalid_state("Only a RAISED dispute can enter review")
    ent["status"] = "UNDER_REVIEW"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/cost-disputes/<did>/uphold")
def uphold(did):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] != "UNDER_REVIEW":
        invalid_state("Only an UNDER_REVIEW dispute can be upheld")
    body = request.get_json(silent=True) or {}
    note = body.get("resolution_note")
    if not isinstance(note, str) or not note:
        invalid_request("resolution_note is required")
    ent["resolution_note"] = note
    ent["status"] = "UPHELD"
    touch(ent)
    _apply_credit(ent)
    return ok_object(serialize(ent))


@bp.post("/cost-disputes/<did>/reject")
def reject(did):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] != "UNDER_REVIEW":
        invalid_state("Only an UNDER_REVIEW dispute can be rejected")
    body = request.get_json(silent=True) or {}
    note = body.get("resolution_note")
    if not isinstance(note, str) or not note:
        invalid_request("resolution_note is required")
    ent["resolution_note"] = note
    ent["status"] = "REJECTED"
    touch(ent)
    _restore_line(ent)
    return ok_object(serialize(ent))


@bp.post("/cost-disputes/<did>/escalate")
def escalate(did):
    user_id, _ = require_roles(["PrincipalRep"])
    ent = _get_or_404(did)
    if user_id != ent["principal_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the raising principal can escalate")
    if ent["status"] != "REJECTED":
        invalid_state("Only a REJECTED dispute can be escalated")
    ent["status"] = "ESCALATED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/cost-disputes/<did>/resolve")
def resolve(did):
    require_roles(["AgencyAdmin"])
    ent = _get_or_404(did)
    if ent["status"] != "ESCALATED":
        invalid_state("Only an ESCALATED dispute can be resolved")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    note = body.get("resolution_note")
    if decision not in ("ACCEPT", "REJECT") or not isinstance(note, str) or not note:
        invalid_request("decision (ACCEPT or REJECT) and resolution_note are required")
    ent["resolution_note"] = note
    if decision == "ACCEPT":
        ent["status"] = "RESOLVED_ACCEPTED"
        touch(ent)
        _apply_credit(ent)
    else:
        ent["status"] = "RESOLVED_REJECTED"
        touch(ent)
        _restore_line(ent)
    return ok_object(serialize(ent))
