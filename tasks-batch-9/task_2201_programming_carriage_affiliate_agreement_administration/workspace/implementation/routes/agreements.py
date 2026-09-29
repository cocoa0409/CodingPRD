"""Carriage agreements: both state dimensions plus the settlement roll-up."""
from datetime import timedelta

from flask import Blueprint

import constants as K
from auth import enforce_scope, guard
from calc import stamp_agreement_rates
from cascades import (
    agreement_commitments,
    recompute_titles,
    renewal_window_open,
    suspend_agreement,
    terminate_agreement,
    unblock_suspended_windows,
)
from common import (
    ALL_READ_ROLES,
    BUSINESS_READ_ROLES,
    created,
    list_endpoint,
    ok,
    read_endpoint,
)
from envelope import respond_object
from errors import ApiError
from lookup import must, put
from store import D, add_months, db, dfloor, new_entity, now, touch
from validation import bad, check_body, field

bp = Blueprint("agreements", __name__)
BASE = "/carriage/agreements"

LIFECYCLE_ACTIONS = [
    "SUBMIT_FOR_NEGOTIATION",
    "RETURN_TO_DRAFT",
    "EXECUTE",
    "SUSPEND",
    "REINSTATE",
    "TERMINATE",
]
RENEWAL_ACTIONS = ["START_ANALYSIS", "OFFER", "REOPEN_ANALYSIS", "RENEW", "LAPSE"]


def _bad_lifecycle():
    raise ApiError(
        "ERR_INVALID_AGREEMENT_STATE",
        "not a declared transition out of the current lifecycle_status",
    )


def _bad_renewal():
    raise ApiError(
        "ERR_INVALID_RENEWAL_STATE",
        "not a declared transition out of the current renewal_status",
    )


