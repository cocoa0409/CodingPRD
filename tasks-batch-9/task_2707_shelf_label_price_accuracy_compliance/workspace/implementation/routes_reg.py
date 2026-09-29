"""Regulatory inspections, findings, refund claims and exception reports."""
from flask import Blueprint

import calc
import services
import views
from auth import actor_id, roles
from core import (
    DECISIONS,
    DB,
    EXCEPTION_REPORT_STATUSES,
    FINDING_CODES,
    FINDING_STATUSES,
    INSPECTION_STATUSES,
    REFUND_STATUSES,
    ROOT_CAUSE_CODES,
    R_COMPLIANCE_OFFICER,
    R_CUSTOMER_SERVICE_DESK,
    R_PRICING_ADMIN,
    R_STORE_MANAGER,
    SEVERITIES,
    apply_changes,
    arg_enum,
    arg_str,
    body,
    fail,
    insert,
    must,
    now,
    ok,
    opt_int,
    opt_str,
    pagination,
    req_dt,
    req_enum,
    req_int,
    req_str,
    rows,
    touch,
)

bp = Blueprint("reg", __name__)


# ---------------------------------------------------------------- inspections
@bp.post("/price-integrity/regulatory-inspections")
@roles(R_COMPLIANCE_OFFICER)
def create_inspection():
    data = body()
    store_id = req_str(data, "store_id")
    scanner_audit_id = req_str(data, "scanner_audit_id")
    inspector_ref = req_str(data, "inspector_ref", 1, 255)
    inspection_date = req_dt(data, "inspection_date")
    store = must("stores", store_id)
    audit = must("scanner_audits", scanner_audit_id)
    inspection = insert(
        "regulatory_inspections",
        {
            "store_id": store["id"],
            "scanner_audit_id": audit["id"],
            "inspector_ref": inspector_ref,
            "inspection_date": inspection_date,
            "status": "SCHEDULED",
            "finding_count": 0,
            "penalty_exposure_cents": 0,
            "refund_liability_cents": 0,
            "refund_credit_cents": 0,
            "assessed_penalty_cents": None,
            "response_round": 0,
            "remediation_summary": None,
            "closed_at": None,
        },
    )
    return ok(views.regulatory_inspection(inspection), 201)


@bp.get("/price-integrity/regulatory-inspections/<iid>")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def get_inspection(iid):
    return ok(views.regulatory_inspection(must("regulatory_inspections", iid)))


@bp.get("/price-integrity/regulatory-inspections")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def list_inspections():
    store_id = arg_str("store_id")
    scanner_audit_id = arg_str("scanner_audit_id")
    status = arg_enum("status", INSPECTION_STATUSES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("regulatory_inspections")
        if (store_id is None or r["store_id"] == store_id)
        and (scanner_audit_id is None or r["scanner_audit_id"] == scanner_audit_id)
        and (status is None or r["status"] == status)
    ]
    return views.paged(items, views.regulatory_inspection, limit, offset)


@bp.post("/price-integrity/regulatory-inspections/<iid>/issue-findings")
@roles(R_COMPLIANCE_OFFICER)
def issue_findings(iid):
    data = body()
    if "findings" not in data or not isinstance(data["findings"], list):
        fail("ERR_INVALID_REQUEST", "findings must be an array")
    parsed = []
    for element in data["findings"]:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "each finding must be an object")
        parsed.append(
            {
                "finding_code": req_enum(element, "finding_code", FINDING_CODES),
                "severity": req_enum(element, "severity", SEVERITIES),
                "affected_item_count": req_int(element, "affected_item_count", 1),
                "affected_aisle_code": opt_str(element, "affected_aisle_code", 1, 8),
            }
        )
    inspection = must("regulatory_inspections", iid)
    # priority 40 — only a SCHEDULED inspection accepts findings
    if inspection["status"] != "SCHEDULED":
        fail("ERR_INSPECTION_INVALID_STATE", "the inspection has left SCHEDULED")
    # priority 44 — the evidence audit must be closed
    audit = DB["scanner_audits"][inspection["scanner_audit_id"]]
    if audit["status"] != "CLOSED":
        fail("ERR_EVIDENCE_AUDIT_NOT_CLOSED", "the evidence audit is not closed")
    if not parsed:
        fail("ERR_FINDINGS_EMPTY", "at least one finding is required")
    for fields in parsed:
        insert(
            "inspection_findings",
            {
                "regulatory_inspection_id": inspection["id"],
                "finding_code": fields["finding_code"],
                "severity": fields["severity"],
                "affected_item_count": fields["affected_item_count"],
                "affected_aisle_code": fields["affected_aisle_code"],
                "status": "OPEN",
                "penalty_component_cents": 0,
                "remediation_action_code": None,
                "remediation_evidence_ref": None,
                "waiver_reason": None,
            },
        )
    store = DB["stores"][inspection["store_id"]]
    juris = services.jurisdiction_of_store(store)
    apply_changes(inspection, {"status": "FINDINGS_ISSUED"})
    services.recompute_penalty(inspection, juris)
    touch(inspection)
    services.recompute_store(store)
    return ok(views.regulatory_inspection(inspection))


