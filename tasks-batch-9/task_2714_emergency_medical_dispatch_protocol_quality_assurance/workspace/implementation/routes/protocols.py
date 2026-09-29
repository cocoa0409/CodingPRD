"""Protocol versions, approval and rollouts (PRD 3.2, 3.3)."""
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import cascades
import helpers
import validate
from auth import ALL_OPERATORS, require
from cascades import set_fields
from envelope import ok, public
from errors import fail
from store import base_row, clock, db

bp = Blueprint("protocols", __name__)

FAMILIES = ("MPDS_CARDSET", "LOCAL_CARDSET")
VERSION_STATUSES = ("DRAFT", "APPROVED", "ACTIVE", "SUPERSEDED")
PINNABLE_STATUSES = ("APPROVED", "ACTIVE", "SUPERSEDED")
WEIGHT_FIELDS = (
    "case_entry_weight",
    "key_questions_weight",
    "pre_arrival_weight",
    "final_coding_weight",
)


def interval_overlaps(a_from, a_to, b_from, b_to):
    """Half-open [from, to) with a null `to` meaning no upper bound."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


def version_in_force(program_id, instant):
    """PRD 3.4 — the single MPDS_CARDSET version governing an instant."""
    for version in db.protocol_versions.values():
        if version["program_id"] != program_id:
            continue
        if version["protocol_family"] != "MPDS_CARDSET":
            continue
        if version["status"] not in PINNABLE_STATUSES:
            continue
        if version["effective_from"] > instant:
            continue
        if version["effective_to"] is not None and version["effective_to"] <= instant:
            continue
        return version
    return None


@bp.post("/audit-programs/<program_id>/protocol-versions")
@require("ProgramAdmin")
def register_version(program_id):
    payload = validate.body()
    family = validate.get_enum(payload, "protocol_family", FAMILIES)
    label = validate.get_str(payload, "version_label")
    effective_from = validate.get_instant(payload, "effective_from")
    effective_to = validate.get_instant(payload, "effective_to", required=False)
    weights = {}
    for field in WEIGHT_FIELDS:
        weights[field] = calc.q4(validate.get_decimal(payload, field))

    # PRD 3.2 — weights sum to exactly 1.0000 at 4 dp and none is negative.
    if any(weights[field] < Decimal("0") for field in WEIGHT_FIELDS):
        fail("ERR_WEIGHTS_NOT_NORMALIZED", "Section weights may not be negative.")
    total = sum(weights[field] for field in WEIGHT_FIELDS)
    if calc.q4(total) != Decimal("1.0000"):
        fail(
            "ERR_WEIGHTS_NOT_NORMALIZED",
            "The four section weights must sum to exactly 1.0000.",
        )

    program = helpers.program(program_id)

    if effective_to is not None and effective_to <= effective_from:
        fail("ERR_INVALID_TIME_WINDOW", "effective_to must be after effective_from.")

    version = base_row()
    version.update(
        {
            "program_id": program["id"],
            "protocol_family": family,
            "version_label": label,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "DRAFT",
            "approved_by_user_id": None,
            "activated_at": None,
            "superseded_at": None,
        }
    )
    version.update(weights)
    db.protocol_versions[version["id"]] = version
    return ok(public(version), 201)


@bp.get("/audit-programs/<program_id>/protocol-versions")
@require(*ALL_OPERATORS)
def list_versions(program_id):
    limit, offset = validate.pagination()
    program = helpers.program(program_id)
    filters = {
        "status": request.args.get("status"),
        "protocol_family": request.args.get("protocol_family"),
    }
    rows = [
        v
        for v in db.protocol_versions.values()
        if v["program_id"] == program["id"] and helpers.matches(v, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


@bp.get("/protocol-versions/<version_id>")
@require(*ALL_OPERATORS)
def read_version(version_id):
    return ok(public(helpers.protocol_version(version_id)))


@bp.post("/protocol-versions/<version_id>/approve")
@require("MedicalDirector")
def approve_version(version_id):
    payload = validate.body()
    validate.get_str(payload, "approval_note", required=False)
    version = helpers.protocol_version(version_id)

    if version["status"] != "DRAFT":
        fail("ERR_VERSION_NOT_APPROVABLE", "Only a DRAFT version may be approved.")

    total = sum(version[field] for field in WEIGHT_FIELDS)
    if calc.q4(total) != Decimal("1.0000"):
        fail(
            "ERR_WEIGHTS_NOT_NORMALIZED",
            "The four section weights must sum to exactly 1.0000.",
        )

    # Draft versions are invisible to this check (PRD 3.2).
    for other in db.protocol_versions.values():
        if other["id"] == version["id"]:
            continue
        if other["program_id"] != version["program_id"]:
            continue
        if other["protocol_family"] != version["protocol_family"]:
            continue
        if other["status"] not in PINNABLE_STATUSES:
            continue
        if interval_overlaps(
            version["effective_from"],
            version["effective_to"],
            other["effective_from"],
            other["effective_to"],
        ):
            fail(
                "ERR_PROTOCOL_WINDOW_OVERLAP",
                "The governing interval overlaps version %s." % other["version_label"],
            )

    set_fields(version, {"status": "APPROVED", "approved_by_user_id": g.user_id})
    return ok(public(version))


@bp.post("/protocol-versions/<version_id>/rollouts")
@require("ProgramAdmin")
def create_rollout(version_id):
    payload = validate.body()
    scheduled = validate.get_instant(payload, "scheduled_golive_at")
    target_count = validate.get_int(payload, "target_dispatcher_count", minimum=1)
    hours = validate.get_decimal(
        payload,
        "required_training_hours",
        required=False,
        default=Decimal("2.0"),
        exclusive_min=0,
    )
    version = helpers.protocol_version(version_id)

    trained = cascades.trained_count_for_version(version["id"])
    rollout = base_row()
    rollout.update(
        {
            "protocol_version_id": version["id"],
            "scheduled_golive_at": scheduled,
            "target_dispatcher_count": target_count,
            "required_training_hours": calc.q1(hours),
            "trained_dispatcher_count": trained,
            "training_status": cascades.training_status_for(trained, target_count),
            "golive_status": "SCHEDULED",
            "went_live_at": None,
        }
    )
    db.rollouts[rollout["id"]] = rollout
    return ok(public(rollout), 201)


@bp.get("/protocol-versions/<version_id>/rollouts")
@require("ProgramAdmin", "QaSupervisor", "MedicalDirector")
def list_rollouts(version_id):
    limit, offset = validate.pagination()
    version = helpers.protocol_version(version_id)
    filters = {"golive_status": request.args.get("golive_status")}
    rows = [
        r
        for r in db.rollouts.values()
        if r["protocol_version_id"] == version["id"] and helpers.matches(r, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


@bp.get("/protocol-versions/<version_id>/retraining-sessions")
@require("ProgramAdmin", "QaSupervisor", "MedicalDirector")
def list_curriculum_sessions(version_id):
    limit, offset = validate.pagination()
    version = helpers.protocol_version(version_id)
    filters = {"status": request.args.get("status")}
    rows = [
        s
        for s in db.sessions.values()
        if s["protocol_version_id"] == version["id"] and helpers.matches(s, filters)
    ]
    return helpers.respond_list(rows, limit, offset)


@bp.post("/protocol-rollouts/<rollout_id>/go-live")
@require("ProgramAdmin")
def go_live(rollout_id):
    payload = validate.body()
    validate.get_str(payload, "golive_note", required=False)
    rollout = helpers.rollout(rollout_id)
    version = db.protocol_versions.get(rollout["protocol_version_id"])

    if rollout["golive_status"] != "SCHEDULED" or version is None or version["status"] != "APPROVED":
        fail(
            "ERR_ROLLOUT_NOT_LIVEABLE",
            "The rollout must still be SCHEDULED on an APPROVED version.",
        )

    # The training dimension is derived, so read it fresh before the guard.
    trained = cascades.trained_count_for_version(version["id"])
    set_fields(
        rollout,
        {
            "trained_dispatcher_count": trained,
            "training_status": cascades.training_status_for(
                trained, rollout["target_dispatcher_count"]
            ),
        },
    )

    if clock() < rollout["scheduled_golive_at"]:
        fail(
            "ERR_GOLIVE_WINDOW_NOT_OPEN",
            "The logical clock has not reached scheduled_golive_at.",
        )
    if rollout["training_status"] != "COMPLETE":
        fail("ERR_TRAINING_INCOMPLETE", "Retraining is not complete for this rollout.")

    set_fields(rollout, {"golive_status": "LIVE", "went_live_at": clock()})
    cascades.cascade_b_golive(rollout)
    return ok(public(rollout))