@bp.route(BASE, methods=["POST"])
def create_agreement():
    guard(["AffiliateSalesExec"])
    body = check_body(
        {
            "distributor_id": field("id", required=True),
            "contract_code": field("string", required=True, min_len=1, max_len=100),
            "term_start_date": field("datetime", required=True),
            "term_end_date": field("datetime", required=True),
            "base_license_fee_cents_per_sub": field(
                "number", required=True, exclusive_min=0
            ),
            "escalator_pct": field("number", required=True, minimum=0, maximum="0.15"),
            "penetration_floor_pct": field(
                "number", required=True, exclusive_min=0, maximum=1
            ),
            "committed_tier": field("enum", required=True, enum=K.TIERS),
            "launch_fee_cents": field("int", default=0, minimum=0),
            "marketing_commitment_cents": field("int", default=0, minimum=0),
        }
    )
    if body["term_end_date"] <= body["term_start_date"]:
        bad("term_end_date must be strictly later than term_start_date")

    distributor = must("distributor", body["distributor_id"])

    for existing in db.agreements.values():
        if (
            existing["distributor_id"] == distributor["id"]
            and existing["contract_code"] == body["contract_code"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_CONTRACT_CODE",
                "contract_code already used by this operator",
            )

    record = new_entity()
    record.update(
        {
            "distributor_id": distributor["id"],
            "contract_code": body["contract_code"],
            "term_start_date": body["term_start_date"],
            "term_end_date": body["term_end_date"],
            "base_license_fee_cents_per_sub": body["base_license_fee_cents_per_sub"],
            "escalator_pct": body["escalator_pct"],
            "penetration_floor_pct": body["penetration_floor_pct"],
            "committed_tier": body["committed_tier"],
            "launch_fee_cents": body["launch_fee_cents"],
            "marketing_commitment_cents": body["marketing_commitment_cents"],
            "lifecycle_status": "DRAFT",
            "renewal_status": "NOT_DUE",
            "negotiation_round": 0,
            "escalated_rate_cents_per_sub": None,
            "effective_rate_cents_per_sub": None,
            "applied_escalator_years": 0,
            "mfn_capped": False,
            "penetration_compliance_status": "UNKNOWN",
            "penetration_breach_count": 0,
            "consecutive_compliant_periods": 0,
            "recognized_revenue_cents": 0,
            "executed_at": None,
            "suspension_reason": "NONE",
            "renewal_analysis_started_at": None,
            "renewal_offer_sent_at": None,
            "_executed_by": None,
        }
    )
    stamp_agreement_rates(record)
    put("agreement", record)
    return created(record)


@bp.route(BASE, methods=["GET"])
def list_agreements():
    return list_endpoint(
        "agreement",
        ALL_READ_ROLES,
        ["distributor_id", "lifecycle_status", "renewal_status", "committed_tier"],
    )


@bp.route(BASE + "/<agreement_id>", methods=["GET"])
def read_agreement(agreement_id):
    return read_endpoint("agreement", ALL_READ_ROLES, agreement_id)


@bp.route(BASE + "/<agreement_id>", methods=["PATCH"])
def patch_agreement(agreement_id):
    guard(["AffiliateSalesExec"])
    body = check_body(
        {
            "base_license_fee_cents_per_sub": field("number", exclusive_min=0),
            "escalator_pct": field("number", minimum=0, maximum="0.15"),
            "penetration_floor_pct": field("number", exclusive_min=0, maximum=1),
            "committed_tier": field("enum", enum=K.TIERS),
            "term_end_date": field("datetime"),
            "launch_fee_cents": field("int", minimum=0),
            "marketing_commitment_cents": field("int", minimum=0),
        }
    )
    agreement = must("agreement", agreement_id)
    if agreement["lifecycle_status"] not in ("DRAFT", "NEGOTIATING"):
        raise ApiError(
            "ERR_INVALID_AGREEMENT_STATE",
            "commercial terms may only be amended pre-execution",
        )
    if (
        body["term_end_date"] is not None
        and body["term_end_date"] <= agreement["term_start_date"]
    ):
        bad("term_end_date must be strictly later than term_start_date")

    for key in (
        "base_license_fee_cents_per_sub",
        "escalator_pct",
        "penetration_floor_pct",
        "committed_tier",
        "term_end_date",
        "launch_fee_cents",
        "marketing_commitment_cents",
    ):
        if body[key] is not None:
            agreement[key] = body[key]

    stamp_agreement_rates(agreement)
    touch(agreement)
    return ok(agreement)


def _open_invoices_of_agreement(agreement_id):
    return [
        i
        for i in db.invoices.values()
        if i["agreement_id"] == agreement_id
        and i["status"] in ("ISSUED", "PARTIALLY_PAID")
    ]


def _open_commitment(agreement, commitment_type, committed_cents, deadline):
    record = new_entity()
    record.update(
        {
            "agreement_id": agreement["id"],
            "commitment_type": commitment_type,
            "committed_cents": committed_cents,
            "performance_deadline": deadline,
            "earned_cents": 0,
            "earned_unbilled_cents": 0,
            "billed_cents": 0,
            "forfeited_cents": 0,
            "remaining_cents": committed_cents,
            "status": "OPEN",
        }
    )
    put("commitment", record)
    return record


@bp.route(BASE + "/<agreement_id>/lifecycle", methods=["POST"])
def agreement_lifecycle(agreement_id):
    caller = guard(["AffiliateSalesExec"])
    body = check_body(
        {
            "action": field("enum", required=True, enum=LIFECYCLE_ACTIONS),
            "suspension_reason": field("enum", enum=K.SUSPENSION_REASONS),
        }
    )
    agreement = must("agreement", agreement_id)
    enforce_scope(caller, agreement["distributor_id"])
    distributor = db.distributors.get(agreement["distributor_id"])
    action = body["action"]
    state = agreement["lifecycle_status"]
    current = now()

    if action == "SUBMIT_FOR_NEGOTIATION":
        if state != "DRAFT":
            _bad_lifecycle()
        if agreement["term_end_date"] <= current:
            raise ApiError(
                "ERR_INVALID_AGREEMENT_STATE", "the term has already run out"
            )
        if distributor["status"] not in ("ACTIVE", "CREDIT_HOLD"):
            raise ApiError(
                "ERR_DISTRIBUTOR_CREDIT_HOLD",
                "a SUSPENDED or TERMINATED operator cannot open negotiations",
            )
        agreement["lifecycle_status"] = "NEGOTIATING"
        agreement["negotiation_round"] += 1
        stamp_agreement_rates(agreement)
        touch(agreement)
        return ok(agreement)

    if action == "RETURN_TO_DRAFT":
        if state != "NEGOTIATING":
            _bad_lifecycle()
        # negotiation_round records entries into negotiation, not exits.
        agreement["lifecycle_status"] = "DRAFT"
        touch(agreement)
        return ok(agreement)

    if action == "EXECUTE":
        if state != "NEGOTIATING":
            _bad_lifecycle()
        if distributor["status"] != "ACTIVE":
            raise ApiError(
                "ERR_DISTRIBUTOR_CREDIT_HOLD",
                "the operator must be strictly ACTIVE to execute an agreement",
            )
        if not (agreement["term_start_date"] <= current < agreement["term_end_date"]):
            raise ApiError(
                "ERR_INVALID_AGREEMENT_STATE",
                "the current logical instant lies outside the term",
            )
        if dfloor(
            D(agreement["penetration_floor_pct"]) * D(distributor["total_subscribers"])
        ) < 1:
            raise ApiError(
                "ERR_PENETRATION_FLOOR_UNENFORCEABLE",
                "the penetration floor does not bind even one subscriber",
            )

        agreement["lifecycle_status"] = "EXECUTED"
        agreement["executed_at"] = current
        agreement["_executed_by"] = caller.user_id
        stamp_agreement_rates(agreement)
        touch(agreement)

        distributor["executed_agreement_count"] += 1
        touch(distributor)

        if agreement["launch_fee_cents"] > 0:
            _open_commitment(
                agreement,
                "LAUNCH_FEE",
                agreement["launch_fee_cents"],
                current + timedelta(days=K.LAUNCH_FEE_PERFORMANCE_DAYS),
            )
        if agreement["marketing_commitment_cents"] > 0:
            _open_commitment(
                agreement,
                "MARKETING_SUPPORT",
                agreement["marketing_commitment_cents"],
                agreement["term_end_date"],
            )
        return ok(agreement)

    if action == "SUSPEND":
        if state != "EXECUTED":
            _bad_lifecycle()
        suspend_agreement(agreement, "MANUAL_SUSPENSION")
        return ok(agreement)

    if action == "REINSTATE":
        if state != "SUSPENDED":
            _bad_lifecycle()
        if distributor["status"] != "ACTIVE":
            raise ApiError(
                "ERR_DISTRIBUTOR_CREDIT_HOLD", "the operator is not ACTIVE again"
            )
        if (
            agreement["suspension_reason"] == "PENETRATION_BREACH"
            and agreement["penetration_breach_count"] > 0
        ):
            raise ApiError(
                "ERR_BREACH_COUNT_NOT_CLEARED",
                "the penetration breach counter is still positive",
            )
        if agreement["term_end_date"] <= current:
            raise ApiError("ERR_INVALID_AGREEMENT_STATE", "the term is no longer live")

        agreement["lifecycle_status"] = "EXECUTED"
        agreement["suspension_reason"] = "NONE"
        touch(agreement)
        recompute_titles(unblock_suspended_windows(agreement["id"]))
        return ok(agreement)

    # TERMINATE
    if state == "NEGOTIATING":
        if agreement["renewal_status"] in ("RENEWAL_ANALYSIS", "RENEWAL_OFFERED"):
            agreement["renewal_status"] = "LAPSED"
        agreement["lifecycle_status"] = "TERMINATED"
        touch(agreement)
        return ok(agreement)

    if state == "SUSPENDED":
        if _open_invoices_of_agreement(agreement["id"]):
            raise ApiError(
                "ERR_OPEN_RECEIVABLE_BLOCKS_TERMINATION",
                "an invoice of this agreement is still ISSUED or PARTIALLY_PAID",
            )
        terminate_agreement(agreement)
        return ok(agreement)

    _bad_lifecycle()


@bp.route(BASE + "/<agreement_id>/renewal", methods=["POST"])
def agreement_renewal(agreement_id):
    caller = guard(["AffiliateSalesExec"])
    body = check_body({"action": field("enum", required=True, enum=RENEWAL_ACTIONS)})
    agreement = must("agreement", agreement_id)
    enforce_scope(caller, agreement["distributor_id"])
    distributor = db.distributors.get(agreement["distributor_id"])
    action = body["action"]
    state = agreement["renewal_status"]

    if action == "START_ANALYSIS":
        if state != "NOT_DUE":
            _bad_renewal()
        if agreement["lifecycle_status"] not in ("EXECUTED", "SUSPENDED"):
            raise ApiError(
                "ERR_AGREEMENT_NOT_EXECUTED",
                "renewal work needs a live or suspended term",
            )
        if not renewal_window_open(agreement):
            raise ApiError(
                "ERR_RENEWAL_WINDOW_NOT_OPEN",
                "the renewal window has not opened yet",
            )
        agreement["renewal_status"] = "RENEWAL_ANALYSIS"
        agreement["renewal_analysis_started_at"] = now()
        touch(agreement)
        return ok(agreement)

    if action == "OFFER":
        if state != "RENEWAL_ANALYSIS":
            _bad_renewal()
        has_model = any(
            a["agreement_id"] == agreement["id"] for a in db.renewal_analyses.values()
        )
        if not has_model:
            raise ApiError(
                "ERR_RENEWAL_REQUIRES_ANALYSIS", "the offer must be evidence-backed"
            )
        agreement["renewal_status"] = "RENEWAL_OFFERED"
        agreement["renewal_offer_sent_at"] = now()
        touch(agreement)
        return ok(agreement)

    if action == "REOPEN_ANALYSIS":
        if state != "RENEWAL_OFFERED":
            _bad_renewal()
        agreement["renewal_status"] = "RENEWAL_ANALYSIS"
        agreement["negotiation_round"] += 1
        touch(agreement)
        return ok(agreement)

    if action == "RENEW":
        if state != "RENEWAL_OFFERED":
            _bad_renewal()
        if agreement["lifecycle_status"] != "EXECUTED":
            raise ApiError(
                "ERR_AGREEMENT_NOT_EXECUTED",
                "a suspended agreement may not be renewed until reinstated",
            )
        if distributor["status"] != "ACTIVE":
            raise ApiError("ERR_DISTRIBUTOR_CREDIT_HOLD", "the operator is not ACTIVE")
        agreement["renewal_status"] = "RENEWED"
        agreement["term_end_date"] = add_months(
            agreement["term_end_date"], K.RENEWAL_TERM_MONTHS
        )
        stamp_agreement_rates(agreement)
        touch(agreement)
        return ok(agreement)

    # LAPSE
    if state != "RENEWAL_OFFERED":
        _bad_renewal()
    agreement["renewal_status"] = "LAPSED"
    touch(agreement)
    return ok(agreement)


@bp.route(BASE + "/<agreement_id>/settlement-summary", methods=["GET"])
def settlement_summary(agreement_id):
    caller = guard(BUSINESS_READ_ROLES)
    agreement = must("agreement", agreement_id)
    enforce_scope(caller, agreement["distributor_id"])

    reports = [
        r
        for r in db.subscriber_reports.values()
        if r["agreement_id"] == agreement["id"]
        and r["status"] in ("ACCEPTED", "AUDIT_ADJUSTED")
    ]
    accepted_total = sum(r["license_fee_due_cents"] for r in reports)

    invoices = [
        i for i in db.invoices.values() if i["agreement_id"] == agreement["id"]
    ]
    invoiced_gross = sum(
        i["gross_license_fee_cents"] for i in invoices if i["status"] != "VOID"
    )
    open_receivable = sum(
        i["net_due_cents"] - i["paid_cents"]
        for i in invoices
        if i["status"] in ("ISSUED", "PARTIALLY_PAID")
    )

    lines = agreement_commitments(agreement["id"])
    committed = sum(c["committed_cents"] for c in lines)
    earned = sum(c["earned_cents"] for c in lines)
    remaining = sum(c["remaining_cents"] for c in lines)
    forfeited = sum(c["forfeited_cents"] for c in lines)
    conserved = all(
        c["committed_cents"]
        == c["earned_cents"] + c["remaining_cents"] + c["forfeited_cents"]
        for c in lines
    )

    return respond_object(
        {
            "agreement_id": agreement["id"],
            "recognized_revenue_cents": agreement["recognized_revenue_cents"],
            "accepted_report_fee_total_cents": accepted_total,
            "invoiced_gross_total_cents": invoiced_gross,
            "open_receivable_cents": open_receivable,
            "marketing_committed_cents": committed,
            "marketing_earned_cents": earned,
            "marketing_remaining_cents": remaining,
            "marketing_forfeited_cents": forfeited,
            "marketing_conserved_identity_holds": conserved,
            "revenue_identity_holds": (
                agreement["recognized_revenue_cents"] == accepted_total
            ),
        }
    )
