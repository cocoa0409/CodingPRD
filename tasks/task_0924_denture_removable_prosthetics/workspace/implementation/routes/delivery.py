"""Delivery, the two clocks that disagree, and the recall cycle (PRD 3.6)."""
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
from util import ZERO, add_days

bp = Blueprint("delivery", __name__)

PROSTHESIS_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
]


@bp.post("/prosthetics/prostheses")
@guards.endpoint(["Prosthodontist"])
def deliver(ctx):
    arch = guards.fk_row(ctx, "case_arch_id")
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.body_fks(ctx, ["case_arch_id", "superseded_prosthesis_id"])  # rung 6
    guards.require_string(ctx, "case_arch_id")  # rung 7

    if arch["arch_status"] != "READY_FOR_DELIVERY":  # rung 13
        raise ApiError("ERR_CROSS_ENTITY_STATE")

    superseded = guards.fk_row(ctx, "superseded_prosthesis_id")
    case = nav.case_of_arch(arch)
    clock = now()
    prosthesis_type = case["prosthesis_type"]

    # --- delivery cascade link 1: the appliance itself ---------------------
    frequency_anchor = (
        superseded["frequency_anchor_at"] if superseded is not None else clock
    )
    prosthesis = db.create(
        "prostheses",
        {
            "case_arch_id": arch["id"],
            "superseded_prosthesis_id": superseded["id"] if superseded else None,
            "prosthesis_type": prosthesis_type,
            "is_remake": superseded is not None,
            "delivered_at": clock,
            "warranty_status": "IN_WARRANTY",
            "warranty_expires_at": calc.warranty_expires_at(clock),
            "frequency_anchor_at": frequency_anchor,
            "replacement_eligible_date": calc.replacement_eligible_date(
                frequency_anchor
            ),
            "recall_status": "RECALL_SCHEDULED",
            "recall_due_at": calc.recall_due_at(clock, prosthesis_type, 0),
            "recall_cycle_count": 0,
            "adjustments_used": 0,
            "adjustment_window_ends_at": add_days(
                clock, pconst.ADJUSTMENT_ALLOWANCE_WINDOW_DAYS
            ),
            "in_patient_possession": True,
            "mandatory_reline_due_at": (
                add_days(clock, pconst.IMMEDIATE_DENTURE_RELINE_DUE_DAYS)
                if prosthesis_type == "IMMEDIATE_DENTURE"
                else None
            ),
        },
    )

    # --- link 2: the arch --------------------------------------------------
    arch["arch_status"] = "DELIVERED"
    touch(arch)

    # --- link 3: bubble the case up ---------------------------------------
    siblings = nav.arches_of_case(case)
    settled = all(
        a["arch_status"] in ("DELIVERED", "ARCH_ABANDONED") for a in siblings
    )
    any_delivered = any(a["arch_status"] == "DELIVERED" for a in siblings)
    if case["case_status"] == "IN_FABRICATION" and settled and any_delivered:
        case["case_status"] = "DELIVERED"
        case["delivered_at"] = clock
        domain.recompute_case_totals(case)
        touch(case)

        # --- link 4: auto-create one claim against the PRIMARY coverage ----
        primary = nav.coverage_at_rank(case["patient_id"], "PRIMARY")
        if primary is not None:
            domain.create_claim_row(case, primary["id"])

    # --- a remake delivery closes out the appliance it replaces -----------
    if superseded is not None:
        domain.void_superseded_prosthesis(superseded)

    return envelope.created(projections.prosthesis(prosthesis))


@bp.get("/prosthetics/prostheses/<prosthesis_id>")
@guards.endpoint(PROSTHESIS_READ + ["Patient"])
def get_prosthesis(ctx, prosthesis_id):
    row = guards.path_row("prosthesis_id", prosthesis_id)
    domain.refresh_prosthesis(row)
    return envelope.ok(projections.prosthesis(row))


@bp.get("/prosthetics/prostheses")
@guards.endpoint(PROSTHESIS_READ)
def list_prostheses(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.prostheses.values())
    for row in rows:
        domain.refresh_prosthesis(row)
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_arch_id", "case_arch_id", None),
            ("superseded_prosthesis_id", "superseded_prosthesis_id", None),
            (
                "warranty_status",
                "warranty_status",
                guards.status_members("warranty_status"),
            ),
            (
                "recall_status",
                "recall_status",
                guards.status_members("recall_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.prosthesis(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/prostheses/<prosthesis_id>/recall-complete")
@guards.endpoint(["Prosthodontist"])
def recall_complete(ctx, prosthesis_id):
    prosthesis = guards.path_row("prosthesis_id", prosthesis_id)  # rung 4
    # Outside the global write gate: recall is a safety follow-up on an
    # appliance the patient already has.
    outcome = guards.require_enum_value(ctx, "recall_outcome")  # rung 7
    guards.check_enum("recall_outcome", outcome)  # rung 8

    domain.refresh_prosthesis(prosthesis)
    # rung 10 is axis-scoped: this operation drives the recall axis only.
    guards.terminal_guard(prosthesis, "recall_status")
    guards.from_state_guard(  # rung 12
        prosthesis,
        "recall_status",
        ("RECALL_SCHEDULED", "RECALL_DUE", "RECALL_OVERDUE"),
    )

    if outcome == "NO_ACTION":
        prosthesis["recall_cycle_count"] = prosthesis["recall_cycle_count"] + 1
        prosthesis["recall_due_at"] = calc.recall_due_at(
            prosthesis["delivered_at"],
            prosthesis["prosthesis_type"],
            prosthesis["recall_cycle_count"],
        )
        prosthesis["recall_status"] = "RECALL_SCHEDULED"
        touch(prosthesis)
    elif outcome == "RELINE_INDICATED":
        prosthesis["recall_status"] = "RECALL_COMPLETED"
        touch(prosthesis)
        # Minted by the system, so it carries no laboratory routing of its own
        # and stays in REQUESTED.
        domain.create_service_row(prosthesis, "HARD_RELINE_LAB", "REQUESTED")
    else:  # REMAKE_EVALUATION
        prosthesis["recall_status"] = "RECALL_COMPLETED"
        touch(prosthesis)
        arch = nav.arch_of(prosthesis)
        if arch is not None:
            domain.create_remake_request(
                arch, "RECALL_EVALUATION", ctx.user_id, None
            )

    return envelope.ok(projections.prosthesis(prosthesis))
