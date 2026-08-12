"""Routes: physical certificate deposits, lost/stolen registry,
audit engagements and findings."""

from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, g, request

from db import store, new_record, bump, serialize, today
from errors import ApiError
from services import (
    create_alert, recompute_aggregates, recompute_counts, recompute_posture,
    to_dec, round2,
)
from util import (
    endpoint, ok_object, list_response, field, MISSING, require_fields,
    check_enum, get_or_404, parse_date, is_int, is_num, ALL_ROLES,
)
from routes_accounts import _check_account_mutable_for_posting, _check_posture_not_severe

bp = Blueprint("ops", __name__)

DEPOSIT_STATUSES = {"RECEIVED", "ELIGIBILITY_REVIEW", "AUTHENTICITY_REVIEW",
                    "CLEARANCE_HOLD", "READY_TO_ACCEPT", "ACCEPTED", "REJECTED",
                    "REJECTED_SUSPICIOUS", "RESUBMITTED"}
REGISTRY_STATUSES = {"ACTIVE", "CANCELLED"}
SCOPE_UNITS = {"AML_PROGRAM", "CIP_PROCESS", "SANCTIONS_SCREENING", "TRANSACTION_MONITORING"}
ENGAGEMENT_STATUSES = {"PLANNED", "FIELDWORK", "REPORTED", "CLOSED"}
FINDING_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
FINDING_STATUSES = {"OPEN", "REMEDIATION_SUBMITTED", "REMEDIATED", "ACCEPTED_RISK"}

FINDING_DEADLINE_DAYS = {"CRITICAL": 30, "HIGH": 60, "MEDIUM": 90, "LOW": 180}


def _registry_active_hit(cert_number):
    return any(e["certificate_number"] == cert_number and e["status"] == "ACTIVE"
               for e in store.lost_stolen.values())


# ---------------------------------------------------------------------------
# Physical certificate deposits
# ---------------------------------------------------------------------------

@bp.post("/aml/accounts/<accountId>/certificate-deposits")
@endpoint(["OperationsAnalyst"])
def intake_deposit(accountId):
    account = get_or_404("accounts", accountId, "ERR_ACCOUNT_NOT_FOUND")
    _check_account_mutable_for_posting(account)
    _check_posture_not_severe(account)
    cert_no = field("certificate_number")
    if isinstance(cert_no, str) and _registry_active_hit(cert_no):
        raise ApiError("ERR_CERT_REPORTED_LOST_STOLEN", 403,
                       "Certificate number is on the ACTIVE lost/stolen registry")
    if isinstance(cert_no, str) and any(
            d["certificate_number"] == cert_no
            and d["status"] not in ("REJECTED", "REJECTED_SUSPICIOUS")
            for d in store.deposits.values()):
        raise ApiError("ERR_DUPLICATE_CERTIFICATE_NUMBER", 409,
                       "certificate_number already used by a non-rejected deposit")
    qty = field("quantity")
    if is_num(qty) and not is_int(qty):
        raise ApiError("ERR_INVALID_REQUEST", 400, "quantity must be a whole number of shares")
    if is_int(qty) and qty <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quantity must be a positive integer")
    require_fields([
        ("certificate_number", "nstr", True),
        ("cusip", "nstr", True),
        ("security_name", "nstr", True),
        ("quantity", "int", True),
        ("unit_price", "num", True),
        ("has_restrictive_legend", "bool", False),
    ])
    legend = field("has_restrictive_legend")
    unit_price = to_dec(field("unit_price"))
    # Linked DEPOSIT_CERT transaction booked directly in FLAGGED status
    txn = new_record()
    txn.update({
        "account_id": account["id"],
        "txn_type": "DEPOSIT_CERT",
        "security_id": field("cusip"),
        "quantity": to_dec(qty),
        "unit_price": unit_price,
        "amount": round2(to_dec(qty) * unit_price),
        "is_low_priced": unit_price < Decimal("5.00"),
        "status": "FLAGGED",
        "reversal_reason": None,
    })
    store.transactions[txn["id"]] = txn
    rec = new_record()
    rec.update({
        "account_id": account["id"],
        "transaction_id": txn["id"],
        "certificate_number": cert_no,
        "cusip": field("cusip"),
        "security_name": field("security_name"),
        "quantity": qty,
        "unit_price": unit_price,
        "has_restrictive_legend": legend if legend is not MISSING else False,
        "is_low_priced": unit_price < Decimal("5.00"),
        "status": "RECEIVED",
        "hold_release_date": None,
        "decision_reason": None,
    })
    store.deposits[rec["id"]] = rec
    recompute_aggregates(account)
    bump(account)
    return ok_object(serialize(rec), 201)


