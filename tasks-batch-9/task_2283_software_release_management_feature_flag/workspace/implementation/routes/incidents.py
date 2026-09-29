"""Incident reporting, linkage and the release-office decision."""

from flask import Blueprint, request

import db
import validate as v
from db import make, now, store, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import calc, cascade

bp = Blueprint("incidents", __name__)


@bp.post("/incidents")
def report_incident():
    user_id, _role = authenticate(("SRE", "Engineer"))
    body = v.get_body()
    title = v.req_str(body, "title", allow_blank=False)
    severity = v.req_enum(body, "severity", ("SEV1", "SEV2", "SEV3", "SEV4"))
    detected_at = v.req_dt(body, "detected_at")
    release_train_id = v.req_str(body, "release_train_id", allow_blank=False)

    db.get_train(release_train_id)
    linked_release_id, linked_deployment_id = calc.incident_release_linkage(
        release_train_id, detected_at
    )

    incident = make(
        "incidents",
        {
            "title": title,
            "severity": severity,
            "detected_at": detected_at,
            "release_train_id": release_train_id,
            "linked_release_id": linked_release_id,
            "linked_deployment_id": linked_deployment_id,
            "reporter_user_id": user_id,
            "state": "OPEN",
            "decision": None,
            "decided_at": None,
        },
    )
    return object_response(db.public(incident), 201)


@bp.get("/incidents/<incident_id>")
def read_incident(incident_id):
    authenticate(ANY)
    incident = db.get_incident(incident_id)
    return object_response(db.public(incident))


@bp.get("/incidents")
def list_incidents():
    authenticate(ANY)
    limit, offset = v.pagination()
    records = db.by_creation(store.incidents.values())
    for field in ("release_train_id", "linked_release_id", "linked_deployment_id", "state"):
        wanted = request.args.get(field)
        if wanted is not None:
            records = [i for i in records if i[field] == wanted]
    items = [db.public(i) for i in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/incidents/<incident_id>/decide")
def decide_incident(incident_id):
    authenticate(("SRE",))
    body = v.get_body()
    decision = v.req_enum(body, "decision", ("ROLLBACK", "FORWARD_FIX", "NO_ACTION"))
    incident = db.get_incident(incident_id)

    if incident["state"] != "OPEN":
        fail("ERR_INCIDENT_ALREADY_DECIDED", "This incident has already been decided")

    deployment = None
    if decision == "ROLLBACK":
        release = (
            store.releases.get(incident["linked_release_id"])
            if incident["linked_release_id"]
            else None
        )
        deployment = (
            store.deployments.get(incident["linked_deployment_id"])
            if incident["linked_deployment_id"]
            else None
        )
        if release is None or release["phase"] not in ("STABILIZING", "RELEASED"):
            fail("ERR_NO_LINKED_RELEASE", "No rollback-eligible release is linked")
        if deployment is None or deployment["delivery_state"] != "COMPLETED":
            fail("ERR_NO_LINKED_RELEASE", "No COMPLETED deployment is linked")
    elif decision == "NO_ACTION":
        if incident["severity"] not in ("SEV3", "SEV4"):
            fail("ERR_NO_LINKED_RELEASE", "A %s incident may not be closed with NO_ACTION" % incident["severity"])

    upd(incident, state="DECIDED", decision=decision, decided_at=now())

    if decision == "ROLLBACK" and deployment is not None:
        cascade.deployment_rollback(deployment)

    return object_response(db.public(incident))
