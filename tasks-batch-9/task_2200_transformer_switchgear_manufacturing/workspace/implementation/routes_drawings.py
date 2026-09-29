"""Submittal drawings and the revision cycle (PRD 3.2)."""
from flask import Blueprint

import calc
import clock
import common
import envelope
import posture
import rbac
import store
import validation
from errors import ApiError
from validation import BOOLEAN, INTEGER, STRING, f

bp = Blueprint("drawings", __name__)

IN_REVIEW = ("DRAFT", "SUBMITTED", "UNDER_REVIEW")
DISPOSITIONS = ["APPROVED", "APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT"]


def _check_latest(drawing, order):
    highest = max((d.get("revision_round") or 0)
                  for d in store.where("drawing", engineered_order_id=order["id"]))
    if (drawing.get("revision_round") or 0) != highest:
        raise ApiError("ERR_DRAWING_REVISION_NOT_LATEST",
                       "revision_round %s is not the latest on the order" % drawing.get("revision_round"))


def _check_not_frozen(order):
    posture.refresh(order)
    if order.get("production_posture") == "FROZEN":
        raise ApiError("ERR_POSTURE_BLOCKED",
                       "posture is FROZEN: %s" % ", ".join(order.get("posture_reason_codes") or []))


@bp.route("/engineered-orders/<oid>/submittal-drawings", methods=["POST"])
def create_drawing(oid):
    rbac.authenticate("POST /engineered-orders/{id}/submittal-drawings")
    order = common.resolve("order", oid)
    payload = validation.body()
    data = validation.validate(payload, [
        f("drawing_set_code", STRING, required=True),
        f("authored_by_user_id", STRING, required=True),
        f("expected_engineered_order_version", INTEGER, required=True),
    ])
    validation.check_order_version(data, order)
    common.check_order_not_cancelled(order)
    common.check_engineering_open(order)
    siblings = store.where("drawing", engineered_order_id=oid)
    for d in siblings:
        if d.get("status") in IN_REVIEW:
            raise ApiError("ERR_REVISION_ROUND_CONFLICT",
                           "drawing %s is still in %s" % (d["id"], d.get("status")))
    predecessor = None
    highest = 0
    for d in siblings:
        rnd = d.get("revision_round") or 0
        if rnd > highest:
            highest = rnd
            predecessor = d
    drawing = {
        "engineered_order_id": oid,
        "revision_round": highest + 1,
        "drawing_set_code": data["drawing_set_code"],
        "status": "DRAFT",
        "authored_by_user_id": data["authored_by_user_id"],
        "reviewed_by_user_id": None,
        "notes_count": 0,
        "as_noted_changes_bill_of_material": False,
        "submitted_at": None,
        "disposition_at": None,
        "supersedes_drawing_id": predecessor["id"] if predecessor is not None else None,
    }
    store.insert("drawing", drawing)
    if predecessor is not None and predecessor.get("status") == "REVISE_AND_RESUBMIT":
        predecessor["status"] = "VOID"
        predecessor["void_reason"] = "SUPERSEDED_BY_REVISION"
        store.touch("drawing", predecessor)
    store.touch("order", order)
    posture.refresh(order)
    return envelope.created(store.public(drawing))


@bp.route("/engineered-orders/<oid>/submittal-drawings", methods=["GET"])
def list_order_drawings(oid):
    rbac.authenticate("GET /engineered-orders/{id}/submittal-drawings")
    common.resolve("order", oid)
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.where("drawing", engineered_order_id=oid),
                               {"status": common.qstr("status")})
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/submittal-drawings", methods=["GET"])
def list_drawings():
    rbac.authenticate("GET /submittal-drawings")
    limit, offset = envelope.pagination()
    rows = common.apply_filters(store.all_rows("drawing"), {
        "engineered_order_id": common.qstr("engineered_order_id"),
        "supersedes_drawing_id": common.qstr("supersedes_drawing_id"),
        "status": common.qstr("status"),
        "revision_round": common.qint("revision_round"),
    })
    return envelope.listing(store.public_list(rows), limit, offset)


@bp.route("/submittal-drawings/<did>", methods=["GET"])
def get_drawing(did):
    rbac.authenticate("GET /submittal-drawings/{id}")
    return envelope.ok(store.public(common.resolve("drawing", did)))


