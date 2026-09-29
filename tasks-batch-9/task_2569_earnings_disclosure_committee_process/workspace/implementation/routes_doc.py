"""Draft documents, tie-out items, adjusted measures and the question bank."""
from flask import Blueprint, request

import calc
from authz import (
    ALL_ROLES,
    ROLE_CONTROLLER,
    ROLE_IR,
    ROLE_LEGAL,
    authorize,
    gate_action,
    require_action,
)
from core import TouchLog, bad, public, store, success_object
from helpers import apply_eq, paged, sort_created_asc
from validate import (
    as_bool,
    as_enum,
    as_integer,
    as_number,
    as_string,
    body_of,
    enum_filter,
    opt_bool,
    pagination,
    present,
    req_present,
    str_filter,
)

bp = Blueprint("document", __name__)

DOC_TYPES = ("EARNINGS_RELEASE", "PERIODIC_FILING", "CALL_SCRIPT", "CURRENT_REPORT")
DOC_STATUSES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED", "FILED")
TIE_OUT_STATUSES = ("MATCHED", "VARIANCE", "WAIVED")
MEASURE_STATUSES = ("DRAFT", "RECONCILED", "PROMINENCE_FAILED", "REJECTED")
QA_TOPICS = ("GUIDANCE", "MARGIN", "LIQUIDITY", "LITIGATION", "SEGMENT_PERFORMANCE")
RISK_TIERS = ("LOW", "MEDIUM", "HIGH")
QA_STATUSES = ("DRAFT", "BLOCKED", "CLEARED")
NARROW_ROLES = [r for r in ALL_ROLES if r != "BusinessLeader"]

DOC_WRITE_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED")
TIE_OUT_WRITE_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED")


def _validate_reconciliation_items(value):
    if not isinstance(value, list):
        bad("ERR_INVALID_REQUEST", "'reconciliation_items' must be a list")
    for entry in value:
        if not isinstance(entry, dict):
            bad("ERR_INVALID_REQUEST", "each reconciliation item must be an object")
        if "label" not in entry or "amount" not in entry:
            bad("ERR_INVALID_REQUEST", "each reconciliation item needs 'label' and 'amount'")
        as_string(entry["label"], "label", 200, allow_empty=True)
        as_number(entry["amount"], "amount")
    return [{"label": entry["label"], "amount": entry["amount"]} for entry in value]


# ------------------------------------------------------------------ documents

@bp.get("/disclosure/documents")
def list_documents():
    authorize(request, ALL_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("document")
    rows = apply_eq(rows, "cycle_id", str_filter(request.args, "cycle_id"))
    rows = apply_eq(rows, "author_member_id", str_filter(request.args, "author_member_id"))
    rows = apply_eq(rows, "doc_type", enum_filter(request.args, "doc_type", DOC_TYPES))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", DOC_STATUSES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/documents/<document_id>")
def get_document(document_id):
    authorize(request, ALL_ROLES)
    return success_object(public(store.must_get("document", document_id)))