@bp.get("/aml/certificate-deposits")
@endpoint(ALL_ROLES)
def list_deposits():
    return list_response(
        list(store.deposits.values()),
        {
            "account_id": request.args.get("account_id"),
            "transaction_id": request.args.get("transaction_id"),
            "status": request.args.get("status"),
        },
        enum_filters=[("status", DEPOSIT_STATUSES)],
    )


@bp.get("/aml/certificate-deposits/<did>")
@endpoint(ALL_ROLES)
def get_deposit(did):
    return ok_object(serialize(get_or_404("deposits", did, "ERR_DEPOSIT_NOT_FOUND")))


@bp.post("/aml/certificate-deposits/<did>/advance")
@endpoint(["OperationsAnalyst"])
def advance_deposit(did):
    dep = get_or_404("deposits", did, "ERR_DEPOSIT_NOT_FOUND")
    s = dep["status"]
    if s == "RECEIVED":
        dep["status"] = "ELIGIBILITY_REVIEW"
    elif s in ("ELIGIBILITY_REVIEW", "RESUBMITTED"):
        # lost/stolen re-checked at the door of authenticity review
        if _registry_active_hit(dep["certificate_number"]):
            raise ApiError("ERR_CERT_REPORTED_LOST_STOLEN", 403,
                           "Certificate number is on the ACTIVE lost/stolen registry")
        dep["status"] = "AUTHENTICITY_REVIEW"
    elif s == "AUTHENTICITY_REVIEW":
        dep["status"] = "CLEARANCE_HOLD"
        hold_days = (10 if dep["is_low_priced"] else 5) \
            + (5 if dep.get("has_restrictive_legend") else 0)
        dep["hold_release_date"] = (today() + timedelta(days=hold_days)).isoformat()
    else:
        raise ApiError("ERR_DEPOSIT_NOT_ADVANCEABLE", 409,
                       "Deposit cannot be advanced from %s" % s)
    bump(dep)
    return ok_object(serialize(dep))


@bp.post("/aml/certificate-deposits/<did>/supplement")
@endpoint(["OperationsAnalyst"])
def supplement_deposit(did):
    dep = get_or_404("deposits", did, "ERR_DEPOSIT_NOT_FOUND")
    require_fields([("note", "nstr", True)])
    bump(dep)  # no state change; version bump is the OCC interplay
    return ok_object(serialize(dep))


