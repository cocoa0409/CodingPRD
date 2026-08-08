"""Case intake, arch planning, the exam close-out and fabrication start
(PRD 3.2)."""
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

bp = Blueprint("cases", __name__)

CASE_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
]


# ===========================================================================
# ProsthesisCase
# ===========================================================================
@bp.post("/prosthetics/cases")
@guards.endpoint(["Prosthodontist", "FrontOffice"])
def create_case(ctx):
    patient = guards.fk_row(ctx, "patient_id")
    guards.write_gate(patient)  # rung 5
    guards.body_fks(ctx, ["patient_id"])  # rung 6
    guards.require_string(ctx, "patient_id")  # rung 7
    prosthesis_type = guards.require_enum_value(ctx, "prosthesis_type")
    guards.check_enum("prosthesis_type", prosthesis_type)  # rung 8

    row = db.create(
        "cases",
        {
            "patient_id": ctx.body["patient_id"],
            "prosthesis_type": prosthesis_type,
            "case_status": "INTAKE",
            "fee_schedule_total": ZERO,
            "predetermination_required": False,
            "billed_amount": ZERO,
            "insurance_paid_amount": ZERO,
            "prompt_pay_discount_amount": ZERO,
            "patient_responsibility_amount": ZERO,
            "fabrication_started_at": None,
            "delivered_at": None,
        },
    )
    return envelope.created(projections.case(row))


@bp.get("/prosthetics/cases/<case_id>")
@guards.endpoint(CASE_READ + ["Patient"])
def get_case(ctx, case_id):
    row = guards.path_row("case_id", case_id)
    return envelope.ok(projections.case(row))


