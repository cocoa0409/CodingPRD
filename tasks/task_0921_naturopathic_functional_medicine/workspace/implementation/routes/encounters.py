"""Encounters: booking, settlement, cancellation and no-show."""

import math
from datetime import timedelta

from flask import Blueprint

import config
import ladder
from clock import clock, parse_instant
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.dispensary import membership_with_visits
from services.intake import materialise_patient_intake

bp = Blueprint("encounters", __name__)

BASE_FEE = {
    "IN_PERSON": config.VISIT_FEE_IN_PERSON_CENTS,
    "TELEHEALTH": config.VISIT_FEE_TELEHEALTH_CENTS,
    "EVISIT": config.EVISIT_FEE_CENTS,
}


def extended_block_count(duration_minutes):
    """Ceiling of the excess over the threshold; the threshold itself is inclusive."""
    if duration_minutes is None or duration_minutes <= config.EXTENDED_VISIT_THRESHOLD_MINUTES:
        return 0
    excess = duration_minutes - config.EXTENDED_VISIT_THRESHOLD_MINUTES
    return int(math.ceil(excess / float(config.EXTENDED_VISIT_BLOCK_MINUTES)))


def licensure_ok(patient, practitioner):
    return patient["state_code"] in (practitioner["licensed_state_codes"] or [])


@bp.route("/encounters", methods=["POST"])
def create_encounter():
    def cross(ctx):
        start = parse_instant(ctx.body.get("scheduled_start"))
        end = parse_instant(ctx.body.get("scheduled_end"))
        if start is not None and end is not None and end <= start:
            raise ApiError(
                "ERR_VALIDATION", "scheduled_end must be strictly after scheduled_start."
            )

    def intake_gate(ctx):
        patient = ctx.fk["patient_id"]
        materialise_patient_intake(patient)
        if patient["intake_booking_score"] < config.INTAKE_BOOKING_MIN_SCORE:
            raise ApiError("ERR_INTAKE_INCOMPLETE")

    def licensure(ctx):
        if ctx.body["modality"] not in ("TELEHEALTH", "EVISIT"):
            return
        if not licensure_ok(ctx.fk["patient_id"], ctx.fk["practitioner_id"]):
            raise ApiError("ERR_STATE_NOT_LICENSED")

    def consent(ctx):
        if ctx.body["modality"] not in ("TELEHEALTH", "EVISIT"):
            return
        if not ctx.fk["patient_id"]["telehealth_consent"]:
            raise ApiError("ERR_MODALITY_CONSENT_MISSING")

    def occupancy(ctx):
        modality = ctx.body["modality"]
        if modality == "EVISIT":
            return  # an e-visit never occupies the practitioner
        start = parse_instant(ctx.body["scheduled_start"])
        end = parse_instant(ctx.body["scheduled_end"])
        practitioner_id = ctx.fk["practitioner_id"]["id"]
        for row in db.encounters.values():
            if row["practitioner_id"] != practitioner_id:
                continue
            if row["scheduling_status"] not in ("SCHEDULED", "COMPLETED"):
                continue
            if row["modality"] == "EVISIT":
                continue
            other_start = parse_instant(row["scheduled_start"])
            other_end = parse_instant(row["scheduled_end"])
            if other_start is None or other_end is None:
                continue
            if row["modality"] == "TELEHEALTH" and modality == "TELEHEALTH":
                other_end = other_end + timedelta(
                    minutes=config.TELEHEALTH_TURNAROUND_BUFFER_MINUTES
                )
            # HALF-OPEN [start, end): touching windows do not collide.
            if start < other_end and other_start < end:
                raise ApiError("ERR_PRACTITIONER_DOUBLE_BOOKED")

    def handler(ctx):
        patient = ctx.fk["patient_id"]
        practitioner = ctx.fk["practitioner_id"]
        modality = ctx.body["modality"]
        row = make_row(
            patient_id=patient["id"],
            practitioner_id=practitioner["id"],
            source_thread_id=None,
            modality=modality,
            scheduled_start=ctx.body["scheduled_start"],
            scheduled_end=ctx.body["scheduled_end"],
            scheduling_status="SCHEDULED",
            billing_status="CASH_PENDING",
            duration_minutes=None,
            service_code=None,
            diagnosis_codes=[],
            base_fee_cents=0,
            extended_block_count=0,
            cash_charged_cents=0,
            entitlement_consumed=False,
            completed_at=None,
            cancelled_at=None,
            cancel_reason=None,
        )
        if modality in ("IN_PERSON", "TELEHEALTH"):
            membership = membership_with_visits(patient["id"])
            if membership is not None:
                membership["visits_consumed"] += 1
                membership["visits_remaining"] -= 1
                bump(membership)
                row["billing_status"] = "ENTITLEMENT_RESERVED"
                row["entitlement_consumed"] = True
                row["_membership_id"] = membership["id"]
        db.encounters[row["id"]] = row
        return serializers.encounter(row)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_PATIENT,
            ],
            "body_fks": ["patient_id", "practitioner_id"],
            "owner": lambda ctx: ctx.fk["patient_id"]["id"]
            if ctx.fk.get("patient_id")
            else None,
            "shape": [
                ("patient_id", "string", True),
                ("practitioner_id", "string", True),
                ("modality", "string", True),
                ("scheduled_start", "datetime", True),
                ("scheduled_end", "datetime", True),
            ],
            "cross": cross,
            "enums": {"modality": config.MODALITIES},
            "business": [intake_gate, licensure, consent, occupancy],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/encounters/<eid>", methods=["GET"])
