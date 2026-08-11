from flask import Blueprint, request

from db import store, touch
from envelope import ok, ok_list
from errors import ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_VALIDATION, raise_err
from security import require_roles
from services import (
    TENURE_RISK_WARN_DAYS,
    create_audit,
    cumulative_tenure,
    governing_card,
    markup_allowed,
)
from validators import apply_filters, get_body, opt_str, paginate, req_str
import serializers

bp = Blueprint("audits", __name__)

READ_ROLES = ("ProgramAdmin", "HiringManager", "FinanceAnalyst")


def _get_audit(audit_id):
    a = store.audits.get(audit_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"Compliance audit {audit_id} not found.")
    return a


@bp.post("/v1/compliance-audits/run")
def run_audit():
    require_roles("ProgramAdmin")
    body = get_body()
    timesheet_id = opt_str(body, "timesheet_id")
    assignment_id = opt_str(body, "assignment_id")
    if (timesheet_id is None) == (assignment_id is None):
        raise_err(
            ERR_VALIDATION,
            "Exactly one of timesheet_id and assignment_id must be supplied.",
        )
    ts = None
    if timesheet_id is not None:
        ts = store.timesheets.get(timesheet_id)
        if ts is None:
            raise_err(ERR_NOT_FOUND, f"Timesheet {timesheet_id} not found.")
        a = store.assignments.get(ts["assignment_id"])
        if a is None:
            raise_err(ERR_NOT_FOUND, f"Assignment {ts['assignment_id']} not found.")
    else:
        a = store.assignments.get(assignment_id)
        if a is None:
            raise_err(ERR_NOT_FOUND, f"Assignment {assignment_id} not found.")
    eng = store.engagements.get(a["engagement_id"])
    worker = store.workers.get(a["worker_id"])
    sup = store.suppliers.get(a["supplier_id"])

    card = None
    if eng is not None:
        card = governing_card(eng["role_code"], eng["skill_code"], eng["geo_code"])

    findings = []
    subject_kwargs = {"timesheet_id": ts["id"]} if ts else {"assignment_id": a["id"]}

    if card is not None and a["bill_rate_cents"] > card["bill_rate_ceiling_cents"]:
        findings.append(
            create_audit(
                supplier_id=a["supplier_id"],
                finding="OVER_RATE",
                severity="HIGH",
                details=(
                    f"Bill rate {a['bill_rate_cents']} exceeds governing ceiling "
                    f"{card['bill_rate_ceiling_cents']}."
                ),
                **subject_kwargs,
            )
        )
    if card is not None and sup is not None and not markup_allowed(
        a["bill_rate_cents"], a["pay_rate_cents"], card, sup["tier"]
    ):
        findings.append(
            create_audit(
                supplier_id=a["supplier_id"],
                finding="MARKUP_EXCEEDED",
                severity="HIGH",
                details="Markup exceeds the tighter of the card cap and the supplier tier cap.",
                **subject_kwargs,
            )
        )
    if a["status"] == "ACTIVE" and worker is not None:
        tenure = cumulative_tenure(worker)
        if tenure >= TENURE_RISK_WARN_DAYS:
            findings.append(
                create_audit(
                    supplier_id=a["supplier_id"],
                    finding="TENURE_RISK",
                    severity="LOW",
                    details=(
                        f"Worker cumulative tenure {tenure} days is within 30 days "
                        f"of the 730-day limit."
                    ),
                    **subject_kwargs,
                )
            )
    return ok_list(
        [serializers.audit(f) for f in findings], len(findings), len(findings), 0, status=201
    )


@bp.get("/v1/compliance-audits")
def list_audits():
    require_roles(*READ_ROLES)
    filters = {
        "supplier_id": request.args.get("supplier_id"),
        "engagement_id": request.args.get("engagement_id"),
        "timesheet_id": request.args.get("timesheet_id"),
        "assignment_id": request.args.get("assignment_id"),
        "finding": request.args.get("finding"),
        "status": request.args.get("status"),
    }
    records = apply_filters(list(store.audits.values()), filters)
    page, total, limit, offset = paginate(records, serializers.audit)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/compliance-audits/<audit_id>")
def get_audit(audit_id):
    require_roles(*READ_ROLES)
    return ok(serializers.audit(_get_audit(audit_id)))


@bp.post("/v1/compliance-audits/<audit_id>/acknowledge")
def acknowledge_audit(audit_id):
    require_roles("ProgramAdmin")
    a = _get_audit(audit_id)
    if a["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN audit can be acknowledged.")
    a["status"] = "ACKNOWLEDGED"
    touch(a)
    return ok(serializers.audit(a))


def _dispose(audit_id, target):
    require_roles("ProgramAdmin")
    body = get_body()
    note = req_str(body, "resolution_note")
    a = _get_audit(audit_id)
    if a["status"] != "ACKNOWLEDGED":
        raise_err(ERR_INVALID_STATE, "Only an ACKNOWLEDGED audit can be resolved or dismissed.")
    a["status"] = target
    a["resolution_note"] = note
    touch(a)
    sup = store.suppliers.get(a["supplier_id"])
    if sup is not None:
        sup["open_violation_count"] -= 1
        touch(sup)
    return ok(serializers.audit(a))


@bp.post("/v1/compliance-audits/<audit_id>/resolve")
def resolve_audit(audit_id):
    return _dispose(audit_id, "RESOLVED")


@bp.post("/v1/compliance-audits/<audit_id>/dismiss")
def dismiss_audit(audit_id):
    return _dispose(audit_id, "DISMISSED")
