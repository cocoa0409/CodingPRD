"""Complaints, investigation, resolution and remediation credits (PRD §3.8)."""

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import (COMPLAINT_ANALYST, COMPLIANCE_OFFICER,
                        NETWORK_ENGINEER, REGULATORY_LIAISON, RETAIL_AGENT,
                        SUBSCRIBER, authorize, require_own_account)
from services import calculations as calc
from services import reconcile

bp = Blueprint("complaints", __name__)

ALLEGATION_TYPES = ("SPEED_SHORTFALL", "LATENCY_SHORTFALL",
                    "RELIABILITY_OUTAGE", "FEE_MISMATCH")
CREDIT_BASES = ("PRORATA_DAYS", "FLAT_SEVERITY_TIER")
FINDINGS = ("UPHELD", "DISMISSED")
NON_TERMINAL = ("INTAKE", "TRIAGED", "UNDER_INVESTIGATION", "INFO_REQUESTED")
TERMINAL_FOR_FILING = ("UPHELD", "DISMISSED", "WITHDRAWN")


def _assess(complaint):
    label = db.store.label_versions.get(complaint["disputed_label_version_id"])
    ratio, severity = calc.complaint_shortfall_assessment(complaint, label)
    complaint["shortfall_ratio"] = ratio
    complaint["severity"] = severity


# ---------------------------------------------------------------------------
# intake and reads
# ---------------------------------------------------------------------------

@bp.route("/complaints", methods=["POST"])
def create_complaint():
    principal = authorize(SUBSCRIBER, COMPLAINT_ANALYST)
    body = validators.json_body()

    account_ref = validators.get_id_ref(body, "account_id")
    label_ref = validators.get_id_ref(body, "disputed_label_version_id")
    allegation = validators.get_enum(body, "allegation_type", ALLEGATION_TYPES)
    observed_date = validators.get_datetime(body, "service_observed_date")
    affected_days = validators.get_int(body, "affected_days", minimum=1,
                                       maximum=60)
    narrative = validators.get_str(body, "narrative", 1, 2000)
    download = validators.get_number(body, "measured_download_mbps", minimum=0,
                                     required=False, default=None,
                                     nullable=True)
    upload = validators.get_number(body, "measured_upload_mbps", minimum=0,
                                   required=False, default=None, nullable=True)
    latency = validators.get_int(body, "measured_latency_ms", minimum=1,
                                 required=False, default=None, nullable=True)

    if allegation == "SPEED_SHORTFALL" and download is None:
        validators.bad("Field 'measured_download_mbps' is required for a "
                       "SPEED_SHORTFALL allegation.")
    if allegation == "LATENCY_SHORTFALL" and latency is None:
        validators.bad("Field 'measured_latency_ms' is required for a "
                       "LATENCY_SHORTFALL allegation.")

    account = lookup.subscriber_account(account_ref)
    label = lookup.label_version(label_ref)

    require_own_account(principal, account["id"])

    observed = db.parse_iso(observed_date)
    label_from = db.dt_of(label, "effective_from")
    label_until = db.dt_of(label, "effective_until")
    covers = (label_from is not None and label_from <= observed
              and (label_until is None or observed < label_until))
    pinned = (label["typical_download_mbps"] is not None
              and label["typical_upload_mbps"] is not None
              and label["typical_latency_ms"] is not None)
    if not covers or not pinned:
        fail(errors.ERR_LABEL_INVALID_STATE)

    complaint = db.new_record()
    complaint.update({
        "account_id": account["id"],
        "disputed_label_version_id": label["id"],
        "allegation_type": allegation,
        "service_observed_date": observed_date,
        "affected_days": affected_days,
        "measured_download_mbps": download,
        "measured_upload_mbps": upload,
        "measured_latency_ms": latency,
        "narrative": narrative,
        "state": "INTAKE",
        "triaged_at": None,
        "sla_due_at": None,
        "resolved_at": None,
        "reopened_count": 0,
        "investigation_cycles": 0,
        "shortfall_ratio": None,
        "severity": "NONE",
        "evidence_gap": False,
        "credit_basis": None,
        "remediation_credit_cents": 0,
        "resolution": "NONE",
        "resolution_note": None,
        "info_request_note": None,
    })
    db.store.complaints[complaint["id"]] = complaint
    return response.success(serializers.complaint(complaint), 201)


@bp.route("/complaints/<complaint_id>", methods=["GET"])
def read_complaint(complaint_id):
    principal = authorize(COMPLIANCE_OFFICER, NETWORK_ENGINEER,
                          COMPLAINT_ANALYST, REGULATORY_LIAISON, RETAIL_AGENT,
                          SUBSCRIBER)
    complaint = lookup.complaint(complaint_id)
    require_own_account(principal, complaint["account_id"])
    return response.success(serializers.complaint(complaint), 200)


