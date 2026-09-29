"""Variance research, escalation and loss-prevention closure (PRD section 3.8)."""
from flask import Blueprint

import calc
import clock
import db
import domain
import response
import serializers
import validation
from auth import endpoint, user_id
from errors import bad_request, err
from routes.common import list_collection

bp = Blueprint("cases", __name__)

CASE_READ_ROLES = [
    "CashOfficeClerk",
    "StoreManager",
    "LossPreventionInvestigator",
    "TreasuryAnalyst",
]
DISPOSITIONS = ("SUBSTANTIATED", "UNSUBSTANTIATED")
RESEARCHABLE = ("OPEN", "RESEARCHING")


@bp.post("/cash-ops/variance-cases/<case_id>/attributions")
@endpoint(["CashOfficeClerk", "StoreManager"])
def record_attribution(case_id):
    data = validation.body()
    bucket = validation.req_enum(data, "bucket", calc.ATTRIBUTION_BUCKETS)
    amount_cents = validation.req_int(data, "amount_cents", minimum=None)
    note = validation.req_str(data, "note")
    expected_version = validation.opt_int(data, "expected_variance_case_version", minimum=0)
    case = domain.get_case(case_id)
    if case["status"] not in RESEARCHABLE:
        raise err(
            "ERR_VARIANCE_CASE_INVALID_STATE",
            "attributions are only accepted on an OPEN or RESEARCHING case",
        )
    attributed = sum(domain.bucket_total(case, name) for name in calc.ATTRIBUTION_BUCKETS)
    projected = attributed + amount_cents
    if projected < 0 or projected > case["total_variance_cents"]:
        raise err(
            "ERR_ATTRIBUTION_EXCEEDS_VARIANCE",
            "the attribution would push the research outside the case",
        )
    if expected_version is not None and expected_version != case["version"]:
        raise err(
            "ERR_CASE_VERSION_STALE",
            "expected_variance_case_version does not match the case",
        )
    case["attributions"].append(
        {
            "bucket": bucket,
            "amount_cents": amount_cents,
            "note": note,
            "recorded_at": clock.now(),
        }
    )
    if case["status"] == "OPEN":
        case["status"] = "RESEARCHING"
    if domain.unexplained_cents(case) == 0 and not case["suspected_theft"]:
        case["status"] = "EXPLAINED"
    db.touch(case)
    domain.reevaluate_journal(db.sales_journals.get(case["sales_journal_id"]))
    return response.object_response(serializers.variance_case(case))


@bp.post("/cash-ops/variance-cases/<case_id>/escalate")
@endpoint(["StoreManager", "LossPreventionInvestigator"])
def escalate_case(case_id):
    data = validation.body()
    validation.req_str(data, "escalation_reason")
    case = domain.get_case(case_id)
    if case["status"] not in RESEARCHABLE:
        raise err(
            "ERR_VARIANCE_CASE_INVALID_STATE",
            "only an OPEN or RESEARCHING case may be escalated",
        )
    journal = domain.get_journal(case["sales_journal_id"])
    store = domain.get_store(journal["store_id"])
    gated = case["total_variance_cents"] >= store["theft_escalation_threshold_cents"]
    if not gated and case["cashier_id"] is not None:
        window_start = clock.plus_days(clock.now(), -calc.ESCALATION_PATTERN_DAYS)
        siblings = [
            other
            for other in db.ordered(db.variance_cases)
            if other["id"] != case["id"]
            and other["cashier_id"] == case["cashier_id"]
            and other["created_at"] >= window_start
        ]
        gated = len(siblings) >= 2
    if not gated:
        raise err(
            "ERR_ESCALATION_THRESHOLD_NOT_MET",
            "neither the magnitude nor the rolling pattern warrants escalation",
        )
    case["status"] = "ESCALATED"
    case["escalated_by_user_id"] = user_id()
    case["suspected_theft"] = True
    db.touch(case)
    if case["cashier_id"] is not None:
        cashier = db.cashiers.get(case["cashier_id"])
        if cashier is not None:
            cashier["till_eligibility"] = "BARRED"
            db.touch(cashier)
            for session in db.ordered(db.till_sessions):
                if session["cashier_id"] != cashier["id"] or session["status"] != "ACTIVE":
                    continue
                session["status"] = "PENDING_COUNT"
                session["forced_close"] = True
                session["pos_cash_sales_cents"] = None
                session["pos_card_sales_cents"] = None
                session["pos_paid_out_cents"] = None
                db.touch(session)
    domain.freeze_store_safes(store["id"])
    domain.reevaluate_journal(journal)
    return response.object_response(serializers.variance_case(case))


@bp.post("/cash-ops/variance-cases/<case_id>/close")
@endpoint(["LossPreventionInvestigator"])
def close_case(case_id):
    data = validation.body()
    disposition = validation.req_enum(data, "disposition", DISPOSITIONS)
    if "closing_note" in data and data["closing_note"] is not None:
        closing_note = validation.req_str(data, "closing_note")
    else:
        closing_note = None
    case = domain.get_case(case_id)
    if case["status"] != "ESCALATED":
        raise err(
            "ERR_VARIANCE_CASE_INVALID_STATE",
            "only an ESCALATED case may be closed with a disposition",
        )
    journal = domain.get_journal(case["sales_journal_id"])
    store = domain.get_store(journal["store_id"])
    remainder = domain.unexplained_cents(case)
    case["disposition"] = disposition
    case["closing_note"] = closing_note
    if disposition == "SUBSTANTIATED":
        case["status"] = "CLOSED_SUBSTANTIATED"
        safe = domain.earliest_safe(store["id"])
        if safe is not None:
            domain.write_txn(
                safe_id=safe["id"],
                txn_type="VARIANCE_ADJUSTMENT",
                declared_amount_cents=remainder,
                actor_user_id=user_id(),
                memo="variance adjustment for case %s" % case["id"],
            )
    else:
        case["status"] = "CLOSED_UNSUBSTANTIATED"
    db.touch(case)
    if disposition == "UNSUBSTANTIATED" and case["cashier_id"] is not None:
        cashier = db.cashiers.get(case["cashier_id"])
        if cashier is not None:
            still_escalated = [
                other
                for other in db.variance_cases.values()
                if other["cashier_id"] == cashier["id"] and other["status"] == "ESCALATED"
            ]
            if not still_escalated:
                rolling = cashier["rolling_absolute_variance_cents"]
                if rolling >= store["rolling_variance_threshold_cents"]:
                    cashier["till_eligibility"] = "RESTRICTED"
                else:
                    cashier["till_eligibility"] = "ELIGIBLE"
                db.touch(cashier)
    if not domain.store_has_escalated_case(store["id"]):
        domain.restore_store_safes(store["id"])
    domain.reevaluate_journal(journal)
    return response.object_response(serializers.variance_case(case))


@bp.get("/cash-ops/variance-cases/<case_id>")
@endpoint(CASE_READ_ROLES)
def read_case(case_id):
    case = domain.get_case(case_id)
    return response.object_response(serializers.variance_case(case))


@bp.get("/cash-ops/variance-cases")
@endpoint(CASE_READ_ROLES)
def list_cases():
    return list_collection(
        db.variance_cases,
        [
            ("sales_journal_id", "sales_journal_id"),
            ("cashier_id", "cashier_id"),
            ("deposit_id", "deposit_id"),
            ("case_type", "case_type"),
            ("status", "status"),
        ],
        serializers.variance_case,
    )
