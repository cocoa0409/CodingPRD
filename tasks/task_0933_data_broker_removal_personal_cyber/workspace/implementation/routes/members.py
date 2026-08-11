"""Member lifecycle, the authorization axis, identity evidence and reports."""

from flask import Blueprint, request

import calc
import cascades
import constants as K
import context
import derive
import envelope
import rows
import serializers
import states
from clock import CLOCK, parse_instant
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("members", __name__)

ALL_READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_PRIVACY_AGENT,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


@bp.get("/members/<member_id>")
def read_member(member_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    member = ctx.path("member", member_id)
    ctx.own(member["account_id"], member["id"])
    return envelope.ok(serializers.member(member))


@bp.post("/members/<member_id>/activate")
def activate_member(member_id):
    ctx = Ctx(request, [K.ROLE_MEMBER, K.ROLE_ACCOUNT_OWNER])
    member = ctx.path("member", member_id)
    ctx.load_body()
    fields = ctx.validate([{"name": "invitation_token", "type": "string", "required": True}])
    ctx.own(member["account_id"], member["id"])
    account = DB.accounts.get(member["account_id"])
    ctx.write_gates(account)
    states.gate("member_status", member["status"], ("INVITED",))
    # The supplied token must equal the one stored on the row. The catalogue
    # names no dedicated code for a mismatch, so it is reported as a body-shape
    # failure (ERR_VALIDATION) rather than inventing one.
    if fields["invitation_token"] != member["invitation_token"]:
        raise ApiError("ERR_VALIDATION", "The supplied invitation_token does not match.")
    member["status"] = "ACTIVE"
    member["activated_at"] = CLOCK.now
    member["invitation_token"] = None
    rows.touch(member)
    return envelope.ok(serializers.member(member))


@bp.post("/members/<member_id>/authorization")
def member_authorization(member_id):
    ctx = Ctx(request, [K.ROLE_MEMBER, K.ROLE_ACCOUNT_OWNER])
    member = ctx.path("member", member_id)
    ctx.load_body()
    fields = ctx.validate(
        [{"name": "action", "type": "string", "required": True, "enum": K.AUTHORIZATION_ACTIONS}]
    )
    ctx.own(member["account_id"], member["id"])
    account = DB.accounts.get(member["account_id"])
    ctx.write_gates(account)
    action = fields["action"]
    allowed = ("GRANTED",) if action == "REVOKE" else ("REVOKED",)
    states.gate("member_authorization", member["authorization_status"], allowed)
    # Rung 21
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    if action == "REVOKE":
        cascades.revoke_authorization(member)
    else:
        member["authorization_status"] = "GRANTED"
        member["authorization_revoked_at"] = None
        rows.touch(member)
    return envelope.ok(serializers.member(member))


@bp.post("/members/<member_id>/remove")
def remove_member(member_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_ACCOUNT_OWNER])
    member = ctx.path("member", member_id)
    ctx.own(member["account_id"])
    account = DB.accounts.get(member["account_id"])
    ctx.write_gates(account)
    states.gate("member_status", member["status"], ("INVITED", "ACTIVE"))
    # Declared transition precondition with no dedicated code: the primary
    # member cannot be removed. Reported through rung 18's generic state code.
    if member["is_primary"]:
        raise ApiError("ERR_INVALID_STATE", "The primary member cannot be removed.")
    cascades.remove_member(member)
    return envelope.ok(serializers.member(member))


@bp.get("/members/<member_id>/monitored-profiles")
def list_member_profiles(member_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    member = ctx.path("member", member_id)
    status = context.enum_filter(request, "status", K.PROFILE_STATUSES)
    limit, offset = context.pagination(request)
    ctx.own(member["account_id"], member["id"])
    result = [
        p
        for p in derive.member_profiles(member["id"])
        if status is None or p["status"] == status
    ]
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.profile(p) for p in page], limit, offset, total)