@bp.get("/prosthetics/cases")
@guards.endpoint(CASE_READ)
def list_cases(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.cases.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("patient_id", "patient_id", None),
            ("case_status", "case_status", guards.status_members("case_status")),
        ],
    )
    return envelope.listing(
        [projections.case(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/cases/<case_id>/complete-exam")
@guards.endpoint(["Prosthodontist"])
def complete_exam(ctx, case_id):
    case = guards.path_row("case_id", case_id)  # rung 4
    # Outside the global write gate: closing out an existing case reduces
    # exposure rather than adding to it.
    arches = nav.arches_of_case(case)
    if not arches:  # rung 7
        guards.bad_request("The case has no arch units to price.")
    guards.terminal_guard(case, "case_status")  # rung 10
    guards.from_state_guard(case, "case_status", ("INTAKE",))  # rung 12

    fee = calc.arch_fee(case["prosthesis_type"])
    total = ZERO
    for arch in arches:
        if arch["arch_status"] == "ARCH_ABANDONED":
            continue
        arch["fee_schedule_amount"] = fee
        total = total + fee
    case["fee_schedule_total"] = q2(total)
    case["predetermination_required"] = (
        case["fee_schedule_total"] >= pconst.PREDETERMINATION_REQUIRED_MIN_FEE
    )
    case["case_status"] = "EXAM_COMPLETE"
    domain.recompute_case_totals(case)
    touch(case)
    return envelope.ok(projections.case(case))


@bp.post("/prosthetics/cases/<case_id>/cancel")
@guards.endpoint(["Prosthodontist"])
def cancel_case(ctx, case_id):
    case = guards.path_row("case_id", case_id)  # rung 4
    if "cancellation_reason" in ctx.body and ctx.body["cancellation_reason"] is not None:
        if not isinstance(ctx.body["cancellation_reason"], str):  # rung 7
            guards.bad_request("Field 'cancellation_reason' must be a string.")
    guards.terminal_guard(case, "case_status")  # rung 10
    guards.from_state_guard(  # rung 12
        case, "case_status", ("INTAKE", "EXAM_COMPLETE", "IN_FABRICATION")
    )

    case["case_status"] = "CANCELLED"
    for arch in nav.arches_of_case(case):
        if arch["arch_status"] in ("ARCH_CLOSED", "ARCH_ABANDONED"):
            continue
        arch["arch_status"] = "ARCH_ABANDONED"
        touch(arch)
        for lab_case in nav.labcases_of_arch(arch):
            domain.cancel_lab_case(lab_case)
        for tryin in nav.tryins_of_arch(arch):
            if tryin["approval_status"] in ("PENDING_APPROVAL", "ADJUST_REQUESTED"):
                tryin["approval_status"] = "CANCELLED"
                touch(tryin)
    touch(case)
    return envelope.ok(projections.case(case))


# ===========================================================================
# CaseArch
# ===========================================================================
@bp.post("/prosthetics/case-arches")
@guards.endpoint(["Prosthodontist"])
def create_arch(ctx):
    case = guards.fk_row(ctx, "case_id")
    guards.write_gate(nav.patient_of_case(case) if case else None)  # rung 5
    guards.body_fks(ctx, ["case_id"])  # rung 6
    guards.require_string(ctx, "case_id")  # rung 7
    arch_position = guards.require_enum_value(ctx, "arch_position")
    for existing in nav.arches_of_case(case):  # rung 7 uniqueness pair
        if existing["arch_position"] == arch_position:
            guards.bad_request(
                "An arch already exists on this case at that position."
            )
    guards.check_enum("arch_position", arch_position)  # rung 8

    row = db.create(
        "arches",
        {
            "case_id": case["id"],
            "arch_position": arch_position,
            "arch_status": "PLANNED",
            "required_milestones": list(
                pconst.MILESTONES_BY_TYPE[case["prosthesis_type"]]
            ),
            "retake_count": 0,
            "remake_eligibility": "ELIGIBLE",
            "fee_schedule_amount": ZERO,
            "last_lab_received_at": None,
        },
    )
    return envelope.created(projections.arch(row))


@bp.get("/prosthetics/case-arches/<case_arch_id>")
@guards.endpoint(CASE_READ)
def get_arch(ctx, case_arch_id):
    row = guards.path_row("case_arch_id", case_arch_id)
    return envelope.ok(projections.arch(row))


@bp.get("/prosthetics/case-arches")
@guards.endpoint(CASE_READ)
def list_arches(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.arches.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_id", "case_id", None),
            ("arch_status", "arch_status", guards.status_members("arch_status")),
        ],
    )
    return envelope.listing(
        [projections.arch(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/case-arches/<case_arch_id>/start-fabrication")
@guards.endpoint(["Prosthodontist"])
def start_fabrication(ctx, case_arch_id):
    arch = guards.path_row("case_arch_id", case_arch_id)  # rung 4
    case = nav.case_of_arch(arch)
    guards.write_gate(nav.patient_of_case(case))  # rung 5
    guards.terminal_guard(arch, "arch_status")  # rung 10
    guards.from_state_guard(  # rung 12
        arch, "arch_status", ("PLANNED", "REMAKE_PENDING")
    )

    from_planned = arch["arch_status"] == "PLANNED"
    # rung 13 -- cross-entity state on the parent case
    required_case_state = "EXAM_COMPLETE" if from_planned else "IN_FABRICATION"
    if case["case_status"] != required_case_state:
        raise ApiError("ERR_CROSS_ENTITY_STATE")

    # rung 30 -- the predetermination gate, declared on the PLANNED leg
    if from_planned and case["predetermination_required"]:
        if domain.live_predetermination(case) is None:
            raise ApiError("ERR_PREDETERMINATION_REQUIRED")

    arch["arch_status"] = "IMPRESSION_PENDING"
    arch["retake_count"] = 0
    if from_planned:
        arch["required_milestones"] = list(
            pconst.MILESTONES_BY_TYPE[case["prosthesis_type"]]
        )
    touch(arch)

    if from_planned and case["case_status"] == "EXAM_COMPLETE":
        case["case_status"] = "IN_FABRICATION"
        case["fabrication_started_at"] = now()
        touch(case)

    return envelope.ok(projections.arch(arch))
