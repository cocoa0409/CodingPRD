"""AuditRight endpoints."""

from datetime import timedelta

from flask import Blueprint

from db import db, new_resource, touch, clock
from errors import err
from response import success_object
from services import calc
from services.core import recompute_billing_posture, recompute_recovery_ytd
from services.validate import (
    body, req_int, req_date, req_string, filter_arg_str,
)
from routes.helpers import (
    get_lease_or_404, get_child_or_404, list_response,
)

bp = Blueprint("audits", __name__)


@bp.post("/lease-admin/leases/<lease_id>/audit-rights")
def create_audit_right(lease_id):
    get_lease_or_404(lease_id)
    data = body()
    reconciliation_id = req_string(data, "reconciliation_id")
    invoked_on = req_date(data, "invoked_on")
    # Referential integrity (pipeline step 8): the reconciliation must exist,
    # belong to this lease, and be CLOSED (audit rights attach to a closed
    # reconciliation).
    recon = db["reconciliations"].get(reconciliation_id)
    if recon is None or recon["lease_id"] != lease_id:
        err("ERR_REFERENTIAL_INTEGRITY",
            "reconciliation_id must reference a Reconciliation on this lease")
    if recon["status"] != "CLOSED":
        err("ERR_REFERENTIAL_INTEGRITY",
            "An AuditRight may only be invoked against a closed Reconciliation")
    # window_close_date = reconciliation closed_date + 365 days (fixed
    # calendar rule, no weekend roll-forward).
    closed = calc.d(recon["closed_date"]) if recon.get("closed_date") \
        else clock.current().date()
    aid, common = new_resource()
    ar = {
        **common,
        "lease_id": lease_id,
        "reconciliation_id": reconciliation_id,
        "invoked_on": invoked_on,
        "window_close_date": (closed + timedelta(days=calc.WINDOW_DAYS))
            .isoformat(),
        "status": "INVOKED",
        "findings_delta_cents": None,
    }
    db["audit_rights"][aid] = ar
    return success_object(ar, status=201)


@bp.get("/lease-admin/leases/<lease_id>/audit-rights")
def list_lease_audit_rights(lease_id):
    get_lease_or_404(lease_id)
    return list_response(
        [a for a in db["audit_rights"].values()
         if a["lease_id"] == lease_id],
        filters=[
            (filter_arg_str("status"), lambda r, v: r["status"] == v),
        ])


@bp.get("/lease-admin/audit-rights/<audit_id>")
def get_audit_right(audit_id):
    return success_object(
        get_child_or_404("audit_rights", audit_id, "AuditRight"))


@bp.get("/lease-admin/audit-rights")
def list_audit_rights_filtered():
    return list_response(db["audit_rights"].values(), filters=[
        (filter_arg_str("lease_id"), lambda r, v: r["lease_id"] == v),
        (filter_arg_str("reconciliation_id"),
         lambda r, v: r["reconciliation_id"] == v),
        (filter_arg_str("status"), lambda r, v: r["status"] == v),
    ])


@bp.post("/lease-admin/audit-rights/<audit_id>/start-fieldwork")
def start_fieldwork(audit_id):
    ar = get_child_or_404("audit_rights", audit_id, "AuditRight")
    if ar["status"] != "INVOKED":
        err("ERR_INVALID_STATE", "Start-fieldwork requires status == INVOKED")
    # Window check (pipeline step 13): strictly before window_close_date.
    if clock.current().date() >= calc.d(ar["window_close_date"]):
        err("ERR_AUDIT_WINDOW_CLOSED", "The audit window has closed")
    ar["status"] = "FIELDWORK"
    touch(ar)
    return success_object(ar)


@bp.post("/lease-admin/audit-rights/<audit_id>/issue-findings")
def issue_findings(audit_id):
    ar = get_child_or_404("audit_rights", audit_id, "AuditRight")
    data = body()
    findings_delta_cents = req_int(data, "findings_delta_cents")
    if ar["status"] != "FIELDWORK":
        err("ERR_INVALID_STATE",
            "Issue-findings requires status == FIELDWORK")
    if clock.current().date() >= calc.d(ar["window_close_date"]):
        err("ERR_AUDIT_WINDOW_CLOSED", "The audit window has closed")
    ar["findings_delta_cents"] = findings_delta_cents
    ar["status"] = "FINDINGS_ISSUED"
    touch(ar)
    return success_object(ar)


@bp.post("/lease-admin/audit-rights/<audit_id>/settle")
def settle_audit(audit_id):
    ar = get_child_or_404("audit_rights", audit_id, "AuditRight")
    if ar["status"] != "FINDINGS_ISSUED":
        err("ERR_INVALID_STATE", "Settle requires status == FINDINGS_ISSUED")
    ar["status"] = "SETTLED"
    touch(ar)
    findings = ar["findings_delta_cents"]
    # Cascade: every ESCALATED challenge on the same reconciliation resolves
    # per the findings' sign.
    for ch in db["tenant_challenges"].values():
        if ch["reconciliation_id"] == ar["reconciliation_id"] and \
           ch["status"] == "ESCALATED":
            if findings < 0:
                ch["status"] = "RESOLVED_ACCEPTED"
                ch["resolution_delta_cents"] = findings
            else:
                ch["status"] = "RESOLVED_REJECTED"
                ch["resolution_delta_cents"] = 0
            touch(ch)
    # Reconciliation true-up and the lease's recovery YTD adjust.
    recon = db["reconciliations"].get(ar["reconciliation_id"])
    if recon is not None:
        recon["true_up_cents"] = (recon["true_up_cents"] or 0) + findings
        touch(recon)
    lease = db["leases"].get(ar["lease_id"])
    if lease is not None:
        recompute_recovery_ytd(lease)
        lease["cached_recovery_ytd_cents"] += findings
        touch(lease)
        recompute_billing_posture(lease)
    return success_object(ar)