@bp.get("/members/<member_id>/identity-documents")
def list_documents(member_id):
    ctx = Ctx(
        request,
        [K.ROLE_PLATFORM_ADMIN, K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER],
    )
    member = ctx.path("member", member_id)
    status = context.enum_filter(request, "status", K.DOCUMENT_STATUSES)
    limit, offset = context.pagination(request)
    ctx.own(member["account_id"], member["id"])
    result = [
        d
        for d in DB.documents.values()
        if d["member_id"] == member["id"] and (status is None or d["status"] == status)
    ]
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.document(d) for d in page], limit, offset, total)


@bp.post("/members/<member_id>/identity-documents")
def upload_document(member_id):
    ctx = Ctx(request, [K.ROLE_PRIVACY_AGENT, K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    member = ctx.path("member", member_id)
    ctx.load_body()
    fields = ctx.validate(
        [
            {
                "name": "document_type",
                "type": "string",
                "required": True,
                "enum": K.DOCUMENT_TYPES,
            },
            {"name": "document_reference", "type": "string", "required": True},
            {"name": "expires_at", "type": "datetime", "required": True},
        ]
    )
    # Rung 10 -- expires_at must be at least one second after the current instant.
    expires_dt = parse_instant(fields["expires_at"])
    if (expires_dt - CLOCK.now).total_seconds() < K.IDENTITY_DOC_MIN_LEAD_SECONDS:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    ctx.own(member["account_id"], member["id"])
    account = DB.accounts.get(member["account_id"])
    ctx.write_gates(account)
    document = rows.new_row(
        "documents",
        {
            "member_id": member["id"],
            "document_type": fields["document_type"],
            "document_reference": fields["document_reference"],
            # Verbatim literal for echo, parsed value for logic.
            "expires_at": fields["expires_at"],
            "expires_at_dt": expires_dt,
            "status": "PENDING",
            "verified_at": None,
            "rejection_reason_code": None,
        },
    )
    return envelope.created(serializers.document(document))


@bp.get("/members/<member_id>/exposure-summary")
def exposure_summary(member_id):
    ctx = Ctx(request, ALL_READ_ROLES)
    member = ctx.path("member", member_id)
    ctx.own(member["account_id"], member["id"])
    profiles = derive.member_profiles(member["id"])
    exposures = []
    for profile in profiles:
        exposures.extend(derive.profile_exposures(profile["id"]))

    def tally(status):
        return len([e for e in exposures if e["status"] == status])

    requests = [r for r in DB.removal_requests.values() if r["member_id"] == member["id"]]
    broker_groups = {}
    for e in exposures:
        broker_groups[e["broker_id"]] = broker_groups.get(e["broker_id"], 0) + 1
    brokers = []
    for broker_id, count in broker_groups.items():
        broker = DB.brokers.get(broker_id)
        brokers.append(
            {
                "broker_id": broker_id,
                "name": broker["name"] if broker else None,
                "exposure_count": count,
            }
        )
    brokers.sort(key=lambda b: (-b["exposure_count"], b["name"] or ""))
    suppressed = tally("SUPPRESSED") + tally("RE_SUPPRESSED")
    return envelope.ok(
        {
            "member_id": member["id"],
            "profile_count": len(profiles),
            "exposure_total": len(exposures),
            "found_count": tally("FOUND"),
            "reappeared_count": tally("REAPPEARED"),
            "suppressed_count": tally("SUPPRESSED"),
            "re_suppressed_count": tally("RE_SUPPRESSED"),
            "open_removal_count": len(
                [
                    r
                    for r in requests
                    if r["status"] in ("DRAFTED", "SUBMITTED", "ACKNOWLEDGED", "ESCALATED")
                ]
            ),
            "completed_removal_count": len(
                [r for r in requests if r["status"] == "COMPLETED"]
            ),
            "coverage_ratio": calc.coverage_ratio(suppressed, len(exposures)),
            "brokers": brokers,
        }
    )
