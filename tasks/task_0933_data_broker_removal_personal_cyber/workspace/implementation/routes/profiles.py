"""Monitored profiles, their identifiers and the hygiene report (PRD §3.3, §3.7)."""

from flask import Blueprint, request

import cascades
import constants as K
import context
import derive
import envelope
import ledger
import rows
import serializers
import states
from clock import CLOCK
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("profiles", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


def _account_of(profile):
    return derive.account_of_profile(profile)


@bp.post("/monitored-profiles")
def draft_profile():
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "member_id", "type": "string", "required": True},
            {"name": "full_name", "type": "string", "required": True},
            {"name": "date_of_birth", "type": "string", "required": True},
            {"name": "primary_address", "type": "string", "required": True},
            {
                "name": "rescan_cadence_days",
                "type": "integer",
                "required": False,
                "min": 7,
                "max": 180,
                "default": 30,
            },
            {
                "name": "two_factor_attested",
                "type": "boolean",
                "required": False,
                "default": False,
            },
        ]
    )
    # Rung 11
    member = DB.members.get(fields["member_id"])
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    # Rung 12
    ctx.own(member["account_id"], member["id"])
    account = DB.accounts.get(member["account_id"])
    ctx.write_gates(account)
    # Rung 16
    if member["authorization_status"] != "GRANTED":
        raise ApiError("ERR_AUTHORIZATION_REVOKED")
    # Rung 21
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    profile = rows.new_row(
        "profiles",
        {
            "member_id": member["id"],
            "full_name": fields["full_name"],
            "date_of_birth": fields["date_of_birth"],
            "primary_address": fields["primary_address"],
            "rescan_cadence_days": fields["rescan_cadence_days"],
            "two_factor_attested": fields["two_factor_attested"],
            "status": "DRAFT",
            "activated_at": None,
            "retired_at": None,
            "last_completed_scan_at": None,
        },
    )
    return envelope.created(serializers.profile(profile))