@bp.post("/disclosure/documents")
def create_document():
    authorize(request, [ROLE_CONTROLLER, ROLE_IR, ROLE_LEGAL])
    body = body_of(request)
    cycle = None
    author = None
    if present(body, "cycle_id"):
        cycle = store.must_get("cycle", body["cycle_id"])
    if present(body, "author_member_id"):
        author = store.must_get("member", body["author_member_id"])
    if cycle is None:
        req_present(body, "cycle_id")
    if author is None:
        req_present(body, "author_member_id")
    doc_type = as_enum(req_present(body, "doc_type"), "doc_type", DOC_TYPES)
    title = as_string(req_present(body, "title"), "title", 200)
    safe_harbor_present = opt_bool(body, "safe_harbor_present", False)
    expected_cycle_version = as_integer(
        req_present(body, "expected_cycle_version"), "expected_cycle_version"
    )

    if expected_cycle_version != cycle["version"]:
        bad("ERR_STALE_CYCLE_VERSION", "expected_cycle_version does not match the cycle")
    if cycle["status"] == "ABANDONED":
        bad("ERR_ENTITY_TERMINAL", "cycle is ABANDONED")
    if cycle["status"] not in ("CLOSE_OPEN", "REVIEW_OPEN", "FILED"):
        bad("ERR_INVALID_STATE", "the cycle does not admit document drafting")
    if author["charter_id"] != cycle["charter_id"]:
        bad("ERR_MEMBER_CHARTER_MISMATCH", "the author does not belong to the cycle's charter")
    if author["status"] != "ACTIVE":
        bad("ERR_MEMBER_SEAT_INVALID", "the author's seat is not ACTIVE")

    log = TouchLog()
    for existing in store.where("document", cycle_id=cycle["id"], doc_type=doc_type):
        if existing["status"] in ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED"):
            existing["status"] = "SUPERSEDED"
            log.touch(existing)
    row = store.new_row(
        "document",
        {
            "cycle_id": cycle["id"],
            "author_member_id": author["id"],
            "doc_type": doc_type,
            "title": title,
            "safe_harbor_present": safe_harbor_present,
            "status": "DRAFT",
            "revision_round": 0,
            "change_note": None,
            "tie_out_status": "NOT_STARTED",
            "tie_out_total_variance_bp": 0,
            "tie_out_tier_multiplier": 1.00,
            "measure_gate_status": "NO_MEASURES",
            "qa_gate_status": "CLEARED",
        },
    )
    log.touch(cycle)
    return success_object(public(row), 201)


