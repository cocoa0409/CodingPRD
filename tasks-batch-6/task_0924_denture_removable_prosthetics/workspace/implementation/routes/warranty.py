"""Warranty claims: the four-way fault fan-out and its re-entrant clinical
review leg (PRD 3.7)."""
from flask import Blueprint

import calc
import domain
import envelope
import guards
import nav
import pconst
import projections
from errors import ApiError
from store import db, now, sorted_rows, touch
from util import ZERO, q2

bp = Blueprint("warranty", __name__)

CLAIM_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
]


@bp.post("/prosthetics/warranty-claims")
@guards.endpoint(["Prosthodontist", "FrontOffice"])
def create_warranty_claim(ctx):
    # Outside the global write gate: fault adjudication decides who owes.
    guards.body_fks(  # rung 6
        ctx,
        ["prosthesis_id", "post_delivery_service_id", "attributed_lab_case_id"],
    )
    guards.require_string(ctx, "prosthesis_id", "reported_issue")  # rung 7
    prosthesis = db.prostheses[ctx.body["prosthesis_id"]]

    row = db.create(
        "warranty_claims",
        {
            "prosthesis_id": prosthesis["id"],
            "post_delivery_service_id": ctx.body.get("post_delivery_service_id"),
            "attributed_lab_case_id": ctx.body.get("attributed_lab_case_id"),
            "reported_issue": ctx.body["reported_issue"],
            "claim_status": "SUBMITTED",
            "fault_verdict": None,
            "lab_credit_amount": ZERO,
            "patient_charge_amount": ZERO,
            "warranty_consumed": False,
            "adjudicated_at": None,
        },
    )
    return envelope.created(projections.warranty_claim(row))


@bp.get("/prosthetics/warranty-claims/<warranty_claim_id>")
@guards.endpoint(CLAIM_READ + ["Patient"])
def get_warranty_claim(ctx, warranty_claim_id):
    row = guards.path_row("warranty_claim_id", warranty_claim_id)
    return envelope.ok(projections.warranty_claim(row))


@bp.get("/prosthetics/warranty-claims")
@guards.endpoint(CLAIM_READ)
def list_warranty_claims(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.warranty_claims.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("prosthesis_id", "prosthesis_id", None),
            ("post_delivery_service_id", "post_delivery_service_id", None),
            ("attributed_lab_case_id", "attributed_lab_case_id", None),
            ("claim_status", "claim_status", guards.status_members("claim_status")),
        ],
    )
    return envelope.listing(
        [projections.warranty_claim(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


def _apply_verdict(claim, verdict, prosthesis):
    """The side-effect set shared by adjudication and clinical review."""
    claim["fault_verdict"] = verdict
    claim["adjudicated_at"] = now()

    if verdict == "INDETERMINATE":
        claim["claim_status"] = "CLINICAL_REVIEW"
        touch(claim)
        return

    if verdict == "CLINIC_FAULT":
        claim["claim_status"] = "CLINIC_FAULT"
        claim["warranty_consumed"] = True
        claim["lab_credit_amount"] = ZERO
        claim["patient_charge_amount"] = ZERO
        if prosthesis["warranty_status"] == "IN_WARRANTY":
            prosthesis["warranty_status"] = "WARRANTY_CONSUMED"
            touch(prosthesis)
    elif verdict == "LAB_FAULT":
        claim["claim_status"] = "LAB_FAULT"
        claim["warranty_consumed"] = True
        claim["patient_charge_amount"] = ZERO
        lab_case = db.labcases.get(claim["attributed_lab_case_id"])
        credit = calc.lab_remake_credit("LAB_FAULT", lab_case)
        claim["lab_credit_amount"] = credit
        if lab_case is not None and credit > ZERO:
            lab = db.labs.get(lab_case["dental_lab_id"])
            if lab is not None:
                lab["credit_issued_total"] = q2(lab["credit_issued_total"] + credit)
                lab["credit_available_balance"] = q2(
                    lab["credit_issued_total"] - lab["credit_applied_total"]
                )
        if prosthesis["warranty_status"] == "IN_WARRANTY":
            prosthesis["warranty_status"] = "WARRANTY_CONSUMED"
            touch(prosthesis)
    else:  # PATIENT_FAULT -- the warranty is deliberately NOT consumed
        claim["claim_status"] = "PATIENT_FAULT"
        claim["warranty_consumed"] = False
        claim["lab_credit_amount"] = ZERO
        claim["patient_charge_amount"] = pconst.FEE_REPAIR

    touch(claim)
    case = nav.case_of_prosthesis(prosthesis)
    if case is not None:
        domain.recompute_case_totals(case)


def _verdict_guards(ctx, claim, field, origins):
    """Rungs 7, 8, 10, 12, 23 and 24 for both adjudication endpoints."""
    verdict = guards.require_enum_value(ctx, field)  # rung 7

    # FRICTION POINT (PRD 3.7): a LAB_FAULT verdict recorded with no
    # attributed_lab_case_id is treated as a MISSING REQUIRED INPUT and refused
    # with ERR_VALIDATION at rung 7, rather than being admitted with a 0.00
    # CLINIC_BORNE credit.
    if verdict == "LAB_FAULT" and not claim["attributed_lab_case_id"]:
        guards.bad_request(
            "A LAB_FAULT verdict requires the claim to carry an attributed_lab_case_id."
        )

    guards.check_enum(field, verdict)  # rung 8
    guards.terminal_guard(claim, "claim_status")  # rung 10
    guards.from_state_guard(claim, "claim_status", origins)  # rung 12

    prosthesis = db.prostheses[claim["prosthesis_id"]]
    domain.refresh_prosthesis(prosthesis)

    # rung 23 -- WARRANTY_EXPIRED deliberately PASSES so rung 24 stays reachable
    if prosthesis["warranty_status"] in ("WARRANTY_CONSUMED", "WARRANTY_VOIDED"):
        raise ApiError("ERR_WARRANTY_CONSUMED")

    # rung 24 -- not applied to PATIENT_FAULT or INDETERMINATE
    if verdict in ("CLINIC_FAULT", "LAB_FAULT"):
        if now() > prosthesis["warranty_expires_at"]:
            raise ApiError("ERR_WARRANTY_EXPIRED")

    return verdict, prosthesis


@bp.post("/prosthetics/warranty-claims/<warranty_claim_id>/adjudicate")
@guards.endpoint(["ClinicalDirector"])
def adjudicate(ctx, warranty_claim_id):
    claim = guards.path_row("warranty_claim_id", warranty_claim_id)  # rung 4
    verdict, prosthesis = _verdict_guards(
        ctx, claim, "fault_verdict", ("SUBMITTED",)
    )
    _apply_verdict(claim, verdict, prosthesis)
    return envelope.ok(projections.warranty_claim(claim))


@bp.post("/prosthetics/warranty-claims/<warranty_claim_id>/clinical-review")
@guards.endpoint(["ClinicalDirector"])
def clinical_review(ctx, warranty_claim_id):
    claim = guards.path_row("warranty_claim_id", warranty_claim_id)  # rung 4
    verdict, prosthesis = _verdict_guards(
        ctx, claim, "resolved_verdict", ("CLINICAL_REVIEW",)
    )
    _apply_verdict(claim, verdict, prosthesis)
    return envelope.ok(projections.warranty_claim(claim))
