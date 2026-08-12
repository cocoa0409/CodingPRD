"""Credential-hygiene findings (PRD §3.7)."""

from flask import Blueprint, request

import constants as K
import context
import derive
import envelope
import rows
import serializers
import states
from clock import CLOCK
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("findings", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


def _profile_of(finding):
    return DB.profiles.get(finding["profile_id"])


def _account_of(finding):
    return derive.account_of_profile(_profile_of(finding))


@bp.post("/credential-findings")
def record_finding():
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "profile_id", "type": "string", "required": True},
            {
                "name": "finding_type",
                "type": "string",
                "required": True,
                "enum": K.FINDING_TYPES,
            },
            {"name": "detail", "type": "string", "required": True},
        ]
    )
    # Rung 11
    profile = DB.profiles.get(fields["profile_id"])
    if profile is None:
        raise ApiError("ERR_PROFILE_NOT_FOUND")
    ctx.write_gates(derive.account_of_profile(profile))
    finding = rows.new_row(
        "findings",
        {
            "profile_id": profile["id"],
            "finding_type": fields["finding_type"],
            "detail": fields["detail"],
            "status": "OPEN",
            "remediated_at": None,
        },
    )
    # The profile's hygiene figures are re-derived at read time.
    return envelope.created(serializers.finding(finding))


def _visible(ctx, finding):
    if not ctx.is_scoped_caller:
        return True
    profile = _profile_of(finding)
    if profile is None:
        return False
    account = derive.account_of_profile(profile)
    if account is None or account["id"] != ctx.caller_member["account_id"]:
        return False
    if ctx.is_non_primary_member and profile["member_id"] != ctx.caller_member["id"]:
        return False
    return True


@bp.get("/credential-findings")
def list_findings():
    ctx = Ctx(request, ALL_READ_ROLES)
    status = context.enum_filter(request, "status", K.FINDING_STATUSES)
    limit, offset = context.pagination(request)
    profile_id = context.plain_filter(request, "profile_id")
    # `finding_type` is NOT on rung 8's closed list.
    finding_type = context.plain_filter(request, "finding_type")
    result = []
    for finding in DB.findings.values():
        if profile_id is not None and finding["profile_id"] != profile_id:
            continue
        if finding_type is not None and finding["finding_type"] != finding_type:
            continue
        if status is not None and finding["status"] != status:
            continue
        if not _visible(ctx, finding):
            continue
        result.append(finding)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.finding(f) for f in page], limit, offset, total)


@bp.get("/credential-findings/<finding_id>")
def read_finding(finding_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    finding = ctx.path("finding", finding_id)
    profile = _profile_of(finding)
    ctx.own(derive.account_of_profile(profile)["id"], profile["member_id"])
    return envelope.ok(serializers.finding(finding))


@bp.post("/credential-findings/<finding_id>/remediate")
def remediate_finding(finding_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    finding = ctx.path("finding", finding_id)
    profile = _profile_of(finding)
    account = derive.account_of_profile(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    states.gate("finding_status", finding["status"], ("OPEN",))
    finding["status"] = "REMEDIATED"
    finding["remediated_at"] = CLOCK.now
    rows.touch(finding)
    return envelope.ok(serializers.finding(finding))


@bp.post("/credential-findings/<finding_id>/reopen")
def reopen_finding(finding_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT])
    finding = ctx.path("finding", finding_id)
    ctx.write_gates(_account_of(finding))
    states.gate("finding_status", finding["status"], ("REMEDIATED",))
    finding["status"] = "OPEN"
    finding["remediated_at"] = None
    rows.touch(finding)
    return envelope.ok(serializers.finding(finding))
