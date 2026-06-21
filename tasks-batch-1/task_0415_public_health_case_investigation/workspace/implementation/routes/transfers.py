"""Jurisdiction transfers: request + resolve (with case rehome cascade)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from helpers import (base_entity, touch, parse_pagination, sorted_by_creation,
                     get_or_404, get_in_program_or_404, require_string, require_enum,
                     require_non_negative_int)
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import ser_transfer
from services import inc_active_monitoring, dec_active_monitoring

bp = Blueprint("transfers", __name__)


@bp.route("/surveillance/jurisdiction-transfers", methods=["POST"])
def request_transfer():
    _, role = get_user_context()
    require_role(role, {"EpiAnalyst"})
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    case_id = require_string(body, "case_id")
    to_jurisdiction_id = require_string(body, "to_jurisdiction_id")
    reason = require_string(body, "reason", required=False)

    with db.lock:
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        case = get_in_program_or_404(db.cases, case_id, program_id, "ERR_CASE_NOT_FOUND")
        get_in_program_or_404(db.jurisdictions, to_jurisdiction_id, program_id, "ERR_JURISDICTION_NOT_FOUND")

        expected_case_version = require_non_negative_int(body, "expected_case_version")

        # OCC check (priority 6) — before any state/business check
        if expected_case_version != case["version"]:
            raise err("ERR_STALE_CASE_VERSION",
                      "expected_case_version does not match case.version")

        # state legality (priority 7)
        if case["status"] not in ("UNDER_INVESTIGATION", "CLASSIFIED"):
            raise err("ERR_CASE_NOT_TRANSFERABLE",
                      "Case not in UNDER_INVESTIGATION/CLASSIFIED for transfer")

        # to != from
        if to_jurisdiction_id == case["jurisdiction_id"]:
            raise err("ERR_SAME_JURISDICTION_TRANSFER",
                      "Transfer target equals the case's current jurisdiction")

        # no other REQUESTED transfer for this case
        for t in db.transfers.values():
            if t["case_id"] == case_id and t["status"] == "REQUESTED":
                raise err("ERR_TRANSFER_PENDING_EXISTS",
                          "A REQUESTED transfer already exists for the case")

        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": program_id,
            "case_id": case_id,
            "from_jurisdiction_id": case["jurisdiction_id"],
            "to_jurisdiction_id": to_jurisdiction_id,
            "expected_case_version": expected_case_version,
            "reason": reason,
            "status": "REQUESTED",
        })
        db.transfers[ent["id"]] = ent

        # drive case into TRANSFER_PENDING, remember prior status, bump version
        case["_prior_status"] = case["status"]
        case["status"] = "TRANSFER_PENDING"
        touch(case)
        return success(ser_transfer(ent), 201)


@bp.route("/surveillance/jurisdiction-transfers", methods=["GET"])
def list_transfers():
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin", "EpiAnalyst", "CaseInvestigator"})
    with db.lock:
        filters = ["program_id", "case_id", "to_jurisdiction_id", "from_jurisdiction_id", "status"]
        items = []
        for t in db.transfers.values():
            ok = True
            for f in filters:
                v = request.args.get(f)
                if v is not None and t.get(f) != v:
                    ok = False
                    break
            if ok:
                items.append(t)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_transfer(t) for t in page], limit, offset, total)


@bp.route("/surveillance/jurisdiction-transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, {"JurisdictionAdmin", "EpiAnalyst", "CaseInvestigator"})
    with db.lock:
        t = get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
        return success(ser_transfer(t), 200)


@bp.route("/surveillance/jurisdiction-transfers/<transfer_id>", methods=["PUT"])
def resolve_transfer(transfer_id):
    _, role = get_user_context()
    require_role(role, {"EpiAnalyst"})
    with db.lock:
        t = get_or_404(db.transfers, transfer_id, "ERR_TRANSFER_NOT_FOUND")
        body = request.get_json(silent=True) or {}
        status = require_enum(body, "status", {"ACCEPTED", "REJECTED"})
        if t["status"] != "REQUESTED":
            raise err("ERR_TRANSFER_NOT_RESOLVABLE", "Transfer not in REQUESTED for accept/reject")

        case = db.cases.get(t["case_id"])
        prior_status = case.get("_prior_status") if case else None

        if status == "ACCEPTED":
            t["status"] = "ACCEPTED"
            if case is not None:
                old_jur = case["jurisdiction_id"]
                new_jur = t["to_jurisdiction_id"]
                case["jurisdiction_id"] = new_jur
                # cascade: reassign matching non-VOIDED contacts
                for ct in db.contacts.values():
                    if ct["source_case_id"] != case["id"]:
                        continue
                    if ct["status"] == "VOIDED":
                        continue
                    if ct["monitoring_jurisdiction_id"] != old_jur:
                        continue
                    ct["monitoring_jurisdiction_id"] = new_jur
                    if ct["status"] == "MONITORING_ACTIVE":
                        dec_active_monitoring(old_jur)
                        inc_active_monitoring(new_jur)
                    touch(ct)
        else:
            t["status"] = "REJECTED"

        touch(t)
        if case is not None:
            case["status"] = prior_status if prior_status else case["status"]
            case["_prior_status"] = None
            touch(case)
        return success(ser_transfer(t), 200)
