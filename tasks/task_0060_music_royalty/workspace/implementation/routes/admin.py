"""Admin / test-driving routes: PSP callback, clock advance, sweep, external sync list."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import payout as payout_svc
from services import admin_ops

bp = Blueprint("admin", __name__)


@bp.route("/_events/psp-callback", methods=["POST"])
def psp_callback():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = payout_svc.psp_callback(body)
    return success_response(data)


@bp.route("/_events/external-sync", methods=["GET"])
def list_external_sync():
    require_role("PlatformAdmin")
    items, total, limit, offset = admin_ops.list_external_sync(request.args)
    return list_response(items, total, limit, offset)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = admin_ops.advance_clock(body)
    return success_response(data)


@bp.route("/_sweep/run", methods=["POST"])
def sweep_run():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = admin_ops.run_sweep(body)
    return success_response(data)
