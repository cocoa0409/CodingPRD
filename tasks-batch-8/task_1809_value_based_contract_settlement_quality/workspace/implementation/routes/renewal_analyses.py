"""RenewalAnalysis endpoints (list/get/complete; create lives in contracts.py)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import calculations as calc
from util import apply_filters, paginate, parse_pagination, sort_by_created_at

bp = Blueprint("renewal_analyses", __name__)


@bp.route("/vbc/renewal-analyses", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_renewal_analyses(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.renewal_analyses.values()))
    items = apply_filters(items, ["contract_id", "analysis_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/renewal-analyses/<analysis_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_renewal_analysis(analysis_id: str, _user_id: str, _role: str):
    analysis = db.renewal_analyses.get(analysis_id)
    if analysis is None:
        raise_err(ERR_NOT_FOUND, "RenewalAnalysis id does not exist")
    return success_object(analysis)


@bp.route("/vbc/renewal-analyses/<analysis_id>/complete", methods=["POST"])
@require_roles("ContractManager")
def complete_renewal_analysis(analysis_id: str, _user_id: str, _role: str):
    analysis = db.renewal_analyses.get(analysis_id)
    if analysis is None:
        raise_err(ERR_NOT_FOUND, "RenewalAnalysis id does not exist")
    if analysis["analysis_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT analysis can be completed")
    contract = db.contracts[analysis["contract_id"]]
    metrics = calc.compute_renewal_metrics(contract)
    analysis.update(metrics)
    analysis["analysis_status"] = "COMPLETE"
    db.touch(analysis)
    return success_object(analysis)
