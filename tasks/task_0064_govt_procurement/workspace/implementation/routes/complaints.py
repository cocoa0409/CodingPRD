"""Complaint routes."""

from flask import Blueprint

from common import get_json_body
from middleware import require_roles
from response import success
from services import complaint as svc


bp = Blueprint("complaints", __name__, url_prefix="/procurement")


@bp.post("/projects/<pid>/complaints")
@require_roles("Supplier")
def file_complaint(pid):
    body = get_json_body()
    return success(svc.file_complaint(pid, body), 201)


@bp.post("/complaints/<cid>/accept")
@require_roles("Regulator")
def accept(cid):
    return success(svc.accept_complaint(cid), 200)


@bp.post("/complaints/<cid>/uphold")
@require_roles("Regulator")
def uphold(cid):
    body = get_json_body()
    return success(svc.uphold_complaint(cid, body), 200)


@bp.post("/complaints/<cid>/dismiss")
@require_roles("Regulator")
def dismiss(cid):
    return success(svc.dismiss_complaint(cid), 200)


@bp.post("/complaints/<cid>/withdraw")
@require_roles("Supplier")
def withdraw(cid):
    return success(svc.withdraw_complaint(cid), 200)
