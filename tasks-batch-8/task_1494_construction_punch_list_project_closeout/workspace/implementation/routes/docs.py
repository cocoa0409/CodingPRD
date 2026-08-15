"""Closeout documents (PRD 3.5): submission singularity rules, revision
numbering, and the approve/reject decision loop."""
from flask import Blueprint

from authz import GCPM, SUBREP, ALL_ROLES, require_roles
from db import store
from derived import maybe_advance_project, recompute_trade
from errors import (
    doc_already_pending, doc_type_already_satisfied, invalid_state,
    not_responsible_party, trade_not_in_project,
)
from respond import success
from serialize import ser_doc
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, query_filters,
    req_enum, req_str, sorted_by_creation, touch,
)

bp = Blueprint("docs", __name__, url_prefix="/closeout")

DOC_TYPES = ("OM_MANUAL", "WARRANTY_DOC", "AS_BUILT")

# Document decisions rest with the GCProjectManager only in the closeout phase.
DECISION_PHASES = ("CLOSEOUT_IN_PROGRESS", "FINAL_RELEASE_PENDING")


@bp.route("/closeout-documents", methods=["POST"])
def create_doc():
    uid, role = require_roles([SUBREP, GCPM])
    data = json_body()
    # Priority 3 (responsible party): for a SubcontractorRep the identity check
    # is evaluable from the payload's trade_package_id alone.
    if role == SUBREP and data.get("trade_package_id") != uid:
        raise not_responsible_party()
    project_id = req_str(data, "project_id")
    trade_package_id = req_str(data, "trade_package_id")
    doc_type = req_enum(data, "doc_type", DOC_TYPES)
    file_ref = req_str(data, "file_ref")
    get_or_404(store.projects, project_id)
    t = get_or_404(store.trade_packages, trade_package_id)
    # Priority 3 remainder: the responsible-type side of the rule needs the
    # fetched trade (SubcontractorRep -> SUBCONTRACTOR; GCProjectManager ->
    # SELF_PERFORMED).
    if role == SUBREP and t["responsible_type"] != "SUBCONTRACTOR":
        raise not_responsible_party()
    if role == GCPM and t["responsible_type"] != "SELF_PERFORMED":
        raise not_responsible_party()
    # Domain (priority 11): at most one pending doc per (trade, doc_type); an
    # APPROVED pair is locked.
    siblings = [d for d in store.closeout_documents.values()
                if d["trade_package_id"] == trade_package_id
                and d["doc_type"] == doc_type]
    if any(d["status"] == "SUBMITTED" for d in siblings):
        raise doc_already_pending()
    if any(d["status"] == "APPROVED" for d in siblings):
        raise doc_type_already_satisfied()
    # Referential (priority 12).
    if t["project_id"] != project_id:
        raise trade_not_in_project()
    d = {
        "id": new_id(),
        "_seq": next(store.seq),
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "doc_type": doc_type,
        "file_ref": file_ref,
        "revision": len(siblings) + 1,  # server-counted revision
        "status": "SUBMITTED",
        "rejection_reason": None,
    }
    d.update(new_common_fields())
    store.closeout_documents[d["id"]] = d
    return success(ser_doc(d), status=201)


@bp.route("/closeout-documents/<did>", methods=["GET"])
def get_doc(did):
    require_roles(ALL_ROLES)
    return success(ser_doc(get_or_404(store.closeout_documents, did)))


@bp.route("/closeout-documents", methods=["GET"])
def list_docs():
    require_roles(ALL_ROLES)
    filters = query_filters("project_id", "trade_package_id", "doc_type", "status")
    items = [d for d in store.closeout_documents.values()
             if all(d[k] == v for k, v in filters.items())]
    page, pagination = paginate(sorted_by_creation(items))
    return success([ser_doc(d) for d in page], response_type="array",
                   pagination=pagination)


@bp.route("/closeout-documents/<did>/approve", methods=["POST"])
def approve_doc(did):
    require_roles([GCPM])
    d = get_or_404(store.closeout_documents, did)
    p = store.projects[d["project_id"]]
    if p["status"] not in DECISION_PHASES:
        raise invalid_state("Documents may only be decided in the closeout phase")
    if d["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED document can be approved")
    d["status"] = "APPROVED"
    touch(d)
    # Flip the trade's doc flag; recompute closeout_ready; maybe cascade (PRD 3.5).
    recompute_trade(store.trade_packages[d["trade_package_id"]])
    maybe_advance_project(p)
    return success(ser_doc(d))


@bp.route("/closeout-documents/<did>/reject", methods=["POST"])
def reject_doc(did):
    require_roles([GCPM])
    data = json_body()
    reason = req_str(data, "rejection_reason")
    d = get_or_404(store.closeout_documents, did)
    p = store.projects[d["project_id"]]
    if p["status"] not in DECISION_PHASES:
        raise invalid_state("Documents may only be decided in the closeout phase")
    if d["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED document can be rejected")
    d["status"] = "REJECTED"
    d["rejection_reason"] = reason
    touch(d)
    return success(ser_doc(d))
