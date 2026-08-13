"""Auth header extraction, RBAC, body parsing, shape validation, pagination,
existence and ownership helpers. Validation order follows PRD section 2.5."""
from flask import request

import errors as E
from db import store
from util import is_date_str, is_dt_str

ROLES = {"SystemAdmin", "Coordinator", "Agent", "TitleRep", "LenderRep"}

CONTRACT_TYPES = ("PURCHASE_SALE", "LISTING_ONLY")
BILLING_MODELS = ("PER_FILE", "SUBSCRIPTION")
DOC_TYPES = ("EXECUTED_CONTRACT", "INSPECTION_REPORT", "APPRAISAL_REPORT", "LOAN_COMMITMENT",
             "TITLE_COMMITMENT", "T47_DISCLOSURE", "NHD_REPORT", "TDS_DISCLOSURE",
             "HOA_ADDENDUM", "CLOSING_DISCLOSURE", "AMENDMENT_EXECUTED", "OTHER")
PARTIES = ("BUYER_AGENT", "SELLER_AGENT", "LENDER", "TITLE", "COORDINATOR", "SYSTEM")
DIRECTIONS = ("INBOUND", "OUTBOUND", "SYSTEM")


# ---- priority 1: header presence / well-formedness ----
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        E.raise_err(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID header missing or malformed")
    if role is None or role not in ROLES:
        E.raise_err(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-Role header missing or malformed")
    return uid, role


# ---- priority 2: role permission ----
def require_roles(role, allowed):
    if role not in allowed:
        E.raise_err(E.ERR_INSUFFICIENT_PERMISSIONS,
                    f"Role {role} is not permitted for this endpoint")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        E.raise_err(E.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


# ---- priority 3: existence ----
_LOOKUPS = {
    "coordinator": (lambda: store.coordinators, E.ERR_COORDINATOR_NOT_FOUND, "Coordinator"),
    "agent": (lambda: store.agents, E.ERR_AGENT_NOT_FOUND, "Agent"),
    "template": (lambda: store.templates, E.ERR_TEMPLATE_NOT_FOUND, "ChecklistTemplate"),
    "subscription": (lambda: store.subscriptions, E.ERR_SUBSCRIPTION_NOT_FOUND, "Subscription"),
    "file": (lambda: store.files, E.ERR_FILE_NOT_FOUND, "TransactionFile"),
    "milestone": (lambda: store.milestones, E.ERR_MILESTONE_NOT_FOUND, "Milestone"),
    "deadline": (lambda: store.deadlines, E.ERR_DEADLINE_NOT_FOUND, "Deadline"),
    "reminder": (lambda: store.reminders, E.ERR_REMINDER_NOT_FOUND, "Reminder"),
    "document": (lambda: store.documents, E.ERR_DOCUMENT_NOT_FOUND, "Document"),
    "communication": (lambda: store.communications, E.ERR_COMMUNICATION_NOT_FOUND, "CommunicationEntry"),
    "amendment": (lambda: store.amendments, E.ERR_AMENDMENT_NOT_FOUND, "Amendment"),
    "signature_request": (lambda: store.signature_requests, E.ERR_SIGNATURE_REQUEST_NOT_FOUND, "SignatureRequest"),
    "closing_verification": (lambda: store.closing_verifications, E.ERR_CLOSING_VERIFICATION_NOT_FOUND, "ClosingVerification"),
    "invoice": (lambda: store.invoices, E.ERR_INVOICE_NOT_FOUND, "Invoice"),
}


def get_or_404(kind, rid):
    table_fn, err_id, label = _LOOKUPS[kind]
    rec = table_fn().get(rid) if isinstance(rid, str) else None
    if rec is None:
        E.raise_err(err_id, f"{label} not found: {rid}")
    return rec


# ---- priority 4: ownership / scope ----
def own_file(uid, file_rec):
    if file_rec["coordinator_id"] != uid:
        E.raise_err(E.ERR_RESOURCE_NOT_OWNED,
                    "Coordinator does not own the target resource")


def own_file_chain(uid, child_rec, child_label="resource"):
    file_rec = store.files.get(child_rec.get("file_id"))
    if file_rec is not None and file_rec["coordinator_id"] != uid:
        E.raise_err(E.ERR_RESOURCE_NOT_OWNED,
                    f"Coordinator does not own the file behind this {child_label}")
    return file_rec


# ---- priority 12: request shape ----
def validate_shape(data, spec):
    """spec entries: (name, kind, required[, choices_or_validator]).
    kind: string|int|bool|array|date|datetime|enum."""
    allowed = {entry[0] for entry in spec}
    for key in data:
        if key not in allowed:
            E.raise_err(E.ERR_INVALID_REQUEST, f"Unknown field: {key}")
    for entry in spec:
        name, kind, required = entry[0], entry[1], entry[2]
        extra = entry[3] if len(entry) > 3 else None
        if name not in data or data[name] is None:
            if required:
                E.raise_err(E.ERR_INVALID_REQUEST, f"Missing required field: {name}")
            continue
        v = data[name]
        ok = True
        if kind == "string":
            ok = isinstance(v, str)
        elif kind == "int":
            ok = isinstance(v, int) and not isinstance(v, bool)
        elif kind == "bool":
            ok = isinstance(v, bool)
        elif kind == "array":
            ok = isinstance(v, list)
        elif kind == "date":
            ok = is_date_str(v)
        elif kind == "datetime":
            ok = is_dt_str(v)
        elif kind == "enum":
            ok = isinstance(v, str) and v in extra
            extra = None
        if not ok:
            E.raise_err(E.ERR_INVALID_REQUEST, f"Invalid value for field: {name}")
        if callable(extra):
            extra(v)


def non_negative_int(v):
    if v < 0:
        E.raise_err(E.ERR_INVALID_REQUEST, "Value must be >= 0")


def state_code_ok(v):
    if not (isinstance(v, str) and len(v) == 2 and v.isupper() and v.isalpha()):
        E.raise_err(E.ERR_INVALID_REQUEST, "state_code must be two uppercase letters")


# ---- pagination (PRD section 2.3) ----
def page_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            E.raise_err(E.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            E.raise_err(E.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            E.raise_err(E.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            E.raise_err(E.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def apply_page(recs, limit, offset):
    recs = sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(recs)
    return recs[offset:offset + limit], total


def filter_eq(recs, field, value):
    if value is None:
        return recs
    return [r for r in recs if r.get(field) == value]
