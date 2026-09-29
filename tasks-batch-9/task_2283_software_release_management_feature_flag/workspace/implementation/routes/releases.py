"""Release reads, the cut, the final release gate, freeze exceptions and
change-request authoring."""

from flask import Blueprint, request

import db
import validate as v
from db import make, now, store, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import calc, cascade

bp = Blueprint("releases", __name__)

IN_FLIGHT = ("DRAFT", "RISK_CLASSIFIED", "CAB_REVIEW")


@bp.get("/releases/<release_id>")
def read_release(release_id):
    authenticate(ANY)
    release = db.get_release(release_id)
    return object_response(db.public(release))


def _spans_intersect(a, b):
    """Closed spans; touching at a single endpoint counts as intersecting."""
    return a["cut_at"] <= b["stabilization_end_at"] and b["cut_at"] <= a["stabilization_end_at"]


@bp.post("/releases/<release_id>/cut")
def cut_release(release_id):
    authenticate(("ReleaseManager",))
    v.get_body()
    release = db.get_release(release_id)
    train = store.release_trains.get(release["release_train_id"])

    if release["phase"] not in ("OPEN", "FROZEN"):
        fail("ERR_RELEASE_PHASE_INVALID", "Release phase %s may not be cut" % release["phase"])
    if now() < release["freeze_at"]:
        fail("ERR_CUT_BEFORE_FREEZE", "The logical clock has not reached freeze_at")

    concurrent = [
        other
        for other in db.releases_of_train(release["release_train_id"])
        if other["id"] != release["id"]
        and other["phase"] in ("CUT", "STABILIZING")
        and _spans_intersect(release, other)
    ]
    if len(concurrent) + 1 > train["max_concurrent_stabilizing"]:
        fail(
            "ERR_STABILIZATION_CAPACITY_EXCEEDED",
            "Train allows at most %d concurrently stabilizing releases"
            % train["max_concurrent_stabilizing"],
        )

    # Pinned order: defer in-flight work first, then pin the attested score.
    for change in db.by_creation(db.changes_of_release(release["id"])):
        if change["state"] in IN_FLIGHT:
            upd(change, state="DEFERRED")

    attested = calc.readiness_attested(release)
    upd(
        release,
        readiness_score_attested=attested,
        readiness_score_projected=calc.readiness_projected(release),
        rollback_plan_confirmed=calc.rollback_plan_confirmed(release),
        phase="CUT",
    )
    upd(train, open_release_count=train["open_release_count"] - 1)
    return object_response(db.public(release))


@bp.post("/releases/<release_id>/release")
def ship_release(release_id):
    authenticate(("ReleaseManager",))
    v.get_body()
    release = db.get_release(release_id)

    if release["phase"] != "STABILIZING":
        fail(
            "ERR_RELEASE_PHASE_INVALID",
            "Only a STABILIZING release may be declared shipped",
        )

    prod_completed = []
    for deployment in db.by_creation(db.deployments_of_release(release["id"])):
        if deployment["delivery_state"] != "COMPLETED":
            continue
        env = store.environments.get(deployment["environment_id"])
        if env is not None and env["tier"] == "PROD":
            prod_completed.append((deployment, env))

    # Rank 15 sits above the readiness gate at rank 37.
    if any(env["requires_compliance_evidence"] for _, env in prod_completed):
        sealed = [
            p for p in db.packets_of_release(release["id"]) if p["state"] == "SEALED"
        ]
        if not sealed:
            fail(
                "ERR_EVIDENCE_PACKET_REQUIRED",
                "A SEALED compliance evidence packet is required for this release",
            )

    if not prod_completed:
        fail("ERR_RELEASE_NOT_READY", "No COMPLETED deployment on a PROD environment")
    if release["readiness_score_attested"] is None or release["readiness_score_attested"] < 80:
        fail("ERR_RELEASE_NOT_READY", "readiness_score_attested is below 80")
    if not release["rollback_plan_confirmed"]:
        fail("ERR_RELEASE_NOT_READY", "rollback_plan_confirmed is false")

    upd(release, phase="RELEASED", released_at=now())
    for change in db.by_creation(db.changes_of_release(release["id"])):
        if change["state"] == "MERGED":
            upd(change, state="DEPLOYED", deployment_verified=True)
    cascade.refresh_verified_change_count(release)
    return object_response(db.public(release))


@bp.post("/releases/<release_id>/freeze-exceptions")
def grant_freeze_exception(release_id):
    authenticate(("ComplianceOfficer",))
    body = v.get_body()
    v.req_str(body, "justification", allow_blank=False)
    release = db.get_release(release_id)
    train = store.release_trains.get(release["release_train_id"])

    if upd(release, freeze_exception_approved=True) and train is not None:
        upd(train, freeze_exception_count=train["freeze_exception_count"] + 1)
    return object_response(db.public(release))


@bp.post("/releases/<release_id>/change-requests")
def create_change(release_id):
    user_id, _role = authenticate(("Engineer",))
    body = v.get_body()
    title = v.req_str(body, "title", max_len=120, allow_blank=False)
    summary_internal = v.req_str(body, "summary_internal", allow_blank=False)
    lines_changed = v.req_int(body, "lines_changed", minimum=0)
    touched = v.req_int(body, "touched_subsystem_count", minimum=0)
    blast = v.req_enum(
        body, "declared_blast_radius", ("INTERNAL", "SINGLE_TENANT", "GLOBAL")
    )
    summary_customer = v.opt_str(body, "summary_customer_facing")
    customer_facing = v.opt_bool(body, "customer_facing", default=False)
    migration = v.opt_bool(body, "has_schema_migration", default=False)
    rollback_plan = v.opt_str(body, "rollback_plan")
    rollback_tested = v.opt_bool(body, "rollback_tested", default=False)

    db.get_release(release_id)

    change = make(
        "change_requests",
        {
            "release_id": release_id,
            "title": title,
            "summary_internal": summary_internal,
            "summary_customer_facing": summary_customer,
            "customer_facing": customer_facing,
            "author_user_id": user_id,
            "lines_changed": lines_changed,
            "touched_subsystem_count": touched,
            "has_schema_migration": migration,
            "declared_blast_radius": blast,
            "rollback_plan": rollback_plan,
            "rollback_tested": rollback_tested,
            "risk_score_preliminary": None,
            "risk_score_final": None,
            "risk_class": None,
            "state": "DRAFT",
            "approval_technical_count": 0,
            "approval_compliance_count": 0,
            "approval_cab_count": 0,
            "dependency_depth": 0,
            "merged_at": None,
            "deployment_verified": False,
        },
    )
    return object_response(db.public(change), 201)


@bp.get("/releases/<release_id>/change-requests")
def list_changes(release_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_release(release_id)
    records = db.by_creation(db.changes_of_release(release_id))
    state = request.args.get("state")
    if state is not None:
        records = [c for c in records if c["state"] == state]
    items = [db.public(c) for c in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))
