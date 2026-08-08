"""Laboratory coordination: bench lines, the shelf-life clock and the QC
reject-and-resend cycle (PRD 3.5)."""
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
from util import ZERO, add_hours, q2

bp = Blueprint("labwork", __name__)

LABCASE_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
    "LabTechnician",
]


@bp.post("/prosthetics/lab-cases")
@guards.endpoint(["Prosthodontist", "FrontOffice"])
def create_lab_case(ctx):
    arch = guards.fk_row(ctx, "case_arch_id")
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.body_fks(ctx, ["case_arch_id", "dental_lab_id"])  # rung 6

    # rung 7
    guards.require_string(ctx, "case_arch_id", "dental_lab_id")
    lab = db.labs[ctx.body["dental_lab_id"]]
    bench_line = guards.require_int(ctx, "bench_line", 1, lab["bench_line_count"])
    turnaround_class = guards.require_enum_value(ctx, "turnaround_class")
    unit_count = guards.require_int(
        ctx, "unit_count", pconst.UNIT_COUNT_MIN, pconst.UNIT_COUNT_MAX
    )
    purpose = guards.require_enum_value(ctx, "purpose")
    guards.require_int(ctx, "expected_case_arch_version")
    invoice_amount = guards.optional_number(
        ctx, "lab_invoice_amount", pconst.LAB_DEFAULT_INVOICE_AMOUNT
    )

    # rung 8
    guards.check_enum("turnaround_class", turnaround_class)
    guards.check_enum("purpose", purpose)

    guards.occ(ctx, "expected_case_arch_version", arch)  # rung 9

    if arch["arch_status"] != "LAB_FABRICATION":  # rung 13
        raise ApiError("ERR_CROSS_ENTITY_STATE")

    # supersede: a newer draft displaces an older draft on the same arch
    for existing in nav.labcases_of_arch(arch):
        if existing["lab_status"] == "DRAFT":
            domain.cancel_lab_case(existing)
    touch(arch)

    row = db.create(
        "labcases",
        {
            "case_arch_id": arch["id"],
            "dental_lab_id": lab["id"],
            "bench_line": bench_line,
            "turnaround_class": turnaround_class,
            "unit_count": unit_count,
            "lab_invoice_amount": q2(invoice_amount),
            "purpose": purpose,
            "lab_status": "DRAFT",
            "dispatched_at": None,
            "promised_due_at": None,
            "shelf_life_expires_at": None,
            "rush_fee_amount": ZERO,
            "received_at": None,
            "resend_count": 0,
            "qc_result": None,
            "expired_at": None,
        },
    )
    return envelope.created(projections.labcase(row))


@bp.get("/prosthetics/lab-cases/<lab_case_id>")
@guards.endpoint(LABCASE_READ)
def get_lab_case(ctx, lab_case_id):
    row = guards.path_row("lab_case_id", lab_case_id)
    return envelope.ok(projections.labcase(row))


