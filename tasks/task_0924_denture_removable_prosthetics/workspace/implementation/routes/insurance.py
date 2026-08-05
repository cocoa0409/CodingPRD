"""Insurance: predetermination, claims and the two-stage coordination of
benefits (PRD 3.8)."""
from flask import Blueprint

import calc
import domain
import envelope
import guards
import nav
import pconst
import projections
from errors import ApiError
from store import bump, db, now, sorted_rows, touch
from util import ZERO, add_days, q2

bp = Blueprint("insurance", __name__)

PREDET_READ = ["FrontOffice", "Prosthodontist", "PlatformAdmin"]
CLAIM_READ = ["FrontOffice", "Prosthodontist", "PlatformAdmin"]


# ===========================================================================
# Predetermination
# ===========================================================================
@bp.post("/prosthetics/predeterminations")
@guards.endpoint(["FrontOffice"])
def create_predetermination(ctx):
    # Outside the global write gate: insurance work is part of the remedy path.
    guards.body_fks(ctx, ["case_id", "coverage_id"])  # rung 6
    guards.require_string(ctx, "case_id", "coverage_id")  # rung 7
    case = db.cases[ctx.body["case_id"]]

    row = db.create(
        "predeterminations",
        {
            "case_id": case["id"],
            "coverage_id": ctx.body["coverage_id"],
            "requested_amount": case["fee_schedule_total"],
            "determination_status": "SUBMITTED",
            "alternate_benefit_type": None,
            "allowed_amount": ZERO,
            "estimated_plan_payment": ZERO,
            "estimated_patient_responsibility": ZERO,
            "determined_at": None,
            "expires_at": None,
        },
    )
    return envelope.created(projections.predetermination(row))


@bp.get("/prosthetics/predeterminations/<predetermination_id>")
@guards.endpoint(PREDET_READ)
def get_predetermination(ctx, predetermination_id):
    row = guards.path_row("predetermination_id", predetermination_id)
    domain.refresh_predetermination(row)
    return envelope.ok(projections.predetermination(row))


