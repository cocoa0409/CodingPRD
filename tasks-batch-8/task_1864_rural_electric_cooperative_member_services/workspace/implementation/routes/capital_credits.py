"""Capital Credit Allocation, Retirement, and Payout endpoints."""
from flask import Blueprint, request, g

from middleware import get_context, require_roles, get_json_body
from response import ok, created, paginate
from errors import ApiError
from services import capital_credit as cc_svc

bp = Blueprint("capital_credits", __name__)


# =============================================================================
# Allocations
# =============================================================================

@bp.route("/coop/capital-credit-allocations", methods=["POST"])
def create_allocation():
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = cc_svc.create_allocation(body)
    result["_created_by"] = uid
    return created(result)


@bp.route("/coop/capital-credit-allocations/<alloc_id>", methods=["GET"])
def get_allocation(alloc_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    result = cc_svc.get_allocation(alloc_id)
    return ok(result)


@bp.route("/coop/capital-credit-allocations", methods=["GET"])
def list_allocations():
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    cooperative_id = request.args.get("cooperative_id")
    fiscal_year = request.args.get("fiscal_year")
    status = request.args.get("status")
    rows = cc_svc.list_allocations(cooperative_id, fiscal_year, status)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/capital-credit-allocations/<alloc_id>/lines", methods=["GET"])
def get_allocation_lines(alloc_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    # Verify allocation exists
    cc_svc.get_allocation(alloc_id)
    rows = cc_svc.get_allocation_lines(alloc_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/capital-credit-allocation-lines/<line_id>", methods=["GET"])
def get_allocation_line(line_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    result = cc_svc.get_allocation_line(line_id)
    return ok(result)


@bp.route("/coop/capital-credit-allocation-lines", methods=["GET"])
def list_allocation_lines():
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    member_id = request.args.get("member_id")
    allocation_id = request.args.get("allocation_id")
    rows = cc_svc.list_allocation_lines(member_id, allocation_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/capital-credit-allocations/<alloc_id>/approve", methods=["POST"])
def approve_allocation(alloc_id):
    uid, role = get_context()
    require_roles(["BoardDirector"])
    result = cc_svc.approve_allocation(alloc_id, uid)
    return ok(result)


@bp.route("/coop/capital-credit-allocations/<alloc_id>/post", methods=["POST"])
def post_allocation(alloc_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = cc_svc.post_allocation(alloc_id, body)
    return ok(result)


@bp.route("/coop/capital-credit-allocations/<alloc_id>/void", methods=["POST"])
def void_allocation(alloc_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = cc_svc.void_allocation(alloc_id)
    return ok(result)


# =============================================================================
# Retirements
# =============================================================================

@bp.route("/coop/capital-credit-retirements", methods=["POST"])
def create_retirement():
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = cc_svc.create_retirement(body)
    result["_created_by"] = uid
    return created(result)


@bp.route("/coop/capital-credit-retirements/<ret_id>", methods=["GET"])
def get_retirement(ret_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    result = cc_svc.get_retirement(ret_id)
    return ok(result)


@bp.route("/coop/capital-credit-retirements", methods=["GET"])
def list_retirements():
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    cooperative_id = request.args.get("cooperative_id")
    status = request.args.get("status")
    rows = cc_svc.list_retirements(cooperative_id, status)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


@bp.route("/coop/capital-credit-retirements/<ret_id>/board-approve", methods=["POST"])
def board_approve_retirement(ret_id):
    uid, role = get_context()
    require_roles(["BoardDirector"])
    result = cc_svc.board_approve_retirement(ret_id, uid)
    return ok(result)


@bp.route("/coop/capital-credit-retirements/<ret_id>/execute", methods=["POST"])
def execute_retirement(ret_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    body = get_json_body()
    result = cc_svc.execute_retirement(ret_id, body)
    return ok(result)


@bp.route("/coop/capital-credit-retirements/<ret_id>/abort", methods=["POST"])
def abort_retirement(ret_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = cc_svc.abort_retirement(ret_id)
    return ok(result)


@bp.route("/coop/capital-credit-retirements/<ret_id>/payouts", methods=["GET"])
def get_retirement_payouts(ret_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep", "BoardDirector"])
    # Verify retirement exists
    cc_svc.get_retirement(ret_id)
    rows = cc_svc.get_retirement_payouts(ret_id)
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)


# =============================================================================
# Payouts
# =============================================================================

@bp.route("/coop/capital-credit-payouts/<payout_id>/cash", methods=["POST"])
def cash_payout(payout_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = cc_svc.cash_payout(payout_id)
    return ok(result)


@bp.route("/coop/capital-credit-payouts/<payout_id>/mark-unclaimed", methods=["POST"])
def mark_unclaimed_payout(payout_id):
    uid, role = get_context()
    require_roles(["MemberServicesRep"])
    result = cc_svc.mark_unclaimed_payout(payout_id)
    return ok(result)