@bp.get("/price-integrity/inspection-findings/<fid>")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def get_finding(fid):
    return ok(views.inspection_finding(must("inspection_findings", fid)))


@bp.get("/price-integrity/regulatory-inspections/<iid>/findings")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def list_findings(iid):
    status = arg_enum("status", FINDING_STATUSES)
    severity = arg_enum("severity", SEVERITIES)
    limit, offset = pagination()
    must("regulatory_inspections", iid)
    items = [
        r
        for r in rows("inspection_findings")
        if r["regulatory_inspection_id"] == iid
        and (status is None or r["status"] == status)
        and (severity is None or r["severity"] == severity)
    ]
    return views.paged(items, views.inspection_finding, limit, offset)


@bp.post("/price-integrity/inspection-findings/<fid>/transition")
@roles(R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def transition_finding(fid):
    data = body()
    target_status = req_enum(
        data,
        "target_status",
        ["REMEDIATION_PLANNED", "REMEDIATED", "WAIVED", "ESCALATED"],
    )
    remediation_action_code = opt_str(data, "remediation_action_code", 1, 64)
    remediation_evidence_ref = opt_str(data, "remediation_evidence_ref", 1, 255)
    waiver_reason = opt_str(data, "waiver_reason", 0, 500)
    finding = must("inspection_findings", fid)
    inspection = DB["regulatory_inspections"][finding["regulatory_inspection_id"]]
    store = DB["stores"][inspection["store_id"]]
    juris = services.jurisdiction_of_store(store)
    status = finding["status"]

    if target_status == "REMEDIATION_PLANNED":
        # priority 40 — declared from OPEN or ESCALATED only
        if status not in ("OPEN", "ESCALATED"):
            fail("ERR_FINDING_INVALID_STATE", "the finding cannot be planned from here")
        # priority 64 — the action code is the evidence of a plan
        if remediation_action_code is None:
            fail(
                "ERR_REMEDIATION_EVIDENCE_REQUIRED",
                "remediation_action_code is required",
            )
        apply_changes(
            finding,
            {
                "status": "REMEDIATION_PLANNED",
                "remediation_action_code": remediation_action_code,
            },
        )
    elif target_status == "REMEDIATED":
        if status != "REMEDIATION_PLANNED":
            fail("ERR_FINDING_INVALID_STATE", "remediation was never planned")
        action_code = remediation_action_code or finding["remediation_action_code"]
        if action_code is None or remediation_evidence_ref is None:
            fail(
                "ERR_REMEDIATION_EVIDENCE_REQUIRED",
                "remediation_action_code and remediation_evidence_ref are required",
            )
        apply_changes(
            finding,
            {
                "status": "REMEDIATED",
                "remediation_action_code": action_code,
                "remediation_evidence_ref": remediation_evidence_ref,
            },
        )
    elif target_status == "WAIVED":
        if status != "OPEN":
            fail("ERR_FINDING_INVALID_STATE", "only an open finding can be waived")
        if inspection["status"] == "CLOSED":
            fail("ERR_INSPECTION_INVALID_STATE", "the inspection is closed")
        if waiver_reason is None or not waiver_reason.strip():
            fail("ERR_REMEDIATION_EVIDENCE_REQUIRED", "waiver_reason is required")
        apply_changes(
            finding,
            {
                "status": "WAIVED",
                "waiver_reason": waiver_reason,
                "penalty_component_cents": 0,
            },
        )
        services.recompute_penalty(inspection, juris)
        apply_changes(finding, {"penalty_component_cents": 0})
    else:
        fail("ERR_FINDING_INVALID_STATE", "escalation is a system transition only")

    touch(finding)
    # every individual finding transition silently advances the inspection
    touch(inspection)
    services.recompute_store(store)
    return ok(views.inspection_finding(finding))


@bp.post("/price-integrity/regulatory-inspections/<iid>/response")
@roles(R_STORE_MANAGER, R_COMPLIANCE_OFFICER)
def submit_response(iid):
    data = body()
    remediation_summary = req_str(data, "remediation_summary", 1, 2000)
    expected = req_int(data, "expected_regulatory_inspection_version", 1)
    inspection = must("regulatory_inspections", iid)
    # priority 40 — declared from FINDINGS_ISSUED or RESPONSE_REJECTED only
    if inspection["status"] not in ("FINDINGS_ISSUED", "RESPONSE_REJECTED"):
        fail("ERR_INSPECTION_INVALID_STATE", "no response is due in this state")
    # priority 45 — version pinning
    if expected != inspection["version"]:
        fail("ERR_STALE_INSPECTION_VERSION", "the inspection has moved on")
    apply_changes(
        inspection,
        {
            "status": "RESPONSE_SUBMITTED",
            "remediation_summary": remediation_summary,
            "response_round": inspection["response_round"] + 1,
        },
    )
    touch(inspection)
    return ok(views.regulatory_inspection(inspection))


@bp.post("/price-integrity/regulatory-inspections/<iid>/adjudicate")
@roles(R_COMPLIANCE_OFFICER)
def adjudicate(iid):
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    assessed_override = opt_int(data, "assessed_penalty_cents", 0)
    opt_str(data, "rejection_note", 0, 500)
    inspection = must("regulatory_inspections", iid)
    # priority 40 — only a submitted response can be adjudicated
    if inspection["status"] != "RESPONSE_SUBMITTED":
        fail("ERR_INSPECTION_INVALID_STATE", "no response is awaiting adjudication")
    store = DB["stores"][inspection["store_id"]]
    juris = services.jurisdiction_of_store(store)

    if decision == "REJECT":
        services.escalate_findings(inspection)
        apply_changes(inspection, {"status": "RESPONSE_REJECTED"})
        touch(inspection)
        services.recompute_store(store)
        return ok(views.regulatory_inspection(inspection))

    for finding in services.inspection_findings(inspection["id"]):
        if finding["status"] == "OPEN":
            fail("ERR_FINDING_INVALID_STATE", "every finding must have been actioned")
    # step one — exposure from the current findings
    exposure = services.recompute_penalty(inspection, juris)
    # priority 74 — the override may not exceed the fresh exposure
    if assessed_override is not None and assessed_override > exposure:
        fail("ERR_PENALTY_OVERRIDE_TOO_HIGH", "the override exceeds the exposure")
    # step two — refund liability of the evidence audit
    liability = sum(
        claim["claimed_amount_cents"]
        for claim in services.audit_claims(inspection["scanner_audit_id"])
        if claim["status"] in ("APPROVED", "PAID")
    )
    # step three — the credit, from two independently floored candidates
    credit = calc.refund_credit(liability, exposure)
    # step four — the assessed penalty
    if assessed_override is not None:
        assessed = assessed_override
    else:
        assessed = max(0, exposure - credit)
    apply_changes(
        inspection,
        {
            "refund_liability_cents": liability,
            "refund_credit_cents": credit,
            "assessed_penalty_cents": assessed,
            "status": "CLOSED",
            "closed_at": now(),
        },
    )
    touch(inspection)
    # step five — the store's cumulative exposure, then the posture
    services.recompute_store(store)
    return ok(views.regulatory_inspection(inspection))


# ---------------------------------------------------------------- refund claims
@bp.post("/price-integrity/refund-claims")
@roles(R_CUSTOMER_SERVICE_DESK, R_STORE_MANAGER)
def create_refund_claim():
    data = body()
    scan_line_id = req_str(data, "scan_line_id")
    customer_ref = req_str(data, "customer_ref", 1, 128)
    expected = req_int(data, "expected_scanner_audit_version", 1)
    scan_line = must("scan_lines", scan_line_id)
    audit = DB["scanner_audits"][scan_line["scanner_audit_id"]]
    # priority 42 — the evidence audit must be closed
    if audit["status"] != "CLOSED":
        fail("ERR_AUDIT_NOT_CLOSED", "the evidence audit is not closed")
    # priority 45 — version pinning
    if expected != audit["version"]:
        fail("ERR_STALE_SCANNER_AUDIT_VERSION", "the audit has moved on")
    # priority 63 — only an overcharge is refundable
    if scan_line["classification"] != "OVERCHARGE":
        fail("ERR_NOT_AN_OVERCHARGE", "the scan line is not an overcharge")
    # priority 63 — one claim per scan line and customer
    if any(
        r["scan_line_id"] == scan_line_id and r["customer_ref"] == customer_ref
        for r in DB["refund_claims"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "the customer already claimed this observation")
    store = DB["stores"][audit["store_id"]]
    juris = services.jurisdiction_of_store(store)
    amount, policy = calc.refund_claim_amount(scan_line, juris)
    # priority 72 — the per-audit refund budget, evaluated last
    if (
        store["refund_liability_outstanding_cents"] + amount
        > juris["refund_budget_per_audit_cents"]
    ):
        fail("ERR_REFUND_BUDGET_EXCEEDED", "the refund budget is exhausted")
    claim = insert(
        "refund_claims",
        {
            "scan_line_id": scan_line["id"],
            "store_id": store["id"],
            "customer_ref": customer_ref,
            "claimed_amount_cents": amount,
            "policy_applied": policy,
            "status": "PENDING",
            "denial_reason": None,
            "paid_at": None,
        },
    )
    services.recompute_store(store)
    return ok(views.refund_claim(claim), 201)


@bp.get("/price-integrity/refund-claims/<cid>")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER, R_CUSTOMER_SERVICE_DESK)
def get_refund_claim(cid):
    return ok(views.refund_claim(must("refund_claims", cid)))


@bp.get("/price-integrity/refund-claims")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER, R_CUSTOMER_SERVICE_DESK)
def list_refund_claims():
    scan_line_id = arg_str("scan_line_id")
    store_id = arg_str("store_id")
    status = arg_enum("status", REFUND_STATUSES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("refund_claims")
        if (scan_line_id is None or r["scan_line_id"] == scan_line_id)
        and (store_id is None or r["store_id"] == store_id)
        and (status is None or r["status"] == status)
    ]
    return views.paged(items, views.refund_claim, limit, offset)


@bp.post("/price-integrity/refund-claims/<cid>/settle")
@roles(R_CUSTOMER_SERVICE_DESK, R_STORE_MANAGER)
def settle_refund_claim(cid):
    data = body()
    target_status = req_enum(data, "target_status", ["APPROVED", "PAID", "DENIED"])
    denial_reason = opt_str(data, "denial_reason", 0, 500)
    claim = must("refund_claims", cid)
    status = claim["status"]
    # priority 41 — a repeat of a settlement already applied
    if status == target_status:
        fail("ERR_TRANSITION_ALREADY_APPLIED", "the settlement is already applied")
    store = DB["stores"][claim["store_id"]]

    if target_status == "APPROVED":
        # priority 40 — only a pending claim is approvable
        if status != "PENDING":
            fail("ERR_REFUND_CLAIM_INVALID_STATE", "the claim is no longer pending")
        apply_changes(claim, {"status": "APPROVED"})
    elif target_status == "DENIED":
        if status not in ("PENDING", "APPROVED"):
            fail("ERR_REFUND_CLAIM_INVALID_STATE", "the claim cannot be denied")
        # priority 76 — the denial must carry a reason
        if denial_reason is None or not denial_reason.strip():
            fail("ERR_DENIAL_REASON_REQUIRED", "denial_reason is required")
        apply_changes(claim, {"status": "DENIED", "denial_reason": denial_reason})
    else:
        # priority 76 — payment requires an approved claim the liability covers
        if status != "APPROVED":
            fail("ERR_REFUND_NOT_APPROVED", "the claim is not approved")
        if store["refund_liability_outstanding_cents"] < claim["claimed_amount_cents"]:
            fail("ERR_REFUND_NOT_APPROVED", "the outstanding liability does not cover it")
        apply_changes(claim, {"status": "PAID", "paid_at": now()})
    services.recompute_store(store)
    return ok(views.refund_claim(claim))