@bp.post("/aml/certificate-deposits/<did>/decision")
@endpoint(["ComplianceOfficer"])
def decide_deposit(did):
    dep = get_or_404("deposits", did, "ERR_DEPOSIT_NOT_FOUND")
    if dep["status"] != "READY_TO_ACCEPT":
        raise ApiError("ERR_DEPOSIT_NOT_DECIDABLE", 409,
                       "Deposit must be READY_TO_ACCEPT to decide")
    ev = field("expected_deposit_version")
    if is_int(ev) and ev != dep["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_deposit_version does not match the deposit's current version")
    outcome = check_enum("outcome", {"ACCEPT", "REJECT", "REJECT_SUSPICIOUS"})
    require_fields([("expected_deposit_version", "int", True),
                    ("outcome", "str", True), ("reason", "str", False)])
    reason = field("reason")
    if reason is not MISSING:
        dep["decision_reason"] = reason
    account = store.accounts[dep["account_id"]]
    txn = store.transactions[dep["transaction_id"]]
    if outcome == "ACCEPT":
        dep["status"] = "ACCEPTED"
        if txn["status"] == "FLAGGED":
            txn["status"] = "CLEARED"
            bump(txn)
        bump(dep)
    elif outcome == "REJECT":
        dep["status"] = "REJECTED"
        if txn["status"] in ("POSTED", "FLAGGED"):
            txn["status"] = "REVERSED"
            txn["reversal_reason"] = reason if reason is not MISSING else "Deposit rejected"
            bump(txn)
            recompute_aggregates(account)
            bump(account)
        bump(dep)
    else:  # REJECT_SUSPICIOUS — three-hop cascade
        dep["status"] = "REJECTED_SUSPICIOUS"
        bump(dep)
        # Hop 1: reverse the linked transaction
        if txn["status"] in ("POSTED", "FLAGGED"):
            txn["status"] = "REVERSED"
            txn["reversal_reason"] = reason if reason is not MISSING else "Deposit rejected as suspicious"
            bump(txn)
        recompute_aggregates(account)
        # Hop 2: suspicion flag + posture recompute (at least ELEVATED)
        account["has_suspicion_flag"] = True
        # Hop 3: CERT_SUSPICION alert on the reversed transaction
        create_alert(None, account, txn, "CERT_SUSPICION", today(), today(), txn["amount"])
        recompute_counts(account)
        recompute_posture(account)
        bump(account)
    return ok_object(serialize(dep))


@bp.post("/aml/certificate-deposits/<did>/resubmit")
@endpoint(["OperationsAnalyst"])
def resubmit_deposit(did):
    dep = get_or_404("deposits", did, "ERR_DEPOSIT_NOT_FOUND")
    if dep["status"] != "REJECTED":
        raise ApiError("ERR_DEPOSIT_NOT_RESUBMITTABLE", 409,
                       "Deposit must be REJECTED to resubmit")
    require_fields([("note", "nstr", True)])
    dep["status"] = "RESUBMITTED"
    bump(dep)
    return ok_object(serialize(dep))


# ---------------------------------------------------------------------------
# Lost/stolen certificate registry
# ---------------------------------------------------------------------------

