"""Routes: CirculationAuditRecords."""

from flask import Blueprint

from auth import require_roles
from db import store, new_record, touch
from errors import err
from routes_pub import list_response, PD, CM, PD_CM
from serializers import ser_audit
from services import (
    get_publication,
    get_audit,
    paid_percentage_bps,
    suspend_subscription,
    expire_pending_renewal_events,
)
from util import body, success, req_datetime, require_fields

bp = Blueprint("audits", __name__)


@bp.post("/publications/<publicationId>/circulation-audits")
@require_roles(CM)
def create_audit(publicationId):
    pub = get_publication(publicationId)
    data = body()
    require_fields(data, ["audit_period_start", "audit_period_end"])
    start = req_datetime(data, "audit_period_start")
    end = req_datetime(data, "audit_period_end")
    if end <= start:
        raise err(
            "ERR_INVALID_AUDIT_PERIOD", "audit_period_end must be > audit_period_start"
        )
    if any(
        a["publication_id"] == pub["id"] and a["status"] == "DRAFT"
        for a in store.audits.values()
    ):
        raise err(
            "ERR_DRAFT_AUDIT_EXISTS",
            "Only one DRAFT audit per publication at a time",
        )
    rec = new_record()
    rec.update(
        {
            "publication_id": pub["id"],
            "audit_period_start": start,
            "audit_period_end": end,
            "total_distribution": 0,
            "paid_distribution": 0,
            "controlled_distribution": 0,
            "paid_percentage_bps": 0,
            "qualification_result": "PENDING",
            "status": "DRAFT",
        }
    )
    store.audits[rec["id"]] = rec
    return success(ser_audit(rec), 201)


@bp.get("/publications/<publicationId>/circulation-audits")
@require_roles(PD_CM)
def list_audits(publicationId):
    pub = get_publication(publicationId)
    records = [a for a in store.audits.values() if a["publication_id"] == pub["id"]]
    return list_response(records, ser_audit, ("status",))


@bp.get("/publications/<publicationId>/circulation-audits/<auditId>")
@require_roles(PD_CM)
def get_audit_detail(publicationId, auditId):
    get_publication(publicationId)
    return success(ser_audit(get_audit(auditId, publicationId)), 200)


@bp.get("/circulation-audits/<auditId>")
@require_roles(PD_CM)
def get_audit_flat(auditId):
    return success(ser_audit(get_audit(auditId)), 200)


@bp.post("/publications/<publicationId>/circulation-audits/<auditId>/file")
@require_roles(CM)
def file_audit(publicationId, auditId):
    pub = get_publication(publicationId)
    audit = get_audit(auditId, publicationId)
    if audit["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "CirculationAuditRecord must be DRAFT to file")
    period_issues = []
    for issue in store.issues.values():
        if issue["publication_id"] != pub["id"]:
            continue
        mail_date = issue["mail_date"]
        if audit["audit_period_start"] <= mail_date <= audit["audit_period_end"]:
            if issue["status"] != "FINALIZED":
                raise err(
                    "ERR_UNFILED_ISSUES_IN_PERIOD",
                    "Cannot file audit: Issues in period are not FINALIZED",
                )
            period_issues.append(issue)
    issue_ids = {i["id"] for i in period_issues}
    batch_ids = {
        b["id"] for b in store.batches.values() if b["issue_id"] in issue_ids
    }
    labels = [l for l in store.labels.values() if l["batch_id"] in batch_ids]
    total = len(labels)
    paid = 0
    controlled = 0
    for lbl in labels:
        subscriber = store.subscribers.get(lbl["subscriber_id"])
        if subscriber is None:
            continue
        if subscriber["circulation_class"] == "PAID_QUALIFIED":
            paid += 1
        elif subscriber["circulation_class"] == "CONTROLLED_QUALIFIED":
            controlled += 1
    paid_bps = paid_percentage_bps(paid, total)
    model = pub["circulation_model"]
    if model == "PAID":
        result = "QUALIFIED" if paid_bps >= 7000 else "NON_QUALIFIED"
    elif model == "CONTROLLED":
        result = "QUALIFIED" if paid_bps <= 3000 else "NON_QUALIFIED"
    else:  # MIXED
        result = "QUALIFIED" if 3000 <= paid_bps <= 7000 else "NON_QUALIFIED"
    audit["total_distribution"] = total
    audit["paid_distribution"] = paid
    audit["controlled_distribution"] = controlled
    audit["paid_percentage_bps"] = paid_bps
    audit["qualification_result"] = result
    audit["status"] = "FILED"
    touch(audit)
    return success(ser_audit(audit), 200)


@bp.post("/publications/<publicationId>/circulation-audits/<auditId>/pass")
@require_roles(PD)
def pass_audit(publicationId, auditId):
    get_publication(publicationId)
    audit = get_audit(auditId, publicationId)
    if audit["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "CirculationAuditRecord must be FILED")
    if audit["qualification_result"] != "QUALIFIED":
        raise err(
            "ERR_AUDIT_NOT_QUALIFIED",
            "Cannot mark audit passed: qualification_result != QUALIFIED",
        )
    audit["status"] = "AUDIT_PASSED"
    touch(audit)
    return success(ser_audit(audit), 200)


@bp.post("/publications/<publicationId>/circulation-audits/<auditId>/fail")
@require_roles(PD)
def fail_audit(publicationId, auditId):
    pub = get_publication(publicationId)
    audit = get_audit(auditId, publicationId)
    if audit["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "CirculationAuditRecord must be FILED")
    if audit["qualification_result"] != "NON_QUALIFIED":
        raise err(
            "ERR_AUDIT_NOT_FAILED",
            "Cannot mark audit failed: qualification_result != NON_QUALIFIED",
        )
    audit["status"] = "AUDIT_FAILED"
    touch(audit)
    # Failed audit on a PAID publication cascades into suspension.
    if pub["circulation_model"] == "PAID" and pub["status"] == "ACTIVE":
        pub["status"] = "SUSPENDED"
        touch(pub)
        for sub in store.subscriptions.values():
            if sub["publication_id"] == pub["id"] and sub["status"] == "ACTIVE":
                suspend_subscription(sub, cascade_from_publication=True)
                expire_pending_renewal_events(sub["id"])
    return success(ser_audit(audit), 200)
