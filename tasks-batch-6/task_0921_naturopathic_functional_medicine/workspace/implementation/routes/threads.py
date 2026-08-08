"""Asynchronous message threads and the e-visit conversion."""

from datetime import timedelta

from flask import Blueprint

import config
import ladder
from clock import clock, parse_instant
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.threads import conversion_eligible, sla_breached
from routes.encounters import licensure_ok

bp = Blueprint("threads", __name__)

CLINICAL_ROLES = (config.ROLE_ND, config.ROLE_HEALTH_COACH)


@bp.route("/message-threads", methods=["POST"])
def create_thread():
    def handler(ctx):
        patient = ctx.fk["patient_id"]
        practitioner = ctx.fk["practitioner_id"]
        opened_at = clock.now()
        row = make_row(
            patient_id=patient["id"],
            practitioner_id=practitioner["id"],
            subject=ctx.body["subject"],
            status="OPEN",
            patient_message_count=1,
            clinician_message_count=0,
            clinical_minutes_total=0,
            opened_at=clock.stamp(),
            sla_due_at=clock.render(
                opened_at + timedelta(hours=config.MESSAGE_SLA_HOURS)
            ),
            first_clinical_reply_at=None,
            sla_breached=False,
            evisit_conversion_eligible=False,
        )
        db.threads[row["id"]] = row
        return serializers.thread(row)

    return ladder.run(
        {
            "roles": [config.ROLE_PATIENT],
            "body_fks": ["patient_id", "practitioner_id"],
            "owner": lambda ctx: ctx.fk["patient_id"]["id"]
            if ctx.fk.get("patient_id")
            else None,
            "shape": [
                ("patient_id", "string", True),
                ("practitioner_id", "string", True),
                ("subject", "string", True),
                ("body", "string", True),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/message-threads/<tid>", methods=["GET"])
def get_thread(tid):
    def handler(ctx):
        thread = ctx.path["thread"]
        thread["sla_breached"] = sla_breached(thread)
        thread["evisit_conversion_eligible"] = conversion_eligible(thread)
        return serializers.thread(thread)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_PATIENT,
            ],
            "path": [("thread", tid)],
            "owner": lambda ctx: ctx.path["thread"]["patient_id"],
            "handler": handler,
        }
    )


@bp.route("/message-threads", methods=["GET"])
def list_threads():
    def handler(ctx):
        rows = ordered(db.threads.values())
        for field in ("patient_id", "practitioner_id", "status"):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.thread)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/message-threads/<tid>/messages", methods=["POST"])
def post_message(tid):
    def own_state(ctx):
        if ctx.path["thread"]["status"] not in ("OPEN", "ANSWERED"):
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        thread = ctx.path["thread"]
        if ctx.role in CLINICAL_ROLES:
            minutes = ctx.body.get("clinical_minutes") or 0
            thread["clinician_message_count"] += 1
            thread["clinical_minutes_total"] += minutes
            if thread["first_clinical_reply_at"] is None:
                thread["first_clinical_reply_at"] = clock.stamp()
            thread["status"] = "ANSWERED"
        else:
            thread["patient_message_count"] += 1
            thread["status"] = "OPEN"
        thread["sla_breached"] = sla_breached(thread)
        thread["evisit_conversion_eligible"] = conversion_eligible(thread)
        bump(thread)
        return serializers.thread(thread)

    return ladder.run(
        {
            "roles": [config.ROLE_PATIENT, config.ROLE_ND, config.ROLE_HEALTH_COACH],
            "path": [("thread", tid)],
            "owner": lambda ctx: ctx.path["thread"]["patient_id"],
            "own_state": own_state,
            "shape": [
                ("body", "string", True),
                ("clinical_minutes", "int", False, {"min": 0}),
            ],
            "handler": handler,
        }
    )


@bp.route("/message-threads/<tid>/convert-to-evisit", methods=["POST"])
def convert_to_evisit(tid):
    def own_state(ctx):
        if ctx.path["thread"]["status"] not in ("OPEN", "ANSWERED"):
            raise ApiError("ERR_INVALID_STATE")

    def dependent_state(ctx):
        if not conversion_eligible(ctx.path["thread"]):
            raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    def licensure(ctx):
        thread = ctx.path["thread"]
        patient = db.patients.get(thread["patient_id"])
        practitioner = db.practitioners.get(thread["practitioner_id"])
        if patient is None or practitioner is None:
            return
        if not licensure_ok(patient, practitioner):
            raise ApiError("ERR_STATE_NOT_LICENSED")

    def consent(ctx):
        patient = db.patients.get(ctx.path["thread"]["patient_id"])
        if patient is not None and not patient["telehealth_consent"]:
            raise ApiError("ERR_MODALITY_CONSENT_MISSING")

    def handler(ctx):
        thread = ctx.path["thread"]
        patient = db.patients.get(thread["patient_id"])
        encounter = make_row(
            patient_id=thread["patient_id"],
            practitioner_id=thread["practitioner_id"],
            source_thread_id=thread["id"],
            modality="EVISIT",
            scheduled_start=None,
            scheduled_end=None,
            scheduling_status="COMPLETED",
            billing_status="CASH_CHARGED",
            duration_minutes=config.EXTENDED_VISIT_BLOCK_MINUTES,
            service_code=None,
            diagnosis_codes=[],
            base_fee_cents=config.EVISIT_FEE_CENTS,
            extended_block_count=0,
            cash_charged_cents=config.EVISIT_FEE_CENTS,
            entitlement_consumed=False,
            completed_at=clock.stamp(),
            cancelled_at=None,
            cancel_reason=None,
        )
        db.encounters[encounter["id"]] = encounter
        if patient is not None:
            patient["cash_charged_total_cents"] += config.EVISIT_FEE_CENTS
            touch(patient)
        thread["status"] = "CONVERTED_TO_EVISIT"
        touch(thread)
        return serializers.encounter(encounter)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("thread", tid)],
            "own_state": own_state,
            "dependent_state": dependent_state,
            "shape": [],
            "business": [licensure, consent],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/message-threads/<tid>/close", methods=["POST"])
def close_thread(tid):
    def own_state(ctx):
        if ctx.path["thread"]["status"] not in ("OPEN", "ANSWERED"):
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        thread = ctx.path["thread"]
        thread["status"] = "CLOSED"
        bump(thread)
        return serializers.thread(thread)

    return ladder.run(
        {
            "roles": [config.ROLE_ND, config.ROLE_HEALTH_COACH],
            "path": [("thread", tid)],
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )
