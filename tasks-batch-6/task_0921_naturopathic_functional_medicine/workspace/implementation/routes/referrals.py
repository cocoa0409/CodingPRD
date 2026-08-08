"""Referrals: routine raising and loop closure."""

from datetime import timedelta

from flask import Blueprint

import config
import ladder
from clock import clock, render_date
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.gate import recompute_gate

bp = Blueprint("referrals", __name__)

ACTION_SOURCE_STATES = {
    "ACKNOWLEDGE": ("SENT",),
    "REPORT": ("ACKNOWLEDGED",),
    "CLOSE": ("REPORT_RECEIVED",),
    "DECLINE": ("SENT",),
    "RE_REFER": ("DECLINED",),
}


@bp.route("/referrals", methods=["POST"])
def create_referral():
    def handler(ctx):
        row = make_row(
            patient_id=ctx.fk["patient_id"]["id"],
            referring_practitioner_id=ctx.user_id,
            lab_order_id=None,
            referral_type="ROUTINE",
            recipient_name=ctx.body["recipient_name"],
            specialty=ctx.body["specialty"],
            reason=ctx.body["reason"],
            status="SENT",
            attempt_no=1,
            due_by_date=render_date(
                clock.today() + timedelta(days=config.RED_FLAG_REFERRAL_DUE_DAYS)
            ),
            acknowledged_at=None,
            report_summary=None,
            report_received_at=None,
            closed_at=None,
            decline_reason=None,
        )
        db.referrals[row["id"]] = row
        return serializers.referral(row)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "body_fks": ["patient_id"],
            "shape": [
                ("patient_id", "string", True),
                ("recipient_name", "string", True),
                ("specialty", "string", True),
                ("reason", "string", True),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_PATIENT,
            ],
            "path": [("referral", rid)],
            "owner": lambda ctx: ctx.path["referral"]["patient_id"],
            "handler": lambda ctx: serializers.referral(ctx.path["referral"]),
        }
    )


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    def handler(ctx):
        rows = ordered(db.referrals.values())
        for field in (
            "patient_id",
            "lab_order_id",
            "referring_practitioner_id",
            "referral_type",
            "status",
        ):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.referral)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_CLINICAL_DIRECTOR,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/referrals/<rid>/transitions", methods=["POST"])
def referral_transition(rid):
    def own_state(ctx):
        action = ctx.body.get("action")
        if action not in ACTION_SOURCE_STATES:
            return
        if ctx.path["referral"]["status"] not in ACTION_SOURCE_STATES[action]:
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        referral = ctx.path["referral"]
        action = ctx.body["action"]

        if action == "ACKNOWLEDGE":
            referral["status"] = "ACKNOWLEDGED"
            referral["acknowledged_at"] = clock.stamp()
        elif action == "REPORT":
            referral["status"] = "REPORT_RECEIVED"
            referral["report_summary"] = ctx.body.get("report_summary")
            referral["report_received_at"] = clock.stamp()
        elif action == "CLOSE":
            referral["status"] = "CLOSED"
            referral["closed_at"] = clock.stamp()
        elif action == "DECLINE":
            referral["status"] = "DECLINED"
            referral["decline_reason"] = ctx.body.get("decline_reason")
        else:  # RE_REFER
            if referral["attempt_no"] < config.REFERRAL_MAX_ATTEMPTS:
                referral["status"] = "SENT"
                referral["attempt_no"] += 1
                if ctx.body.get("recipient_name") is not None:
                    referral["recipient_name"] = ctx.body["recipient_name"]
                referral["decline_reason"] = None
            else:
                referral["status"] = "ABANDONED"
        bump(referral)

        patient = db.patients.get(referral["patient_id"])
        if patient is not None:
            before = patient["clinical_write_gate"]
            recompute_gate(patient)
            if patient["clinical_write_gate"] != before:
                touch(patient)
        return serializers.referral(referral)

    return ladder.run(
        {
            "roles": [config.ROLE_ND, config.ROLE_PRACTICE_ADMIN],
            "path": [("referral", rid)],
            "own_state": own_state,
            "shape": [
                ("action", "string", True),
                ("recipient_name", "string", False),
                ("decline_reason", "string", False),
                ("report_summary", "string", False),
            ],
            "enums": {"action": config.REFERRAL_ACTIONS},
            "handler": handler,
        }
    )
