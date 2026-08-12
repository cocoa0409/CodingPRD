"""Add-on reads and the suspend/resume pair (PRD §3.8)."""

from flask import Blueprint, request

import cascades
import constants as K
import envelope
import serializers
import states
from context import Ctx
from store import DB

bp = Blueprint("addons", __name__)


@bp.get("/addons/<addon_id>")
def read_addon(addon_id):
    ctx = Ctx(
        request,
        [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER, K.ROLE_AUDITOR],
    )
    addon = ctx.path("addon", addon_id)
    ctx.own(addon["account_id"])  # account-level read
    return envelope.ok(serializers.addon(addon))


@bp.post("/addons/<addon_id>/suspend")
def suspend_addon(addon_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    addon = ctx.path("addon", addon_id)
    account = DB.accounts.get(addon["account_id"])
    ctx.own(addon["account_id"])
    ctx.write_gates(account)
    states.gate("addon_status", addon["status"], ("ACTIVE",))
    cascades.suspend_addon(addon)
    return envelope.ok(serializers.addon(addon))


@bp.post("/addons/<addon_id>/resume")
def resume_addon(addon_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    addon = ctx.path("addon", addon_id)
    account = DB.accounts.get(addon["account_id"])
    ctx.own(addon["account_id"])
    # The declared precondition Account.status == ACTIVE is enforced by global
    # write gate 3 (rung 15), which this endpoint is not exempt from.
    ctx.write_gates(account)
    states.gate("addon_status", addon["status"], ("SUSPENDED",))
    cascades.resume_addon(addon)
    return envelope.ok(serializers.addon(addon))