@bp.get("/prosthetics/predeterminations")
@guards.endpoint(PREDET_READ)
def list_predeterminations(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.predeterminations.values())
    for row in rows:
        domain.refresh_predetermination(row)
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_id", "case_id", None),
            ("coverage_id", "coverage_id", None),
            (
                "determination_status",
                "determination_status",
                guards.status_members("determination_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.predetermination(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/predeterminations/<predetermination_id>/determine")
@guards.endpoint(["FrontOffice"])
def determine(ctx, predetermination_id):
    row = guards.path_row("predetermination_id", predetermination_id)  # rung 4
    determination = guards.require_enum_value(ctx, "determination")  # rung 7
    guards.check_enum("determination", determination)  # rung 8
    domain.refresh_predetermination(row)
    guards.terminal_guard(row, "determination_status")  # rung 10
    guards.from_state_guard(row, "determination_status", ("SUBMITTED",))  # rung 12

    case = db.cases[row["case_id"]]
    coverage = db.coverages.get(row["coverage_id"])
    clock = now()

    if determination == "DENIED":
        row["determination_status"] = "DENIED"
        row["allowed_amount"] = ZERO
        row["estimated_plan_payment"] = ZERO
        row["estimated_patient_responsibility"] = q2(row["requested_amount"])
        row["determined_at"] = clock
        row["expires_at"] = None
        touch(row)
        return envelope.ok(projections.predetermination(row))

    if determination == "ALTERNATE_BENEFIT":
        target = pconst.ALTERNATE_BENEFIT_MAP.get(case["prosthesis_type"])
        if coverage is None or not coverage["alternate_benefit_enabled"] or not target:
            guards.bad_request(
                "An alternate benefit is not available for this coverage or "
                "prosthesis type."
            )
        arch_count = len(nav.non_abandoned_arches(case))
        row["alternate_benefit_type"] = target
        row["allowed_amount"] = q2(pconst.FEE_BY_TYPE[target] * arch_count)
        row["determination_status"] = "ALTERNATE_BENEFIT"
    else:  # APPROVED
        row["alternate_benefit_type"] = None
        row["allowed_amount"] = q2(row["requested_amount"])
        row["determination_status"] = "APPROVED"

    plan_payment, patient_share = calc.predetermination_estimate(
        row["allowed_amount"], coverage, row["requested_amount"]
    )
    row["estimated_plan_payment"] = plan_payment
    row["estimated_patient_responsibility"] = patient_share
    row["determined_at"] = clock
    row["expires_at"] = add_days(clock, pconst.PREDETERMINATION_VALIDITY_DAYS)
    touch(row)
    return envelope.ok(projections.predetermination(row))


# ===========================================================================
# Claim
# ===========================================================================
@bp.post("/prosthetics/claims")
@guards.endpoint(["FrontOffice"])
def create_claim(ctx):
    # Outside the global write gate.
    guards.body_fks(ctx, ["case_id", "coverage_id"])  # rung 6
    guards.require_string(ctx, "case_id", "coverage_id")  # rung 7
    case = db.cases[ctx.body["case_id"]]
    row = domain.create_claim_row(case, ctx.body["coverage_id"])
    return envelope.created(projections.claim(row))


@bp.get("/prosthetics/claims/<claim_id>")
@guards.endpoint(CLAIM_READ + ["Patient"])
def get_claim(ctx, claim_id):
    row = guards.path_row("claim_id", claim_id)
    return envelope.ok(projections.claim(row))


@bp.get("/prosthetics/claims")
@guards.endpoint(CLAIM_READ)
def list_claims(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.claims.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_id", "case_id", None),
            ("coverage_id", "coverage_id", None),
            ("predetermination_id", "predetermination_id", None),
            (
                "adjudication_status",
                "adjudication_status",
                guards.status_members("adjudication_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.claim(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


def _waiting_period_ok(coverage, clock):
    return clock >= add_days(coverage["effective_date"], coverage["waiting_period_days"])


@bp.post("/prosthetics/claims/<claim_id>/submit")
@guards.endpoint(["FrontOffice"])
def submit_claim(ctx, claim_id):
    claim = guards.path_row("claim_id", claim_id)  # rung 4
    # Outside the global write gate.
    guards.terminal_guard(claim, "adjudication_status")  # rung 10
    guards.from_state_guard(  # rung 12
        claim, "adjudication_status", ("DRAFT", "PRIMARY_PAID")
    )

    case = db.cases[claim["case_id"]]
    clock = now()

    if claim["adjudication_status"] == "DRAFT":
        primary = db.coverages.get(claim["coverage_id"])
        if primary is None:
            guards.bad_request("The claim names no coverage.")

        if not _waiting_period_ok(primary, clock):  # rung 28
            raise ApiError("ERR_WAITING_PERIOD")

        # rung 29 -- replacement frequency, over the patient's appliances that
        # belong to a case OTHER than this claim's case.
        prior = [
            p
            for p in nav.prostheses_of_patient(case["patient_id"])
            if nav.case_of_prosthesis(p)["id"] != case["id"]
        ]
        if prior:
            latest = max(p["replacement_eligible_date"] for p in prior)
            if clock < latest:
                raise ApiError("ERR_FREQUENCY_LIMIT")

        if case["predetermination_required"]:  # rung 30
            if domain.live_predetermination(case) is None:
                raise ApiError("ERR_PREDETERMINATION_REQUIRED")

        if calc.coverage_benefit_remaining(primary) <= ZERO:  # rung 31
            raise ApiError("ERR_ANNUAL_MAX_EXHAUSTED")

        resolved = None
        for row in nav.predeterminations_of_case(case):
            domain.refresh_predetermination(row)
        for row in nav.predeterminations_of_case(case):
            if row["determination_status"] in ("APPROVED", "ALTERNATE_BENEFIT"):
                if resolved is None or row["created_at"] >= resolved["created_at"]:
                    resolved = row

        claim["billed_amount"] = case["fee_schedule_total"]
        claim["predetermination_id"] = resolved["id"] if resolved else None
        claim["allowed_amount"] = (
            resolved["allowed_amount"] if resolved else claim["billed_amount"]
        )
        claim["submission_target"] = "PRIMARY"
        claim["submitted_at"] = clock
        claim["adjudication_status"] = "SUBMITTED_PRIMARY"
        touch(claim)
        return envelope.ok(projections.claim(claim))

    # --- second stage: PRIMARY_PAID -> SUBMITTED_SECONDARY -----------------
    secondary = nav.coverage_at_rank(case["patient_id"], "SECONDARY")
    if secondary is None:
        guards.bad_request("The patient holds no secondary coverage.")
    if not _waiting_period_ok(secondary, clock):  # rung 28, re-run
        raise ApiError("ERR_WAITING_PERIOD")

    claim["submission_target"] = "SECONDARY"
    claim["cob_convention_applied"] = secondary["cob_convention"]
    claim["submitted_at"] = clock
    claim["adjudication_status"] = "SUBMITTED_SECONDARY"
    touch(claim)
    return envelope.ok(projections.claim(claim))


@bp.post("/prosthetics/claims/<claim_id>/post-payment")
@guards.endpoint(["FrontOffice"])
def post_payment(ctx, claim_id):
    claim = guards.path_row("claim_id", claim_id)  # rung 4
    outcome = guards.require_enum_value(ctx, "adjudication_outcome")  # rung 7
    guards.check_enum("adjudication_outcome", outcome)  # rung 8
    guards.terminal_guard(claim, "adjudication_status")  # rung 10
    guards.from_state_guard(  # rung 12
        claim, "adjudication_status", ("SUBMITTED_PRIMARY", "SUBMITTED_SECONDARY")
    )

    case = db.cases[claim["case_id"]]
    stage = claim["adjudication_status"]
    clock = now()

    if stage == "SUBMITTED_PRIMARY":
        if outcome == "DENIED":
            claim["adjudication_status"] = "DENIED"
            claim["patient_responsibility_amount"] = q2(claim["billed_amount"])
            claim["adjudicated_at"] = clock
            touch(claim)
            domain.recompute_case_totals(case)
            return envelope.ok(projections.claim(claim))

        primary = db.coverages[claim["coverage_id"]]
        paid = calc.claim_primary_payment(claim, primary)
        claim["primary_paid_amount"] = paid
        claim["plan_paid_amount"] = paid
        responsibility = q2(claim["billed_amount"] - paid)
        claim["patient_responsibility_amount"] = (
            responsibility if responsibility > ZERO else ZERO
        )
        primary["benefit_used_ytd"] = q2(primary["benefit_used_ytd"] + paid)
        claim["adjudication_status"] = "PRIMARY_PAID"
        claim["adjudicated_at"] = clock
        touch(claim)
        domain.recompute_case_totals(case)

        if nav.coverage_at_rank(case["patient_id"], "SECONDARY") is None:
            claim["adjudication_status"] = "CLOSED"
            bump(claim)
            domain.recompute_case_totals(case)
            domain.maybe_close_case(case)
        return envelope.ok(projections.claim(claim))

    # --- SUBMITTED_SECONDARY ----------------------------------------------
    if outcome == "DENIED":
        claim["adjudication_status"] = "DENIED"
        claim["secondary_paid_amount"] = ZERO
        claim["plan_paid_amount"] = claim["primary_paid_amount"]
        claim["adjudicated_at"] = clock
        touch(claim)
        domain.recompute_case_totals(case)
        return envelope.ok(projections.claim(claim))

    secondary = nav.coverage_at_rank(case["patient_id"], "SECONDARY")
    if secondary is None:
        guards.bad_request("The patient holds no secondary coverage.")
    convention = claim["cob_convention_applied"] or secondary["cob_convention"]
    paid = calc.claim_secondary_cob_payment(claim, secondary, convention)
    claim["secondary_paid_amount"] = paid
    claim["plan_paid_amount"] = q2(claim["primary_paid_amount"] + paid)
    responsibility = q2(claim["billed_amount"] - claim["plan_paid_amount"])
    claim["patient_responsibility_amount"] = (
        responsibility if responsibility > ZERO else ZERO
    )
    secondary["benefit_used_ytd"] = q2(secondary["benefit_used_ytd"] + paid)
    claim["adjudication_status"] = "SECONDARY_PAID"
    claim["adjudicated_at"] = clock
    touch(claim)
    domain.recompute_case_totals(case)

    claim["adjudication_status"] = "CLOSED"
    bump(claim)
    domain.recompute_case_totals(case)
    domain.maybe_close_case(case)
    return envelope.ok(projections.claim(claim))


@bp.post("/prosthetics/claims/<claim_id>/reverse")
@guards.endpoint(["FrontOffice"])
def reverse_claim(ctx, claim_id):
    claim = guards.path_row("claim_id", claim_id)  # rung 4
    if "reversal_reason" in ctx.body and ctx.body["reversal_reason"] is not None:
        if not isinstance(ctx.body["reversal_reason"], str):  # rung 7
            guards.bad_request("Field 'reversal_reason' must be a string.")
    guards.terminal_guard(claim, "adjudication_status")  # rung 10
    guards.from_state_guard(claim, "adjudication_status", ("CLOSED",))  # rung 12

    case = db.cases[claim["case_id"]]
    primary = db.coverages.get(claim["coverage_id"])
    if primary is not None and claim["primary_paid_amount"] > ZERO:
        primary["benefit_used_ytd"] = q2(
            primary["benefit_used_ytd"] - claim["primary_paid_amount"]
        )
    secondary = nav.coverage_at_rank(case["patient_id"], "SECONDARY")
    if secondary is not None and claim["secondary_paid_amount"] > ZERO:
        secondary["benefit_used_ytd"] = q2(
            secondary["benefit_used_ytd"] - claim["secondary_paid_amount"]
        )

    claim["primary_paid_amount"] = ZERO
    claim["secondary_paid_amount"] = ZERO
    claim["plan_paid_amount"] = ZERO
    claim["adjudication_status"] = "REVERSED"
    claim["reversed_at"] = now()
    touch(claim)
    domain.recompute_case_totals(case)
    domain.maybe_close_case(case)
    return envelope.ok(projections.claim(claim))
