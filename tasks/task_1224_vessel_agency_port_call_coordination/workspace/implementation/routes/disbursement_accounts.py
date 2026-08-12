"""DisbursementAccount, DALine, and advance-creation endpoints."""
from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.domain import DA_EDITABLE_STATUSES
from services.serializers import serialize, serialize_many
from utils import is_int, new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("disbursement_accounts", __name__)

LINE_CATEGORIES = {"PORT_DUES", "PILOTAGE", "TOWAGE", "BERTH_HIRE", "PROVISIONS",
                   "BUNKERS", "REPAIRS", "STORES", "CREW_COSTS", "CANCELLATION_FEE",
                   "SUNDRY"}


def _get_or_404(did):
    ent = domain.get("disbursement_accounts", did)
    if ent is None:
        not_found("disbursement account")
    return ent


def _new_da_fields(port_call_id, user_id):
    return {
        "port_call_id": port_call_id,
        "status": "PRO_FORMA",
        "total_estimated_cents": 0,
        "agency_fee_estimated_cents": 0,
        "advance_required_cents": 0,
        "advances_received_cents": 0,
        "advances_applied_cents": 0,
        "advances_refunded_cents": 0,
        "funding_available_cents": 0,
        "total_final_cents": None,
        "agency_fee_final_cents": None,
        "balance_due_cents": None,
        "created_by_user_id": user_id,
        "finalized_by_user_id": None,
    }


@bp.post("/disbursement-accounts")
def create_disbursement_account():
    user_id, _ = require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    if call is not None:
        domain.require_call_editable(call)
        # At most one non-SUPERSEDED account: only a PRO_FORMA one is superseded
        existing = domain.current_da_for_call(pcid)
        if existing is not None and existing["status"] != "PRO_FORMA":
            invalid_state("A non-superseded disbursement account already exists for this call")
    # Stage 12: OCC on the port call version
    expected = body.get("expected_port_call_version")
    if call is not None and expected is not None and expected != call["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_port_call_version does not match the current port call version")
    if call is None or expected is None or not is_int(expected):
        invalid_request("port_call_id and an integer expected_port_call_version are required")
    existing = domain.current_da_for_call(pcid)
    if existing is not None:
        existing["status"] = "SUPERSEDED"
        touch(existing)
    ent = new_entity("disbursement_accounts", _new_da_fields(pcid, user_id))
    domain.seed_port_dues_line(ent, call)
    domain.recompute_da_totals(ent)
    touch(call)  # DA creation bumps the port call version
    return ok_object(serialize(ent), status=201)


@bp.get("/disbursement-accounts")
def list_disbursement_accounts():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("disbursement_accounts"))
    for param in ("port_call_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [d for d in items if d[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/disbursement-accounts/<did>")
def get_disbursement_account(did):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(did)))


@bp.post("/disbursement-accounts/<did>/send")
def send_disbursement_account(did):
    require_roles(["AgencyOps"])
    ent = _get_or_404(did)
    if ent["status"] != "PRO_FORMA":
        invalid_state("Only a PRO_FORMA account can be sent")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None:
        domain.require_call_editable(call)
    ent["status"] = "SENT_TO_PRINCIPAL"
    touch(ent)
    return ok_object(serialize(ent))


