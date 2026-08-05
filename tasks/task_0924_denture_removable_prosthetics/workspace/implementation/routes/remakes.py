"""Remake authorisation: the ceiling's mutate-then-reject rung and the
six-link remake cascade (PRD 2.12, 3.7)."""
from flask import Blueprint

import domain
import envelope
import guards
import nav
import pconst
import projections
from errors import ApiError
from store import db, now, sorted_rows, touch
from util import ZERO, q2

bp = Blueprint("remakes", __name__)

REMAKE_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
]


@bp.post("/prosthetics/remake-requests")
@guards.endpoint(["Prosthodontist"])
def create_remake_request(ctx):
    arch = guards.fk_row(ctx, "case_arch_id")
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.body_fks(ctx, ["case_arch_id", "warranty_claim_id"])  # rung 6
    guards.require_string(ctx, "case_arch_id")  # rung 7
    reason_code = guards.require_enum_value(ctx, "reason_code")
    guards.check_enum("reason_code", reason_code)  # rung 8

    # rung 11 -- pre-empts the rung 22 mutate-then-reject on every attempt
    # after the first, and mints no second FINAL_DENIED row.
    if arch["remake_eligibility"] != "ELIGIBLE":
        raise ApiError("ERR_REMAKE_FINAL_DENIED")

    cited = guards.fk_row(ctx, "warranty_claim_id")
    charge_basis = "CHARGEABLE"
    if cited is not None and cited["claim_status"] in ("CLINIC_FAULT", "LAB_FAULT"):
        charge_basis = "NO_CHARGE"

    attempt = domain.arch_remake_request_count(arch) + 1

    # rung 22 -- MUTATE-THEN-REJECT.  The denied row and the arch's flipped
    # eligibility are created, committed, and only then does the call raise.
    if attempt - 1 >= pconst.REMAKE_CEILING_PER_ARCH:
        row = db.create(
            "remake_requests",
            {
                "case_arch_id": arch["id"],
                "warranty_claim_id": cited["id"] if cited else None,
                "reason_code": reason_code,
                "requested_by_user_id": ctx.user_id,
                "approved_by_user_id": None,
                "authorization_status": "FINAL_DENIED",
                "attempt_number": attempt,
                "charge_basis": charge_basis,
                "decided_at": now(),
            },
        )
        arch["remake_eligibility"] = "FINAL_DENIED"
        touch(arch)
        raise ApiError("ERR_REMAKE_LIMIT_EXCEEDED")

    row = db.create(
        "remake_requests",
        {
            "case_arch_id": arch["id"],
            "warranty_claim_id": cited["id"] if cited else None,
            "reason_code": reason_code,
            "requested_by_user_id": ctx.user_id,
            "approved_by_user_id": None,
            "authorization_status": "PENDING_APPROVAL",
            "attempt_number": attempt,
            "charge_basis": charge_basis,
            "decided_at": None,
        },
    )
    return envelope.created(projections.remake_request(row))


@bp.get("/prosthetics/remake-requests/<remake_request_id>")
@guards.endpoint(REMAKE_READ)
def get_remake_request(ctx, remake_request_id):
    row = guards.path_row("remake_request_id", remake_request_id)
    return envelope.ok(projections.remake_request(row))


