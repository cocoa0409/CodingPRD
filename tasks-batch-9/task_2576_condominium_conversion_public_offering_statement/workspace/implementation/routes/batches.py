"""Closing batches: the half-open settlement window, assignment, threshold
evaluation and release sequencing (PRD 3.9)."""

from flask import Blueprint

import clock
import envelope
import rounding
import serializers
import store
import validation as v
from errors import ApiError
from services import projects as project_service, sales

bp = Blueprint("batches", __name__)

SPONSOR = ["ConverterSponsor"]
READ_ROLES = ["ConverterSponsor", "EscrowAgent", "StateRegulator",
              "LenderUnderwriter", "PlatformAdmin"]
ASSIGN_ROLES = ["ConverterSponsor", "EscrowAgent"]
EVALUATE_ROLES = ["ConverterSponsor", "EscrowAgent", "StateRegulator"]

EDITABLE_STATUSES = ("DRAFT", "OPEN_FOR_ASSIGNMENT", "THRESHOLD_SHORT",
                     "THRESHOLD_MET")


def _check_window(project_id, start_at, end_at, exclude_batch_id=None):
    """Priority 38: the inverted or zero-length window and the sibling overlap
    are the same refusal.  The window is half-open, so adjacency is allowed."""
    if end_at <= start_at:
        raise ApiError("ERR_BATCH_WINDOW_OVERLAP")
    if sales.batch_window_conflict(project_id, start_at, end_at,
                                   exclude_batch_id) is not None:
        raise ApiError("ERR_BATCH_WINDOW_OVERLAP")


@bp.post("/conversion-projects/<project_id>/closing-batches")
def create_batch(project_id):
    v.authorize(SPONSOR)
    project = v.get_project(project_id)
    body = v.parse([
        v.field("batch_sequence_no", "integer", minimum=1, maximum=50),
        v.field("window_start_at", "datetime"),
        v.field("window_end_at", "datetime"),
        v.field("min_presale_threshold_pct", "number", minimum=0,
                maximum=100),
        v.field("min_absolute_unit_count", "integer", required=False,
                default=1, minimum=0),
    ])
    v.require_unique(store.project_batches(project["id"]),
                     batch_sequence_no=body["batch_sequence_no"])
    v.gate_not_frozen(project)
    _check_window(project["id"], body["window_start_at"],
                  body["window_end_at"])
    batch = store.new_record(store.closing_batches, {
        "_type": "ClosingBatch",
        "conversion_project_id": project["id"],
        "batch_sequence_no": body["batch_sequence_no"],
        "window_start_at": body["window_start_at"],
        "window_end_at": body["window_end_at"],
        "min_presale_threshold_pct": rounding.pct2(
            body["min_presale_threshold_pct"]),
        "min_absolute_unit_count": body["min_absolute_unit_count"],
        "assigned_agreement_count": 0,
        "qualifying_agreement_count": 0,
        "presale_pct": rounding.pct2(0),
        "status": "DRAFT",
        "released_at": None,
        "last_evaluated_at": None,
    })
    return envelope.object_response(serializers.dump(batch), 201)