@bp.route("/complaints", methods=["GET"])
def list_complaints():
    principal = authorize(COMPLIANCE_OFFICER, NETWORK_ENGINEER,
                          COMPLAINT_ANALYST, REGULATORY_LIAISON, RETAIL_AGENT,
                          SUBSCRIBER)
    validators.pagination_params()
    account_id = request.args.get("account_id")
    label_id = request.args.get("disputed_label_version_id")
    state = request.args.get("state")

    if principal.is_subscriber:
        if account_id is not None and account_id != principal.user_id:
            fail(errors.ERR_ACCOUNT_SCOPE_VIOLATION)
        account_id = principal.user_id

    rows = [c for c in db.store.complaints.values()
            if (account_id is None or c["account_id"] == account_id)
            and (label_id is None
                 or c["disputed_label_version_id"] == label_id)
            and (state is None or c["state"] == state)]
    items, meta = validators.paginate(db.ordered(rows), serializers.complaint)
    return response.success_list(items, meta, 200)


# ---------------------------------------------------------------------------
# investigation lifecycle
# ---------------------------------------------------------------------------

@bp.route("/complaints/<complaint_id>/triage", methods=["POST"])
def triage_complaint(complaint_id):
    authorize(COMPLAINT_ANALYST)
    body = validators.json_body()
    validators.get_str(body, "priority_note", 1, None)

    complaint = lookup.complaint(complaint_id)
    if complaint["state"] != "INTAKE":
        fail(errors.ERR_COMPLAINT_INVALID_STATE)

    triaged_at = db.now()
    complaint["state"] = "TRIAGED"
    complaint["triaged_at"] = db.iso(triaged_at)
    complaint["sla_due_at"] = db.iso(
        db.plus_days(triaged_at, calc.COMPLAINT_SLA_DAYS))
    db.touch(complaint)
    return response.success(serializers.complaint(complaint), 200)


@bp.route("/complaints/<complaint_id>/investigate", methods=["POST"])
def investigate_complaint(complaint_id):
    authorize(COMPLAINT_ANALYST)
    complaint = lookup.complaint(complaint_id)
    if complaint["state"] not in ("TRIAGED", "INFO_REQUESTED"):
        fail(errors.ERR_COMPLAINT_INVALID_STATE)

    resumed = complaint["state"] == "INFO_REQUESTED"
    complaint["state"] = "UNDER_INVESTIGATION"
    if resumed:
        complaint["investigation_cycles"] += 1
    _assess(complaint)
    db.touch(complaint)
    return response.success(serializers.complaint(complaint), 200)


@bp.route("/complaints/<complaint_id>/request-info", methods=["POST"])
def request_complaint_info(complaint_id):
    authorize(COMPLAINT_ANALYST)
    body = validators.json_body()
    note = validators.get_str(body, "info_request_note", 1, None)

    complaint = lookup.complaint(complaint_id)
    if complaint["state"] != "UNDER_INVESTIGATION":
        fail(errors.ERR_COMPLAINT_INVALID_STATE)

    complaint["state"] = "INFO_REQUESTED"
    complaint["info_request_note"] = note
    db.touch(complaint)
    return response.success(serializers.complaint(complaint), 200)


@bp.route("/complaints/<complaint_id>/resolve", methods=["POST"])
def resolve_complaint(complaint_id):
    principal = authorize(COMPLAINT_ANALYST)
    body = validators.json_body()
    finding = validators.get_enum(body, "finding", FINDINGS)
    note = validators.get_str(body, "resolution_note", 1, None)
    basis = validators.get_enum(body, "credit_basis", CREDIT_BASES,
                                required=False, default=None, nullable=True)
    if finding == "UPHELD" and basis is None:
        validators.bad("Field 'credit_basis' is required for an UPHELD "
                       "finding.")
    if finding == "DISMISSED" and basis is not None:
        validators.bad("Field 'credit_basis' must be omitted for a DISMISSED "
                       "finding.")

    complaint = lookup.complaint(complaint_id)
    if complaint["state"] != "UNDER_INVESTIGATION":
        fail(errors.ERR_COMPLAINT_INVALID_STATE)

    if finding == "UPHELD" and complaint["severity"] == "NONE":
        fail(errors.ERR_SHORTFALL_NOT_SUBSTANTIATED)

    account = db.store.subscriber_accounts.get(complaint["account_id"])
    label = db.store.label_versions.get(complaint["disputed_label_version_id"])

    if finding == "DISMISSED":
        complaint["state"] = "DISMISSED"
        complaint["resolution"] = "DISMISSED"
        complaint["resolved_at"] = db.now_iso()
        complaint["resolution_note"] = note
        db.touch(complaint)
        return response.success(serializers.complaint(complaint), 200)

    # ---- UPHELD: the four-hop cascade -------------------------------------
    complaint["credit_basis"] = basis
    amount = calc.remediation_credit_amount(complaint, label, account)

    # Hop 1.
    complaint["state"] = "UPHELD"
    complaint["resolution"] = "UPHELD"
    complaint["resolved_at"] = db.now_iso()
    complaint["resolution_note"] = note
    complaint["remediation_credit_cents"] = amount
    db.touch(complaint)

    # Hop 2.
    credit = db.new_record()
    credit.update({
        "complaint_id": complaint["id"],
        "account_id": complaint["account_id"],
        "basis": basis,
        "amount_cents": amount,
        "status": "ISSUED",
        "issued_by_user_id": principal.user_id,
        "voided_by_user_id": None,
        "voided_at": None,
        "void_reason": None,
    })
    db.store.remediation_credits[credit["id"]] = credit

    # Hops 3 and 4.
    if account is not None:
        reconcile.recompute_account_credit_totals(account)

    # Non-chain consequence on the plan.
    if account is not None:
        plan = db.store.service_plans.get(account["plan_id"])
        if plan is not None:
            reconcile.recompute_upheld_complaint_count(plan)
            calc.recompute_plan_posture(plan)
            db.touch(plan)

    return response.success(serializers.complaint(complaint), 200)