@bp.post("/disclosure/documents/<document_id>/transitions")
def transition_document(document_id):
    actor = authorize(request, [ROLE_CONTROLLER, ROLE_LEGAL, ROLE_IR])
    body = body_of(request)
    gate_action(actor, "document", body)
    document = store.must_get("document", document_id)
    action = require_action("document", body)
    change_note = None
    if action == "REQUEST_CHANGES":
        change_note = as_string(req_present(body, "change_note"), "change_note", 2000)

    if document["status"] in ("FILED", "SUPERSEDED"):
        bad("ERR_ENTITY_TERMINAL", "document is %s" % document["status"])
    cycle = store.get("cycle", document["cycle_id"])

    log = TouchLog()
    if action == "SUBMIT_REVIEW":
        if document["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
            bad("ERR_INVALID_STATE", "SUBMIT_REVIEW requires DRAFT or CHANGES_REQUESTED")
        if cycle is None or cycle["status"] not in ("CLOSE_OPEN", "REVIEW_OPEN", "FILED"):
            bad("ERR_INVALID_STATE", "the cycle does not admit review submission")
        document["status"] = "IN_REVIEW"
        log.touch(document)
        return success_object(public(document))

    if document["status"] != "IN_REVIEW":
        bad("ERR_INVALID_STATE", "%s requires an IN_REVIEW document" % action)
    if actor.user_id == document["author_member_id"]:
        bad("ERR_SOD_SELF_APPROVAL", "the author may not review its own document")

    if action == "REQUEST_CHANGES":
        document["status"] = "CHANGES_REQUESTED"
        document["revision_round"] = document["revision_round"] + 1
        document["change_note"] = change_note
        log.touch(document)
        return success_object(public(document))

    # APPROVE
    if document["doc_type"] in ("EARNINGS_RELEASE", "CALL_SCRIPT") and not document["safe_harbor_present"]:
        bad("ERR_SAFE_HARBOR_MISSING", "safe harbor language is required for this document type")
    if document["doc_type"] == "CALL_SCRIPT" and not document["safe_harbor_present"]:
        for item in store.where("qa_item", script_document_id=document["id"]):
            if item["requires_safe_harbor"]:
                bad(
                    "ERR_SAFE_HARBOR_MISSING",
                    "a question requiring safe harbor is present without the legend",
                )
    if document["qa_gate_status"] == "BLOCKED":
        bad("ERR_QA_ITEM_UNCLEARED", "a HIGH-risk question is still uncleared")
    if document["measure_gate_status"] == "BLOCKED_RECONCILIATION":
        bad("ERR_MEASURE_NOT_RECONCILED", "an adjusted measure is not reconciled")
    if document["measure_gate_status"] == "BLOCKED_PROMINENCE":
        bad("ERR_MEASURE_PROMINENCE", "an adjusted measure fails the prominence test")
    if document["tie_out_status"] != "PASSED":
        bad("ERR_TIE_OUT_NOT_PASSED", "tie_out_status must be PASSED")
    document["status"] = "APPROVED"
    log.touch(document)
    return success_object(public(document))


# --------------------------------------------------------------- tie-out items

@bp.get("/disclosure/tie-out-items")
def list_tie_out_items():
    authorize(request, NARROW_ROLES)
    limit, offset = pagination(request.args)
    rows = store.all_rows("tie_out_item")
    rows = apply_eq(rows, "document_id", str_filter(request.args, "document_id"))
    rows = apply_eq(rows, "preparer_member_id", str_filter(request.args, "preparer_member_id"))
    rows = apply_eq(rows, "reviewer_member_id", str_filter(request.args, "reviewer_member_id"))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", TIE_OUT_STATUSES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.get("/disclosure/tie-out-items/<item_id>")
def get_tie_out_item(item_id):
    authorize(request, NARROW_ROLES)
    return success_object(public(store.must_get("tie_out_item", item_id)))


@bp.post("/disclosure/documents/<document_id>/tie-out-items")
def create_tie_out_item(document_id):
    authorize(request, [ROLE_CONTROLLER])
    document = store.must_get("document", document_id)
    body = body_of(request)
    preparer = None
    if present(body, "preparer_member_id"):
        preparer = store.must_get("member", body["preparer_member_id"])
    line_label = as_string(req_present(body, "line_label"), "line_label", 120)
    reported_value = as_number(req_present(body, "reported_value"), "reported_value")
    source_record_value = as_number(
        req_present(body, "source_record_value"), "source_record_value"
    )
    tolerance_bp = as_integer(
        req_present(body, "tolerance_bp"), "tolerance_bp", minimum=0, maximum=10000
    )
    if preparer is None:
        req_present(body, "preparer_member_id")
    expected_document_version = as_integer(
        req_present(body, "expected_document_version"), "expected_document_version"
    )

    if expected_document_version != document["version"]:
        bad("ERR_STALE_DOCUMENT_VERSION", "expected_document_version does not match the document")
    if document["status"] in ("FILED", "SUPERSEDED"):
        bad("ERR_ENTITY_TERMINAL", "document is %s" % document["status"])
    if document["status"] not in TIE_OUT_WRITE_STATES:
        bad("ERR_INVALID_STATE", "the document does not admit tie-out work")
    cycle = store.get("cycle", document["cycle_id"])
    if cycle is None or preparer["charter_id"] != cycle["charter_id"]:
        bad("ERR_MEMBER_CHARTER_MISMATCH", "the preparer does not belong to the cycle's charter")
    if preparer["status"] != "ACTIVE":
        bad("ERR_MEMBER_SEAT_INVALID", "the preparer's seat is not ACTIVE")
    for sibling in store.where("tie_out_item", document_id=document["id"]):
        if sibling["status"] != "WAIVED" and sibling["line_label"] == line_label:
            bad("ERR_INVALID_REQUEST", "'line_label' must be unique within the document")

    log = TouchLog()
    row = store.new_row(
        "tie_out_item",
        {
            "document_id": document["id"],
            "line_label": line_label,
            "reported_value": reported_value,
            "source_record_value": source_record_value,
            "tolerance_bp": tolerance_bp,
            "preparer_member_id": preparer["id"],
            "reviewer_member_id": None,
            "review_decision": None,
            "raw_variance_bp": 0,
            "effective_tolerance_bp": 0,
            "status": "MATCHED",
        },
    )
    calc.recompute_tie_out(document, log, new_item_ids=(row["id"],))
    calc.tie_out_failure_cascade(document, log)
    log.touch(document)
    return success_object(public(row), 201)


@bp.post("/disclosure/tie-out-items/<item_id>/review")
def review_tie_out_item(item_id):
    actor = authorize(request, [ROLE_CONTROLLER])
    item = store.must_get("tie_out_item", item_id)
    body = body_of(request)
    reviewer = None
    if present(body, "reviewer_member_id"):
        reviewer = store.must_get("member", body["reviewer_member_id"])
    if reviewer is None:
        req_present(body, "reviewer_member_id")
    decision = as_enum(req_present(body, "decision"), "decision", ("ACCEPT", "WAIVE"))

    if item["status"] == "WAIVED":
        bad("ERR_ENTITY_TERMINAL", "the tie-out item is WAIVED")
    document = store.get("document", item["document_id"])
    if decision == "ACCEPT" and item["status"] != "MATCHED":
        bad("ERR_INVALID_STATE", "ACCEPT requires a MATCHED item")
    if document is None or document["status"] not in TIE_OUT_WRITE_STATES:
        bad("ERR_INVALID_STATE", "the document does not admit tie-out review")
    cycle = store.get("cycle", document["cycle_id"])
    if cycle is None or reviewer["charter_id"] != cycle["charter_id"]:
        bad("ERR_MEMBER_CHARTER_MISMATCH", "the reviewer does not belong to the cycle's charter")
    if reviewer["status"] != "ACTIVE":
        bad("ERR_MEMBER_SEAT_INVALID", "the reviewer's seat is not ACTIVE")
    if reviewer["id"] == item["preparer_member_id"]:
        bad("ERR_SOD_SELF_REVIEW", "the preparer may not review its own tie-out line")

    log = TouchLog()
    item["reviewer_member_id"] = reviewer["id"]
    item["review_decision"] = decision
    if decision == "WAIVE":
        item["status"] = "WAIVED"
    log.touch(item)
    calc.recompute_tie_out(document, log, new_item_ids=(item["id"],))
    calc.tie_out_failure_cascade(document, log)
    log.touch(document)
    return success_object(public(item))


# ----------------------------------------------------------- adjusted measures

@bp.get("/disclosure/documents/<document_id>/adjusted-measures")
def list_measures(document_id):
    authorize(request, NARROW_ROLES)
    limit, offset = pagination(request.args)
    store.must_get("document", document_id)
    rows = store.where("measure", document_id=document_id)
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", MEASURE_STATUSES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.post("/disclosure/documents/<document_id>/adjusted-measures")
def create_measure(document_id):
    authorize(request, [ROLE_CONTROLLER])
    document = store.must_get("document", document_id)
    body = body_of(request)
    measure_label = as_string(req_present(body, "measure_label"), "measure_label", 120)
    adjusted_value = as_number(req_present(body, "adjusted_value"), "adjusted_value")
    comparable_gaap_value = as_number(
        req_present(body, "comparable_gaap_value"), "comparable_gaap_value"
    )
    items = _validate_reconciliation_items(req_present(body, "reconciliation_items"))
    adjusted_prominence_index = as_integer(
        req_present(body, "adjusted_prominence_index"),
        "adjusted_prominence_index",
        minimum=1,
        maximum=50,
    )
    gaap_prominence_index = as_integer(
        req_present(body, "gaap_prominence_index"), "gaap_prominence_index", minimum=1, maximum=50
    )

    if document["status"] in ("FILED", "SUPERSEDED"):
        bad("ERR_ENTITY_TERMINAL", "document is %s" % document["status"])
    if document["status"] not in DOC_WRITE_STATES:
        bad("ERR_INVALID_STATE", "the document does not admit adjusted-measure creation")

    log = TouchLog()
    row = store.new_row(
        "measure",
        {
            "document_id": document["id"],
            "measure_label": measure_label,
            "adjusted_value": adjusted_value,
            "comparable_gaap_value": comparable_gaap_value,
            "reconciliation_items": items,
            "adjusted_prominence_index": adjusted_prominence_index,
            "gaap_prominence_index": gaap_prominence_index,
            "reconciliation_sum": None,
            "reconciliation_gap": None,
            "prominence_ok": None,
            "status": "DRAFT",
        },
    )
    calc.recompute_measure_gate(document)
    log.touch(document)
    return success_object(public(row), 201)


@bp.post("/disclosure/adjusted-measures/<measure_id>/reconcile")
def reconcile_measure_route(measure_id):
    authorize(request, [ROLE_CONTROLLER])
    measure = store.must_get("measure", measure_id)
    body = body_of(request)
    items = None
    if present(body, "reconciliation_items"):
        items = _validate_reconciliation_items(body["reconciliation_items"])
    adjusted_index = None
    if present(body, "adjusted_prominence_index"):
        adjusted_index = as_integer(
            body["adjusted_prominence_index"], "adjusted_prominence_index", minimum=1, maximum=50
        )
    gaap_index = None
    if present(body, "gaap_prominence_index"):
        gaap_index = as_integer(
            body["gaap_prominence_index"], "gaap_prominence_index", minimum=1, maximum=50
        )

    if measure["status"] == "RECONCILED":
        bad("ERR_INVALID_STATE", "the measure is already RECONCILED")
    document = store.get("document", measure["document_id"])
    if document is None or document["status"] not in DOC_WRITE_STATES:
        bad("ERR_INVALID_STATE", "the document does not admit measure reconciliation")

    log = TouchLog()
    if items is not None:
        measure["reconciliation_items"] = items
    if adjusted_index is not None:
        measure["adjusted_prominence_index"] = adjusted_index
    if gaap_index is not None:
        measure["gaap_prominence_index"] = gaap_index
    calc.reconcile_measure(measure)
    log.touch(measure)
    calc.recompute_measure_gate(document)
    log.touch(document)
    return success_object(public(measure))


# ------------------------------------------------------------------- questions

@bp.get("/disclosure/documents/<document_id>/qa-items")
def list_qa_items(document_id):
    authorize(request, NARROW_ROLES)
    limit, offset = pagination(request.args)
    store.must_get("document", document_id)
    rows = store.where("qa_item", script_document_id=document_id)
    rows = apply_eq(rows, "topic", enum_filter(request.args, "topic", QA_TOPICS))
    rows = apply_eq(rows, "risk_tier", enum_filter(request.args, "risk_tier", RISK_TIERS))
    rows = apply_eq(rows, "status", enum_filter(request.args, "status", QA_STATUSES))
    return paged(sort_created_asc(rows), limit, offset)


@bp.post("/disclosure/documents/<document_id>/qa-items")
def create_qa_item(document_id):
    authorize(request, [ROLE_IR])
    document = store.must_get("document", document_id)
    body = body_of(request)
    question_text = as_string(req_present(body, "question_text"), "question_text", 400)
    topic = as_enum(req_present(body, "topic"), "topic", QA_TOPICS)
    risk_tier = as_enum(req_present(body, "risk_tier"), "risk_tier", RISK_TIERS)
    requires_safe_harbor = opt_bool(body, "requires_safe_harbor", False)

    if document["status"] in ("FILED", "SUPERSEDED"):
        bad("ERR_ENTITY_TERMINAL", "document is %s" % document["status"])
    if document["status"] not in DOC_WRITE_STATES:
        bad("ERR_INVALID_STATE", "the document does not admit question creation")

    log = TouchLog()
    row = store.new_row(
        "qa_item",
        {
            "script_document_id": document["id"],
            "question_text": question_text,
            "topic": topic,
            "risk_tier": risk_tier,
            "requires_safe_harbor": requires_safe_harbor,
            "clearance_note": None,
            "status": "BLOCKED" if (risk_tier == "HIGH" or requires_safe_harbor) else "DRAFT",
        },
    )
    calc.recompute_qa_gate(document)
    log.touch(document)
    return success_object(public(row), 201)


@bp.post("/disclosure/qa-items/<qa_item_id>/clear")
def clear_qa_item(qa_item_id):
    authorize(request, [ROLE_LEGAL])
    item = store.must_get("qa_item", qa_item_id)
    body = body_of(request)
    clearance_note = as_string(req_present(body, "clearance_note"), "clearance_note", 2000)

    if item["status"] == "CLEARED":
        bad("ERR_INVALID_STATE", "the question is already CLEARED")
    document = store.get("document", item["script_document_id"])
    if document is None or document["status"] not in DOC_WRITE_STATES:
        bad("ERR_INVALID_STATE", "the document does not admit question clearance")
    if item["status"] == "BLOCKED" and not document["safe_harbor_present"]:
        bad("ERR_SAFE_HARBOR_MISSING", "a BLOCKED question needs the script's safe harbor legend")

    log = TouchLog()
    item["status"] = "CLEARED"
    item["clearance_note"] = clearance_note
    log.touch(item)
    calc.recompute_qa_gate(document)
    log.touch(document)
    return success_object(public(item))
