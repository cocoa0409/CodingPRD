"""Corrective actions, recalls, product labels, finished product lots."""
from flask import Blueprint, g, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_RECEIPT_LOT_NOT_FOUND, ERR_PROCESSING_BATCH_NOT_FOUND,
    ERR_CORRECTIVE_ACTION_NOT_FOUND, ERR_RECALL_NOT_FOUND,
    ERR_PRODUCT_LABEL_NOT_FOUND, ERR_FINISHED_LOT_NOT_FOUND,
    ERR_INVALID_STATE, ERR_VALIDATION_FAILED, ERR_SEGREGATION_OF_DUTIES,
    ERR_LABEL_NOT_APPROVED, ERR_LABEL_STALE, ERR_OPEN_CORRECTIVE_ACTIONS,
    ERR_SPECIES_MISMATCH, ERR_FINISHED_WEIGHT_EXCEEDS_OUTPUT,
)
from middleware import (
    require_roles, ANY_OPERATIONAL, ROLE_PROCESSING_SUPERVISOR,
    ROLE_COMPLIANCE_MANAGER,
)
from response import success
from services import (
    serialize_corrective_action, serialize_recall, serialize_label,
    serialize_finished_lot, batch_inputs, OPEN_CA_STATUSES,
)
from utils import get_body, req_str, req_num, req_enum, opt_str, opt_bool, q3, paginate

bp = Blueprint("compliance", __name__)


def get_ca_or_404(ca_id):
    c = store.corrective_actions.get(ca_id)
    if c is None:
        raise ApiError(ERR_CORRECTIVE_ACTION_NOT_FOUND,
                       "Corrective action %s not found" % ca_id, 404)
    return c


def get_label_or_404(label_id):
    l = store.labels.get(label_id)
    if l is None:
        raise ApiError(ERR_PRODUCT_LABEL_NOT_FOUND,
                       "Product label %s not found" % label_id, 404)
    return l


def get_finished_or_404(flot_id):
    f = store.finished_lots.get(flot_id)
    if f is None:
        raise ApiError(ERR_FINISHED_LOT_NOT_FOUND,
                       "Finished product lot %s not found" % flot_id, 404)
    return f


def _touch_supplier(supplier_id):
    supplier = store.suppliers.get(supplier_id)
    if supplier is not None:
        touch(supplier)