# ------------------------------------------------------------ exception reports
def qualifying_audits(store_id, period_start_at, period_end_at):
    """CLOSED audits of the store whose closed_at falls inside the half-open period."""
    out = []
    for audit in rows("scanner_audits"):
        if audit["store_id"] != store_id or audit["status"] != "CLOSED":
            continue
        closed_at = audit["closed_at"]
        if closed_at is None:
            continue
        if period_start_at <= closed_at < period_end_at:
            out.append(audit)
    return out


@bp.post("/price-integrity/exception-reports")
@roles(R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def create_exception_report():
    data = body()
    store_id = req_str(data, "store_id")
    period_start_at = req_dt(data, "period_start_at")
    period_end_at = req_dt(data, "period_end_at")
    store = must("stores", store_id)
    # priority 58 — well-formed interval
    if not period_start_at < period_end_at:
        fail("ERR_INVALID_WINDOW", "period_start_at must precede period_end_at")
    # priority 63 — one report per store and period
    if any(
        r["store_id"] == store_id
        and r["period_start_at"] == period_start_at
        and r["period_end_at"] == period_end_at
        for r in DB["exception_reports"].values()
    ):
        fail("ERR_DUPLICATE_RESOURCE", "the period was already reported")
    audits = qualifying_audits(store["id"], period_start_at, period_end_at)
    scan_lines = []
    for audit in audits:
        scan_lines.extend(services.audit_scan_lines(audit["id"]))
    breakdown = calc.category_ranking(scan_lines)
    # priority 63 — the empty candidate guard
    if not breakdown:
        fail("ERR_NO_QUALIFYING_AUDIT_DATA", "no category reached the minimum sample")
    report = insert(
        "exception_reports",
        {
            "store_id": store["id"],
            "period_start_at": period_start_at,
            "period_end_at": period_end_at,
            "audit_count": len(audits),
            "scan_line_count": len(scan_lines),
            "top_category_code": breakdown[0]["category_code"],
            "top_category_error_rate_pct": breakdown[0]["error_rate_pct"],
            "category_breakdown": breakdown,
            "root_cause_code": None,
            "remediation_owner_associate_id": None,
            "status": "GENERATED",
            "closure_note": None,
        },
    )
    return ok(views.exception_report(report), 201)


@bp.get("/price-integrity/exception-reports/<rid>")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def get_exception_report(rid):
    return ok(views.exception_report(must("exception_reports", rid)))


@bp.get("/price-integrity/exception-reports")
@roles(R_PRICING_ADMIN, R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def list_exception_reports():
    store_id = arg_str("store_id")
    owner = arg_str("remediation_owner_associate_id")
    status = arg_enum("status", EXCEPTION_REPORT_STATUSES)
    limit, offset = pagination()
    items = [
        r
        for r in rows("exception_reports")
        if (store_id is None or r["store_id"] == store_id)
        and (owner is None or r["remediation_owner_associate_id"] == owner)
        and (status is None or r["status"] == status)
    ]
    return views.paged(items, views.exception_report, limit, offset)


@bp.post("/price-integrity/exception-reports/<rid>/assign-root-cause")
@roles(R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def assign_root_cause(rid):
    data = body()
    root_cause_code = req_enum(data, "root_cause_code", ROOT_CAUSE_CODES)
    owner_id = req_str(data, "remediation_owner_associate_id")
    report = must("exception_reports", rid)
    owner = must("associates", owner_id)
    # priority 40 — a root cause is assigned exactly once
    if report["status"] != "GENERATED":
        fail("ERR_EXCEPTION_REPORT_INVALID_STATE", "the root cause is already assigned")
    audits = qualifying_audits(
        report["store_id"], report["period_start_at"], report["period_end_at"]
    )
    # priority 50 — the measurer may not own the remediation
    if any(audit["auditor_associate_id"] == owner["id"] for audit in audits):
        fail("ERR_SEGREGATION_OF_DUTIES", "the auditor may not own the remediation")
    # priority 67 — associate/store agreement
    if owner["store_id"] != report["store_id"]:
        fail("ERR_ASSOCIATE_STORE_MISMATCH", "the owner belongs to another store")
    apply_changes(
        report,
        {
            "status": "REMEDIATION_OPEN",
            "root_cause_code": root_cause_code,
            "remediation_owner_associate_id": owner["id"],
        },
    )
    if root_cause_code == "TRAINING_GAP":
        action = services.issue_action(
            owner, "EXCEPTION_ROOT_CAUSE", "RETRAINING_ASSIGNED", "system", report["id"]
        )
        report["_training_action_id"] = action["id"]
        services.recompute_store(DB["stores"][report["store_id"]])
    return ok(views.exception_report(report))


@bp.post("/price-integrity/exception-reports/<rid>/close")
@roles(R_COMPLIANCE_OFFICER, R_STORE_MANAGER)
def close_exception_report(rid):
    data = body()
    closure_note = req_str(data, "closure_note", 1, 2000)
    report = must("exception_reports", rid)
    # priority 40 — only a report under remediation closes
    if report["status"] != "REMEDIATION_OPEN":
        fail("ERR_EXCEPTION_REPORT_INVALID_STATE", "the report cannot be closed yet")
    if report["root_cause_code"] == "TRAINING_GAP":
        action_id = report.get("_training_action_id")
        action = DB["accountability_actions"].get(action_id) if action_id else None
        if action is not None and action["status"] == "ISSUED":
            fail("ERR_ACTION_INVALID_STATE", "the mandated retraining is outstanding")
    apply_changes(report, {"status": "CLOSED", "closure_note": closure_note})
    return ok(views.exception_report(report))
