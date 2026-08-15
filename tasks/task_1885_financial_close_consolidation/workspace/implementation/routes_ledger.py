"""Routes: journal entries, supporting documents, reconciliations,
reconciling items, elimination pairs, flux explanations."""
from decimal import Decimal

from flask import request

from core import (
    STORE, ApiError, ALL_ROLES, body, bp, bump, logical_now, ok,
    paged_response, req_enum, req_int, req_str, req_ts, require_roles, rhu2,
)
from domain import (
    CURRENCIES, ELIM_TOLERANCE, RECON_TOLERANCE, add_event, compute_bucket,
    compute_elim_amounts, create_je, entity_of_ep, get_doc, get_elim,
    get_entity, get_ep, get_flux, get_item, get_je, get_recon, json_detail,
    lock_gate_ep, period_of_ep, recompute_aged_over_30, recompute_doc_state,
    recompute_recon_difference, recompute_trial_balance,
    recompute_unreconciled_count, ser_doc, ser_elim, ser_flux, ser_item,
    ser_je, ser_line, ser_recon, touch_ep,
)
from core import base_record

READERS = ALL_ROLES

JE_TYPES = ("MANUAL", "ACCRUAL", "RECLASS", "ELIMINATION",
            "CONSOLIDATION_ADJ", "TOP_SIDE")

# Entity-period statuses in which journal work is permitted (PRD §3.5).
JE_WORK_STATES = ("PREPARING", "SUBLEDGER_CUT", "RECONCILED", "REOPENED")


def _ep_lock_for_je(ep):
    period = period_of_ep(ep)
    if period is not None and period["status"] == "FINALIZED":
        raise ApiError("ERR_PERIOD_LOCKED", 409, "Period is FINALIZED")
    if ep["status"] not in JE_WORK_STATES:
        raise ApiError("ERR_PERIOD_LOCKED", 409,
                       "Entity-period status %s does not permit journal "
                       "entry work" % ep["status"])


# ---------------------------------------------------------------------------
# JournalEntry
# ---------------------------------------------------------------------------
@bp.post("/close/entity-periods/<eid>/journal-entries")
def create_journal_entry(eid):
    uid = require_roles("Preparer")
    ep = get_ep(eid)
    lock_gate_ep(ep, child_creation=True)
    b = body()
    je_type = req_enum(b, "je_type", JE_TYPES)
    entry_date = req_ts(b, "entry_date")
    functional_currency = req_enum(b, "functional_currency", CURRENCIES)
    lines_in = b.get("lines")
    if lines_in is None:
        lines_in = []
    if not isinstance(lines_in, list):
        raise ApiError("ERR_VALIDATION", 400, "lines must be an array")
    parsed = []
    for idx, line in enumerate(lines_in, start=1):
        if not isinstance(line, dict):
            raise ApiError("ERR_VALIDATION", 400, "each line must be an object")
        direction = line.get("direction")
        if direction not in ("DEBIT", "CREDIT"):
            raise ApiError("ERR_VALIDATION", 400,
                           "line direction must be DEBIT or CREDIT")
        amount = line.get("amount_minor")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ApiError("ERR_VALIDATION", 400,
                           "line amount_minor must be an integer")
        if amount <= 0:
            raise ApiError("ERR_LINE_NOT_POSITIVE", 409,
                           "line amount_minor must be > 0")
        account_code = line.get("account_code")
        if not isinstance(account_code, str):
            raise ApiError("ERR_VALIDATION", 400,
                           "line account_code must be a string")
        counterparty = line.get("counterparty_entity_id")
        if counterparty is not None:
            get_entity(counterparty)
        line_no = line.get("line_no", idx)
        if isinstance(line_no, bool) or not isinstance(line_no, int):
            raise ApiError("ERR_VALIDATION", 400,
                           "line line_no must be an integer")
        memo = line.get("memo")
        parsed.append({
            "line_no": line_no,
            "account_code": account_code,
            "direction": direction,
            "amount_minor": amount,
            "counterparty_entity_id": counterparty,
            "memo": memo,
        })
    period = period_of_ep(ep)
    if not (period["period_start"] <= entry_date <= period["period_end"]):
        raise ApiError("ERR_JE_OUT_OF_PERIOD", 409,
                       "entry_date must fall within [period_start, "
                       "period_end]")
    entity = entity_of_ep(ep)
    if functional_currency != entity["functional_currency"]:
        raise ApiError("ERR_JE_CCY_MISMATCH", 409,
                       "functional_currency must equal the entity's "
                       "functional currency")
    je = create_je(ep, je_type, entry_date, parsed, uid)
    return ok(ser_je(je), 201)