@bp.get("/monitored-profiles/<profile_id>")
def read_profile(profile_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    profile = ctx.path("profile", profile_id)
    ctx.own(_account_of(profile)["id"], profile["member_id"])
    return envelope.ok(serializers.profile(profile))


@bp.patch("/monitored-profiles/<profile_id>")
def edit_profile(profile_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    profile = ctx.path("profile", profile_id)
    ctx.load_body()
    body = ctx.body
    ctx.validate(
        [
            {
                "name": "two_factor_attested",
                "type": "boolean",
                "required": False,
            },
            {
                "name": "rescan_cadence_days",
                "type": "integer",
                "required": False,
                "min": 7,
                "max": 180,
            },
        ]
    )
    account = _account_of(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    if "two_factor_attested" in body:
        profile["two_factor_attested"] = body["two_factor_attested"]
    if "rescan_cadence_days" in body:
        profile["rescan_cadence_days"] = body["rescan_cadence_days"]
    # hygiene_score / hygiene_band are re-derived at read time under the newly
    # selected variant.
    rows.touch(profile)
    return envelope.ok(serializers.profile(profile))


@bp.post("/monitored-profiles/<profile_id>/activate")
def activate_profile(profile_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    profile = ctx.path("profile", profile_id)
    account = _account_of(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    states.gate("profile_status", profile["status"], ("DRAFT", "PAUSED"))
    member = DB.members.get(profile["member_id"])
    # Rung 21
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    from_draft = profile["status"] == "DRAFT"
    if from_draft:
        # Rung 40
        if not derive.profile_identifiers(profile["id"]):
            raise ApiError("ERR_PROFILE_HAS_NO_IDENTIFIER")
        # Rung 43
        pools = derive.pool_figures(account["id"])
        if pools["profile"]["remaining"] < 1:
            raise ApiError("ERR_PROFILE_QUOTA_EXCEEDED")
        profile["status"] = "ACTIVE"
        profile["activated_at"] = CLOCK.now
        ledger.append(
            account_id=account["id"],
            member_id=member["id"],
            resource_type="PROFILE",
            entry_type="CONSUME",
            amount=1,
            reason_code="PROFILE_ACTIVATED",
            source_reference=profile["id"],
        )
    else:
        # PAUSED -> ACTIVE consumes no new unit: the unit taken at first
        # activation was never released.
        profile["status"] = "ACTIVE"
    rows.touch(profile)
    return envelope.ok(serializers.profile(profile))


@bp.post("/monitored-profiles/<profile_id>/pause")
def pause_profile(profile_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    profile = ctx.path("profile", profile_id)
    account = _account_of(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    states.gate("profile_status", profile["status"], ("ACTIVE",))
    cascades.pause_profile(profile, account["id"])
    return envelope.ok(serializers.profile(profile))


@bp.post("/monitored-profiles/<profile_id>/retire")
def retire_profile(profile_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    profile = ctx.path("profile", profile_id)
    account = _account_of(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    states.gate("profile_status", profile["status"], ("DRAFT", "ACTIVE", "PAUSED"))
    cascades.retire_profile(profile, account["id"])
    return envelope.ok(serializers.profile(profile))


@bp.post("/monitored-profiles/<profile_id>/identifiers")
def add_identifier(profile_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    profile = ctx.path("profile", profile_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {
                "name": "identifier_type",
                "type": "string",
                "required": True,
                "enum": K.IDENTIFIER_TYPES,
            },
            {
                "name": "identifier_value",
                "type": "string",
                "required": True,
                "min_len": 1,
                "max_len": 120,
            },
            {"name": "expected_profile_version", "type": "integer", "required": True},
        ]
    )
    account = _account_of(profile)
    ctx.own(account["id"], profile["member_id"])
    ctx.write_gates(account)
    # Rung 17
    if fields["expected_profile_version"] != profile["version"]:
        raise ApiError("ERR_STALE_PROFILE_VERSION")
    held = derive.profile_identifiers(profile["id"])
    # Rung 36
    for row in held:
        if (
            row["identifier_type"] == fields["identifier_type"]
            and row["identifier_value"] == fields["identifier_value"]
        ):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER")
    # Rung 37 -- STRICT boundary: the 8th is admitted, the 9th is rejected.
    if len(held) >= K.MAX_IDENTIFIERS_PER_PROFILE:
        raise ApiError("ERR_IDENTIFIER_CAP_EXCEEDED")
    identifier = rows.new_row(
        "identifiers",
        {
            "profile_id": profile["id"],
            "identifier_type": fields["identifier_type"],
            "identifier_value": fields["identifier_value"],
        },
        common=False,
    )
    rows.touch(profile)
    return envelope.created(serializers.identifier(identifier))


@bp.get("/monitored-profiles/<profile_id>/identifiers")
def list_identifiers(profile_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    profile = ctx.path("profile", profile_id)
    # `identifier_type` is NOT on rung 8's closed list, so an unknown value is
    # simply a filter that matches nothing -- it never routes to ERR_INVALID_ENUM.
    identifier_type = context.plain_filter(request, "identifier_type")
    limit, offset = context.pagination(request)
    ctx.own(_account_of(profile)["id"], profile["member_id"])
    result = [
        i
        for i in derive.profile_identifiers(profile["id"])
        if identifier_type is None or i["identifier_type"] == identifier_type
    ]
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing(
        [serializers.identifier(i) for i in page], limit, offset, total
    )


@bp.get("/monitored-profiles/<profile_id>/hygiene-score")
def hygiene_report(profile_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    profile = ctx.path("profile", profile_id)
    ctx.own(_account_of(profile)["id"], profile["member_id"])
    figures = derive.profile_hygiene(profile)
    return envelope.ok(
        {
            "profile_id": profile["id"],
            "variant": figures["variant"],
            "open_finding_count": figures["open_finding_count"],
            "raw_penalty": figures["raw_penalty"],
            "capped_penalty": figures["capped_penalty"],
            "adjusted_penalty": figures["adjusted_penalty"],
            "hygiene_score": figures["hygiene_score"],
            "hygiene_band": figures["hygiene_band"],
        }
    )
