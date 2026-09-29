"""Release trains, the freeze gate and release creation."""

from datetime import timedelta

from flask import Blueprint, request

import db
import validate as v
from db import make, store, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import cascade

bp = Blueprint("trains", __name__)


@bp.post("/release-trains")
def create_train():
    authenticate(("ReleaseManager",))
    body = v.get_body()
    name = v.req_str(body, "name", max_len=80, allow_blank=False)
    cadence_days = v.req_int(body, "cadence_days", minimum=1)
    lead_hours = v.req_int(body, "code_freeze_lead_hours", minimum=0)
    stabilization_hours = v.req_int(body, "stabilization_hours", minimum=0)
    risk_budget_points = v.req_int(body, "risk_budget_points", minimum=0)
    max_concurrent = v.opt_int(body, "max_concurrent_stabilizing", default=1, minimum=1)

    train = make(
        "release_trains",
        {
            "name": name,
            "cadence_days": cadence_days,
            "code_freeze_lead_hours": lead_hours,
            "stabilization_hours": stabilization_hours,
            "max_concurrent_stabilizing": max_concurrent,
            "risk_budget_points": risk_budget_points,
            "phase": "ACTIVE",
            "frozen_at": None,
            "freeze_exception_count": 0,
            "open_release_count": 0,
        },
    )
    return object_response(db.public(train), 201)


@bp.get("/release-trains/<train_id>")
def read_train(train_id):
    authenticate(ANY)
    train = db.get_train(train_id)
    return object_response(db.public(train))


@bp.post("/release-trains/<train_id>/freeze-state")
def freeze_state(train_id):
    authenticate(("ReleaseManager",))
    body = v.get_body()
    action = v.req_enum(body, "action", ("FREEZE", "UNFREEZE"))
    train = db.get_train(train_id)

    if action == "FREEZE":
        if train["phase"] != "ACTIVE":
            fail("ERR_RELEASE_PHASE_INVALID", "Train is not ACTIVE")
        if train["open_release_count"] < 1:
            fail("ERR_RELEASE_PHASE_INVALID", "Train has no open release to freeze")
        cascade.train_freeze(train)
    else:
        if train["phase"] != "FROZEN":
            fail("ERR_RELEASE_PHASE_INVALID", "Train is not FROZEN")
        cascade.train_unfreeze(train)

    return object_response(db.public(train))


@bp.post("/release-trains/<train_id>/releases")
def create_release(train_id):
    authenticate(("ReleaseManager",))
    body = v.get_body()
    version_label = v.req_str(body, "version_label", allow_blank=False)
    cut_at = v.req_dt(body, "cut_at")
    train = db.get_train(train_id)

    for existing in db.releases_of_train(train_id):
        if existing["version_label"] == version_label:
            fail(
                "ERR_VERSION_LABEL_DUPLICATE",
                "version_label '%s' already exists on this train" % version_label,
            )

    release = make(
        "releases",
        {
            "release_train_id": train_id,
            "version_label": version_label,
            "cut_at": cut_at,
            "freeze_at": cut_at - timedelta(hours=train["code_freeze_lead_hours"]),
            "stabilization_end_at": cut_at + timedelta(hours=train["stabilization_hours"]),
            "phase": "OPEN",
            "committed_change_count": 0,
            "verified_change_count": 0,
            "risk_budget_consumed_points": 0,
            "readiness_score_projected": 100,
            "readiness_score_attested": None,
            "rollback_plan_confirmed": True,
            "evidence_packet_required": False,
            "freeze_exception_approved": False,
            "released_at": None,
            "rolled_back_at": None,
        },
    )
    upd(train, open_release_count=train["open_release_count"] + 1)
    return object_response(db.public(release), 201)


@bp.get("/release-trains/<train_id>/releases")
def list_releases(train_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_train(train_id)
    records = db.by_creation(db.releases_of_train(train_id))
    phase = request.args.get("phase")
    if phase is not None:
        records = [r for r in records if r["phase"] == phase]
    items = [db.public(r) for r in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))