@bp.post("/aml/lost-stolen-certificates")
@endpoint(["SystemAdmin"])
def create_lost_stolen():
    cert_no = field("certificate_number")
    if isinstance(cert_no, str) and any(e["certificate_number"] == cert_no
                                        for e in store.lost_stolen.values()):
        raise ApiError("ERR_DUPLICATE_CERTIFICATE_NUMBER", 409,
                       "certificate_number already on the registry")
    require_fields([("certificate_number", "nstr", True), ("cusip", "nstr", True)])
    rec = new_record()
    rec.update({"certificate_number": cert_no, "cusip": field("cusip"), "status": "ACTIVE"})
    store.lost_stolen[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/lost-stolen-certificates")
@endpoint(ALL_ROLES)
def list_lost_stolen():
    return list_response(
        list(store.lost_stolen.values()),
        {"certificate_number": request.args.get("certificate_number"),
         "status": request.args.get("status")},
        enum_filters=[("status", REGISTRY_STATUSES)],
    )


@bp.get("/aml/lost-stolen-certificates/<eid>")
@endpoint(ALL_ROLES)
def get_lost_stolen(eid):
    return ok_object(serialize(get_or_404("lost_stolen", eid, "ERR_LOST_STOLEN_ENTRY_NOT_FOUND")))


# ---------------------------------------------------------------------------
# Audit engagements
# ---------------------------------------------------------------------------

@bp.post("/aml/audit-engagements")
@endpoint(["IndependentAuditor"])
def create_engagement():
    scope = check_enum("scope_unit", SCOPE_UNITS)
    sd_raw, ed_raw = field("start_date"), field("end_date")
    sd, ed = parse_date(sd_raw), parse_date(ed_raw)
    # Temporal overlap (priority 12): closed interval per scope_unit, non-CLOSED
    if sd is not None and ed is not None and scope is not None:
        for e in store.engagements.values():
            if e["scope_unit"] != scope or e["status"] == "CLOSED":
                continue
            es, ee = date.fromisoformat(e["start_date"]), date.fromisoformat(e["end_date"])
            if sd <= ee and ed >= es:
                raise ApiError("ERR_OVERLAPPING_AUDIT_ENGAGEMENT", 409,
                               "Engagement window overlaps a non-CLOSED engagement of the same scope_unit")
    if (sd_raw is not MISSING and sd is None) or (ed_raw is not MISSING and ed is None):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "Dates must be well-formed YYYY-MM-DD")
    if sd is not None and ed is not None and ed < sd:
        raise ApiError("ERR_INVALID_DATE_RANGE", 400, "end_date must not be earlier than start_date")
    require_fields([("scope_unit", "str", True),
                    ("start_date", "date", True), ("end_date", "date", True)])
    rec = new_record()
    rec.update({
        "scope_unit": scope,
        "start_date": sd_raw,
        "end_date": ed_raw,
        "lead_auditor_id": g.user_id,
        "report_summary": None,
        "status": "PLANNED",
    })
    store.engagements[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/audit-engagements")
@endpoint(ALL_ROLES)
def list_engagements():
    return list_response(
        list(store.engagements.values()),
        {"status": request.args.get("status"),
         "scope_unit": request.args.get("scope_unit")},
        enum_filters=[("status", ENGAGEMENT_STATUSES), ("scope_unit", SCOPE_UNITS)],
    )


@bp.get("/aml/audit-engagements/<eid>")
@endpoint(ALL_ROLES)
def get_engagement(eid):
    return ok_object(serialize(get_or_404("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")))


@bp.post("/aml/audit-engagements/<eid>/begin-fieldwork")
@endpoint(["IndependentAuditor"])
def begin_fieldwork(eid):
    eng = get_or_404("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if eng["status"] != "PLANNED":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", 409, "Engagement must be PLANNED to begin fieldwork")
    eng["status"] = "FIELDWORK"
    bump(eng)
    return ok_object(serialize(eng))


@bp.post("/aml/audit-engagements/<eid>/issue-report")
@endpoint(["IndependentAuditor"])
def issue_report(eid):
    eng = get_or_404("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if eng["status"] != "FIELDWORK":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", 409, "Engagement must be FIELDWORK to issue a report")
    require_fields([("report_summary", "nstr", True)])
    eng["status"] = "REPORTED"
    eng["report_summary"] = field("report_summary")
    bump(eng)
    return ok_object(serialize(eng))


@bp.post("/aml/audit-engagements/<eid>/close")
@endpoint(["IndependentAuditor"])
def close_engagement(eid):
    eng = get_or_404("engagements", eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if eng["status"] != "REPORTED":
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", 409, "Engagement must be REPORTED to close")
    if any(f["engagement_id"] == eid and f["status"] not in ("REMEDIATED", "ACCEPTED_RISK")
           for f in store.findings.values()):
        raise ApiError("ERR_ENGAGEMENT_HAS_OPEN_FINDINGS", 409,
                       "Close blocked: findings must all be REMEDIATED or ACCEPTED_RISK")
    eng["status"] = "CLOSED"
    bump(eng)
    return ok_object(serialize(eng))


# ---------------------------------------------------------------------------
# Audit findings
# ---------------------------------------------------------------------------

@bp.post("/aml/audit-engagements/<engagementId>/findings")
@endpoint(["IndependentAuditor"])
def create_finding(engagementId):
    eng = get_or_404("engagements", engagementId, "ERR_ENGAGEMENT_NOT_FOUND")
    if eng["status"] not in ("FIELDWORK", "REPORTED"):
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", 409,
                       "Findings are recorded while the engagement is FIELDWORK or REPORTED")
    severity = check_enum("severity", FINDING_SEVERITIES)
    require_fields([("severity", "str", True), ("description", "nstr", True)])
    rec = new_record()
    rec.update({
        "engagement_id": eng["id"],
        "severity": severity,
        "description": field("description"),
        "remediation_deadline": (today() + timedelta(days=FINDING_DEADLINE_DAYS[severity])).isoformat(),
        "is_overdue": False,
        "status": "OPEN",
        "remediation_note": None,
        "submitted_by": None,
        "verified_by": None,
    })
    store.findings[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/aml/audit-findings")
@endpoint(ALL_ROLES)
def list_findings():
    return list_response(
        list(store.findings.values()),
        {"engagement_id": request.args.get("engagement_id"),
         "status": request.args.get("status"),
         "severity": request.args.get("severity")},
        enum_filters=[("status", FINDING_STATUSES), ("severity", FINDING_SEVERITIES)],
    )


@bp.get("/aml/audit-findings/<fid>")
@endpoint(ALL_ROLES)
def get_finding(fid):
    return ok_object(serialize(get_or_404("findings", fid, "ERR_FINDING_NOT_FOUND")))


@bp.post("/aml/audit-findings/<fid>/submit-remediation")
@endpoint(["ComplianceOfficer"])
def submit_remediation(fid):
    finding = get_or_404("findings", fid, "ERR_FINDING_NOT_FOUND")
    if finding["status"] != "OPEN":
        raise ApiError("ERR_FINDING_NOT_OPEN", 409, "Finding must be OPEN to submit remediation")
    require_fields([("remediation_note", "nstr", True)])
    finding["status"] = "REMEDIATION_SUBMITTED"
    finding["remediation_note"] = field("remediation_note")
    finding["submitted_by"] = g.user_id
    bump(finding)
    return ok_object(serialize(finding))


@bp.post("/aml/audit-findings/<fid>/verify-remediation")
@endpoint(["IndependentAuditor"])
def verify_remediation(fid):
    finding = get_or_404("findings", fid, "ERR_FINDING_NOT_FOUND")
    # Segregation of duties (priority 3): verifier != remediation submitter
    if finding.get("submitted_by") is not None and g.user_id == finding["submitted_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "The verifying auditor must differ from the remediation submitter")
    if finding["status"] != "REMEDIATION_SUBMITTED":
        raise ApiError("ERR_FINDING_NOT_SUBMITTED", 409,
                       "Finding must be REMEDIATION_SUBMITTED to verify")
    decision = check_enum("decision", {"CONFIRM", "REJECT"})
    require_fields([("decision", "str", True)])
    finding["status"] = "REMEDIATED" if decision == "CONFIRM" else "OPEN"
    finding["verified_by"] = g.user_id
    bump(finding)
    return ok_object(serialize(finding))


@bp.post("/aml/audit-findings/<fid>/accept-risk")
@endpoint(["IndependentAuditor"])
def accept_risk(fid):
    finding = get_or_404("findings", fid, "ERR_FINDING_NOT_FOUND")
    if finding["status"] != "OPEN":
        raise ApiError("ERR_FINDING_NOT_OPEN", 409, "Finding must be OPEN to accept risk")
    if finding["severity"] not in ("LOW", "MEDIUM"):
        raise ApiError("ERR_RISK_ACCEPTANCE_NOT_ALLOWED", 409,
                       "Only LOW or MEDIUM severity findings may be risk-accepted")
    require_fields([("rationale", "nstr", True)])
    finding["status"] = "ACCEPTED_RISK"
    bump(finding)
    return ok_object(serialize(finding))
