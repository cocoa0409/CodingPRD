"""Protocol authoring, issue, activation and the three terminal outcomes."""

from flask import Blueprint

import config
import ladder
from clock import clock
from errors import ApiError
from store import db, bump, make_row, ordered, touch
from services import serializers
from services.protocols import (
    complete_lines,
    live_items,
    protocol_items,
    reverse_recent_dispenses,
    stop_lines,
)

bp = Blueprint("protocols", __name__)


def _protocol_patient(protocol):
    return db.patients.get(protocol["patient_id"])


@bp.route("/protocols", methods=["POST"])
def create_protocol():
    def handler(ctx):
        patient = ctx.fk["patient_id"]
        predecessor = ctx.fk.get("supersedes_protocol_id")
        version_no = 1
        if predecessor is not None:
            version_no = predecessor["version_no"] + 1
        row = make_row(
            patient_id=patient["id"],
            practitioner_id=ctx.user_id,
            supersedes_protocol_id=ctx.body.get("supersedes_protocol_id"),
            title=ctx.body["title"],
            version_no=version_no,
            status="DRAFT",
            symptom_score_baseline=ctx.body["symptom_score_baseline"],
            advancement_blocked=False,
            interaction_flags=[],
            issued_at=None,
            activated_at=None,
        )
        db.protocols[row["id"]] = row
        bump(patient)
        return serializers.protocol(row)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "body_fks": ["patient_id", "supersedes_protocol_id"],
            "gate": lambda ctx: ctx.fk.get("patient_id"),
            "occ": ("expected_patient_version", lambda ctx: ctx.fk.get("patient_id")),
            "shape": [
                ("patient_id", "string", True),
                ("title", "string", True),
                (
                    "symptom_score_baseline",
                    "int",
                    True,
                    {"min": 0, "max": config.SYMPTOM_SCALE_MAX},
                ),
                ("expected_patient_version", "int", True),
                ("supersedes_protocol_id", "string", False),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/protocols/<prid>", methods=["GET"])
def get_protocol(prid):
    return ladder.run(
        {
            "roles": [
                config.ROLE_PRACTICE_ADMIN,
                config.ROLE_ND,
                config.ROLE_HEALTH_COACH,
                config.ROLE_DISPENSARY_TECH,
                config.ROLE_CLINICAL_DIRECTOR,
                config.ROLE_PATIENT,
            ],
            "path": [("protocol", prid)],
            "owner": lambda ctx: ctx.path["protocol"]["patient_id"],
            "handler": lambda ctx: serializers.protocol(ctx.path["protocol"]),
        }
    )


@bp.route("/protocols", methods=["GET"])
def list_protocols():
    def handler(ctx):
        rows = ordered(db.protocols.values())
        for field in (
            "patient_id",
            "practitioner_id",
            "supersedes_protocol_id",
            "status",
        ):
            value = ctx.args_get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        return ladder.list_result(ctx, rows, serializers.protocol)

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


@bp.route("/protocols/<prid>/items", methods=["POST"])
def add_protocol_item(prid):
    def handler(ctx):
        protocol = ctx.path["protocol"]
        row = make_row(
            protocol_id=protocol["id"],
            product_id=ctx.body["product_id"],
            dose_amount_mg=ctx.body["dose_amount_mg"],
            frequency_per_day=ctx.body["frequency_per_day"],
            duration_days=ctx.body["duration_days"],
            titration_interval_days=ctx.body["titration_interval_days"],
            status="ACTIVE",
            titration_step_no=0,
            last_decision=None,
            last_decision_at=None,
            next_review_due_at=None,
            titration_locked=False,
            discontinue_reason=None,
        )
        db.protocol_items[row["id"]] = row
        bump(protocol)
        return serializers.protocol_item(row)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("protocol", prid)],
            "body_fks": ["product_id"],
            "gate": lambda ctx: _protocol_patient(ctx.path["protocol"]),
            "shape": [
                ("product_id", "string", True),
                ("dose_amount_mg", "number", True, {"positive": True}),
                ("frequency_per_day", "int", True, {"positive": True}),
                ("duration_days", "int", True, {"positive": True}),
                ("titration_interval_days", "int", True, {"positive": True}),
            ],
            "handler": handler,
            "status": 201,
        }
    )


