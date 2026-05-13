"""Contract + contract-template + royalty-schedule endpoints."""
from flask import Blueprint, request, g

import db
from errors import APIError, ERR_BAD_REQUEST
from middleware import require_roles
from response import success, success_list
from services import contract_logic, serializers
from services.common import make_unversioned, check_version, get_or_404
from utils import get_str, get_enum, get_pagination, paginate

bp = Blueprint("contracts", __name__)


# ---------------- Contract Templates -----------------

@bp.route("/contract-templates", methods=["POST"])
@require_roles("Admin")
def create_template():
    body = request.get_json(silent=True) or {}
    code = get_str(body, "code", required=True, pattern=r"^[A-Z0-9_]{2,32}$")
    contract_type = get_enum(body, "contract_type", contract_logic.VALID_CONTRACT_TYPES)
    body_text = get_str(body, "body")
    with db.lock():
        if code in db.contract_template_codes:
            raise APIError(ERR_BAD_REQUEST, 422, "Duplicate template code")
        template = make_unversioned({
            "code": code,
            "contract_type": contract_type,
            "body": body_text,
        })
        db.contract_templates[template["id"]] = template
        db.contract_template_codes.add(code)
    return success(serializers.serialize_contract_template(template), 201)


@bp.route("/contract-templates", methods=["GET"])
@require_roles("Admin", "IPManager")
def list_templates():
    limit, offset = get_pagination(request.args)
    contract_type = request.args.get("contract_type")
    items = list(db.contract_templates.values())
    if contract_type:
        items = [t for t in items if t["contract_type"] == contract_type]
    items.sort(key=lambda t: t["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_contract_template(t) for t in window]
    return success_list(data, limit, offset, total)


# ---------------- Contracts -----------------

@bp.route("/contracts", methods=["POST"])
@require_roles("IPManager")
def create_contract():
    body = request.get_json(silent=True) or {}
    with db.lock():
        contract = contract_logic.draft_contract(body, g.user_role, g.user_id)
    return success(serializers.serialize_contract(contract), 201)


@bp.route("/contracts/<cid>/start-signing", methods=["POST"])
@require_roles("IPManager")
def start_signing(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        contract = get_or_404(db.contracts, cid)
        check_version(contract, body)
        contract_logic.start_signing(contract, g.user_role, g.user_id)
    return success(serializers.serialize_contract(contract))


@bp.route("/contracts/<cid>/sign", methods=["POST"])
@require_roles("IPManager", "Admin")
def sign(cid):
    body = request.get_json(silent=True) or {}
    party_id = get_str(body, "party_id")
    with db.lock():
        contract = get_or_404(db.contracts, cid)
        contract_logic.sign_contract(contract, party_id, g.user_role, g.user_id)
    return success(serializers.serialize_contract(contract))


@bp.route("/contracts/<cid>/file-with-authority", methods=["POST"])
@require_roles("IPManager")
def file_with_authority(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        contract = get_or_404(db.contracts, cid)
        check_version(contract, body)
        contract_logic.file_with_authority(contract, g.user_role, g.user_id)
    return success(serializers.serialize_contract(contract))


@bp.route("/contracts/<cid>/amend", methods=["POST"])
@require_roles("IPManager")
def amend(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        contract = get_or_404(db.contracts, cid)
        check_version(contract, body)
        contract_logic.amend_contract(contract, g.user_role, g.user_id)
    return success(serializers.serialize_contract(contract))


@bp.route("/contracts/<cid>/terminate", methods=["POST"])
@require_roles("IPManager")
def terminate(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        contract = get_or_404(db.contracts, cid)
        check_version(contract, body)
        contract_logic.terminate_contract(contract, g.user_role, g.user_id)
    return success(serializers.serialize_contract(contract))


# ---------------- Royalty Schedules -----------------

@bp.route("/contracts/<cid>/royalty-schedules", methods=["POST"])
@require_roles("IPManager")
def create_royalty(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        contract = get_or_404(db.contracts, cid)
        rs = contract_logic.create_royalty_schedule(contract, body, g.user_role, g.user_id)
    return success(serializers.serialize_royalty_schedule(rs), 201)


@bp.route("/royalty-schedules/<rs_id>/settle", methods=["POST"])
@require_roles("FinanceManager")
def settle_royalty(rs_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        rs = get_or_404(db.royalty_schedules, rs_id)
        check_version(rs, body)
        contract_logic.settle_royalty_schedule(rs, body, g.user_role, g.user_id)
    return success(serializers.serialize_royalty_schedule(rs))