@bp.get("/conversion-projects/<project_id>/closing-batches")
def list_project_batches(project_id):
    v.authorize(READ_ROLES)
    project = v.get_project(project_id)
    limit, offset = v.pagination()
    records = [b for b in store.project_batches(project["id"])
               if v.matches(b, status=v.filter_value("status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/closing-batches/<batch_id>")
def get_batch(batch_id):
    v.authorize(READ_ROLES)
    batch = v.get_batch(batch_id)
    return envelope.object_response(serializers.dump(batch), 200)


@bp.patch("/closing-batches/<batch_id>")
def patch_batch(batch_id):
    v.authorize(SPONSOR)
    batch = v.get_batch(batch_id)
    project = v.get_project(batch["conversion_project_id"])
    body = v.parse([
        v.field("window_start_at", "datetime", required=False),
        v.field("window_end_at", "datetime", required=False),
        v.field("min_presale_threshold_pct", "number", required=False,
                minimum=0, maximum=100),
        v.field("min_absolute_unit_count", "integer", required=False,
                minimum=0),
    ])
    v.gate_not_frozen(project)
    v.require_state(batch, "status", EDITABLE_STATUSES)
    start_at = body.get("window_start_at", batch["window_start_at"])
    end_at = body.get("window_end_at", batch["window_end_at"])
    if "window_start_at" in body or "window_end_at" in body:
        _check_window(project["id"], start_at, end_at, batch["id"])
    batch["window_start_at"] = start_at
    batch["window_end_at"] = end_at
    if "min_presale_threshold_pct" in body:
        batch["min_presale_threshold_pct"] = rounding.pct2(
            body["min_presale_threshold_pct"])
    if "min_absolute_unit_count" in body:
        batch["min_absolute_unit_count"] = body["min_absolute_unit_count"]
    # A threshold edit does not by itself re-evaluate the batch.
    store.touch(batch)
    return envelope.object_response(serializers.dump(batch), 200)


@bp.post("/closing-batches/<batch_id>/agreement-assignments")
def assign_agreement(batch_id):
    v.authorize(ASSIGN_ROLES)
    batch = v.get_batch(batch_id)
    project = v.get_project(batch["conversion_project_id"])
    body = v.raw_body()
    agreement = v.body_ref(body, "purchase_agreement_id", v.get_agreement)
    v.require_scope(project["id"], agreement)
    fields = v.parse([
        v.field("purchase_agreement_id", "id"),
        v.field("expected_closing_batch_version", "integer"),
    ])
    v.require_version(fields["expected_closing_batch_version"], batch,
                      "ERR_STALE_BATCH_VERSION")
    v.gate_not_frozen(project)
    if agreement["closing_batch_id"] is not None:
        raise ApiError("ERR_AGREEMENT_ALREADY_ASSIGNED")
    agreement["closing_batch_id"] = batch["id"]
    store.touch(agreement)
    if batch["status"] == "DRAFT":
        batch["status"] = "OPEN_FOR_ASSIGNMENT"
        store.touch(batch)
    sales.write_batch_counters(batch, project)
    store.touch(batch)
    return envelope.object_response(serializers.dump(batch), 201)


@bp.get("/closing-batches/<batch_id>/agreements")
def list_batch_agreements(batch_id):
    v.authorize(READ_ROLES)
    batch = v.get_batch(batch_id)
    limit, offset = v.pagination()
    records = [
        a for a in store.batch_agreements(batch["id"])
        if v.matches(a,
                     contract_status=v.filter_value("contract_status"),
                     escrow_status=v.filter_value("escrow_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.delete("/closing-batches/<batch_id>/agreement-assignments/"
           "<purchase_agreement_id>")
def unassign_agreement(batch_id, purchase_agreement_id):
    v.authorize(SPONSOR)
    batch = v.get_batch(batch_id)
    agreement = v.get_agreement(purchase_agreement_id)
    project = v.get_project(batch["conversion_project_id"])
    v.require_scope(project["id"], agreement)
    v.gate_not_frozen(project)
    if agreement["closing_batch_id"] != batch["id"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # A released batch's book is closed to unassignment.
    v.require_state(batch, "status", EDITABLE_STATUSES)
    agreement["closing_batch_id"] = None
    store.touch(agreement)
    sales.write_batch_counters(batch, project)
    if batch["status"] == "THRESHOLD_MET" and not sales.thresholds_met(batch):
        batch["status"] = "THRESHOLD_SHORT"
        project_service.recompute_posture(project)
    store.touch(batch)
    return envelope.object_response(serializers.dump(batch), 200)


@bp.post("/closing-batches/<batch_id>/threshold-evaluations")
def evaluate_threshold(batch_id):
    v.authorize(EVALUATE_ROLES)
    batch = v.get_batch(batch_id)
    project = v.get_project(batch["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(batch, "status",
                    ("OPEN_FOR_ASSIGNMENT", "THRESHOLD_SHORT",
                     "THRESHOLD_MET"))
    if not store.included_units(project["id"]):
        raise ApiError("ERR_NO_INCLUDED_UNITS")
    sales.write_batch_counters(batch, project)
    batch["status"] = ("THRESHOLD_MET" if sales.thresholds_met(batch)
                       else "THRESHOLD_SHORT")
    batch["last_evaluated_at"] = clock.now()
    store.touch(batch)
    presale = sales.presale_sold_pct(project)
    if project["presale_sold_pct"] != presale:
        project["presale_sold_pct"] = presale
        store.touch(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(batch), 200)


@bp.post("/closing-batches/<batch_id>/release")
def release_batch(batch_id):
    v.authorize(["EscrowAgent"])
    batch = v.get_batch(batch_id)
    project = v.get_project(batch["conversion_project_id"])
    # Priority 22: the posture must be exactly OPEN, not merely un-frozen, and
    # it outranks the state precondition on this one endpoint.
    v.gate_posture_open(project)
    v.require_state(batch, "status", ("THRESHOLD_MET",))
    for sibling in store.project_batches(project["id"]):
        if sibling["id"] != batch["id"] and sibling["status"] == "RELEASED":
            # Releases are strictly serialised, one batch at a time; the
            # catalogue has no dedicated id for the clash.
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    statement = store.project_statement(project["id"])
    if statement is None or statement["status"] != "EFFECTIVE":
        raise ApiError("ERR_POS_NOT_EFFECTIVE")
    package = store.project_package(project["id"])
    if package is None or package["status"] != "RECORDED":
        raise ApiError("ERR_DECLARATION_NOT_RECORDED")
    # Priority 50 covers both halves of the threshold refusal.
    if not sales.thresholds_met(batch):
        raise ApiError("ERR_PRESALE_THRESHOLD_NOT_MET")
    for agreement in store.batch_agreements(batch["id"]):
        if agreement["contract_status"] not in ("HARD", "CLOSED"):
            raise ApiError("ERR_PRESALE_THRESHOLD_NOT_MET")
    batch["status"] = "RELEASED"
    batch["released_at"] = clock.now()
    store.touch(batch)
    if project["status"] == "PRESALE":
        project["status"] = "CLOSINGS"
        store.touch(project)
    project_service.recompute_posture(project)
    return envelope.object_response(serializers.dump(batch), 200)


@bp.get("/closing-batches/<batch_id>/threshold-summary")
def threshold_summary(batch_id):
    v.authorize(READ_ROLES)
    batch = v.get_batch(batch_id)
    project = v.get_project(batch["conversion_project_id"])
    # A pure read: the counters are computed but the status never moves.
    assigned, qualifying, presale = sales.batch_counters(batch, project)
    payload = serializers.dump(batch)
    payload["assigned_agreement_count"] = assigned
    payload["qualifying_agreement_count"] = qualifying
    payload["presale_pct"] = rounding.number(presale)
    payload["threshold_met"] = (
        presale >= batch["min_presale_threshold_pct"]
        and qualifying >= batch["min_absolute_unit_count"])
    return envelope.object_response(payload, 200)