@bp.route("/protocols/<prid>/issue", methods=["POST"])
def issue_protocol(prid):
    def own_state(ctx):
        protocol = ctx.path["protocol"]
        if protocol["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        if not protocol_items(protocol["id"]):
            raise ApiError(
                "ERR_INVALID_STATE", "A protocol must carry at least one line to issue."
            )

    def intake_gate(ctx):
        from services.intake import materialise_patient_intake

        patient = _protocol_patient(ctx.path["protocol"])
        materialise_patient_intake(patient)
        if patient["intake_protocol_score"] < config.INTAKE_PROTOCOL_MIN_SCORE:
            raise ApiError("ERR_INTAKE_INCOMPLETE")

    def contraindication(ctx):
        protocol = ctx.path["protocol"]
        patient = _protocol_patient(protocol)
        reported = set(patient["medication_classes"] or [])
        flags = []
        for item in protocol_items(protocol["id"]):
            product = db.products.get(item["product_id"])
            if product is None:
                continue
            hits = reported.intersection(product["interacts_with_med_classes"] or [])
            if not hits:
                continue
            if product["interaction_severity"] == "SEVERE":
                raise ApiError("ERR_CONTRAINDICATION_SEVERE")
            if product["interaction_severity"] == "MODERATE":
                flags.append(
                    {
                        "protocol_item_id": item["id"],
                        "product_id": product["id"],
                        "interaction_severity": "MODERATE",
                        "medication_classes": sorted(hits),
                    }
                )
        ctx.scratch["interaction_flags"] = flags

    def handler(ctx):
        protocol = ctx.path["protocol"]
        protocol["status"] = "ISSUED"
        protocol["issued_at"] = clock.stamp()
        protocol["interaction_flags"] = ctx.scratch.get("interaction_flags", [])
        bump(protocol)
        return serializers.protocol(protocol)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("protocol", prid)],
            "gate": lambda ctx: _protocol_patient(ctx.path["protocol"]),
            "own_state": own_state,
            "shape": [],
            "business": [intake_gate, contraindication],
            "handler": handler,
        }
    )


@bp.route("/protocols/<prid>/activate", methods=["POST"])
def activate_protocol(prid):
    def own_state(ctx):
        if ctx.path["protocol"]["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        protocol = ctx.path["protocol"]
        protocol["status"] = "ACTIVE"
        protocol["activated_at"] = clock.stamp()

        predecessor = db.protocols.get(protocol.get("supersedes_protocol_id"))
        if predecessor is not None and predecessor["status"] == "ACTIVE":
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)
            stopped = live_items(predecessor["id"])
            stop_lines(stopped, config.REASON_SUPERSEDED_BY_REVISION)
            for item in stopped:
                item["titration_locked"] = False
            # No dispense is reversed on this path: superseding never moves money.
        bump(protocol)
        return serializers.protocol(protocol)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("protocol", prid)],
            "gate": lambda ctx: _protocol_patient(ctx.path["protocol"]),
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )


@bp.route("/protocols/<prid>/complete", methods=["POST"])
def complete_protocol(prid):
    def own_state(ctx):
        if ctx.path["protocol"]["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        protocol = ctx.path["protocol"]
        protocol["status"] = "COMPLETED"
        complete_lines(live_items(protocol["id"]))
        bump(protocol)
        return serializers.protocol(protocol)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("protocol", prid)],
            "own_state": own_state,
            "shape": [],
            "handler": handler,
        }
    )


@bp.route("/protocols/<prid>/discontinue", methods=["POST"])
def discontinue_protocol(prid):
    def own_state(ctx):
        if ctx.path["protocol"]["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")

    def handler(ctx):
        protocol = ctx.path["protocol"]
        stopped = live_items(protocol["id"])
        protocol["status"] = "DISCONTINUED"
        stop_lines(stopped, config.REASON_PROTOCOL_DISCONTINUED)
        reverse_recent_dispenses(stopped)
        bump(protocol)
        return serializers.protocol(protocol)

    return ladder.run(
        {
            "roles": [config.ROLE_ND],
            "path": [("protocol", prid)],
            "own_state": own_state,
            "shape": [("reason", "string", True)],
            "handler": handler,
        }
    )
