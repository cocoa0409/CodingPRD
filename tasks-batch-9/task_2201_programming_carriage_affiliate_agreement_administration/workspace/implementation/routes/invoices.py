"""Invoices: the six-step waterfall, issuance cascade and compensating void."""
from datetime import timedelta

from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import stamp_invoice_amounts
from cascades import apply_credit_hold, refresh_commitment_status
from common import (
    BUSINESS_READ_ROLES,
    check_occ,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_distributor,
    sod_invoice_create,
)
from errors import ApiError
from lookup import must, put
from store import creation_order, db, new_entity, now, touch
from validation import bad, check_body, field

bp = Blueprint("invoices", __name__)
BASE = "/carriage/invoices"

INVOICE_ACTIONS = ["ISSUE", "RECORD_PAYMENT", "WRITE_OFF", "VOID"]
OPEN_STATUSES = ("ISSUED", "PARTIALLY_PAID")


def _period_reports(agreement_id, period_month):
    """Every substantiated report of the period, billed or not."""
    rows = [
        r
        for r in db.subscriber_reports.values()
        if r["agreement_id"] == agreement_id
        and r["period_month"] == period_month
        and r["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
    ]
    return creation_order(rows)


def _release_hold_if_clear(distributor):
    """The operator leaves CREDIT_HOLD once both balances are back in line."""
    if (
        distributor["status"] == "CREDIT_HOLD"
        and distributor["receivable_balance_cents"] <= distributor["credit_limit_cents"]
        and distributor["audit_recovery_balance_cents"] == 0
    ):
        distributor["status"] = "ACTIVE"
        distributor["credit_hold_reason"] = "NONE"


@bp.route(BASE, methods=["POST"])
def create_invoice():
    caller = guard(["RevenueAccountant"])
    # segregation of duties runs ahead of every other authorisation-shaped rule
    sod_invoice_create(caller)
    scope_from_body_distributor(caller)
    body = check_body(
        {
            "distributor_id": field("id", required=True),
            "agreement_id": field("id", required=True),
            "period_month": field("period", required=True),
            "invoice_kind": field("enum", required=True, enum=K.INVOICE_KINDS),
            "audit_engagement_id": field("id"),
            "expected_distributor_version": field("int", required=True, minimum=0),
        }
    )
    kind = body["invoice_kind"]
    distributor = must("distributor", body["distributor_id"])
    agreement = must("agreement", body["agreement_id"])
    engagement = None
    if body["audit_engagement_id"] is not None:
        engagement = must("engagement", body["audit_engagement_id"])

    if kind == "AUDIT_RECOVERY" and engagement is None:
        bad("audit_engagement_id is required for an AUDIT_RECOVERY invoice")
    if kind == "LICENSE_FEE" and engagement is not None:
        bad("audit_engagement_id must be null for a LICENSE_FEE invoice")

    check_occ(
        distributor,
        body["expected_distributor_version"],
        "ERR_STALE_DISTRIBUTOR_VERSION",
    )

    if kind == "LICENSE_FEE":
        # CHECK 1 - nothing this invoice would bill may already be claimed
        candidates = _period_reports(agreement["id"], body["period_month"])
        if any(r.get("invoice_id") is not None for r in candidates):
            raise ApiError(
                "ERR_REPORT_ALREADY_BILLED",
                "a report of this period is already carried by another invoice",
            )
        # CHECK 2 - there has to be something to bill
        if not candidates:
            raise ApiError(
                "ERR_NO_BILLABLE_REPORTS",
                "no substantiated unbilled report exists for this period",
            )
    else:
        # CHECK 2 - the engagement must have issued findings worth billing
        if (
            engagement["status"] != "FINDINGS_ISSUED"
            or engagement["recovery_amount_cents"] <= 0
        ):
            raise ApiError(
                "ERR_NO_BILLABLE_REPORTS",
                "the engagement has no issued recovery to bill",
            )
        # CHECK 3 - one recovery, one invoice
        if engagement["recovery_invoice_id"] is not None:
            raise ApiError(
                "ERR_RECOVERY_ALREADY_INVOICED",
                "this engagement's recovery has already been invoiced",
            )

    record = new_entity()
    record.update(
        {
            "distributor_id": distributor["id"],
            "agreement_id": agreement["id"],
            "period_month": body["period_month"],
            "invoice_kind": kind,
            "audit_engagement_id": body["audit_engagement_id"],
            "gross_license_fee_cents": 0,
            "coop_cap_pct": 0,
            "coop_offset_cents": 0,
            "launch_fee_offset_cents": 0,
            "recovery_adjustment_cents": 0,
            "net_due_cents": 0,
            "carryforward_cents": 0,
            "paid_cents": 0,
            "issued_at": None,
            "status": "DRAFT",
            "_consumed": [],
        }
    )
    # A draft only PROJECTS its offsets: no marketing ledger moves here, and no
    # report has its invoice_id claimed.
    stamp_invoice_amounts(record)
    put("invoice", record)

    if kind == "AUDIT_RECOVERY":
        engagement["status"] = "RECOVERY_INVOICED"
        engagement["recovery_invoice_id"] = record["id"]
        touch(engagement)

    # drafting increments the operator's version by one
    touch(distributor)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_invoices():
    return list_endpoint(
        "invoice",
        BUSINESS_READ_ROLES,
        [
            "distributor_id",
            "agreement_id",
            "audit_engagement_id",
            "invoice_kind",
            "status",
            "period_month",
        ],
    )


@bp.route(BASE + "/<invoice_id>", methods=["GET"])
def read_invoice(invoice_id):
    return read_endpoint("invoice", BUSINESS_READ_ROLES, invoice_id)


def _engagement_of(invoice):
    if invoice["invoice_kind"] != "AUDIT_RECOVERY":
        return None
    return db.audit_engagements.get(invoice.get("audit_engagement_id"))


def _consume_offsets(invoice):
    """Turn the projected plan into real billed_cents on the ledger lines."""
    consumed = []
    for line in invoice.get("_offset_plan") or []:
        commitment = db.marketing_commitments.get(line["commitment_id"])
        if commitment is None:
            continue
        take = min(line["amount_cents"], commitment["earned_unbilled_cents"])
        if take <= 0:
            continue
        commitment["billed_cents"] += take
        refresh_commitment_status(commitment)
        touch(commitment)
        consumed.append({"commitment_id": commitment["id"], "amount_cents": take})
    invoice["_consumed"] = consumed


def _restore_offsets(invoice):
    """The exact inverse of _consume_offsets, line by line."""
    for line in invoice.get("_consumed") or []:
        commitment = db.marketing_commitments.get(line["commitment_id"])
        if commitment is None:
            continue
        commitment["billed_cents"] -= line["amount_cents"]
        refresh_commitment_status(commitment)
        touch(commitment)
    invoice["_consumed"] = []


def _claim_reports(invoice):
    ids = invoice.get("_source_report_ids") or []
    for report_id in ids:
        report = db.subscriber_reports.get(report_id)
        if report is None or report.get("invoice_id") is not None:
            continue
        report["invoice_id"] = invoice["id"]
        touch(report)


def _unclaim_reports(invoice):
    rows = [
        r for r in db.subscriber_reports.values() if r.get("invoice_id") == invoice["id"]
    ]
    for report in creation_order(rows):
        report["invoice_id"] = None
        touch(report)


@bp.route(BASE + "/<invoice_id>/lifecycle", methods=["POST"])
def invoice_lifecycle(invoice_id):
    caller = guard(["RevenueAccountant"])
    body = check_body(
        {
            "action": field("enum", required=True, enum=INVOICE_ACTIONS),
            "amount_cents": field("int"),
        }
    )
    invoice = must("invoice", invoice_id)
    enforce_scope(caller, invoice["distributor_id"])
    distributor = db.distributors.get(invoice["distributor_id"])
    action = body["action"]
    if action == "RECORD_PAYMENT" and body["amount_cents"] is None:
        bad("amount_cents is required to record a payment")

    kind = invoice["invoice_kind"]

    if action == "ISSUE":
        if invoice["status"] != "DRAFT":
            raise ApiError(
                "ERR_INVALID_INVOICE_STATE", "issuance is possible from DRAFT only"
            )
        # an AUDIT_RECOVERY invoice is deliberately exempt from the credit test
        if kind == "LICENSE_FEE" and distributor["status"] != "ACTIVE":
            raise ApiError(
                "ERR_DISTRIBUTOR_CREDIT_HOLD",
                "a held operator cannot be handed a new license-fee bill",
            )
        if invoice["net_due_cents"] <= 0:
            raise ApiError(
                "ERR_INVOICE_ZERO_NET_DUE",
                "a fully-offset invoice must be voided, not issued",
            )

        invoice["status"] = "ISSUED"
        invoice["issued_at"] = now()
        touch(invoice)

        _consume_offsets(invoice)
        _claim_reports(invoice)

        # LINK 1 - the receivable takes the invoice on
        net = invoice["net_due_cents"]
        distributor["receivable_balance_cents"] += net
        if kind == "AUDIT_RECOVERY":
            distributor["audit_recovery_balance_cents"] += net

        # LINKS 2 to 5 - the credit breach darkens agreements, windows, titles
        if (
            distributor["receivable_balance_cents"] > distributor["credit_limit_cents"]
            and distributor["status"] == "ACTIVE"
        ):
            apply_credit_hold(distributor, "RECEIVABLE_LIMIT_BREACH")
        else:
            touch(distributor)
        return ok(invoice)

    if action == "RECORD_PAYMENT":
        if invoice["status"] not in OPEN_STATUSES:
            raise ApiError(
                "ERR_INVALID_INVOICE_STATE",
                "cash applies to an ISSUED or PARTIALLY_PAID invoice only",
            )
        amount = body["amount_cents"]
        if amount <= 0 or invoice["paid_cents"] + amount > invoice["net_due_cents"]:
            raise ApiError(
                "ERR_PAYMENT_EXCEEDS_BALANCE",
                "the payment must be positive and no larger than the open balance",
            )

        invoice["paid_cents"] += amount
        settled = invoice["paid_cents"] == invoice["net_due_cents"]
        invoice["status"] = "PAID" if settled else "PARTIALLY_PAID"
        touch(invoice)

        distributor["receivable_balance_cents"] -= amount
        if kind == "AUDIT_RECOVERY":
            distributor["audit_recovery_balance_cents"] -= amount

        if settled:
            engagement = _engagement_of(invoice)
            if engagement is not None and engagement["status"] == "RECOVERY_INVOICED":
                engagement["status"] = "COLLECTED"
                touch(engagement)

        _release_hold_if_clear(distributor)
        touch(distributor)
        return ok(invoice)

    if action == "WRITE_OFF":
        if invoice["status"] not in OPEN_STATUSES:
            raise ApiError(
                "ERR_INVALID_INVOICE_STATE",
                "only an ISSUED or PARTIALLY_PAID invoice can be written off",
            )
        if now() < invoice["issued_at"] + timedelta(days=K.WRITE_OFF_AGE_DAYS):
            raise ApiError(
                "ERR_WRITE_OFF_TOO_EARLY",
                "the invoice has not aged 120 days since issuance",
            )
        remainder = invoice["net_due_cents"] - invoice["paid_cents"]
        invoice["status"] = "WRITTEN_OFF"
        touch(invoice)

        # a credit-loss event: recognized_revenue_cents is deliberately intact
        distributor["receivable_balance_cents"] -= remainder
        if kind == "AUDIT_RECOVERY":
            distributor["audit_recovery_balance_cents"] -= remainder
        touch(distributor)
        return ok(invoice)

    # VOID
    if invoice["status"] == "DRAFT":
        # a draft only projected its offsets, so there is nothing to restore
        invoice["status"] = "VOID"
        touch(invoice)
        return ok(invoice)

    if invoice["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_INVOICE_STATE", "voiding is possible from DRAFT or ISSUED only"
        )
    if invoice["paid_cents"] > 0:
        raise ApiError(
            "ERR_INVALID_INVOICE_STATE",
            "a partially collected invoice must be written off, never voided",
        )

    net = invoice["net_due_cents"]
    invoice["status"] = "VOID"
    touch(invoice)

    _restore_offsets(invoice)
    _unclaim_reports(invoice)

    distributor["receivable_balance_cents"] -= net
    if kind == "AUDIT_RECOVERY":
        distributor["audit_recovery_balance_cents"] -= net
    # the operator may come off hold, but suspended agreements stay suspended
    _release_hold_if_clear(distributor)
    touch(distributor)

    engagement = _engagement_of(invoice)
    if engagement is not None and engagement["status"] == "RECOVERY_INVOICED":
        # findings_issued_at is deliberately NOT re-stamped
        engagement["status"] = "FINDINGS_ISSUED"
        engagement["recovery_invoice_id"] = None
        touch(engagement)
    return ok(invoice)
