"""Most-favored-nations clauses and the effective-rate cascade (PRD 3.3)."""
from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import (
    active_mfn_clause,
    mfn_benchmark,
    stamp_agreement_rates,
    stamp_invoice_amounts,
    stamp_report_final,
)
from common import (
    BUSINESS_READ_ROLES,
    check_occ,
    created,
    list_endpoint,
    ok,
    read_endpoint,
    scope_from_body_agreement,
)
from errors import ApiError
from lookup import must, put
from store import creation_order, db, new_entity, touch
from validation import check_body, field

bp = Blueprint("mfn", __name__)
BASE = "/carriage/mfn-clauses"


def rate_change_cascade(agreement):
    """The four linked steps that follow a movement of the effective rate."""
    # LINK 1 - the agreement itself
    stamp_agreement_rates(agreement)
    touch(agreement)

    distributor = db.distributors.get(agreement["distributor_id"])

    # LINK 2 - unbilled substantiated reports re-price under the FINAL variant
    reports = [
        r
        for r in db.subscriber_reports.values()
        if r["agreement_id"] == agreement["id"]
        and r["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
    ]
    for report in creation_order(reports):
        if report.get("invoice_id") is not None:
            continue
        stamp_report_final(report, agreement, distributor)
        # an audited period keeps the recovery already folded into its fee
        if report["status"] == "AUDIT_ADJUSTED":
            report["license_fee_due_cents"] += report["audit_adjustment_cents"]
        touch(report)

    # LINK 3 - recognized revenue is the sum over substantiated reports
    agreement["recognized_revenue_cents"] = sum(
        r["license_fee_due_cents"] for r in reports
    )

    # LINK 4 - every DRAFT invoice of the agreement re-runs the waterfall
    drafts = [
        i
        for i in db.invoices.values()
        if i["agreement_id"] == agreement["id"] and i["status"] == "DRAFT"
    ]
    for invoice in creation_order(drafts):
        stamp_invoice_amounts(invoice)
        touch(invoice)


@bp.route(BASE, methods=["POST"])
def create_mfn_clause():
    caller = guard(["AffiliateSalesExec"])
    scope_from_body_agreement(caller)
    body = check_body(
        {
            "agreement_id": field("id", required=True),
            "mfn_scope": field("enum", required=True, enum=K.MFN_SCOPES),
            "min_peer_subscribers": field("int", default=0, minimum=0),
            "rate_floor_cents": field("number", required=True, minimum=0),
        }
    )
    agreement = must("agreement", body["agreement_id"])

    if active_mfn_clause(agreement["id"]) is not None:
        raise ApiError(
            "ERR_MULTIPLE_ACTIVE_MFN_CLAUSES",
            "the agreement already holds an ACTIVE clause",
        )

    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "mfn_scope": body["mfn_scope"],
            "min_peer_subscribers": body["min_peer_subscribers"],
            "rate_floor_cents": body["rate_floor_cents"],
            "benchmark_rate_cents": None,
            "benchmark_peer_agreement_id": None,
            "benchmark_status": "NOT_EVALUATED",
            "last_reset_at": None,
            "status": "ACTIVE",
        }
    )
    put("mfn", record)
    # Creating a clause does not move the agreement's effective rate.
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_mfn_clauses():
    return list_endpoint(
        "mfn",
        BUSINESS_READ_ROLES,
        ["agreement_id", "benchmark_peer_agreement_id", "status", "benchmark_status"],
    )


@bp.route(BASE + "/<clause_id>", methods=["GET"])
def read_mfn_clause(clause_id):
    return read_endpoint("mfn", BUSINESS_READ_ROLES, clause_id)


@bp.route(BASE + "/<clause_id>/reset", methods=["POST"])
def reset_mfn_clause(clause_id):
    caller = guard(["AffiliateSalesExec"])
    body = check_body(
        {
            "action": field("enum", required=True, enum=["RESET", "WAIVE"]),
            "expected_agreement_version": field("int", required=True, minimum=0),
        }
    )
    clause = must("mfn", clause_id)
    agreement = db.agreements.get(clause["agreement_id"])
    enforce_scope(caller, agreement["distributor_id"] if agreement else None)

    check_occ(
        agreement, body["expected_agreement_version"], "ERR_STALE_AGREEMENT_VERSION"
    )

    if clause["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_MFN_STATE", "the clause is no longer ACTIVE")

    if body["action"] == "RESET":
        mfn_benchmark(clause)
        touch(clause)
        rate_change_cascade(agreement)
        return ok(clause)

    # WAIVE - the clause stops capping anything
    clause["status"] = "WAIVED"
    touch(clause)
    stamp_agreement_rates(agreement)
    touch(agreement)
    return ok(clause)
