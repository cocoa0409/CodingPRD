"""Accumulation ledger read endpoints (PRD §2.6)."""
from flask import Blueprint, request

from routes.helpers import READ_ALL, get_one, list_response

bp = Blueprint("accumulations", __name__)


@bp.get("/stop-loss/accumulations/<rid>")
def get_accumulation(rid):
    return get_one("accumulations", rid, READ_ALL)


@bp.get("/stop-loss/accumulations")
def list_accumulations():
    return list_response("accumulations", READ_ALL, {
        "contract_id": request.args.get("contract_id"),
        "member_id": request.args.get("member_id"),
        "scope": request.args.get("scope"),
    })