@bp.get("/prosthetics/remake-requests")
@guards.endpoint(REMAKE_READ)
def list_remake_requests(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.remake_requests.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_arch_id", "case_arch_id", None),
            ("warranty_claim_id", "warranty_claim_id", None),
            (
                "authorization_status",
                "authorization_status",
                guards.status_members("authorization_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.remake_request(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/remake-requests/<remake_request_id>/approve")
@guards.endpoint(["ClinicalDirector"])
def approve_remake(ctx, remake_request_id):
    request_row = guards.path_row("remake_request_id", remake_request_id)  # rung 4
    # Outside the global write gate: the creation was already gated.
    guards.terminal_guard(request_row, "authorization_status")  # rung 10
    guards.from_state_guard(  # rung 12
        request_row, "authorization_status", ("PENDING_APPROVAL",)
    )

    arch = nav.arch_of(request_row)
    cited = db.warranty_claims.get(request_row["warranty_claim_id"])

    # rung 13 -- cross-entity state
    if request_row["warranty_claim_id"] is not None:
        if cited is None or cited["claim_status"] not in ("CLINIC_FAULT", "LAB_FAULT"):
            raise ApiError("ERR_CROSS_ENTITY_STATE")
    if arch["arch_status"] not in ("DELIVERED", "MILESTONE_PENDING"):
        raise ApiError("ERR_CROSS_ENTITY_STATE")

    # rung 14 -- segregation of duties, enforced on identity not on role
    if ctx.user_id == request_row["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # --- remake cascade link 1 ---------------------------------------------
    request_row["authorization_status"] = "APPROVED"
    request_row["approved_by_user_id"] = ctx.user_id
    request_row["decided_at"] = now()
    touch(request_row)

    # --- link 2: the arch enters REMAKE_PENDING ----------------------------
    arch["arch_status"] = "REMAKE_PENDING"
    touch(arch)

    # --- link 3: void the latest appliance, cancel the arch's open lab work -
    latest = nav.latest_prosthesis_of_arch(arch)
    if latest is not None:
        domain.void_superseded_prosthesis(latest)
    for lab_case in nav.labcases_of_arch(arch):
        if lab_case["lab_status"] in pconst.CANCELLABLE_LAB_STATUSES:
            domain.cancel_lab_case(lab_case)

    # --- link 4: move laboratory credit ------------------------------------
    applied = ZERO
    if request_row["charge_basis"] == "NO_CHARGE" and cited is not None:
        if cited["claim_status"] == "LAB_FAULT":
            lab_case = db.labcases.get(cited["attributed_lab_case_id"])
            lab = db.labs.get(lab_case["dental_lab_id"]) if lab_case else None
            if lab is not None:
                available = lab["credit_available_balance"]
                credit = cited["lab_credit_amount"]
                applied = credit if credit < available else available
                if applied > ZERO:
                    lab["credit_applied_total"] = q2(
                        lab["credit_applied_total"] + applied
                    )
                    lab["credit_available_balance"] = q2(
                        lab["credit_issued_total"] - lab["credit_applied_total"]
                    )

    # --- link 5 and link 6: re-strike the case's live plan ------------------
    case = nav.case_of_arch(arch)
    if applied > ZERO and case is not None:
        for plan in nav.plans_of_case(case):
            if plan["plan_status"] in ("ACTIVE", "DELINQUENT"):
                domain.apply_lab_credit_to_plan(plan, applied)
                break

    # --- the case-level cycle ----------------------------------------------
    if case is not None and case["case_status"] == "DELIVERED":
        case["case_status"] = "IN_FABRICATION"
        case["delivered_at"] = None
        touch(case)

    return envelope.ok(projections.remake_request(request_row))


@bp.post("/prosthetics/remake-requests/<remake_request_id>/deny")
@guards.endpoint(["ClinicalDirector"])
def deny_remake(ctx, remake_request_id):
    request_row = guards.path_row("remake_request_id", remake_request_id)  # rung 4
    if "denial_reason" in ctx.body and ctx.body["denial_reason"] is not None:
        if not isinstance(ctx.body["denial_reason"], str):  # rung 7
            guards.bad_request("Field 'denial_reason' must be a string.")
    guards.terminal_guard(request_row, "authorization_status")  # rung 10
    guards.from_state_guard(  # rung 12
        request_row, "authorization_status", ("PENDING_APPROVAL",)
    )
    if ctx.user_id == request_row["requested_by_user_id"]:  # rung 14
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    request_row["authorization_status"] = "DENIED"
    request_row["approved_by_user_id"] = ctx.user_id
    request_row["decided_at"] = now()
    touch(request_row)
    return envelope.ok(projections.remake_request(request_row))
