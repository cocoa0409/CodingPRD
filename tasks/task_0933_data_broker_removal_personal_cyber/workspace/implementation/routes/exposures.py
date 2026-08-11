"""Exposure inventory reads (PRD §3.4)."""

from flask import Blueprint, request

import constants as K
import context
import derive
import envelope
import serializers
from context import Ctx
from store import DB, ordered

bp = Blueprint("exposures", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


def _visible(ctx, exposure):
    if not ctx.is_scoped_caller:
        return True
    profile = DB.profiles.get(exposure["profile_id"])
    if profile is None:
        return False
    account = derive.account_of_profile(profile)
    if account is None or account["id"] != ctx.caller_member["account_id"]:
        return False
    if ctx.is_non_primary_member and profile["member_id"] != ctx.caller_member["id"]:
        return False
    return True


@bp.get("/exposures")
def list_exposures():
    ctx = Ctx(request, ALL_READ_ROLES)
    status = context.enum_filter(request, "status", K.EXPOSURE_STATUSES)
    limit, offset = context.pagination(request)
    profile_id = context.plain_filter(request, "profile_id")
    broker_id = context.plain_filter(request, "broker_id")
    scan_id = context.plain_filter(request, "discovered_by_scan_id")
    result = []
    for exposure in DB.exposures.values():
        if profile_id is not None and exposure["profile_id"] != profile_id:
            continue
        if broker_id is not None and exposure["broker_id"] != broker_id:
            continue
        if scan_id is not None and exposure["discovered_by_scan_id"] != scan_id:
            continue
        if status is not None and exposure["status"] != status:
            continue
        if not _visible(ctx, exposure):
            continue
        result.append(exposure)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.exposure(e) for e in page], limit, offset, total)


@bp.get("/exposures/<exposure_id>")
def read_exposure(exposure_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    exposure = ctx.path("exposure", exposure_id)
    profile = DB.profiles.get(exposure["profile_id"])
    ctx.own(derive.account_of_profile(profile)["id"], profile["member_id"])
    return envelope.ok(serializers.exposure(exposure))