@bp.get("/close/journal-entries/<jid>")
def get_one_je(jid):
    require_roles(*READERS)
    return ok(ser_je(get_je(jid)))


@bp.get("/close/entity-periods/<eid>/journal-entries")
def list_ep_jes(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    records = [j for j in STORE["journal_entries"].values()
               if j["entity_period_id"] == ep["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [j for j in records if j["status"] == status]
    je_type = request.args.get("je_type")
    if je_type is not None:
        records = [j for j in records if j["je_type"] == je_type]
    return paged_response(records, ser_je)


@bp.get("/close/journal-entries/<jid>/lines")
def list_je_lines(jid):
    require_roles(*READERS)
    je = get_je(jid)
    records = [l for l in STORE["je_lines"].values()
               if l["journal_entry_id"] == je["id"]]
    return paged_response(records, ser_line)


@bp.post("/close/journal-entries/<jid>/submit")
def submit_je(jid):
    require_roles("Preparer")
    je = get_je(jid)
    if je["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DRAFT journal entry can be submitted")
    ep = get_ep(je["entity_period_id"])
    _ep_lock_for_je(ep)
    if je["debit_total_minor"] != je["credit_total_minor"] \
            or je["debit_total_minor"] <= 0:
        raise ApiError("ERR_JE_UNBALANCED", 409,
                       "debit_total_minor must equal credit_total_minor and "
                       "both must be > 0")
    if je["je_type"] in ("MANUAL", "TOP_SIDE") \
            and je["doc_state"] == "DOC_MISSING":
        raise ApiError("ERR_DOC_REQUIRED", 409,
                       "MANUAL/TOP_SIDE entries require at least one "
                       "supporting document")
    je["status"] = "SUBMITTED"
    bump(je)
    return ok(ser_je(je))


@bp.post("/close/journal-entries/<jid>/approve")
def approve_je(jid):
    uid = require_roles("Approver")
    je = get_je(jid)
    if je["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED journal entry can be approved")
    if uid == je["preparer_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Approver must differ from the entry's preparer")
    ep = get_ep(je["entity_period_id"])
    period = period_of_ep(ep)
    if period is not None and period["status"] == "FINALIZED":
        raise ApiError("ERR_PERIOD_LOCKED", 409, "Period is FINALIZED")
    if ep["status"] in ("SOFT_LOCKED", "HARD_LOCKED"):
        raise ApiError("ERR_PERIOD_LOCKED", 409,
                       "Entity-period is locked; approval not permitted")
    if je["doc_state"] != "DOC_VERIFIED":
        raise ApiError("ERR_DOC_NOT_VERIFIED", 409,
                       "doc_state must be DOC_VERIFIED before approval")
    je["approver_user_id"] = uid
    je["status"] = "APPROVED"
    bump(je)
    return ok(ser_je(je))


@bp.post("/close/journal-entries/<jid>/post")
def post_je(jid):
    uid = require_roles("Preparer")
    je = get_je(jid)
    if je["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED journal entry can be posted")
    if uid == je["approver_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Poster must differ from the entry's approver")
    ep = get_ep(je["entity_period_id"])
    _ep_lock_for_je(ep)
    je["status"] = "POSTED"
    je["posted_at"] = logical_now()
    bump(je)
    recompute_trial_balance(ep)
    ep["_translation_stale"] = True
    touch_ep(ep)
    period = period_of_ep(ep)
    add_event(period["id"], ep["id"], "JE_POSTED", uid,
              json_detail({"journal_entry_id": je["id"]}))
    return ok(ser_je(je))


@bp.post("/close/journal-entries/<jid>/reject")
def reject_je(jid):
    uid = require_roles("Approver")
    je = get_je(jid)
    if je["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a SUBMITTED journal entry can be rejected")
    if uid == je["preparer_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Rejecter must differ from the entry's preparer")
    reason = body().get("rejection_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError("ERR_REJECTION_REASON_REQUIRED", 409,
                       "rejection_reason must be non-empty")
    je["status"] = "REJECTED"
    je["rejection_reason"] = reason
    bump(je)
    return ok(ser_je(je))


@bp.post("/close/journal-entries/<jid>/rework")
def rework_je(jid):
    uid = require_roles("Preparer")
    je = get_je(jid)
    if je["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REJECTED journal entry can be reworked")
    if uid != je["preparer_user_id"]:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the original preparer may rework the entry")
    je["status"] = "DRAFT"
    je["rejection_reason"] = None
    attached = any(d["status"] == "ATTACHED"
                   for d in STORE["documents"].values()
                   if d["journal_entry_id"] == je["id"])
    je["doc_state"] = "DOC_ATTACHED" if attached else "DOC_MISSING"
    bump(je)
    return ok(ser_je(je))


# ---------------------------------------------------------------------------
# SupportingDocument
# ---------------------------------------------------------------------------
@bp.post("/close/journal-entries/<jid>/documents")
def attach_document(jid):
    uid = require_roles("Preparer")
    je = get_je(jid)
    ep = get_ep(je["entity_period_id"])
    lock_gate_ep(ep, child_creation=True)
    b = body()
    file_name = req_str(b, "file_name")
    content_hash = req_str(b, "content_hash")
    doc_category = req_enum(b, "doc_category",
                            ("INVOICE", "CONTRACT", "BANK_STATEMENT",
                             "SCHEDULE", "OTHER"))
    for d in STORE["documents"].values():
        if d["journal_entry_id"] == je["id"] and d["status"] != "REJECTED" \
                and d["content_hash"] == content_hash:
            raise ApiError("ERR_DOC_DUPLICATE", 409,
                           "A document with this content_hash is already "
                           "attached to the journal entry")
    rec = base_record()
    rec.update({
        "journal_entry_id": je["id"],
        "file_name": file_name,
        "content_hash": content_hash,
        "doc_category": doc_category,
        "uploaded_by_user_id": uid,
        "verified_by_user_id": None,
        "status": "ATTACHED",
    })
    STORE["documents"][rec["id"]] = rec
    recompute_doc_state(je)
    return ok(ser_doc(rec), 201)


@bp.get("/close/journal-entries/<jid>/documents")
def list_documents(jid):
    require_roles(*READERS)
    je = get_je(jid)
    records = [d for d in STORE["documents"].values()
               if d["journal_entry_id"] == je["id"]]
    return paged_response(records, ser_doc)


@bp.post("/close/documents/<did>/verify")
def verify_document(did):
    uid = require_roles("Approver")
    doc = get_doc(did)
    if doc["status"] != "ATTACHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ATTACHED document can be verified")
    je = get_je(doc["journal_entry_id"])
    if je["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Documents can be verified only while the entry is "
                       "DRAFT or SUBMITTED")
    if uid == doc["uploaded_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Verifier must differ from the document uploader")
    doc["status"] = "VERIFIED"
    doc["verified_by_user_id"] = uid
    bump(doc)
    recompute_doc_state(je)
    return ok(ser_doc(doc))


@bp.post("/close/documents/<did>/reject")
def reject_document(did):
    require_roles("Approver")
    doc = get_doc(did)
    if doc["status"] != "ATTACHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ATTACHED document can be rejected")
    doc["status"] = "REJECTED"
    bump(doc)
    je = get_je(doc["journal_entry_id"])
    recompute_doc_state(je)
    return ok(ser_doc(doc))


# ---------------------------------------------------------------------------
# Reconciliation + ReconcilingItem
# ---------------------------------------------------------------------------
@bp.post("/close/entity-periods/<eid>/reconciliations")
def create_recon(eid):
    require_roles("Preparer")
    ep = get_ep(eid)
    lock_gate_ep(ep, child_creation=True)
    b = body()
    account_code = req_str(b, "account_code")
    recon_type = req_enum(b, "recon_type",
                          ("BANK", "INTERCOMPANY", "SUBLEDGER_GL", "SUSPENSE"))
    gl_balance = req_int(b, "gl_balance_minor")
    sub_balance = req_int(b, "subledger_balance_minor")
    rec = base_record()
    diff = gl_balance - sub_balance
    rec.update({
        "entity_period_id": ep["id"],
        "account_code": account_code,
        "recon_type": recon_type,
        "gl_balance_minor": gl_balance,
        "subledger_balance_minor": sub_balance,
        "difference_minor": diff,
        "is_within_tolerance": abs(diff) <= RECON_TOLERANCE,
        "status": "OPEN",
        "cleared_by_user_id": None,
        "reviewed_by_user_id": None,
    })
    STORE["reconciliations"][rec["id"]] = rec
    recompute_unreconciled_count(ep)
    return ok(ser_recon(rec), 201)


@bp.get("/close/entity-periods/<eid>/reconciliations")
def list_ep_recons(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    records = [r for r in STORE["reconciliations"].values()
               if r["entity_period_id"] == ep["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paged_response(records, ser_recon)


@bp.get("/close/reconciliations/<rid>")
def get_one_recon(rid):
    require_roles(*READERS)
    return ok(ser_recon(get_recon(rid)))


def _recon_lock_gate(recon):
    ep = get_ep(recon["entity_period_id"])
    lock_gate_ep(ep)
    return ep


@bp.post("/close/reconciliations/<rid>/review")
def review_recon(rid):
    uid = require_roles("Preparer")
    recon = get_recon(rid)
    if recon["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN reconciliation can move to IN_REVIEW")
    ep = _recon_lock_gate(recon)
    if ep["status"] not in ("SUBLEDGER_CUT", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Review requires the entity-period in SUBLEDGER_CUT "
                       "or REOPENED")
    recon["reviewed_by_user_id"] = uid
    recon["status"] = "IN_REVIEW"
    bump(recon)
    return ok(ser_recon(recon))


@bp.post("/close/reconciliations/<rid>/clear")
def clear_recon(rid):
    uid = require_roles("Preparer")
    recon = get_recon(rid)
    if recon["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_REVIEW reconciliation can be cleared")
    if uid == recon["reviewed_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 409,
                       "Clearer must differ from the reviewer")
    ep = _recon_lock_gate(recon)
    recompute_recon_difference(recon)
    if not recon["is_within_tolerance"]:
        raise ApiError("ERR_RECON_UNRESOLVED_ITEMS", 409,
                       "Open reconciling items remain and the difference is "
                       "out of tolerance")
    recon["cleared_by_user_id"] = uid
    recon["status"] = "CLEARED"
    bump(recon)
    recompute_unreconciled_count(ep)
    period = period_of_ep(ep)
    add_event(period["id"], ep["id"], "RECON_CLEARED", uid,
              json_detail({"reconciliation_id": recon["id"]}))
    return ok(ser_recon(recon))


@bp.post("/close/reconciliations/<rid>/return")
def return_recon(rid):
    require_roles("Preparer")
    recon = get_recon(rid)
    if recon["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an IN_REVIEW reconciliation can be returned")
    _recon_lock_gate(recon)
    recon["reviewed_by_user_id"] = None
    recon["status"] = "OPEN"
    bump(recon)
    return ok(ser_recon(recon))


@bp.post("/close/reconciliations/<rid>/items")
def create_item(rid):
    require_roles("Preparer")
    recon = get_recon(rid)
    if recon["status"] not in ("OPEN", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Items can be added only to OPEN or IN_REVIEW "
                       "reconciliations")
    ep = get_ep(recon["entity_period_id"])
    lock_gate_ep(ep, child_creation=True)
    b = body()
    description = req_str(b, "description")
    amount = req_int(b, "amount_minor")
    item_date = req_ts(b, "item_date")
    period = period_of_ep(ep)
    rec = base_record()
    rec.update({
        "reconciliation_id": recon["id"],
        "description": description,
        "amount_minor": amount,
        "item_date": item_date,
        "aging_bucket": "CURRENT",
        "status": "OPEN",
        "resolved_at": None,
    })
    rec["aging_bucket"] = compute_bucket(rec, period, logical_now())
    STORE["recon_items"][rec["id"]] = rec
    recompute_recon_difference(recon)
    recompute_aged_over_30(ep)
    return ok(ser_item(rec), 201)


@bp.get("/close/reconciliations/<rid>/items")
def list_items(rid):
    require_roles(*READERS)
    recon = get_recon(rid)
    records = [i for i in STORE["recon_items"].values()
               if i["reconciliation_id"] == recon["id"]]
    return paged_response(records, ser_item)


@bp.get("/close/reconciliations/<rid>/flux")
def list_recon_flux(rid):
    require_roles(*READERS)
    recon = get_recon(rid)
    records = [f for f in STORE["fluxes"].values()
               if f.get("reconciliation_id") == recon["id"]]
    return paged_response(records, ser_flux)


@bp.post("/close/reconciling-items/<iid>/resolve")
def resolve_item(iid):
    require_roles("Preparer")
    item = get_item(iid)
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN item can be resolved")
    recon = get_recon(item["reconciliation_id"])
    if recon["status"] not in ("OPEN", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Parent reconciliation is not OPEN or IN_REVIEW")
    ep = get_ep(recon["entity_period_id"])
    lock_gate_ep(ep)
    item["status"] = "RESOLVED"
    item["resolved_at"] = logical_now()
    period = period_of_ep(ep)
    item["aging_bucket"] = compute_bucket(item, period, logical_now())
    bump(item)
    recompute_recon_difference(recon)
    recompute_aged_over_30(ep)
    return ok(ser_item(item))


@bp.post("/close/reconciling-items/<iid>/write-off")
def write_off_item(iid):
    uid = require_roles("Approver")
    item = get_item(iid)
    if item["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN item can be written off")
    recon = get_recon(item["reconciliation_id"])
    ep = get_ep(recon["entity_period_id"])
    lock_gate_ep(ep)
    period = period_of_ep(ep)
    item["aging_bucket"] = compute_bucket(item, period, logical_now())
    if item["aging_bucket"] not in ("AGE_31_60", "AGE_61_90", "AGE_OVER_90"):
        raise ApiError("ERR_WRITEOFF_TOO_YOUNG", 409,
                       "CURRENT and AGE_1_30 items are too young to write "
                       "off")
    if abs(item["amount_minor"]) >= period["materiality_threshold_minor"]:
        raise ApiError("ERR_WRITEOFF_ABOVE_MATERIALITY", 409,
                       "Items at or above materiality cannot be written off")
    item["status"] = "WRITTEN_OFF"
    item["resolved_at"] = logical_now()
    item["aging_bucket"] = compute_bucket(item, period, logical_now())
    bump(item)
    recompute_recon_difference(recon)
    recompute_aged_over_30(ep)
    amount = abs(item["amount_minor"])
    create_je(ep, "MANUAL", logical_now(), [
        {"account_code": recon["account_code"], "direction": "DEBIT",
         "amount_minor": amount},
        {"account_code": recon["account_code"] + "-WRITEOFF",
         "direction": "CREDIT", "amount_minor": amount},
    ], uid)
    return ok(ser_item(item))


# ---------------------------------------------------------------------------
# ElimPair
# ---------------------------------------------------------------------------
@bp.post("/close/periods/<pid>/elim-pairs")
def create_elim_pair(pid):
    require_roles("Preparer")
    from domain import get_period
    period = get_period(pid)
    b = body()
    ep_a = get_ep(req_str(b, "entity_period_id_a"))
    ep_b = get_ep(req_str(b, "entity_period_id_b"))
    if ep_a["close_period_id"] != period["id"] \
            or ep_b["close_period_id"] != period["id"]:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "Both entity-periods must belong to this period")
    account_code = req_str(b, "account_code")
    amount_a = req_int(b, "amount_a_minor")
    amount_b = req_int(b, "amount_b_minor")
    if ep_a["id"] == ep_b["id"] \
            or ep_a["entity_id"] == ep_b["entity_id"]:
        raise ApiError("ERR_ELIM_SAME_ENTITY", 409,
                       "Elimination pair must span two distinct entities")
    rec = base_record()
    rec.update({
        "close_period_id": period["id"],
        "entity_period_id_a": ep_a["id"],
        "entity_period_id_b": ep_b["id"],
        "account_code": account_code,
        "amount_a_minor": amount_a,
        "amount_b_minor": amount_b,
        "eliminated_amount_minor": 0,
        "residual_minor": 0,
        "status": "PROPOSED",
    })
    STORE["elim_pairs"][rec["id"]] = rec
    return ok(ser_elim(rec), 201)


@bp.get("/close/periods/<pid>/elim-pairs")
def list_period_elims(pid):
    require_roles(*READERS)
    from domain import get_period
    period = get_period(pid)
    records = [p for p in STORE["elim_pairs"].values()
               if p["close_period_id"] == period["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paged_response(records, ser_elim)


@bp.get("/close/entity-periods/<eid>/elim-pairs")
def list_ep_elims(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    records = [p for p in STORE["elim_pairs"].values()
               if ep["id"] in (p["entity_period_id_a"],
                               p["entity_period_id_b"])]
    return paged_response(records, ser_elim)


@bp.post("/close/elim-pairs/<x>/match")
def match_elim(x):
    require_roles("Preparer")
    pair = get_elim(x)
    if pair["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROPOSED pair can be matched")
    ep_a = get_ep(pair["entity_period_id_a"])
    ep_b = get_ep(pair["entity_period_id_b"])
    for ep in (ep_a, ep_b):
        if ep["status"] not in ("RECONCILED", "READY_FOR_CONSOL", "REOPENED"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Both sides must be RECONCILED, READY_FOR_CONSOL, "
                           "or REOPENED to match")
    period = period_of_ep(ep_a)
    eliminated, residual = compute_elim_amounts(pair, period, strict_fx=True)
    pair["eliminated_amount_minor"] = eliminated
    pair["residual_minor"] = residual
    pair["status"] = "MATCHED"
    bump(pair)
    return ok(ser_elim(pair))


@bp.post("/close/elim-pairs/<x>/eliminate")
def eliminate_elim(x):
    uid = require_roles("Preparer")
    pair = get_elim(x)
    if pair["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a MATCHED pair can be eliminated")
    if abs(pair["residual_minor"]) > ELIM_TOLERANCE:
        raise ApiError("ERR_ELIM_RESIDUAL_EXCEEDED", 409,
                       "abs(residual_minor) exceeds the elimination "
                       "tolerance of 500")
    ep_a = get_ep(pair["entity_period_id_a"])
    ep_b = get_ep(pair["entity_period_id_b"])
    amount = pair["eliminated_amount_minor"]
    for ep, other in ((ep_a, ep_b), (ep_b, ep_a)):
        other_entity = entity_of_ep(other)
        create_je(
            ep, "ELIMINATION", logical_now(),
            [{"account_code": pair["account_code"], "direction": "DEBIT",
              "amount_minor": amount,
              "counterparty_entity_id": other_entity["id"]},
             {"account_code": pair["account_code"], "direction": "CREDIT",
              "amount_minor": amount,
              "counterparty_entity_id": other_entity["id"]}],
            uid, approver_user_id="system", status="APPROVED")
    pair["status"] = "ELIMINATED"
    bump(pair)
    period = period_of_ep(ep_a)
    add_event(period["id"], None, "ELIMINATION_RUN", uid,
              json_detail({"elim_pair_id": pair["id"],
                           "eliminated_amount_minor": amount}))
    return ok(ser_elim(pair))


@bp.post("/close/elim-pairs/<x>/dispute")
def dispute_elim(x):
    require_roles("Preparer")
    pair = get_elim(x)
    if pair["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROPOSED pair can be disputed")
    ep_a = get_ep(pair["entity_period_id_a"])
    period = period_of_ep(ep_a)
    eliminated, residual = compute_elim_amounts(pair, period, strict_fx=False)
    if eliminated is not None:
        pair["eliminated_amount_minor"] = eliminated
        pair["residual_minor"] = residual
    pair["status"] = "DISPUTED"
    bump(pair)
    return ok(ser_elim(pair))


# ---------------------------------------------------------------------------
# FluxExplanation
# ---------------------------------------------------------------------------
@bp.post("/close/entity-periods/<eid>/flux")
def create_flux(eid):
    require_roles("Preparer")
    ep = get_ep(eid)
    lock_gate_ep(ep, child_creation=True)
    b = body()
    account_code = req_str(b, "account_code")
    prior = req_int(b, "prior_balance_minor")
    current = req_int(b, "current_balance_minor")
    explanation_text = b.get("explanation_text")
    if explanation_text is not None and not isinstance(explanation_text, str):
        raise ApiError("ERR_VALIDATION", 400,
                       "explanation_text must be a string")
    reconciliation_id = b.get("reconciliation_id")
    if reconciliation_id is not None:
        get_recon(reconciliation_id)
    period = period_of_ep(ep)
    variance = current - prior
    pct = rhu2(Decimal(abs(variance)) * Decimal(100)
               / Decimal(max(abs(prior), 1)))
    requires = (abs(variance) >= period["materiality_threshold_minor"]
                or pct >= Decimal("10.00"))
    rec = base_record()
    rec.update({
        "entity_period_id": ep["id"],
        "account_code": account_code,
        "prior_balance_minor": prior,
        "current_balance_minor": current,
        "variance_minor": variance,
        "variance_pct": float(pct),
        "requires_explanation": requires,
        "explanation_text": explanation_text,
        "reconciliation_id": reconciliation_id,
        "status": "OPEN",
    })
    STORE["fluxes"][rec["id"]] = rec
    return ok(ser_flux(rec), 201)


@bp.get("/close/entity-periods/<eid>/flux")
def list_ep_flux(eid):
    require_roles(*READERS)
    ep = get_ep(eid)
    records = [f for f in STORE["fluxes"].values()
               if f["entity_period_id"] == ep["id"]]
    return paged_response(records, ser_flux)


@bp.post("/close/flux/<fid>/explain")
def explain_flux(fid):
    require_roles("Preparer")
    flux = get_flux(fid)
    if flux["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an OPEN flux row can be explained")
    text = body().get("explanation_text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError("ERR_EXPLANATION_REQUIRED", 409,
                       "explanation_text must be non-empty")
    flux["explanation_text"] = text
    flux["status"] = "EXPLAINED"
    bump(flux)
    return ok(ser_flux(flux))


@bp.post("/close/flux/<fid>/accept")
def accept_flux(fid):
    require_roles("Controller")
    flux = get_flux(fid)
    if flux["status"] != "EXPLAINED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an EXPLAINED flux row can be accepted")
    if flux.get("reconciliation_id"):
        recon = get_recon(flux["reconciliation_id"])
        if recon["status"] != "CLEARED":
            raise ApiError("ERR_FLUX_RECON_NOT_CLEARED", 409,
                           "Linked reconciliation must be CLEARED before "
                           "flux acceptance")
    flux["status"] = "ACCEPTED"
    bump(flux)
    return ok(ser_flux(flux))


@bp.post("/close/flux/<fid>/reject")
def reject_flux(fid):
    require_roles("Controller")
    flux = get_flux(fid)
    if flux["status"] != "EXPLAINED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an EXPLAINED flux row can be rejected")
    flux["status"] = "REJECTED"
    bump(flux)
    return ok(ser_flux(flux))


@bp.post("/close/flux/<fid>/reopen")
def reopen_flux(fid):
    require_roles("Preparer")
    flux = get_flux(fid)
    if flux["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a REJECTED flux row can be reopened")
    flux["status"] = "OPEN"
    flux["explanation_text"] = None
    bump(flux)
    return ok(ser_flux(flux))
