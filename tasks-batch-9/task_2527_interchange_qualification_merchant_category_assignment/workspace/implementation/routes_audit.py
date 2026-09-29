"""Merchant category audits and the logical clock (PRD 3.9 and 2.6)."""

from flask import Blueprint, request

import calc
import listing
import resolve
import validate as v
from auth import ALL_ROLES, authenticate
from envelope import array_response, empty_response, object_response, paginate
from errors import (
    ERR_INVALID_STATE,
    ERR_MCC_NOT_DEFINED,
    ERR_SEGREGATION_OF_DUTIES,
    fail,
)
from store import serialize, serialize_many, sorted_rows, store, touch

bp = Blueprint("audit", __name__)

MANUAL_TRIGGER_REASONS = ("RECLASS_SUSPICION", "PERIODIC", "COMPLAINT")


def acting_user():
    return request.headers.get("X-User-ID")


@bp.post("/merchant-category-audits")
def open_audit():
    authenticate(["ComplianceAuditor"])
    data = v.body()

    merchant_id = v.raw_id(data, "merchant_id")
    if merchant_id is not None:
        resolve.merchant(merchant_id)

    v.req_str(data, "merchant_id")
    # DOWNGRADE_THRESHOLD is reserved for the finalization cascade, so supplying
    # it manually is an out-of-domain enum value.
    trigger_reason = v.req_enum(data, "trigger_reason", MANUAL_TRIGGER_REASONS)

    merchant = store.merchants[data["merchant_id"]]
    if merchant["mcc_status"] not in ("PENDING_VERIFICATION", "VERIFIED"):
        fail(ERR_INVALID_STATE, "The merchant's category posture does not permit an audit.")

    audit = calc.open_audit_on_merchant(merchant, trigger_reason, None)
    return object_response(serialize("MerchantCategoryAudit", audit), 201)


@bp.post("/merchant-category-audits/<row_id>/start-fieldwork")
def start_fieldwork(row_id):
    authenticate(["ComplianceAuditor"])
    audit = resolve.audit(row_id)
    data = v.body()
    start = v.req_ts(data, "fieldwork_start")
    end = v.req_ts(data, "fieldwork_end")
    if start > end:
        v.bad("'fieldwork_start' must be at or before 'fieldwork_end'.")
    if audit["status"] != "SCHEDULED":
        fail(ERR_INVALID_STATE, "Only a SCHEDULED audit may begin fieldwork.")
    if not start < end:
        fail(ERR_INVALID_STATE,
             "'fieldwork_start' must be strictly earlier than 'fieldwork_end'.")
    audit["status"] = "FIELDWORK"
    audit["auditor_user_id"] = acting_user()
    audit["fieldwork_start"] = start
    audit["fieldwork_end"] = end
    touch(audit)
    return object_response(serialize("MerchantCategoryAudit", audit))


def _require_fieldwork_owner(audit):
    if audit["status"] != "FIELDWORK":
        fail(ERR_INVALID_STATE, "The audit is not in FIELDWORK.")
    if audit["auditor_user_id"] != acting_user():
        fail(ERR_INVALID_STATE,
             "Only the auditor recorded on the audit may take a fork branch.")


@bp.post("/merchant-category-audits/<row_id>/sustain-findings")
def sustain_findings(row_id):
    authenticate(["ComplianceAuditor"])
    audit = resolve.audit(row_id)
    data = v.body()
    correct_mcc = v.req_mcc(data, "correct_mcc")
    note = v.req_str(data, "findings_note", 1, 2000)
    _require_fieldwork_owner(audit)
    if not calc.mcc_code_exists(correct_mcc):
        fail(ERR_MCC_NOT_DEFINED, "correct_mcc names no MCC definition.")

    merchant = store.merchants.get(audit["merchant_id"])
    # The ledger is read before any part of the cascade runs.
    ledger = int(merchant["lifetime_net_assessed_cents"]) if merchant else 0
    audit["status"] = "FINDINGS_SUSTAINED"
    audit["correct_mcc"] = correct_mcc
    audit["findings_note"] = note
    audit["penalty_assessed_cents"] = calc.misrepresentation_penalty(ledger)
    touch(audit)

    if merchant is not None:
        merchant["assigned_mcc"] = correct_mcc
        merchant["mcc_status"] = "MISREPRESENTED"
        touch(merchant)
        calc.terminate_ineligible_enrollments(merchant)
        calc.deny_suspended_requests(merchant["id"])
    return object_response(serialize("MerchantCategoryAudit", audit))


@bp.post("/merchant-category-audits/<row_id>/clear-findings")
def clear_findings(row_id):
    authenticate(["ComplianceAuditor"])
    audit = resolve.audit(row_id)
    data = v.body()
    note = v.req_str(data, "findings_note", 1, 2000)
    _require_fieldwork_owner(audit)

    audit["status"] = "FINDINGS_CLEARED"
    audit["findings_note"] = note
    touch(audit)

    merchant = store.merchants.get(audit["merchant_id"])
    if merchant is not None:
        snapshot = merchant.get("mcc_status_before_review")
        if snapshot is not None:
            merchant["mcc_status"] = snapshot
        merchant["mcc_status_before_review"] = None
        touch(merchant)
        calc.restore_suspended_requests(merchant["id"])
    return object_response(serialize("MerchantCategoryAudit", audit))


@bp.post("/merchant-category-audits/<row_id>/close")
def close_audit(row_id):
    authenticate(["ComplianceAuditor"])
    audit = resolve.audit(row_id)
    if audit["status"] not in ("FINDINGS_SUSTAINED", "FINDINGS_CLEARED"):
        fail(ERR_INVALID_STATE, "Only a finished fork branch may be closed.")
    if audit["auditor_user_id"] == acting_user():
        fail(ERR_SEGREGATION_OF_DUTIES)
    audit["status"] = "CLOSED"
    audit["closed_by_user_id"] = acting_user()
    touch(audit)
    return object_response(serialize("MerchantCategoryAudit", audit))


@bp.get("/merchant-category-audits/<row_id>")
def get_audit(row_id):
    authenticate(ALL_ROLES)
    audit = resolve.audit(row_id)
    return object_response(serialize("MerchantCategoryAudit", audit))


@bp.get("/merchant-category-audits")
def list_audits():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.audits.values()))
    rows = listing.apply_string_filters(rows, [
        ("merchant_id", "merchant_id"),
        ("status", "status"),
        ("trigger_reason", "trigger_reason"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("MerchantCategoryAudit", page), meta)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["NetworkAdmin"])
    data = v.body()
    target = v.req_ts(data, "to_iso8601")
    calc.set_logical_clock(target)
    return empty_response(200)
