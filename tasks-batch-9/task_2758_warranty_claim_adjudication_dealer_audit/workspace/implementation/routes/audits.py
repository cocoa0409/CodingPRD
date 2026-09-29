"""On-site dealer audits, extrapolated chargebacks and appeal rights (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import util
from errors import ApiError
from middleware import (
    ADJUDICATION_MANAGER,
    APPEAL_REVIEWER,
    AUDIT_MANAGER,
    CLAIM_ADJUDICATOR,
    DEALER_WARRANTY_ADMIN,
    FIELD_AUDITOR,
    WARRANTY_ADMIN,
    auth,
    fetch,
    scope,
)
from routes.common import ALL_ROLES, apply_filters, resolve_fk, str_filter
from services import calc, cascade
from util import as_date

bp = Blueprint("audits", __name__)

LIVE_AUDIT_STATUSES = ("SCHEDULED", "IN_FIELD", "FINDINGS_ISSUED", "APPEALED")
FINDING_CODES = (
    "NO_REPAIR_ORDER",
    "NO_TECHNICIAN_SIGNATURE",
    "PART_NOT_ON_HAND",
    "TIME_NOT_DOCUMENTED",
    "NARRATIVE_UNSUPPORTED",
)
FINDING_READ_ROLES = (WARRANTY_ADMIN, FIELD_AUDITOR, AUDIT_MANAGER, APPEAL_REVIEWER, DEALER_WARRANTY_ADMIN)
AUDIT_LIST_ROLES = (WARRANTY_ADMIN, FIELD_AUDITOR, AUDIT_MANAGER, APPEAL_REVIEWER)
APPEAL_READ_ROLES = (WARRANTY_ADMIN, FIELD_AUDITOR, AUDIT_MANAGER, APPEAL_REVIEWER, DEALER_WARRANTY_ADMIN)
APPEAL_LIST_ROLES = (WARRANTY_ADMIN, FIELD_AUDITOR, AUDIT_MANAGER, APPEAL_REVIEWER)


def appeals_of(audit_id):
    return [a for a in db.ordered(db.appeals) if a["audit_id"] == audit_id]


def profile_of(dealer):
    return db.state_law_profiles[dealer["state_law_profile_id"]]


# ---------------------------------------------------------------- scheduling
@bp.post("/warranty/audits")
def schedule_audit():
    auth(AUDIT_MANAGER)
    data = util.body()
    dealer = resolve_fk(data, "dealer_id", db.dealers, "ERR_DEALER_NOT_FOUND")
    util.get_str(data, "dealer_id")
    period_start = util.get_date(data, "period_start")
    period_end = util.get_date(data, "period_end")
    if period_end <= period_start:
        util.bad("Field 'period_end' must be strictly after 'period_start'.")
    sample_size = util.get_int(data, "sample_size")
    if sample_size <= 0:
        util.bad("Field 'sample_size' must be strictly positive.")
    lead_auditor_user_id = util.get_str(data, "lead_auditor_user_id")
    expected_dealer_version = util.get_int(data, "expected_dealer_version", required=False)
    if expected_dealer_version is not None and expected_dealer_version != dealer["version"]:
        raise ApiError("ERR_STALE_DEALER_VERSION", "The dealer's version has advanced since it was read.")
    for other in db.ordered(db.audits):
        if other["dealer_id"] != dealer["id"] or other["status"] not in LIVE_AUDIT_STATUSES:
            continue
        if period_start < as_date(other["period_end"]) and as_date(other["period_start"]) < period_end:
            raise ApiError(
                "ERR_AUDIT_PERIOD_OVERLAP",
                "A live audit of this dealer already covers part of the requested period.",
            )
    audit = db.new_record(
        db.audits,
        dealer_id=dealer["id"],
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        sample_size=sample_size,
        lead_auditor_user_id=lead_auditor_user_id,
        status="SCHEDULED",
        sample_paid_snapshot_cents=0,
        population_paid_snapshot_cents=0,
        error_rate=Decimal("0.0000"),
        extrapolation_factor=Decimal("0.00"),
        sample_chargeback_cents=0,
        extrapolated_chargeback_cents=0,
        total_chargeback_cents=0,
        findings_issued_at=None,
        appeal_deadline=None,
    )
    db.touch(dealer)
    return response.created(audit)


@bp.get("/warranty/audits/<audit_id>")
def read_audit(audit_id):
    actor = auth(*ALL_ROLES)
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    scope(actor, audit["dealer_id"])
    return response.ok(audit)


@bp.get("/warranty/audits")
def list_audits():
    auth(*AUDIT_LIST_ROLES)
    limit, offset = util.pagination()
    rows = db.ordered(db.audits)
    rows = apply_filters(rows, [(str_filter("dealer_id"), "dealer_id"), (str_filter("status"), "status")])
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.post("/warranty/audits/<audit_id>/start")
def start_audit(audit_id):
    auth(FIELD_AUDITOR)
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Only a SCHEDULED audit may be started.")
    audit["status"] = "IN_FIELD"
    db.touch(audit)
    dealer = db.dealers[audit["dealer_id"]]
    cascade.recompute_audit_hold(dealer)
    db.touch(dealer)
    return response.ok(audit)


# ---------------------------------------------------------------- findings
@bp.post("/warranty/audits/<audit_id>/findings")
def attach_finding(audit_id):
    auth(FIELD_AUDITOR)
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    data = util.body()
    claim = resolve_fk(data, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    util.get_str(data, "claim_id")
    finding_code = util.get_enum(data, "finding_code", FINDING_CODES)
    unsupported_amount_cents = util.get_int(data, "unsupported_amount_cents", minimum=0)
    if unsupported_amount_cents <= 0:
        util.bad("Field 'unsupported_amount_cents' must be strictly positive.")
    if unsupported_amount_cents > int(claim["approved_total_cents"] or 0):
        util.bad("Field 'unsupported_amount_cents' may not exceed the cited claim's approved total.")
    evidence_note = util.get_str(data, "evidence_note")
    if audit["status"] != "IN_FIELD":
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Findings may only be attached to an IN_FIELD audit.")
    eligible = (
        claim["dealer_id"] == audit["dealer_id"]
        and claim["status"] == "APPROVED"
        and claim["payment_status"] in ("UNPAID", "PAID")
        and calc.in_period(claim, audit)
        and not any(f["claim_id"] == claim["id"] for f in calc.audit_findings_of(audit["id"]))
    )
    if not eligible:
        raise ApiError(
            "ERR_CLAIM_NOT_ELIGIBLE_FOR_FINDING",
            "The cited claim is not an eligible, uncited, in-period APPROVED claim of the audited dealer.",
        )
    finding = db.new_record(
        db.findings,
        audit_id=audit["id"],
        claim_id=claim["id"],
        appeal_id=None,
        finding_code=finding_code,
        unsupported_amount_cents=unsupported_amount_cents,
        evidence_note=evidence_note,
        status="OPEN",
    )
    return response.created(finding)


@bp.get("/warranty/audit-findings/<finding_id>")
def read_finding(finding_id):
    auth(*FINDING_READ_ROLES)
    finding = fetch(db.findings, finding_id, "ERR_FINDING_NOT_FOUND")
    return response.ok(finding)


@bp.get("/warranty/audit-findings")
def list_findings():
    auth(*FINDING_READ_ROLES)
    limit, offset = util.pagination()
    rows = db.ordered(db.findings)
    rows = apply_filters(
        rows,
        [
            (str_filter("audit_id"), "audit_id"),
            (str_filter("claim_id"), "claim_id"),
            (str_filter("appeal_id"), "appeal_id"),
            (str_filter("status"), "status"),
        ],
    )
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


# ---------------------------------------------------------------- issuing findings
@bp.post("/warranty/audits/<audit_id>/issue-findings")
def issue_findings(audit_id):
    auth(AUDIT_MANAGER)
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["status"] != "IN_FIELD":
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Only an IN_FIELD audit may issue its findings.")
    dealer = db.dealers[audit["dealer_id"]]
    findings = calc.audit_findings_of(audit["id"])
    sampled_claim_ids = {f["claim_id"] for f in findings}
    # ---- steps 1 and 2: pin both paid denominators before any chargeback ----
    sample_paid = 0
    all_paid = 0
    for claim in cascade.dealer_claims(dealer["id"]):
        if claim["status"] != "APPROVED" or claim["payment_status"] != "PAID":
            continue
        if not calc.in_period(claim, audit):
            continue
        amount = int(claim["approved_total_cents"] or 0)
        all_paid += amount
        if claim["id"] in sampled_claim_ids:
            sample_paid += amount
    audit["sample_paid_snapshot_cents"] = sample_paid
    audit["population_paid_snapshot_cents"] = all_paid - sample_paid
    # ---- steps 3 to 6 ----
    calc.apply_steps_3_to_6(audit)
    # ---- write-back ----
    charged_back = []
    for finding in findings:
        if finding["status"] != "OPEN":
            continue
        finding["status"] = "CHARGED_BACK"
        db.touch(finding)
        charged_back.append(finding)
    for finding in charged_back:
        claim = db.claims[finding["claim_id"]]
        if claim["payment_status"] == "PAID":
            cascade.debit_claim(claim, finding["unsupported_amount_cents"])
    for finding in charged_back:
        if finding["unsupported_amount_cents"] > 0:
            cascade.append_ledger(
                dealer,
                "AUDIT_CHARGEBACK_SAMPLE",
                audit["id"],
                finding["claim_id"],
                finding["unsupported_amount_cents"],
            )
    if audit["extrapolated_chargeback_cents"] > 0:
        cascade.append_ledger(
            dealer,
            "AUDIT_CHARGEBACK_EXTRAPOLATION",
            audit["id"],
            None,
            audit["extrapolated_chargeback_cents"],
        )
    db.touch(dealer)
    issued_at = db.now()
    audit["status"] = "FINDINGS_ISSUED"
    audit["findings_issued_at"] = issued_at
    audit["appeal_deadline"] = db.add_days(issued_at, profile_of(dealer)["appeal_window_days"])
    db.touch(audit)
    return response.ok(audit)


@bp.post("/warranty/audits/<audit_id>/close")
def close_audit(audit_id):
    auth(AUDIT_MANAGER)
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    if audit["status"] not in ("FINDINGS_ISSUED", "APPEALED"):
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Only a FINDINGS_ISSUED or APPEALED audit may be closed.")
    if any(appeal["status"] == "FILED" for appeal in appeals_of(audit["id"])):
        raise ApiError("ERR_APPEAL_PENDING", "An appeal of this audit is still pending.")
    for finding in calc.audit_findings_of(audit["id"]):
        if finding["status"] == "CHARGED_BACK":
            finding["status"] = "UPHELD"
            db.touch(finding)
    audit["status"] = "CLOSED"
    db.touch(audit)
    dealer = db.dealers[audit["dealer_id"]]
    cascade.recompute_audit_hold(dealer)
    db.touch(dealer)
    return response.ok(audit)


# ---------------------------------------------------------------- appeals
@bp.post("/warranty/audits/<audit_id>/appeals")
def file_appeal(audit_id):
    actor = auth(DEALER_WARRANTY_ADMIN)
    audit = fetch(db.audits, audit_id, "ERR_AUDIT_NOT_FOUND")
    scope(actor, audit["dealer_id"])
    data = util.body()
    grounds = util.get_str(data, "grounds")
    contested_finding_ids = util.get_str_list(data, "contested_finding_ids", min_len=1)
    expected_audit_version = util.get_int(data, "expected_audit_version", required=False)
    if expected_audit_version is not None and expected_audit_version != audit["version"]:
        raise ApiError("ERR_STALE_AUDIT_VERSION", "The audit's version has advanced since it was read.")
    if audit["status"] != "FINDINGS_ISSUED":
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Only a FINDINGS_ISSUED audit may be appealed.")
    if audit["appeal_deadline"] is not None and db.now() > audit["appeal_deadline"]:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "The statutory appeal window has closed.")
    contested = []
    for finding_id in contested_finding_ids:
        finding = db.findings.get(finding_id)
        if finding is None or finding["audit_id"] != audit["id"] or finding["status"] != "CHARGED_BACK":
            raise ApiError(
                "ERR_FINDING_NOT_IN_AUDIT",
                "Every contested finding must belong to this audit and still be CHARGED_BACK.",
            )
        contested.append(finding)
    appeal = db.new_record(
        db.appeals,
        audit_id=audit["id"],
        filed_by_dealer_id=actor.user_id,
        grounds=grounds,
        contested_finding_ids=list(contested_finding_ids),
        overturned_finding_ids=[],
        reviewer_user_id=None,
        status="FILED",
        reinstated_amount_cents=0,
        decision_note=None,
    )
    for finding in contested:
        finding["appeal_id"] = appeal["id"]
    audit["status"] = "APPEALED"
    db.touch(audit)
    return response.created(appeal)


@bp.get("/warranty/appeals/<appeal_id>")
def read_appeal(appeal_id):
    actor = auth(*APPEAL_READ_ROLES)
    appeal = fetch(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    scope(actor, appeal["filed_by_dealer_id"])
    return response.ok(appeal)


@bp.get("/warranty/appeals")
def list_appeals():
    auth(*APPEAL_LIST_ROLES)
    limit, offset = util.pagination()
    rows = db.ordered(db.appeals)
    rows = apply_filters(
        rows,
        [
            (str_filter("audit_id"), "audit_id"),
            (str_filter("filed_by_dealer_id"), "filed_by_dealer_id"),
            (str_filter("status"), "status"),
        ],
    )
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.post("/warranty/appeals/<appeal_id>/decision")
def decide_appeal(appeal_id):
    actor = auth(APPEAL_REVIEWER)
    appeal = fetch(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    audit = db.audits[appeal["audit_id"]]
    if actor.user_id == audit["lead_auditor_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The auditor who led this audit may not review its appeal.",
        )
    data = util.body()
    action = util.get_enum(data, "action", ("GRANT", "PARTIAL", "DENY"))
    overturned_input = util.get_str_list(data, "overturned_finding_ids", required=False, default=None)
    decision_note = util.get_str(data, "decision_note", required=False)
    contested = list(appeal["contested_finding_ids"])
    if action == "PARTIAL":
        if not overturned_input:
            util.bad("Field 'overturned_finding_ids' must be a non-empty strict subset of the contested set.")
        listed = list(dict.fromkeys(overturned_input))
        if any(item not in contested for item in listed) or len(listed) >= len(contested):
            util.bad("Field 'overturned_finding_ids' must be a non-empty strict subset of the contested set.")
    if appeal["status"] != "FILED":
        raise ApiError("ERR_APPEAL_INVALID_STATE", "Only a FILED appeal may be decided.")
    dealer = db.dealers[audit["dealer_id"]]
    previous_sample = audit["sample_chargeback_cents"]
    previous_extrapolated = audit["extrapolated_chargeback_cents"]
    previous_total = audit["total_chargeback_cents"]
    if action == "GRANT":
        overturned_ids = contested
    elif action == "PARTIAL":
        overturned_ids = [item for item in contested if item in listed]
    else:
        overturned_ids = []
    for finding_id in contested:
        finding = db.findings.get(finding_id)
        if finding is None or finding["status"] != "CHARGED_BACK":
            continue
        finding["status"] = "OVERTURNED" if finding_id in overturned_ids else "UPHELD"
        db.touch(finding)
    appeal["overturned_finding_ids"] = list(overturned_ids)
    appeal["reviewer_user_id"] = actor.user_id
    appeal["decision_note"] = decision_note
    appeal["status"] = {"GRANT": "GRANTED", "PARTIAL": "PARTIALLY_GRANTED", "DENY": "DENIED"}[action]
    # ---- steps 3 to 6 again, against the pinned snapshots ----
    calc.apply_steps_3_to_6(audit)
    sample_delta = previous_sample - audit["sample_chargeback_cents"]
    extrapolation_delta = previous_extrapolated - audit["extrapolated_chargeback_cents"]
    if sample_delta != 0:
        cascade.append_ledger(dealer, "APPEAL_REVERSAL_SAMPLE", appeal["id"], None, -sample_delta)
    if extrapolation_delta != 0:
        cascade.append_ledger(dealer, "APPEAL_REVERSAL_EXTRAPOLATION", appeal["id"], None, -extrapolation_delta)
    for finding_id in overturned_ids:
        finding = db.findings.get(finding_id)
        if finding is None:
            continue
        claim = db.claims.get(finding["claim_id"])
        if claim is None or claim["payment_status"] != "DEBITED":
            continue
        amount = finding["unsupported_amount_cents"]
        claim["debited_amount_cents"] = claim["debited_amount_cents"] - amount
        claim["reinstated_amount_cents"] = claim["reinstated_amount_cents"] + amount
        claim["payment_status"] = "CREDIT_REINSTATED"
        db.touch(claim)
    appeal["reinstated_amount_cents"] = previous_total - audit["total_chargeback_cents"]
    db.touch(appeal)
    if action == "GRANT":
        audit["status"] = "CLOSED"
        db.touch(audit)
        cascade.recompute_audit_hold(dealer)
        db.touch(dealer)
    else:
        db.touch(dealer)
        issued_at = db.now()
        audit["status"] = "FINDINGS_ISSUED"
        audit["findings_issued_at"] = issued_at
        audit["appeal_deadline"] = db.add_days(issued_at, profile_of(dealer)["appeal_window_days"])
        db.touch(audit)
    return response.ok(appeal)
