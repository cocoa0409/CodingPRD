"""Quality claims, laboratory analyses and remediation (PRD 3.7, 3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc, cascade
from validation import (
    apply_page,
    body,
    pagination,
    q_enum,
    q_str,
    rnd,
    v_decimal,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("claims", __name__)

CLAIM_READERS = ("Surveyor", "CreditController", "CustomerRep", "LabTechnician")
ANALYSIS_READERS = ("LabTechnician", "Surveyor", "CustomerRep")
DEFECTS = ("SULFUR_EXCEEDANCE", "WATER_CONTENT", "DENSITY_DEVIATION")
CLAIM_STATUSES = (
    "SUBMITTED",
    "UNDER_ANALYSIS",
    "REMEDIATION_PROPOSED",
    "REMEDIATION_ACCEPTED",
    "REJECTED",
)
CLAIM_DECISIONS = ("PROPOSE", "REJECT")
REMEDIATION_TYPES = ("PRICE_ALLOWANCE", "DEBUNKER")
VERDICTS = ("ON_SPEC", "OFF_SPEC")


def _note_customer_id(note):
    order = store.delivery_orders.get(note["delivery_order_id"])
    nomination = calc.order_nomination(order) if order else None
    return nomination["customer_id"] if nomination else None


# --------------------------------------------------------------------------- #
# quality claims
# --------------------------------------------------------------------------- #


@bp.post("/quality-claims")
@roles("CustomerRep")
def create_claim():
    data = body()
    note = body_ref(data, "bdn_id", store.bunker_delivery_notes, "ERR_BDN_NOT_FOUND")
    if note is not None and g.user_id != _note_customer_id(note):
        raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")

    v_string(data, "bdn_id", min_len=1)
    claimed_defect = v_enum(data, "claimed_defect", DEFECTS)
    affected_quantity_mt = v_decimal(data, "affected_quantity_mt", 3, positive=True)
    replacement_price_usd_per_mt = v_decimal(
        data, "replacement_price_usd_per_mt", 2, required=False, positive=True
    )
    if note is None:
        raise ApiError("ERR_BDN_NOT_FOUND")

    if db.now() > note["created_at"] + timedelta(days=calc.CLAIM_WINDOW_DAYS):
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    if affected_quantity_mt > note["delivered_quantity_mt"]:
        raise ApiError("ERR_AFFECTED_QUANTITY_EXCEEDS_BASIS")

    claim = db.new_record()
    claim.update(
        {
            "bdn_id": note["id"],
            "customer_id": _note_customer_id(note),
            "claimed_defect": claimed_defect,
            "affected_quantity_mt": affected_quantity_mt,
            "quantity_basis_mt": note["delivered_quantity_mt"],
            "replacement_price_usd_per_mt": replacement_price_usd_per_mt,
            "status": "SUBMITTED",
            "analysis_round": 0,
            "remediation_type": None,
            "credit_usd": Decimal("0.00"),
            "proposed_by_user_id": None,
            "accepted_by_user_id": None,
        }
    )
    store.quality_claims[claim["id"]] = claim
    return success(serializers.quality_claim(claim), 201)


@bp.get("/quality-claims/<rec_id>")
@roles(*CLAIM_READERS)
def get_claim(rec_id):
    claim = path_ref(store.quality_claims, rec_id, "ERR_CLAIM_NOT_FOUND")
    return success(serializers.quality_claim(claim))


@bp.get("/quality-claims")
@roles(*CLAIM_READERS)
def list_claims():
    customer_id = q_str("customer_id")
    if g.role == "CustomerRep":
        if customer_id is not None and customer_id != g.user_id:
            raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")
        customer_id = g.user_id
    bdn_id = q_str("bdn_id")
    status = q_enum("status", CLAIM_STATUSES)
    limit, offset = pagination()

    def match(row):
        if bdn_id is not None and row["bdn_id"] != bdn_id:
            return False
        if customer_id is not None and row["customer_id"] != customer_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.sorted_rows(store.quality_claims, match)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.quality_claim(r) for r in page], limit, offset, len(rows))


@bp.post("/quality-claims/<rec_id>/decision")
@roles("Surveyor")
def claim_decision(rec_id):
    claim = path_ref(store.quality_claims, rec_id, "ERR_CLAIM_NOT_FOUND")
    data = body()
    decision = v_enum(data, "decision", CLAIM_DECISIONS)
    remediation_type = v_enum(data, "remediation_type", REMEDIATION_TYPES, required=False)
    if decision == "PROPOSE":
        if remediation_type is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field 'remediation_type' is required to propose."
            )
        if remediation_type == "DEBUNKER" and claim["replacement_price_usd_per_mt"] is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "The DEBUNKER branch requires replacement_price_usd_per_mt on the claim.",
            )

    order = calc.claim_order(claim)
    invoice = calc.non_void_invoice_of_order(order["id"]) if order else None
    if invoice is None:
        raise ApiError("ERR_INVOICE_NOT_ISSUED")
    if claim["status"] != "UNDER_ANALYSIS":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    analysis = calc.governing_analysis(claim["id"])
    verdict = analysis["verdict"] if analysis else None
    if decision == "PROPOSE":
        if verdict != "OFF_SPEC":
            raise ApiError("ERR_NO_OFFSPEC_FINDING")
        claim["status"] = "REMEDIATION_PROPOSED"
        claim["remediation_type"] = remediation_type
        claim["proposed_by_user_id"] = g.user_id
        claim["credit_usd"] = calc.remediation_credit(
            claim, analysis, invoice, remediation_type
        )
    else:
        if verdict != "ON_SPEC":
            raise ApiError("ERR_NO_OFFSPEC_FINDING")
        claim["status"] = "REJECTED"

    touch(claim)
    return success(serializers.quality_claim(claim))


@bp.post("/quality-claims/<rec_id>/request-retest")
@roles("CustomerRep")
def request_retest(rec_id):
    claim = path_ref(store.quality_claims, rec_id, "ERR_CLAIM_NOT_FOUND")
    if g.user_id != claim["customer_id"]:
        raise ApiError("ERR_CUSTOMER_SCOPE_VIOLATION")
    if claim["status"] != "REMEDIATION_PROPOSED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if claim["analysis_round"] >= calc.MAX_ANALYSIS_ROUNDS:
        raise ApiError("ERR_RETEST_LIMIT_REACHED")

    claim["status"] = "UNDER_ANALYSIS"
    claim["remediation_type"] = None
    claim["credit_usd"] = Decimal("0.00")
    claim["proposed_by_user_id"] = None
    touch(claim)
    return success(serializers.quality_claim(claim))


@bp.post("/quality-claims/<rec_id>/accept-remediation")
@roles("CreditController")
def accept_remediation(rec_id):
    claim = path_ref(store.quality_claims, rec_id, "ERR_CLAIM_NOT_FOUND")
    order = calc.claim_order(claim)
    invoice = calc.non_void_invoice_of_order(order["id"]) if order else None
    if invoice is None or invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_ISSUED")
    if claim["status"] != "REMEDIATION_PROPOSED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if claim["proposed_by_user_id"] is not None and claim["proposed_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["status"] = "REMEDIATION_ACCEPTED"
    claim["accepted_by_user_id"] = g.user_id
    touch(claim)

    invoice["claim_credit_usd"] = rnd(invoice["claim_credit_usd"] + claim["credit_usd"], 2)
    invoice["final_amount_usd"] = rnd(
        invoice["provisional_amount_usd"] - invoice["claim_credit_usd"], 2
    )
    invoice["status"] = "CREDIT_APPLIED"
    touch(invoice)

    cascade.recompute_customer_exposure(store.customers.get(invoice["customer_id"]))
    return success(serializers.quality_claim(claim))


# --------------------------------------------------------------------------- #
# laboratory analyses
# --------------------------------------------------------------------------- #


@bp.post("/lab-analyses")
@roles("LabTechnician")
def create_analysis():
    data = body()
    claim = body_ref(data, "claim_id", store.quality_claims, "ERR_CLAIM_NOT_FOUND")
    retest_of = body_ref(
        data, "retest_of_analysis_id", store.lab_analyses, "ERR_LAB_ANALYSIS_NOT_FOUND"
    )

    v_string(data, "claim_id", min_len=1)
    lab_ref = v_string(data, "lab_ref", min_len=1)
    measured_sulfur_pct = v_decimal(data, "measured_sulfur_pct", 3, positive=True)
    expected_claim_version = v_int(data, "expected_claim_version")
    retest_of_analysis_id = v_string(data, "retest_of_analysis_id", required=False)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")

    if expected_claim_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")

    if retest_of_analysis_id is None:
        if claim["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_CLAIM_STATE")
    else:
        if claim["status"] != "UNDER_ANALYSIS":
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        if retest_of["claim_id"] != claim["id"] or retest_of["round_index"] != 1:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "retest_of_analysis_id must reference round 1 of this claim.",
            )

    note = store.bunker_delivery_notes.get(claim["bdn_id"])
    if note is None or calc.sample_custody_status(note) != "RELEASED_TO_LAB":
        raise ApiError("ERR_SAMPLE_NOT_RELEASED")
    if claim["analysis_round"] >= calc.MAX_ANALYSIS_ROUNDS:
        raise ApiError("ERR_RETEST_LIMIT_REACHED")

    order = store.delivery_orders.get(note["delivery_order_id"])
    nomination = calc.order_nomination(order) if order else None
    port = store.ports.get(nomination["port_id"]) if nomination else None
    grade = store.fuel_grades.get(nomination["grade_id"]) if nomination else None
    verdict, exceedance = calc.offspec_verdict(measured_sulfur_pct, port, nomination, grade)

    round_index = claim["analysis_round"] + 1
    analysis = db.new_record()
    analysis.update(
        {
            "claim_id": claim["id"],
            "retest_of_analysis_id": retest_of_analysis_id,
            "lab_ref": lab_ref,
            "measured_sulfur_pct": measured_sulfur_pct,
            "verdict": verdict,
            "exceedance_pct": exceedance,
            "round_index": round_index,
            "analyzed_by_user_id": g.user_id,
        }
    )
    store.lab_analyses[analysis["id"]] = analysis

    claim["analysis_round"] = round_index
    claim["status"] = "UNDER_ANALYSIS"
    touch(claim)
    return success(serializers.lab_analysis(analysis), 201)


@bp.get("/lab-analyses/<rec_id>")
@roles(*ANALYSIS_READERS)
def get_analysis(rec_id):
    analysis = path_ref(store.lab_analyses, rec_id, "ERR_LAB_ANALYSIS_NOT_FOUND")
    return success(serializers.lab_analysis(analysis))


@bp.get("/lab-analyses")
@roles(*ANALYSIS_READERS)
def list_analyses():
    claim_id = q_str("claim_id")
    retest_of_analysis_id = q_str("retest_of_analysis_id")
    verdict = q_enum("verdict", VERDICTS)
    limit, offset = pagination()

    def match(row):
        if claim_id is not None and row["claim_id"] != claim_id:
            return False
        if retest_of_analysis_id is not None and (
            row["retest_of_analysis_id"] != retest_of_analysis_id
        ):
            return False
        if verdict is not None and row["verdict"] != verdict:
            return False
        return True

    rows = db.sorted_rows(store.lab_analyses, match)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.lab_analysis(r) for r in page], limit, offset, len(rows))
