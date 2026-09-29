"""Period usage reporting, fee remittance and reconciliation (PRD 3.7)."""

from flask import Blueprint

import calc
import services
from calc import num
from db import (add_days, create_row, db, get_dt, logical_now, ordered,
                serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_SUPPLIER, actor_id, commit, require_roles, touch)
from response import created_response, object_response
from routes.common import FEE_STATUS, REPORT_STATUS, fetch, list_endpoint
from validation import bad, json_body, read_dt, read_id, read_int, read_str

bp = Blueprint("usage_reports", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_AUDITOR)
REVIEW_ACTIONS = ("ACCEPT", "REJECT", "RECONCILE")
SUBMISSION_ACTIONS = ("SUBMIT",)
REMITTANCE_ACTIONS = ("REMIT",)
NON_REJECTED = ("DRAFT", "SUBMITTED", "ACCEPTED", "RECONCILED")
REPORTABLE_CONTRACT_STATUSES = ("ACTIVE", "SUSPENDED", "EXPIRED")


# =========================================================================
# creation and reads
# =========================================================================

@bp.route("/coop/usage-reports", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def create_report():
    body = json_body(allowed=("contract_id", "period_start", "period_end"),
                     required=("contract_id", "period_start", "period_end"))
    contract_id = read_id(body, "contract_id", required=True)
    start_raw, start_dt = read_dt(body, "period_start", required=True)
    end_raw, end_dt = read_dt(body, "period_end", required=True)
    if start_dt > end_dt:
        bad("period_start must be at or before period_end")

    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")

    # 7. the acting supplier must own the contract
    if actor_id() != contract["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the contract's supplier_id")

    # 44. reporting periods on one contract must not overlap
    _check_overlap(contract_id, start_dt, end_dt, exclude_id=None)

    row = create_row(
        db.reports,
        contract_id=contract_id,
        period_start=None,
        period_end=None,
        status="DRAFT",
        fee_status="NOT_DUE",
        swept_usage_count=0,
        reported_usage_cents=0,
        reported_chargeable_cents=0,
        reported_fee_cents=0,
        audited_fee_cents=None,
        fee_true_up_cents=None,
        fee_rebate_cents=0,
        variance_pct=None,
        variance_flagged=False,
        remitted_cents=0,
        accepted_at=None,
        fee_due_at=None,
        rejection_reason=None,
    )
    set_dt(row, "period_start", start_raw)
    set_dt(row, "period_end", end_raw)
    set_dt(row, "accepted_at", None)
    set_dt(row, "fee_due_at", None)
    return created_response(serialize(row))


def _check_overlap(contract_id, start_dt, end_dt, exclude_id):
    """Closed intervals: touching at a single instant already overlaps."""
    for other in services.reports_of_contract(contract_id):
        if other["id"] == exclude_id:
            continue
        if other["status"] not in NON_REJECTED:
            continue
        other_start = get_dt(other, "period_start")
        other_end = get_dt(other, "period_end")
        if other_start is None or other_end is None:
            continue
        if start_dt <= other_end and other_start <= end_dt:
            fail("ERR_REPORT_PERIOD_OVERLAP",
                 "the period overlaps an existing report on this contract")


@bp.route("/coop/usage-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reports():
    return list_endpoint(
        lambda: ordered(db.reports),
        {"contract_id": ("contract_id", None),
         "status": ("status", REPORT_STATUS),
         "fee_status": ("fee_status", FEE_STATUS)},
    )


@bp.route("/coop/usage-reports/<report_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_report(report_id):
    row = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    return object_response(serialize(row))


# =========================================================================
# submission and the sweep
# =========================================================================

@bp.route("/coop/usage-reports/<report_id>/submission", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def submission(report_id):
    body = json_body(allowed=("action", "note"), required=())
    read_str(body, "action", enum=SUBMISSION_ACTIONS)
    read_str(body, "note")

    report = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    contract = db.contracts[report["contract_id"]]

    # 7. the acting supplier must own the contract
    if actor_id() != contract["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the contract's supplier_id")

    # 15. from-state on the acceptance dimension
    status = report["status"]
    if status not in ("DRAFT", "REJECTED"):
        fail("ERR_REPORT_INVALID_STATE",
             "SUBMIT is not a declared transition out of %s" % status)

    # A first submission additionally requires a reportable contract.
    if status == "DRAFT" and contract["status"] not in REPORTABLE_CONTRACT_STATUSES:
        fail("ERR_CONTRACT_INVALID_STATE",
             "a report may only be submitted on an ACTIVE, SUSPENDED or "
             "EXPIRED contract")

    # 43. the period must have fully elapsed
    period_end = get_dt(report, "period_end")
    if not logical_now() > period_end:
        fail("ERR_REPORT_PERIOD_NOT_ELAPSED", "the reporting period has not elapsed")

    # 44. and must still not overlap any other non-rejected report
    _check_overlap(contract["id"], get_dt(report, "period_start"), period_end,
                   exclude_id=report["id"])

    report["status"] = "SUBMITTED"
    report["rejection_reason"] = None
    services.sweep_report(report, contract)
    touch(report)
    commit()
    return object_response(serialize(report))


# =========================================================================
# cooperative review
# =========================================================================

@bp.route("/coop/usage-reports/<report_id>/review", methods=["POST"])
@require_roles(ROLE_COOP_ADMIN)
def review(report_id):
    body = json_body(allowed=("action", "rejection_reason", "note"),
                     required=("action",))
    action = read_str(body, "action", required=True, enum=REVIEW_ACTIONS)
    rejection_reason = read_str(body, "rejection_reason", max_len=500)
    read_str(body, "note")

    report = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    contract = db.contracts[report["contract_id"]]
    supplier = db.suppliers[contract["supplier_id"]]

    # 15. from-state on the acceptance dimension
    status = report["status"]
    expected = {"ACCEPT": ("SUBMITTED",), "REJECT": ("SUBMITTED",),
                "RECONCILE": ("ACCEPTED",)}[action]
    if status not in expected:
        fail("ERR_REPORT_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    # 21. the remittance dimension must permit the action
    if action == "ACCEPT" and report["fee_status"] != "NOT_DUE":
        fail("ERR_FEE_STATUS_INVALID",
             "the report's fee_status is no longer NOT_DUE")
    if action == "RECONCILE" and report["fee_status"] not in ("PAID", "DELINQUENT"):
        fail("ERR_FEE_STATUS_INVALID",
             "reconciliation requires a PAID or DELINQUENT fee_status")

    if action == "ACCEPT":
        now = logical_now()
        report["status"] = "ACCEPTED"
        report["fee_status"] = "DUE"
        set_dt(report, "accepted_at", now)
        set_dt(report, "fee_due_at", add_days(now, calc.FEE_DUE_DAYS))
        touch(report)
        _settle_ledgers(contract, supplier)
        services.recompute_compliance_posture(contract)

    elif action == "REJECT":
        report["status"] = "REJECTED"
        report["rejection_reason"] = rejection_reason
        services.clear_sweep(report)
        touch(report)
        _settle_ledgers(contract, supplier)
        services.recompute_compliance_posture(contract)

    else:  # RECONCILE
        swept = services.swept_usages(report)
        audited = sum(int(u["admin_fee_cents"]) for u in swept)
        figures = calc.variance(report["reported_fee_cents"], audited)
        report["status"] = "RECONCILED"
        report["audited_fee_cents"] = audited
        report["fee_true_up_cents"] = figures["fee_true_up_cents"]
        report["fee_rebate_cents"] = figures["fee_rebate_cents"]
        report["variance_pct"] = num(figures["variance_pct"])
        report["variance_flagged"] = figures["variance_flagged"]
        touch(report)
        _settle_ledgers(contract, supplier)
        services.recompute_compliance_posture(contract)
        # A flagged variance costs the supplier five performance points, which
        # can cascade all the way to suspending its active contracts.
        services.recompute_supplier_performance(supplier)

    commit()
    return object_response(serialize(report))


def _settle_ledgers(contract, supplier):
    """Recompute both fee ledgers and guard the ledger identity (step 62).

    PRD 3.7 pins two halves of the invariant: fee_outstanding_cents always equals
    fee_assessed_cents_total minus fee_remitted_cents_total, and *no remittance*
    may drive fee_outstanding_cents below zero.  Only the second half is specific
    to a remittance, so a negative outstanding produced by a reconciliation's
    negative true-up is a legitimate ledger state and is guarded at the
    remittance endpoint instead.
    """
    services.recompute_contract_fee_ledger(contract)
    services.recompute_supplier_fee_ledger(supplier)
    if contract["fee_outstanding_cents"] != (
            contract["fee_assessed_cents_total"]
            - contract["fee_remitted_cents_total"]):
        fail("ERR_FEE_LEDGER_INCONSISTENT", "the fee ledger is inconsistent")


# =========================================================================
# remittance
# =========================================================================

@bp.route("/coop/usage-reports/<report_id>/fee-remittance", methods=["POST"])
@require_roles(ROLE_SUPPLIER)
def fee_remittance(report_id):
    body = json_body(allowed=("action", "amount_cents", "note"),
                     required=("amount_cents",))
    read_str(body, "action", enum=REMITTANCE_ACTIONS)
    amount = read_int(body, "amount_cents", required=True, minimum=0)
    read_str(body, "note")

    report = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    contract = db.contracts[report["contract_id"]]
    supplier = db.suppliers[contract["supplier_id"]]

    # 7. the acting supplier must own the contract
    if actor_id() != contract["supplier_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the contract's supplier_id")

    # 21. the remittance dimension must permit the action
    fee_status = report["fee_status"]
    if fee_status not in ("DUE", "DELINQUENT"):
        fail("ERR_FEE_STATUS_INVALID",
             "a remittance requires a DUE or DELINQUENT fee_status")

    # 60. the remittance settles the report exactly
    owed = int(report["reported_fee_cents"]) - int(report["remitted_cents"])
    if amount != owed:
        fail("ERR_REMITTANCE_AMOUNT_MISMATCH",
             "amount_cents must equal the %d cents outstanding on the report"
             % owed)

    # 62. no remittance may drive fee_outstanding_cents below zero, checked
    # before a single figure moves so a refusal leaves the ledger untouched.
    if (int(contract["fee_assessed_cents_total"])
            - int(contract["fee_remitted_cents_total"]) - amount) < 0:
        fail("ERR_FEE_LEDGER_INCONSISTENT",
             "the remittance would drive fee_outstanding_cents below zero")

    report["remitted_cents"] = int(report["remitted_cents"]) + amount
    report["fee_status"] = "PAID"
    touch(report)

    # the ledger identity, then the compensating cascade
    _settle_ledgers(contract, supplier)
    services.recompute_compliance_posture(contract)
    if fee_status == "DELINQUENT":
        # The compensating action of the sweep: the delinquency counters and
        # the three performance points come back off exactly.
        services.recompute_supplier_performance(supplier)

    commit()
    return object_response(serialize(report))