@bp.route("/submittal-drawings/<did>/submit", methods=["POST"])
def submit_drawing(did):
    rbac.authenticate("POST /submittal-drawings/{id}/submit")
    drawing = common.resolve("drawing", did)
    order = common.resolve("order", drawing.get("engineered_order_id"))
    common.check_state("drawing", drawing, ("DRAFT",))
    common.check_order_not_cancelled(order)
    common.check_engineering_open(order)
    if order.get("fulfillment_status") == "CLOSED":
        raise ApiError("ERR_ORDER_FULFILLMENT_STATE_INVALID", "the order is closed")
    _check_latest(drawing, order)
    for other in store.where("drawing", engineered_order_id=order["id"]):
        if other["id"] == did:
            continue
        if other.get("drawing_set_code") == drawing.get("drawing_set_code") \
                and other.get("status") in ("SUBMITTED", "UNDER_REVIEW"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "another revision of %s is already in review" % drawing.get("drawing_set_code"))
    _check_not_frozen(order)

    drawing["status"] = "SUBMITTED"
    drawing["submitted_at"] = clock.now_str()
    store.touch("drawing", drawing)

    released = order.get("released_drawing_revision")
    reopening = released is not None and (drawing.get("revision_round") or 0) > released
    if reopening:
        order["engineering_status"] = "SUBMITTAL_IN_REVIEW"
        common.stale_labels_for_revision(order, drawing.get("revision_round") or 0)
    elif order.get("engineering_status") == "ENG_OPEN":
        order["engineering_status"] = "SUBMITTAL_IN_REVIEW"
    store.touch("order", order)
    posture.refresh(order)
    return envelope.ok(store.public(drawing))


@bp.route("/submittal-drawings/<did>/begin-review", methods=["POST"])
def begin_review(did):
    actor = rbac.authenticate("POST /submittal-drawings/{id}/begin-review")
    drawing = common.resolve("drawing", did)
    order = common.resolve("order", drawing.get("engineered_order_id"))
    common.check_state("drawing", drawing, ("SUBMITTED",))
    common.check_order_not_cancelled(order)
    common.check_engineering_open(order)
    _check_latest(drawing, order)
    drawing["status"] = "UNDER_REVIEW"
    drawing["reviewed_by_user_id"] = actor.user_id
    store.touch("drawing", drawing)
    posture.refresh(order)
    return envelope.ok(store.public(drawing))


@bp.route("/submittal-drawings/<did>/disposition", methods=["POST"])
def disposition_drawing(did):
    actor = rbac.authenticate("POST /submittal-drawings/{id}/disposition")
    drawing = common.resolve("drawing", did)
    order = common.resolve("order", drawing.get("engineered_order_id"))
    rbac.check_sod(actor, drawing.get("authored_by_user_id"))
    payload = validation.body()
    data = validation.validate(payload, [
        f("disposition", STRING, required=True, enum=DISPOSITIONS),
        f("reviewed_by_user_id", STRING, required=True),
        f("notes_count", INTEGER, minimum=0),
        f("as_noted_changes_bill_of_material", BOOLEAN),
    ])
    common.check_state("drawing", drawing, ("UNDER_REVIEW",))
    common.check_order_not_cancelled(order)
    _check_latest(drawing, order)

    verdict = data["disposition"]
    notes = data.get("notes_count", drawing.get("notes_count") or 0)
    if verdict == "APPROVED" and notes != 0:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                       "notes_count must be exactly 0 for an APPROVED disposition")
    if verdict in ("APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT") and notes < 1:
        raise ApiError("ERR_FIELD_VALUE_OUT_OF_RANGE",
                       "notes_count must be at least 1 for a %s disposition" % verdict)
    if verdict in ("APPROVED", "APPROVED_AS_NOTED"):
        clauses = store.where("clause", engineered_order_id=order["id"])
        if not clauses and (order.get("contract_value_cents") or 0) >= 5000000:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "an escalation clause is required before design release")

    drawing["status"] = verdict
    drawing["reviewed_by_user_id"] = data["reviewed_by_user_id"]
    drawing["notes_count"] = notes
    if "as_noted_changes_bill_of_material" in data:
        drawing["as_noted_changes_bill_of_material"] = data["as_noted_changes_bill_of_material"]
    drawing["disposition_at"] = clock.now_str()
    store.touch("drawing", drawing)

    if verdict in ("APPROVED", "APPROVED_AS_NOTED"):
        order["engineering_status"] = "DESIGN_RELEASED"
        order["released_drawing_revision"] = drawing.get("revision_round")
        for c in store.where("clause", engineered_order_id=order["id"]):
            if c.get("status") == "ACTIVE":
                c["status"] = "LOCKED"
                store.touch("clause", c)
        for other in store.where("drawing", engineered_order_id=order["id"]):
            if other["id"] != did and other.get("status") in IN_REVIEW:
                other["status"] = "VOID"
                other["void_reason"] = "SUPERSEDED_BY_APPROVAL"
                store.touch("drawing", other)
    if verdict == "APPROVED_AS_NOTED" and drawing.get("as_noted_changes_bill_of_material"):
        components = set()
        for a in store.where("allocation", engineered_order_id=order["id"]):
            if a.get("status") != "RESERVED":
                continue
            a["status"] = "RELEASED"
            a["release_penalty_cents"] = 0
            a["released_at"] = clock.now_str()
            store.touch("allocation", a)
            components.add(a.get("long_lead_component_id"))
        for cid in components:
            comp = store.get("component", cid)
            if comp is not None:
                calc.refresh_component_buckets(comp)
                store.touch("component", comp)
    store.touch("order", order)
    common.auto_material_edges(order)
    posture.refresh(order)
    return envelope.ok(store.public(drawing))
