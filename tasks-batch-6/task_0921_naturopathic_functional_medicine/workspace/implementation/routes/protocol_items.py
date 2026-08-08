"""Protocol lines: reads, titration decisions and adverse-reaction reports."""

from flask import Blueprint

import config
import ladder
from clock import clock
from errors import ApiError
from store import db, bump, ordered, touch
from services import serializers
from services.protocols import cascade_after_line_stop, decide, next_dose, next_review

bp = Blueprint("protocol_items", __name__)


def _item_protocol(item):
    return db.protocols.get(item["protocol_id"])


def _item_patient(item):
    protocol = _item_protocol(item)
    return db.patients.get(protocol["patient_id"]) if protocol else None


def _item_patient_id(item):
    protocol = _item_protocol(item)
    return protocol["patient_id"] if protocol else None


@bp.route("/protocol-items/<iid>", methods=["GET"])
def get_protocol_item(iid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_DISPENSARY_TECH,
                config.ROLE_PATIENT,
            ],
            "path": [("protocol_item", iid)],
            "owner": lambda ctx: _item_patient_id(ctx.path["protocol_item"]),
            "handler": lambda ctx: serializers.protocol_item(ctx.path["protocol_item"]),
        }
    )


@bp.route("/protocol-items", methods=["GET"])
def list_protocol_items():
    def handler(ctx):
        rows = ordered(db.protocol_items.values())
        for field in ("protocol_id", "product_id", "status"):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.protocol_item)

    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_DISPENSARY_TECH,
            ],
            "paginated": True,
            "handler": handler,
        }
    )


@bp.route("/protocol-items/<iid>/titration-decisions", methods=["POST"])
def titration_decision(iid):
    def own_state(ctx):
        if ctx.path["protocol_item"]["status"] not in ("ACTIVE", "HELD"):
            raise ApiError("ERR_INVALID_STATE")

    def dependent_state(ctx):
        item = ctx.path["protocol_item"]
        protocol = _item_protocol(item)
        if protocol is None or protocol["status"] != "ACTIVE":
            raise ApiError("ERR_DEPENDENT_STATE_INVALID")
        if item["titration_locked"]:
            raise ApiError("ERR_DEPENDENT_STATE_INVALID")

    def handler(ctx):
        item = ctx.path["protocol_item"]
        protocol = _item_protocol(item)
        decision, _delta = decide(
            protocol["symptom_score_baseline"], ctx.body["current_symptom_score"]
        )
        decision_at = clock.stamp()
        item["dose_amount_mg"] = next_dose(decision, item["dose_amount_mg"])
        item["titration_step_no"] += 1
        item["last_decision"] = decision
        item["last_decision_at"] = decision_at
        item["next_review_due_at"] = next_review(decision, item, decision_at)

        if decision == "ADVANCE" or decision == "REDUCE":
            item["status"] = "ACTIVE"
        elif decision == "HOLD":
            item["status"] = "HELD"
        else:
            item["status"] = "DISCONTINUED"
            item["discontinue_reason"] = config.REASON_PROTOCOL_DISCONTINUED
        bump(item)

        if decision == "DISCONTINUE":
            cascade_after_line_stop(protocol)
        return serializers.protocol_item(item)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("protocol_item", iid)],
            "gate": lambda ctx: _item_patient(ctx.path["protocol_item"]),
            "own_state": own_state,
            "dependent_state": dependent_state,
            "shape": [
                (
                    "current_symptom_score",
                    "int",
                    True,
                    {"min": 0, "max": config.SYMPTOM_SCALE_MAX},
                )
            ],
            "handler": handler,
        }
    )


@bp.route("/protocol-items/<iid>/adverse-reactions", methods=["POST"])
def adverse_reaction(iid):
    def own_state(ctx):
        # Only a SEVERE report drives a transition; MILD and MODERATE never do.
        if ctx.body.get("severity") != "SEVERE":
            return
        if ctx.path["protocol_item"]["status"] not in ("ACTIVE", "HELD"):
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        item = ctx.path["protocol_item"]
        if ctx.body["severity"] != "SEVERE":
            return serializers.protocol_item(item)
        item["status"] = "DISCONTINUED"
        item["next_review_due_at"] = None
        item["discontinue_reason"] = config.REASON_ADVERSE_REACTION
        bump(item)
        cascade_after_line_stop(_item_protocol(item))
        return serializers.protocol_item(item)

    return ladder.run(
        {
            "roles": [config.ROLE_PATIENT, config.ROLE_ND, config.ROLE_HEALTH_COACH],
            "path": [("protocol_item", iid)],
            "owner": lambda ctx: _item_patient_id(ctx.path["protocol_item"]),
            "own_state": own_state,
            "shape": [
                ("severity", "string", True),
                ("description", "string", True),
            ],
            "enums": {"severity": config.ADVERSE_REACTION_SEVERITIES},
            "handler": handler,
        }
    )