def get_encounter(eid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_BILLING,
                config.ROLE_PATIENT,
            ],
            "path": [("encounter", eid)],
            "owner": lambda ctx: ctx.path["encounter"]["patient_id"],
            "handler": lambda ctx: serializers.encounter(ctx.path["encounter"]),
        }
    )


@bp.route("/encounters", methods=["GET"])
def list_encounters():
    def handler(ctx):
        rows = ordered(db.encounters.values())
        for field in (
            "patient_id",
            "practitioner_id",
            "source_thread_id",
            "scheduling_status",
            "billing_status",
        ):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.encounter)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_BILLING,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/encounters/<eid>/complete", methods=["POST"])
def complete_encounter(eid):
    def own_state(ctx):
        if ctx.path["encounter"]["scheduling_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        encounter = ctx.path["encounter"]
        patient = db.patients.get(encounter["patient_id"])
        encounter["duration_minutes"] = ctx.body["duration_minutes"]
        encounter["service_code"] = ctx.body["service_code"]
        encounter["diagnosis_codes"] = ctx.body["diagnosis_codes"]
        encounter["scheduling_status"] = "COMPLETED"
        encounter["completed_at"] = clock.stamp()

        base_fee = BASE_FEE[encounter["modality"]]
        blocks = extended_block_count(encounter["duration_minutes"])
        extended_cents = blocks * config.EXTENDED_VISIT_BLOCK_FEE_CENTS
        encounter["base_fee_cents"] = base_fee
        encounter["extended_block_count"] = blocks

        if encounter["billing_status"] == "ENTITLEMENT_RESERVED":
            # Entitlement is the first bucket and covers the base fee only.
            encounter["cash_charged_cents"] = extended_cents
            encounter["billing_status"] = "ENTITLEMENT_CONSUMED"
        else:
            encounter["cash_charged_cents"] = base_fee + extended_cents
            encounter["billing_status"] = "CASH_CHARGED"

        if patient is not None:
            patient["cash_charged_total_cents"] += encounter["cash_charged_cents"]
            if patient["clinical_status"] == "INTAKE":
                patient["clinical_status"] = "ESTABLISHED"
                bump(patient)
            else:
                touch(patient)
        bump(encounter)
        return serializers.encounter(encounter)

    return ladder.run(
        {
            "roles": [config.ROLE_ND, config.ROLE_HEALTH_COACH],
            "path": [("encounter", eid)],
            "own_state": own_state,
            "shape": [
                ("duration_minutes", "int", True, {"positive": True}),
                ("service_code", "string", True),
                ("diagnosis_codes", "array", True, {"of": "string"}),
            ],
            "handler": handler,
        }
    )


@bp.route("/encounters/<eid>/cancel", methods=["POST"])
def cancel_encounter(eid):
    def own_state(ctx):
        if ctx.path["encounter"]["scheduling_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        encounter = ctx.path["encounter"]
        patient = db.patients.get(encounter["patient_id"])
        encounter["scheduling_status"] = "CANCELLED"
        encounter["cancelled_at"] = clock.stamp()
        encounter["cancel_reason"] = ctx.body["reason"]

        start = parse_instant(encounter["scheduled_start"])
        # The boundary is inclusive: exactly 24 hours ahead still refunds.
        timely = start is not None and (start - clock.now()) >= timedelta(
            hours=config.ENCOUNTER_CANCEL_REFUND_WINDOW_HOURS
        )

        if encounter["billing_status"] == "ENTITLEMENT_RESERVED":
            membership = db.memberships.get(encounter.get("_membership_id"))
            if timely:
                encounter["billing_status"] = "REFUNDED"
                if membership is not None:
                    membership["visits_consumed"] -= 1
                    membership["visits_remaining"] += 1
                    bump(membership)
            else:
                encounter["billing_status"] = "FORFEITED"
                if membership is not None:
                    membership["visits_consumed"] -= 1
                    membership["visits_forfeited"] += 1
                    bump(membership)
            encounter["entitlement_consumed"] = False
        elif encounter["billing_status"] == "CASH_PENDING":
            if timely:
                encounter["billing_status"] = "REFUNDED"
            else:
                encounter["billing_status"] = "CASH_CHARGED"
                encounter["cash_charged_cents"] = config.LATE_CANCEL_NO_SHOW_FEE_CENTS
                if patient is not None:
                    patient["cash_charged_total_cents"] += (
                        config.LATE_CANCEL_NO_SHOW_FEE_CENTS
                    )
                    touch(patient)
        bump(encounter)
        return serializers.encounter(encounter)

    return ladder.run(
        {
            "roles": [config.ROLE_PATIENT, config.ROLE_PRACTICE_ADMIN, config.ROLE_ND],
            "path": [("encounter", eid)],
            "owner": lambda ctx: ctx.path["encounter"]["patient_id"],
            "own_state": own_state,
            "shape": [("reason", "string", True)],
            "handler": handler,
        }
    )


@bp.route("/encounters/<eid>/no-show", methods=["POST"])
def no_show_encounter(eid):
    def own_state(ctx):
        if ctx.path["encounter"]["scheduling_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        encounter = ctx.path["encounter"]
        patient = db.patients.get(encounter["patient_id"])
        encounter["scheduling_status"] = "NO_SHOW"
        if encounter["billing_status"] == "ENTITLEMENT_RESERVED":
            # The reserved unit is consumed and never returned.
            encounter["billing_status"] = "ENTITLEMENT_CONSUMED"
            encounter["cash_charged_cents"] = 0
        elif encounter["billing_status"] == "CASH_PENDING":
            encounter["billing_status"] = "CASH_CHARGED"
            encounter["cash_charged_cents"] = config.LATE_CANCEL_NO_SHOW_FEE_CENTS
            if patient is not None:
                patient["cash_charged_total_cents"] += (
                    config.LATE_CANCEL_NO_SHOW_FEE_CENTS
                )
                touch(patient)
        bump(encounter)
        return serializers.encounter(encounter)

    return ladder.run(
        {
            "roles": [config.ROLE_ND, config.ROLE_HEALTH_COACH, config.ROLE_PRACTICE_ADMIN],
            "path": [("encounter", eid)],
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )
