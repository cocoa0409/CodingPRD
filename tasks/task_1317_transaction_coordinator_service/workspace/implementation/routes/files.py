"""Transaction files: create, lifecycle transitions, compliance audit."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, touch, pub, pub_list, fmt_dt
from response import ok_object, ok_list
from services import calc
from services import cascade
from util import parse_date

bp = Blueprint("files", __name__)

FILE_SHAPE = [
    ("billing_model", "enum", True, mw.BILLING_MODELS),
    ("state_code", "string", True, mw.state_code_ok),
    ("contract_type", "enum", True, mw.CONTRACT_TYPES),
    ("property_address", "string", True),
    ("effective_date", "date", True),
    ("closing_date", "date", True),
    ("list_price_cents", "int", True),
    ("seller_agent_id", "string", True),
    ("buyer_agent_id", "string", False),
    ("subscription_id", "string", False),
    ("expected_subscription_version", "int", False),
    ("inspection_offset_days", "int", False, mw.non_negative_int),
    ("appraisal_offset_days", "int", False, mw.non_negative_int),
    ("financing_offset_days", "int", False, mw.non_negative_int),
]


@bp.post("/tc/files")
def create_file():
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    data = mw.body()

    # priority 3: body FK existence, payload order (seller_agent_id, buyer_agent_id).
    seller = store.agents.get(data["seller_agent_id"]) if isinstance(data.get("seller_agent_id"), str) else None
    if data.get("seller_agent_id") is not None and seller is None:
        E.raise_err(E.ERR_AGENT_NOT_FOUND, "seller_agent_id does not resolve")
    buyer = None
    if data.get("buyer_agent_id") is not None:
        buyer = store.agents.get(data["buyer_agent_id"]) if isinstance(data.get("buyer_agent_id"), str) else None
        if buyer is None:
            E.raise_err(E.ERR_AGENT_NOT_FOUND, "buyer_agent_id does not resolve")

    # priority 5: OCC on subscription version (SUBSCRIPTION billing only).
    billing = data.get("billing_model")
    sub = None
    if billing == "SUBSCRIPTION" and isinstance(data.get("subscription_id"), str):
        sub = store.subscriptions.get(data["subscription_id"])
        expected = data.get("expected_subscription_version")
        if sub is not None and isinstance(expected, int) and not isinstance(expected, bool):
            if expected != sub["version"]:
                E.raise_err(E.ERR_STALE_SUBSCRIPTION_VERSION,
                            "expected_subscription_version does not match the subscription version")

    # priority 8: closing_date not before the current clock date.
    if isinstance(data.get("closing_date"), str) and mw.is_date_str(data["closing_date"]):
        if parse_date(data["closing_date"]) < store.now.date():
            E.raise_err(E.ERR_CLOSING_DATE_IN_PAST, "closing_date is before the current clock date")

    # priority 10: referential usability.
    ctype = data.get("contract_type")
    if ctype == "PURCHASE_SALE" and data.get("buyer_agent_id") is None:
        E.raise_err(E.ERR_INVALID_REQUEST, "buyer_agent_id is required for PURCHASE_SALE")
    if billing == "SUBSCRIPTION":
        if data.get("subscription_id") is None:
            E.raise_err(E.ERR_INVALID_REQUEST, "subscription_id is required for SUBSCRIPTION billing")
        if data.get("expected_subscription_version") is None:
            E.raise_err(E.ERR_INVALID_REQUEST,
                        "expected_subscription_version is required for SUBSCRIPTION billing")
        if sub is None or sub["status"] != "ACTIVE" or sub["coordinator_id"] != uid:
            E.raise_err(E.ERR_SUBSCRIPTION_INACTIVE,
                        "Subscription is missing, not ACTIVE, or not owned by the acting coordinator")
    elif billing == "PER_FILE":
        if data.get("subscription_id") is not None:
            E.raise_err(E.ERR_INVALID_REQUEST, "subscription_id is forbidden for PER_FILE billing")
    if seller is not None and seller["coordinator_id"] != uid:
        E.raise_err(E.ERR_AGENT_NOT_FOUND, "seller_agent_id is not on the acting coordinator's roster")
    if buyer is not None and buyer["coordinator_id"] != uid:
        E.raise_err(E.ERR_AGENT_NOT_FOUND, "buyer_agent_id is not on the acting coordinator's roster")

    # priority 12: request shape.
    mw.validate_shape(data, FILE_SHAPE)

    rec = mint({
        "coordinator_id": uid,
        "buyer_agent_id": data.get("buyer_agent_id"),
        "seller_agent_id": data["seller_agent_id"],
        "subscription_id": data.get("subscription_id") if billing == "SUBSCRIPTION" else None,
        "billing_model": billing,
        "state_code": data["state_code"],
        "contract_type": ctype,
        "property_address": data["property_address"],
        "effective_date": data["effective_date"],
        "closing_date": data["closing_date"],
        "inspection_offset_days": data.get("inspection_offset_days"),
        "appraisal_offset_days": data.get("appraisal_offset_days"),
        "financing_offset_days": data.get("financing_offset_days"),
        "list_price_cents": data["list_price_cents"],
        "template_id": None,
        "template_version": None,
        "fee_estimate_cents": None,
        "fee_final_cents": None,
        "last_audit_status": "NONE",
        "open_escalation_count": 0,
        "status": "DRAFT",
        "terminated_reason": None,
        "archived_at": None,
        "_within_quota": False,
        "_rush_cents": 0,
    })
    if billing == "SUBSCRIPTION":
        calc.commit_subscription_slot(sub, rec)
    store.files[rec["id"]] = rec
    return ok_object(pub("file", rec), 201)


@bp.get("/tc/files/<fileId>")
def get_file(fileId):
    mw.auth()
    rec = mw.get_or_404("file", fileId)
    return ok_object(pub("file", rec))


@bp.get("/tc/files")
def list_files():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.files.values())
    for param in ("coordinator_id", "buyer_agent_id", "seller_agent_id",
                  "subscription_id", "template_id", "status"):
        recs = mw.filter_eq(recs, param, request.args.get(param))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("file", page), limit, offset, total)


@bp.post("/tc/files/<fileId>/activate")
def activate_file(fileId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("file", fileId)
    mw.own_file(uid, rec)
    # priority 6: state
    if rec["status"] != "DRAFT":
        E.raise_err(E.ERR_FILE_NOT_DRAFT, "Activation requires a file in DRAFT")
    # priority 8: closing date vs clock
    if parse_date(rec["closing_date"]) < store.now.date():
        E.raise_err(E.ERR_CLOSING_DATE_IN_PAST, "closing_date is before the current clock date")
    # priority 9: closing calendar min gap (difference of 0 or 1 day conflicts).
    for other in store.files.values():
        if other["id"] == rec["id"] or other["coordinator_id"] != rec["coordinator_id"]:
            continue
        if other["status"] not in ("ACTIVE", "PENDING_CLOSE"):
            continue
        gap = abs((parse_date(other["closing_date"]) - parse_date(rec["closing_date"])).days)
        if gap < calc.MIN_CLOSING_GAP_DAYS:
            E.raise_err(E.ERR_CLOSING_DATE_CONFLICT,
                        "Another ACTIVE/PENDING_CLOSE file closes within one day of this closing_date")
    # priority 10: ACTIVE template for (state_code, contract_type); subscription usable.
    template = None
    for t in store.templates.values():
        if t["status"] == "ACTIVE" and t["state_code"] == rec["state_code"] \
                and t["contract_type"] == rec["contract_type"]:
            template = t
            break
    if template is None:
        E.raise_err(E.ERR_TEMPLATE_NOT_FOUND,
                    "No ACTIVE template for this (state_code, contract_type)")
    if rec["billing_model"] == "SUBSCRIPTION":
        sub = store.subscriptions.get(rec.get("subscription_id"))
        if sub is None or sub["status"] != "ACTIVE" or sub["coordinator_id"] != uid:
            E.raise_err(E.ERR_SUBSCRIPTION_INACTIVE,
                        "Subscription is missing, not ACTIVE, or not owned by the acting coordinator")

    # side effects: pin template, instantiate milestones / deadlines / reminders,
    # fee estimate, DRAFT invoice.
    rec["template_id"] = template["id"]
    rec["template_version"] = template["template_version"]
    for d in template["milestone_defs"]:
        mrec = mint({
            "file_id": rec["id"],
            "name": d["name"],
            "offset_days": d["offset_days"],
            "mandatory": d["mandatory"],
            "due_date": calc.milestone_due_date(rec["effective_date"], d["offset_days"]),
            "status": "PENDING",
            "completed_at": None,
            "late_completion": False,
        })
        store.milestones[mrec["id"]] = mrec
    convention = calc.day_convention(rec["state_code"])
    for kind, offset in (("INSPECTION", rec.get("inspection_offset_days")),
                         ("APPRAISAL", rec.get("appraisal_offset_days")),
                         ("FINANCING", rec.get("financing_offset_days"))):
        if offset is None:
            if kind == "FINANCING":
                continue  # cash deal: no financing contingency
            offset = 0
        drec = mint({
            "file_id": rec["id"],
            "kind": kind,
            "offset_days": offset,
            "day_convention": convention,
            "due_date": calc.deadline_due_date(rec["effective_date"], offset, rec["state_code"]),
            "status": "PENDING",
            "met_at": None,
            "escalated": False,
        })
        store.deadlines[drec["id"]] = drec
        calc.create_reminders(drec)
    fee, lines, rush = calc.fee_estimate(rec)
    rec["fee_estimate_cents"] = fee
    rec["_rush_cents"] = rush
    calc.build_invoice(rec, lines)
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok_object(pub("file", rec))


@bp.post("/tc/files/<fileId>/terminate")
def terminate_file(fileId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("file", fileId)
    mw.own_file(uid, rec)
    if rec["status"] not in ("ACTIVE", "PENDING_CLOSE"):
        E.raise_err(E.ERR_FILE_ALREADY_TERMINAL,
                    "Only an ACTIVE or PENDING_CLOSE file can be terminated")
    data = mw.body()
    mw.validate_shape(data, [("reason", "string", False)])
    cascade.terminate_file(rec, data.get("reason"))
    return ok_object(pub("file", rec))


@bp.post("/tc/files/<fileId>/request-close")
def request_close(fileId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("file", fileId)
    mw.own_file(uid, rec)
    if rec["status"] != "ACTIVE":
        E.raise_err(E.ERR_FILE_NOT_ACTIVE, "Request-close requires an ACTIVE file")
    # Compliance gates in fixed sub-order: audit, mandatory milestones, escalations.
    if rec["last_audit_status"] != "PASS":
        E.raise_err(E.ERR_AUDIT_NOT_PASSED, "last_audit_status must be PASS")
    for m in store.milestones.values():
        if m["file_id"] == rec["id"] and m["mandatory"] and m["status"] != "COMPLETED":
            E.raise_err(E.ERR_MANDATORY_MILESTONES_OPEN,
                        "Every mandatory milestone must be COMPLETED")
    if rec["open_escalation_count"] != 0:
        E.raise_err(E.ERR_OPEN_ESCALATIONS, "open_escalation_count must be 0")
    has_financing = any(d["file_id"] == rec["id"] and d["kind"] == "FINANCING"
                        for d in store.deadlines.values())
    cv = mint({
        "file_id": rec["id"],
        "title_status": "PENDING",
        "lender_status": "PENDING" if has_financing else "NOT_REQUIRED",
        "overall_status": "PENDING",
    })
    store.closing_verifications[cv["id"]] = cv
    rec["status"] = "PENDING_CLOSE"
    touch(rec)
    return ok_object(pub("file", rec))


@bp.post("/tc/files/<fileId>/close")
def close_file(fileId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("file", fileId)
    mw.own_file(uid, rec)
    if rec["status"] != "PENDING_CLOSE":
        E.raise_err(E.ERR_FILE_NOT_PENDING_CLOSE, "Close requires a PENDING_CLOSE file")
    cv = next((c for c in store.closing_verifications.values() if c["file_id"] == rec["id"]), None)
    if cv is None or cv["overall_status"] != "CLEAR_TO_CLOSE":
        E.raise_err(E.ERR_NOT_CLEAR_TO_CLOSE, "ClosingVerification is not CLEAR_TO_CLOSE")
    fee, lines = calc.fee_final(rec)
    rec["fee_final_cents"] = fee
    invoice = next((i for i in store.invoices.values() if i["file_id"] == rec["id"]), None)
    if invoice is not None:
        calc.rebuild_invoice(rec, invoice, lines)
    rec["status"] = "CLOSED"
    touch(rec)
    return ok_object(pub("file", rec))


@bp.post("/tc/files/<fileId>/archive")
def archive_file(fileId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("file", fileId)
    mw.own_file(uid, rec)
    if rec["status"] != "CLOSED":
        E.raise_err(E.ERR_FILE_NOT_CLOSED, "Archive requires a CLOSED file")
    invoice = next((i for i in store.invoices.values() if i["file_id"] == rec["id"]), None)
    if invoice is None or invoice["status"] != "PAID":
        E.raise_err(E.ERR_INVOICE_UNPAID, "Archive requires the file's invoice to be PAID")
    rec["status"] = "ARCHIVED"
    rec["archived_at"] = fmt_dt(store.now)
    touch(rec)
    return ok_object(pub("file", rec))


@bp.post("/tc/files/<fileId>/compliance-audit")
def compliance_audit(fileId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("file", fileId)
    mw.own_file(uid, rec)
    result = calc.run_audit(rec)
    return ok_object(result)
