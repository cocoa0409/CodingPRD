"""Disbursement endpoints — PRD §3.8."""
from flask import Blueprint

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int
from services import case_ops

bp = Blueprint("disbursements", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/disbursements", methods=["POST"])
def create_disbursement():
    _uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    body = require_body()
    # Existence (priority 3): ihp_case_id then line_item_id (declaration order)
    ihp_case_id = req_str(body, "ihp_case_id")
    line_item_id = req_str(body, "line_item_id")
    with STORE.lock:
        case = lookup("ihp_cases", ihp_case_id)
        line_item = lookup("award_line_items", line_item_id)

        # Case state precondition (priority 5)
        first = case["status"] == "AWARD_APPROVED"
        if not first and case["status"] != "DISBURSING":
            # If never approved -> first disbursement requires AWARD_APPROVED
            raise ApiError("ERR_CASE_NOT_APPROVED")

        # Declaration not CLOSED (cross-entity gate)
        declaration = case_ops.case_declaration(case)
        if declaration is not None and declaration["status"] == "CLOSED":
            raise ApiError("ERR_DECLARATION_CLOSED")

        # Line item must be APPROVED and belong to this case (priority 7)
        if line_item["ihp_case_id"] != ihp_case_id or line_item["li_status"] != "APPROVED":
            raise ApiError("ERR_LINE_ITEM_NOT_APPROVED")

        # OCC (priority 10)
        expected = req_int(body, "expected_ihp_case_version")
        if expected != case["version"]:
            raise ApiError("ERR_STALE_CASE_VERSION")

        # Amount (priority 13 shape) then fiscal ceiling (priority 12)
        amount_cents = req_int(body, "amount_cents", minimum=1)
        if amount_cents > case["remaining_obligation_cents"]:
            raise ApiError("ERR_DISBURSEMENT_EXCEEDS_OBLIGATION")

        d = base_entity()
        d.update({
            "ihp_case_id": ihp_case_id,
            "line_item_id": line_item_id,
            "expected_ihp_case_version": expected,
            "amount_cents": amount_cents,
            "disb_status": "PAID",
        })
        STORE.disbursements[d["id"]] = d

        case["disbursed_total_cents"] += amount_cents
        case_ops.recompute_obligation(case)
        if first:
            case["status"] = "DISBURSING"
        touch(case)
        return success(serialize(d), status=201)


@bp.route("/disaster-relief/disbursements", methods=["GET"])
def list_disbursements():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.disbursements.values(),
            {"ihp_case_id": "ihp_case_id", "line_item_id": "line_item_id", "disb_status": "disb_status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/disbursements/<did>", methods=["GET"])
def get_disbursement(did):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        d = lookup("disbursements", did)
        return success(serialize(d))


@bp.route("/disaster-relief/disbursements/<did>/void", methods=["POST"])
def void_disbursement(did):
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    with STORE.lock:
        d = lookup("disbursements", did)
        if d["disb_status"] != "PAID":
            raise ApiError("ERR_DISBURSEMENT_NOT_PAID")
        d["disb_status"] = "VOIDED"
        touch(d)
        case = STORE.ihp_cases.get(d["ihp_case_id"])
        if case is not None:
            case["disbursed_total_cents"] -= d["amount_cents"]
            case_ops.recompute_obligation(case)
            touch(case)
        return success(serialize(d))