# ---------------------------------------------------------------- corrective actions
@bp.route("/seafood/corrective-actions", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def create_corrective_action():
    body = get_body()
    lot_id = body.get("receipt_lot_id")
    batch_id = body.get("processing_batch_id")
    if isinstance(lot_id, str) and lot_id not in store.lots:
        raise ApiError(ERR_RECEIPT_LOT_NOT_FOUND,
                       "Receipt lot %s not found" % lot_id, 404)
    if isinstance(batch_id, str) and batch_id not in store.batches:
        raise ApiError(ERR_PROCESSING_BATCH_NOT_FOUND,
                       "Processing batch %s not found" % batch_id, 404)
    source_type = req_enum(
        body, "source_type",
        ("SPECIES_MISMATCH", "HISTAMINE_DEVIATION", "TEMPERATURE_ABUSE",
         "YIELD_VARIANCE", "MANUAL"))
    # p28: manual creation requires MANUAL and at least one subject
    if source_type != "MANUAL":
        raise ApiError(
            ERR_VALIDATION_FAILED,
            "Manual corrective action creation requires source_type MANUAL", 400)
    if lot_id is None and batch_id is None:
        raise ApiError(
            ERR_VALIDATION_FAILED,
            "At least one of receipt_lot_id / processing_batch_id is required",
            400)
    req_str(body, "reason")
    supplier_id = None
    if lot_id is not None:
        entry = store.entries.get(store.lots[lot_id]["import_entry_id"])
        if entry is not None:
            supplier_id = entry["supplier_id"]
    ca = new_entity(
        source_type="MANUAL",
        supplier_id=supplier_id,
        receipt_lot_id=lot_id,
        processing_batch_id=batch_id,
        monitoring_record_id=None,
        opened_by=g.user_id,
        status="OPEN",
        resolution_note=None,
        closed_by=None,
        recall_id=None,
    )
    store.corrective_actions[ca["id"]] = ca
    if supplier_id is not None:
        _touch_supplier(supplier_id)
    return success(serialize_corrective_action(ca), "object", 201)


@bp.route("/seafood/corrective-actions/<cid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_corrective_action(cid):
    return success(serialize_corrective_action(get_ca_or_404(cid)))


@bp.route("/seafood/corrective-actions", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_corrective_actions():
    items = list(store.corrective_actions.values())
    for param in ("supplier_id", "receipt_lot_id", "processing_batch_id",
                  "monitoring_record_id", "recall_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c.get(param) == val]
    page, meta = paginate(items)
    return success([serialize_corrective_action(c) for c in page], "array", 200, meta)


@bp.route("/seafood/corrective-actions/<cid>/investigate", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def investigate_corrective_action(cid):
    ca = get_ca_or_404(cid)
    if ca["status"] not in ("OPEN", "RESOLVED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Only OPEN or RESOLVED corrective actions can move to INVESTIGATING",
            409)
    was_resolved = ca["status"] == "RESOLVED"
    ca["status"] = "INVESTIGATING"
    touch(ca)
    if was_resolved and ca.get("supplier_id") is not None:
        # reopening re-counts the CA as open; bump the supplier version
        _touch_supplier(ca["supplier_id"])
    return success(serialize_corrective_action(ca))


@bp.route("/seafood/corrective-actions/<cid>/resolve", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def resolve_corrective_action(cid):
    ca = get_ca_or_404(cid)
    body = get_body()
    note = req_str(body, "resolution_note")
    if ca["status"] != "INVESTIGATING":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an INVESTIGATING corrective action can be resolved",
                       409)
    if g.user_id == ca["opened_by"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "Resolver must differ from the corrective action opener", 403)
    ca["status"] = "RESOLVED"
    ca["resolution_note"] = note
    ca["closed_by"] = g.user_id
    touch(ca)
    if ca.get("supplier_id") is not None:
        _touch_supplier(ca["supplier_id"])
    return success(serialize_corrective_action(ca))


@bp.route("/seafood/corrective-actions/<cid>/escalate", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def escalate_corrective_action(cid):
    ca = get_ca_or_404(cid)
    body = get_body()
    reason = req_str(body, "reason")
    raw_scope = body.get("scope_lot_ids")
    if (not isinstance(raw_scope, list) or not raw_scope
            or any(not isinstance(i, str) for i in raw_scope)):
        raise ApiError(ERR_VALIDATION_FAILED,
                       "scope_lot_ids must be a non-empty array of ids", 400)
    scope = []
    for lot_id in raw_scope:
        fl = store.finished_lots.get(lot_id)
        if fl is None:
            raise ApiError(ERR_FINISHED_LOT_NOT_FOUND,
                           "Finished product lot %s not found" % lot_id, 404)
        scope.append(fl)
    if ca["status"] not in ("OPEN", "INVESTIGATING"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Only OPEN or INVESTIGATING corrective actions can be escalated", 409)
    for fl in scope:
        if fl["status"] == "RECALLED":
            raise ApiError(ERR_INVALID_STATE,
                           "Finished product lot %s is already RECALLED"
                           % fl["id"], 409)
    recall = new_entity(
        corrective_action_id=ca["id"],
        reason=reason,
        scope_lot_ids=list(raw_scope),
        status="INITIATED",
        notified_at=None,
    )
    store.recalls[recall["id"]] = recall
    ca["recall_id"] = recall["id"]
    ca["status"] = "ESCALATED"
    touch(ca)
    for fl in scope:
        fl["status"] = "RECALLED"
        touch(fl)
    if ca.get("supplier_id") is not None:
        _touch_supplier(ca["supplier_id"])
    return success(serialize_corrective_action(ca))


# ---------------------------------------------------------------- recalls
@bp.route("/seafood/recalls/<rid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_recall(rid):
    r = store.recalls.get(rid)
    if r is None:
        raise ApiError(ERR_RECALL_NOT_FOUND, "Recall %s not found" % rid, 404)
    return success(serialize_recall(r))


@bp.route("/seafood/recalls", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_recalls():
    items = list(store.recalls.values())
    ca_id = request.args.get("corrective_action_id")
    if ca_id is not None:
        items = [r for r in items if r["corrective_action_id"] == ca_id]
    page, meta = paginate(items)
    return success([serialize_recall(r) for r in page], "array", 200, meta)


@bp.route("/seafood/recalls/<rid>/notify", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def notify_recall(rid):
    r = store.recalls.get(rid)
    if r is None:
        raise ApiError(ERR_RECALL_NOT_FOUND, "Recall %s not found" % rid, 404)
    if r["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an INITIATED recall can be notified", 409)
    r["status"] = "NOTIFIED"
    r["notified_at"] = store.clock
    touch(r)
    return success(serialize_recall(r))


# ---------------------------------------------------------------- product labels
@bp.route("/seafood/product-labels", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def create_label():
    body = get_body()
    supersedes = body.get("supersedes_label_id")
    if isinstance(supersedes, str) and supersedes not in store.labels:
        raise ApiError(ERR_PRODUCT_LABEL_NOT_FOUND,
                       "Product label %s not found" % supersedes, 404)
    market_name = req_str(body, "market_name")
    scientific_name = req_str(body, "scientific_name")
    species = req_str(body, "species")
    production_method = req_enum(body, "production_method", ("WILD", "FARMED"))
    coo = req_str(body, "country_of_origin")
    keep_frozen = opt_bool(body, "keep_frozen_statement", False)
    supersedes = opt_str(body, "supersedes_label_id", None)
    label = new_entity(
        market_name=market_name,
        scientific_name=scientific_name,
        species=species,
        production_method=production_method,
        country_of_origin=coo,
        keep_frozen_statement=keep_frozen,
        allergen_statement="Contains: Fish (%s)" % market_name,
        supersedes_label_id=supersedes,
        status="DRAFT",
        approved_at=None,
    )
    store.labels[label["id"]] = label
    return success(serialize_label(label), "object", 201)


@bp.route("/seafood/product-labels/<lid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_label(lid):
    return success(serialize_label(get_label_or_404(lid)))


@bp.route("/seafood/product-labels", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_labels():
    items = list(store.labels.values())
    supersedes = request.args.get("supersedes_label_id")
    status = request.args.get("status")
    if supersedes is not None:
        items = [l for l in items if l.get("supersedes_label_id") == supersedes]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, meta = paginate(items)
    return success([serialize_label(l) for l in page], "array", 200, meta)


@bp.route("/seafood/product-labels/<lid>/approve", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def approve_label(lid):
    label = get_label_or_404(lid)
    if label["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a DRAFT label can be approved", 409)
    superseded = None
    if label.get("supersedes_label_id") is not None:
        superseded = store.labels.get(label["supersedes_label_id"])
        if superseded is None or superseded["status"] != "APPROVED":
            raise ApiError(
                ERR_INVALID_STATE,
                "supersedes_label_id must reference an APPROVED label", 409)
    label["status"] = "APPROVED"
    label["approved_at"] = store.clock
    touch(label)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
        for fl in store.finished_lots.values():
            if fl.get("product_label_id") == superseded["id"]:
                fl["label_stale"] = True
                touch(fl)
    return success(serialize_label(label))


# ---------------------------------------------------------------- finished lots
@bp.route("/seafood/finished-product-lots", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def create_finished_lot():
    body = get_body()
    batch_id = body.get("processing_batch_id")
    if isinstance(batch_id, str) and batch_id not in store.batches:
        raise ApiError(ERR_PROCESSING_BATCH_NOT_FOUND,
                       "Processing batch %s not found" % batch_id, 404)
    batch_id = req_str(body, "processing_batch_id")
    batch = store.batches[batch_id]
    net_weight = req_num(body, "net_weight_kg")
    if net_weight <= 0:
        raise ApiError(ERR_VALIDATION_FAILED, "net_weight_kg must be > 0", 400)
    net_weight = q3(net_weight)
    if batch["status"] not in ("COMPLETED", "RECONCILED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Finished lots require a COMPLETED or RECONCILED batch", 409)
    used = sum(
        (fl["net_weight_kg"] for fl in store.finished_lots.values()
         if fl["processing_batch_id"] == batch["id"]),
        start=q3(0),
    )
    if used + net_weight > batch["actual_output_kg"]:
        raise ApiError(
            ERR_FINISHED_WEIGHT_EXCEEDS_OUTPUT,
            "Sum of finished lot net weights exceeds batch actual_output_kg", 422)
    flot = new_entity(
        processing_batch_id=batch["id"],
        net_weight_kg=net_weight,
        product_label_id=None,
        label_version_pinned=None,
        label_stale=False,
        allergen_statement=None,
        country_of_origin=None,
        status="UNLABELED",
        released_at=None,
    )
    store.finished_lots[flot["id"]] = flot
    return success(serialize_finished_lot(flot), "object", 201)


@bp.route("/seafood/finished-product-lots/<fid>", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def get_finished_lot(fid):
    return success(serialize_finished_lot(get_finished_or_404(fid)))


@bp.route("/seafood/finished-product-lots", methods=["GET"])
@require_roles(*ANY_OPERATIONAL)
def list_finished_lots():
    items = list(store.finished_lots.values())
    batch_id = request.args.get("processing_batch_id")
    label_id = request.args.get("product_label_id")
    status = request.args.get("status")
    if batch_id is not None:
        items = [f for f in items if f["processing_batch_id"] == batch_id]
    if label_id is not None:
        items = [f for f in items if f.get("product_label_id") == label_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, meta = paginate(items)
    return success([serialize_finished_lot(f) for f in page], "array", 200, meta)


def _compute_country_of_origin(batch):
    codes = set()
    for row in batch_inputs(batch["id"]):
        lot = store.lots.get(row["receipt_lot_id"])
        if lot is not None:
            codes.add(lot["harvest_country_code"])
    if len(codes) == 1:
        return next(iter(codes))
    return "MIXED:" + "+".join(sorted(codes))


@bp.route("/seafood/finished-product-lots/<fid>/apply-label", methods=["POST"])
@require_roles(ROLE_PROCESSING_SUPERVISOR)
def apply_label(fid):
    flot = get_finished_or_404(fid)
    body = get_body()
    label_id = body.get("product_label_id")
    if isinstance(label_id, str) and label_id not in store.labels:
        raise ApiError(ERR_PRODUCT_LABEL_NOT_FOUND,
                       "Product label %s not found" % label_id, 404)
    label_id = req_str(body, "product_label_id")
    label = store.labels[label_id]
    if flot["status"] == "UNLABELED":
        pass
    elif flot["status"] == "LABELED" and flot["label_stale"]:
        pass
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            "apply-label requires an UNLABELED lot (or a LABELED lot with a "
            "stale label)", 409)
    if label["status"] != "APPROVED":
        raise ApiError(ERR_LABEL_NOT_APPROVED,
                       "Label must be APPROVED", 409)
    batch = store.batches.get(flot["processing_batch_id"])
    if batch is not None and label["species"] != batch["target_species"]:
        raise ApiError(
            ERR_SPECIES_MISMATCH,
            "Label species %s does not match batch target %s"
            % (label["species"], batch["target_species"]), 422)
    flot["product_label_id"] = label["id"]
    flot["label_version_pinned"] = label["version"]
    flot["label_stale"] = False
    flot["allergen_statement"] = label["allergen_statement"]
    flot["country_of_origin"] = (_compute_country_of_origin(batch)
                                 if batch is not None else None)
    flot["status"] = "LABELED"
    touch(flot)
    return success(serialize_finished_lot(flot))


@bp.route("/seafood/finished-product-lots/<fid>/release", methods=["POST"])
@require_roles(ROLE_COMPLIANCE_MANAGER)
def release_finished_lot(fid):
    flot = get_finished_or_404(fid)
    if flot["status"] != "LABELED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a LABELED finished lot can be released", 409)
    batch = store.batches.get(flot["processing_batch_id"])
    if batch is None or batch["status"] != "RECONCILED":
        raise ApiError(ERR_INVALID_STATE,
                       "The batch must be RECONCILED before release", 409)
    if flot["label_stale"]:
        raise ApiError(ERR_LABEL_STALE,
                       "The pinned label version has been superseded", 409)
    label = store.labels.get(flot.get("product_label_id"))
    if label is None or label["status"] != "APPROVED":
        raise ApiError(ERR_LABEL_NOT_APPROVED,
                       "The pinned label must be APPROVED", 409)
    for c in store.corrective_actions.values():
        if (c.get("processing_batch_id") == batch["id"]
                and c["status"] in OPEN_CA_STATUSES):
            raise ApiError(
                ERR_OPEN_CORRECTIVE_ACTIONS,
                "The batch has OPEN or INVESTIGATING corrective actions", 422)
    flot["status"] = "RELEASED"
    flot["released_at"] = store.clock
    touch(flot)
    return success(serialize_finished_lot(flot))