@bp.get("/disbursement-accounts/<did>/lines")
def list_da_lines(did):
    require_roles(ANY_ROLE)
    ent = _get_or_404(did)
    items = domain.lines_of_da(ent["id"])
    items = sorted(items, key=lambda l: (l["created_at"], l["category"], l["_seq"]))
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.post("/disbursement-accounts/<did>/lines")
def create_da_line(did):
    require_roles(["AgencyOps", "AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] not in DA_EDITABLE_STATUSES:
        invalid_state("Manual lines may only be added while the account is editable")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None:
        domain.require_call_editable(call)
    body = request.get_json(silent=True) or {}
    if (body.get("category") not in LINE_CATEGORIES
            or not isinstance(body.get("description"), str)
            or not is_int(body.get("estimated_cents")) or body.get("estimated_cents", -1) < 0):
        invalid_request("category, description and a non-negative estimated_cents are required")
    line = new_entity("da_lines", {
        "da_id": ent["id"],
        "category": body["category"],
        "description": body["description"],
        "estimated_cents": body["estimated_cents"],
        "actual_cents": None,
        "status": "ESTIMATED",
        "source_type": "MANUAL",
        "source_ref": None,
        "tariff_id": None,
    })
    domain.recompute_da_totals(ent)
    return ok_object(serialize(line), status=201)


def _actualize_all_lines(da, call):
    for line in domain.lines_of_da(da["id"]):
        if line["status"] != "ESTIMATED":
            continue
        if line["source_type"] == "SERVICE_ORDER":
            ref = (line["source_ref"] or "").split(":", 1)[-1]
            src = domain.get("service_orders", ref)
            line["actual_cents"] = (src["actual_cents"] or 0) if src is not None else 0
            line["status"] = "ACTUALIZED"
            touch(line)
        elif line["source_type"] == "PURCHASE_ORDER":
            ref = (line["source_ref"] or "").split(":", 1)[-1]
            src = domain.get("purchase_orders", ref)
            line["actual_cents"] = (src["invoiced_cents"] or 0) if src is not None else 0
            line["status"] = "ACTUALIZED"
            touch(line)
        elif line["source_type"] == "TARIFF" and line["category"] == "PORT_DUES":
            # Keeps the value computed at sailing when present; otherwise price now
            if call["actual_arrival_at"] is not None and call["actual_sailed_at"] is not None:
                tariff = domain.published_tariff(call["port_code"], "PORT_DUES")
                if tariff is None:
                    tariff = domain.get("tariffs", line["tariff_id"])
                if tariff is not None:
                    line["actual_cents"] = domain.port_dues_final(tariff, call)
                    line["status"] = "ACTUALIZED"
                    touch(line)
                else:
                    line["actual_cents"] = line["estimated_cents"]
                    line["status"] = "ACTUALIZED"
                    touch(line)
            else:
                line["actual_cents"] = line["estimated_cents"]
                line["status"] = "ACTUALIZED"
                touch(line)
        else:  # MANUAL lines carry their estimate forward
            line["actual_cents"] = line["estimated_cents"]
            line["status"] = "ACTUALIZED"
            touch(line)


@bp.post("/disbursement-accounts/<did>/finalize")
def finalize_disbursement_account(did):
    user_id, _ = require_roles(["AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] not in ("SENT_TO_PRINCIPAL", "FUNDED"):
        invalid_state("Only a SENT_TO_PRINCIPAL or FUNDED account can be finalized")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is None or call["ops_status"] != "SAILED":
        raise_err("ERR_PORT_CALL_NOT_SAILED", "The port call must be SAILED before finalization")
    if user_id == ent["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "The account creator cannot finalize it")
    _actualize_all_lines(ent, call)
    domain.recompute_da_final(ent)
    ent["finalized_by_user_id"] = user_id
    ent["status"] = "FINAL"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/disbursement-accounts/<did>/refinalize")
def refinalize_disbursement_account(did):
    user_id, _ = require_roles(["AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] != "DISPUTED":
        invalid_state("Only a DISPUTED account can be refinalized")
    if user_id == ent["created_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "The account creator cannot refinalize it")
    for dispute in domain.all_of("cost_disputes"):
        if (dispute["da_id"] == ent["id"]
                and dispute["status"] in ("RAISED", "UNDER_REVIEW", "ESCALATED")):
            raise_err("ERR_DISPUTES_OPEN", "Open disputes block refinalization")
    domain.recompute_da_final(ent)
    ent["finalized_by_user_id"] = user_id
    ent["status"] = "FINAL"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/disbursement-accounts/<did>/settle")
def settle_disbursement_account(did):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(did)
    if ent["status"] != "FINAL":
        invalid_state("Only a FINAL account can be settled")
    for adv in domain.advances_of_da(ent["id"]):
        if (adv["status"] == "RECEIVED"
                and adv["amount_cents"] - adv["applied_cents"] - adv["refunded_cents"] > 0):
            raise_err("ERR_UNREFUNDED_ADVANCES",
                      "An advance still holds an unapplied, unrefunded remainder")
    if ent["balance_due_cents"] != 0:
        raise_err("ERR_BALANCE_NOT_ZERO", "balance_due_cents must be exactly zero to settle")
    ent["status"] = "SETTLED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/disbursement-accounts/<did>/advances")
def create_funding_advance(did):
    user_id, role = require_roles(["AgencyFinance", "PrincipalRep"])
    ent = _get_or_404(did)
    # Entity-backed ownership for PrincipalRep
    if role == "PrincipalRep":
        call = domain.get("port_calls", ent["port_call_id"])
        if call is None or call["principal_id"] != user_id:
            raise_err("ERR_NOT_RESOURCE_OWNER", "The account does not belong to the caller's principal")
    if ent["status"] not in ("SENT_TO_PRINCIPAL", "FUNDED", "FINAL", "DISPUTED"):
        invalid_state("Advances require the account to be SENT_TO_PRINCIPAL, FUNDED, FINAL or DISPUTED")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None:
        domain.require_call_editable(call)
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not is_int(amount) or amount <= 0:
        invalid_request("amount_cents must be a positive integer")
    adv = new_entity("funding_advances", {
        "da_id": ent["id"],
        "amount_cents": amount,
        "applied_cents": 0,
        "refunded_cents": 0,
        "status": "RECEIVED",
        "received_at": db.now(),
    })
    domain.recompute_da_totals(ent)
    return ok_object(serialize(adv), status=201)