@bp.get("/prosthetics/lab-cases")
@guards.endpoint(LABCASE_READ)
def list_lab_cases(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.labcases.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("case_arch_id", "case_arch_id", None),
            ("dental_lab_id", "dental_lab_id", None),
            ("lab_status", "lab_status", guards.status_members("lab_status")),
        ],
    )
    return envelope.listing(
        [projections.labcase(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/lab-cases/<lab_case_id>/dispatch")
@guards.endpoint(["FrontOffice", "Prosthodontist"])
def dispatch_lab_case(ctx, lab_case_id):
    lab_case = guards.path_row("lab_case_id", lab_case_id)  # rung 4
    arch = nav.arch_of(lab_case)
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.terminal_guard(lab_case, "lab_status")  # rung 10
    guards.from_state_guard(lab_case, "lab_status", ("DRAFT",))  # rung 12

    clock = now()

    # rung 20 -- arch possession, a CLOSED interval with a 24 hour buffer
    for other in nav.labcases_of_arch(arch):
        if other["id"] == lab_case["id"]:
            continue
        if other["lab_status"] in pconst.OCCUPYING_LAB_STATUSES:
            raise ApiError("ERR_ARCH_OCCUPIED")
    if arch["last_lab_received_at"] is not None:
        boundary = add_hours(
            arch["last_lab_received_at"], pconst.ARCH_TURNAROUND_BUFFER_HOURS
        )
        if not clock > boundary:
            raise ApiError("ERR_ARCH_OCCUPIED")

    # rung 21 -- bench-line overlap, HALF-OPEN intervals with no buffer
    lab = db.labs[lab_case["dental_lab_id"]]
    promised = calc.lab_promised_due_at(clock, lab, lab_case["turnaround_class"])
    for other in db.labcases.values():
        if other["id"] == lab_case["id"]:
            continue
        if other["dental_lab_id"] != lab_case["dental_lab_id"]:
            continue
        if other["bench_line"] != lab_case["bench_line"]:
            continue
        if other["lab_status"] not in pconst.OCCUPYING_LAB_STATUSES:
            continue
        start, end = other["dispatched_at"], other["promised_due_at"]
        if start is None or end is None:
            continue
        if clock < end and start < promised:
            raise ApiError("ERR_LAB_SLOT_CONFLICT")

    lab_case["lab_status"] = "DISPATCHED"
    lab_case["dispatched_at"] = clock
    lab_case["promised_due_at"] = promised
    lab_case["shelf_life_expires_at"] = calc.lab_shelf_life_expires_at(clock)
    lab_case["rush_fee_amount"] = calc.lab_rush_fee(
        lab_case["turnaround_class"], lab_case["unit_count"]
    )
    touch(lab_case)

    domain.recompute_case_totals(nav.case_of_arch(arch))
    return envelope.ok(projections.labcase(lab_case))


@bp.post("/prosthetics/lab-cases/<lab_case_id>/receive")
@guards.endpoint(["LabTechnician"])
def receive_lab_case(ctx, lab_case_id):
    existing = guards.path_row_or_none("lab_case_id", lab_case_id)
    guards.owner_lab_guard(ctx, existing["dental_lab_id"] if existing else None)  # rung 3
    lab_case = guards.path_row("lab_case_id", lab_case_id)  # rung 4
    # Outside the global write gate: work already at the laboratory must come
    # back regardless of the balance.
    guards.terminal_guard(lab_case, "lab_status")  # rung 10
    guards.from_state_guard(lab_case, "lab_status", ("DISPATCHED", "RESENT"))  # rung 12

    clock = now()
    # rung 15 -- MUTATE-THEN-REJECT.  The bookkeeping write is committed and
    # only then does the call raise; the second attempt is pre-empted by rung 10
    # and reports ERR_TERMINAL_STATE instead.
    if lab_case["shelf_life_expires_at"] is not None and (
        clock > lab_case["shelf_life_expires_at"]
    ):
        lab_case["lab_status"] = "EXPIRED"
        lab_case["expired_at"] = clock
        touch(lab_case)
        raise ApiError("ERR_LAB_CASE_EXPIRED")

    lab_case["lab_status"] = "RETURNED"
    lab_case["received_at"] = clock
    touch(lab_case)

    arch = nav.arch_of(lab_case)
    if arch is not None:
        arch["last_lab_received_at"] = clock
    return envelope.ok(projections.labcase(lab_case))


@bp.post("/prosthetics/lab-cases/<lab_case_id>/qc")
@guards.endpoint(["Prosthodontist"])
def qc_lab_case(ctx, lab_case_id):
    lab_case = guards.path_row("lab_case_id", lab_case_id)  # rung 4
    # Outside the global write gate.
    qc_result = guards.require_enum_value(ctx, "qc_result")  # rung 7
    guards.check_enum("qc_result", qc_result)  # rung 8
    guards.terminal_guard(lab_case, "lab_status")  # rung 10
    guards.from_state_guard(lab_case, "lab_status", ("RETURNED",))  # rung 12

    lab_case["qc_result"] = qc_result
    if qc_result == "PASS":
        lab_case["lab_status"] = "QC_PASSED"
        touch(lab_case)
        if lab_case["purpose"] in ("FABRICATION", "REMAKE"):
            arch = nav.arch_of(lab_case)
            if arch is not None and arch["arch_status"] == "LAB_FABRICATION":
                arch["arch_status"] = "READY_FOR_DELIVERY"
                touch(arch)
        # For RELINE / REBASE / REPAIR / ADDITION the pass simply makes the
        # linked PostDeliveryService completable (checked at rung 13 there).
    else:
        lab_case["lab_status"] = "QC_FAILED"
        touch(lab_case)
    return envelope.ok(projections.labcase(lab_case))


@bp.post("/prosthetics/lab-cases/<lab_case_id>/resend")
@guards.endpoint(["FrontOffice", "Prosthodontist"])
def resend_lab_case(ctx, lab_case_id):
    lab_case = guards.path_row("lab_case_id", lab_case_id)  # rung 4
    arch = nav.arch_of(lab_case)
    guards.write_gate(nav.patient_of_arch(arch) if arch else None)  # rung 5
    guards.terminal_guard(lab_case, "lab_status")  # rung 10
    guards.from_state_guard(lab_case, "lab_status", ("QC_FAILED",))  # rung 12
    if lab_case["resend_count"] >= pconst.LAB_QC_RESEND_CEILING:  # rung 19
        raise ApiError("ERR_QC_RESEND_LIMIT_EXCEEDED")
    # The shelf-life clock keeps running from the ORIGINAL dispatch; on this
    # path the refusal carries no accompanying write.
    if lab_case["shelf_life_expires_at"] is not None and (
        now() > lab_case["shelf_life_expires_at"]
    ):
        raise ApiError("ERR_LAB_CASE_EXPIRED")

    lab_case["lab_status"] = "RESENT"
    lab_case["resend_count"] = lab_case["resend_count"] + 1
    lab_case["received_at"] = None
    touch(lab_case)
    return envelope.ok(projections.labcase(lab_case))
