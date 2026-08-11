"""The broker catalogue and its compliance report (PRD §3.5, §3.9)."""

from flask import Blueprint, request

import calc
import constants as K
import derive
import envelope
import rows
import serializers
from clock import CLOCK
from context import Ctx
from errors import ApiError
from store import DB

bp = Blueprint("brokers", __name__)


@bp.post("/brokers")
def register_broker():
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "name", "type": "string", "required": True},
            {
                "name": "opt_out_method",
                "type": "string",
                "required": True,
                "enum": K.OPT_OUT_METHODS,
            },
            {
                "name": "jurisdiction",
                "type": "string",
                "required": True,
                "enum": K.JURISDICTIONS,
            },
            {
                "name": "response_window_days",
                "type": "integer",
                "required": True,
                "min": K.BROKER_WINDOW_MIN_DAYS,
                "max": K.BROKER_WINDOW_MAX_DAYS,
            },
            {
                "name": "requires_identity_verification",
                "type": "boolean",
                "required": False,
                "default": False,
            },
        ]
    )
    broker = rows.new_row(
        "brokers",
        {
            "name": fields["name"],
            "opt_out_method": fields["opt_out_method"],
            "jurisdiction": fields["jurisdiction"],
            "response_window_days": fields["response_window_days"],
            "requires_identity_verification": fields["requires_identity_verification"],
            "status": "ACTIVE",
            "retired_at": None,
        },
    )
    return envelope.created(serializers.broker(broker))


@bp.post("/brokers/<broker_id>/retire")
def retire_broker(broker_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    broker = ctx.path("broker", broker_id)
    # The broker catalogue is operator-owned and not account-scoped, so the
    # global write gates do not apply here.
    if broker["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    broker["status"] = "RETIRED"
    broker["retired_at"] = CLOCK.now
    rows.touch(broker)
    return envelope.ok(serializers.broker(broker))


@bp.get("/brokers/<broker_id>/compliance-report")
def compliance_report(broker_id):
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN, K.ROLE_PRIVACY_AGENT, K.ROLE_AUDITOR])
    broker = ctx.path("broker", broker_id)
    # `scope` IS on rung 8's closed list.
    raw_scope = request.args.get("scope")
    if raw_scope is None or raw_scope == "":
        scope = "LIFETIME"
    elif raw_scope in K.COMPLIANCE_SCOPES:
        scope = raw_scope
    else:
        raise ApiError("ERR_INVALID_ENUM", "Filter 'scope' carries an undeclared value.")

    if scope == "LIFETIME":
        counts = derive.broker_counts_lifetime(broker["id"])
    else:
        counts = derive.broker_counts_current_window(broker["id"])
    reappearances, expired, rejected, on_time = counts

    best = {}
    for exposure in derive.broker_exposures(broker["id"]):
        if exposure["reappearance_count"] < 1:
            continue
        profile_id = exposure["profile_id"]
        current = best.get(profile_id)
        if current is None or exposure["reappearance_count"] > current:
            best[profile_id] = exposure["reappearance_count"]
    ranked = []
    for profile_id, count in best.items():
        profile = DB.profiles.get(profile_id)
        if profile is None:
            continue
        ranked.append((-count, profile["created_at"], profile["id"], count))
    ranked.sort(key=lambda t: (t[0], t[1], t[2]))
    top = [
        {"profile_id": entry[2], "reappearance_count": entry[3]}
        for entry in ranked[: K.COMPLIANCE_REPORT_TOP_N]
    ]

    return envelope.ok(
        {
            "broker_id": broker["id"],
            "scope": scope,
            "reappearance_count": reappearances,
            "expired_request_count": expired,
            "rejected_request_count": rejected,
            "on_time_completion_count": on_time,
            "compliance_score": calc.compliance_score(
                reappearances, expired, rejected, on_time
            ),
            "top_offending_profiles": top,
        }
    )