@bp.route("/complaints/<complaint_id>/reopen", methods=["POST"])
def reopen_complaint(complaint_id):
    authorize(COMPLAINT_ANALYST)
    body = validators.json_body()
    validators.get_str(body, "reopen_reason", 1, None)

    complaint = lookup.complaint(complaint_id)
    if complaint["state"] != "DISMISSED":
        fail(errors.ERR_COMPLAINT_INVALID_STATE)

    resolved_at = db.dt_of(complaint, "resolved_at")
    elapsed = db.whole_days_between(resolved_at, db.now()) \
        if resolved_at is not None else 0
    if elapsed > calc.REOPEN_WINDOW_DAYS:
        fail(errors.ERR_REOPEN_WINDOW_EXPIRED)
    if complaint["reopened_count"] >= calc.MAX_REOPENS:
        fail(errors.ERR_REOPEN_WINDOW_EXPIRED)

    complaint["state"] = "UNDER_INVESTIGATION"
    complaint["reopened_count"] += 1
    complaint["resolved_at"] = None
    complaint["resolution"] = "NONE"
    complaint["resolution_note"] = None
    db.touch(complaint)
    return response.success(serializers.complaint(complaint), 200)


@bp.route("/complaints/<complaint_id>/withdraw", methods=["POST"])
def withdraw_complaint(complaint_id):
    principal = authorize(SUBSCRIBER)
    body = validators.json_body()
    validators.get_str(body, "withdraw_reason", 1, None)

    complaint = lookup.complaint(complaint_id)
    require_own_account(principal, complaint["account_id"])

    if complaint["state"] not in NON_TERMINAL:
        fail(errors.ERR_COMPLAINT_INVALID_STATE)

    complaint["state"] = "WITHDRAWN"
    complaint["resolution"] = "WITHDRAWN"
    complaint["resolved_at"] = db.now_iso()
    db.touch(complaint)
    return response.success(serializers.complaint(complaint), 200)


# ---------------------------------------------------------------------------
# remediation credits
# ---------------------------------------------------------------------------

@bp.route("/complaints/<complaint_id>/remediation-credits", methods=["GET"])
def list_complaint_credits(complaint_id):
    principal = authorize(COMPLIANCE_OFFICER, COMPLAINT_ANALYST,
                          REGULATORY_LIAISON, RETAIL_AGENT, SUBSCRIBER)
    validators.pagination_params()
    complaint = lookup.complaint(complaint_id)
    require_own_account(principal, complaint["account_id"])

    status = request.args.get("status")
    rows = [c for c in db.store.remediation_credits.values()
            if c["complaint_id"] == complaint["id"]
            and (status is None or c["status"] == status)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.remediation_credit)
    return response.success_list(items, meta, 200)


@bp.route("/remediation-credits/<credit_id>", methods=["GET"])
def read_remediation_credit(credit_id):
    authorize(COMPLIANCE_OFFICER, COMPLAINT_ANALYST, REGULATORY_LIAISON,
              RETAIL_AGENT)
    credit = lookup.remediation_credit(credit_id)
    return response.success(serializers.remediation_credit(credit), 200)


@bp.route("/remediation-credits/<credit_id>/void", methods=["POST"])
def void_remediation_credit(credit_id):
    principal = authorize(COMPLIANCE_OFFICER)
    body = validators.json_body()
    reason = validators.get_str(body, "void_reason", 1, None)

    credit = lookup.remediation_credit(credit_id)
    if credit["status"] != "ISSUED":
        fail(errors.ERR_CREDIT_ALREADY_VOIDED)

    credit["status"] = "VOIDED"
    credit["voided_at"] = db.now_iso()
    credit["voided_by_user_id"] = principal.user_id
    credit["void_reason"] = reason
    db.touch(credit)

    account = db.store.subscriber_accounts.get(credit["account_id"])
    if account is not None:
        reconcile.recompute_account_credit_totals(account)

    complaint = db.store.complaints.get(credit["complaint_id"])
    if complaint is not None and complaint["remediation_credit_cents"] != 0:
        complaint["remediation_credit_cents"] = 0
        db.touch(complaint)

    return response.success(serializers.remediation_credit(credit), 200)
