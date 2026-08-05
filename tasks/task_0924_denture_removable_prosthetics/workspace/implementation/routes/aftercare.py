"""Post-delivery services, warranty fault adjudication and remake
authorisation (PRD 3.7)."""
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

bp = Blueprint("aftercare", __name__)

SERVICE_READ = [
    "Prosthodontist",
    "FrontOffice",
    "ClinicalDirector",
    "PlatformAdmin",
]


def _warranty_backed(service):
    for claim in db.warranty_claims.values():
        if claim.get("post_delivery_service_id") != service["id"]:
            continue
        if claim["claim_status"] in ("CLINIC_FAULT", "LAB_FAULT"):
            return True
    return False


# ===========================================================================
# PostDeliveryService
# ===========================================================================
@bp.post("/prosthetics/services")
@guards.endpoint(["Prosthodontist", "FrontOffice"])
def create_service(ctx):
    prosthesis = guards.fk_row(ctx, "prosthesis_id")

    # rung 5 -- the emergency-repair carve-out needs BOTH conditions.
    raw_type = ctx.body.get("service_type")
    raw_emergency = ctx.body.get("is_emergency_repair")
    emergency_carve_out = raw_type == "REPAIR" and raw_emergency is True
    if not emergency_carve_out:
        guards.write_gate(
            nav.patient_of_prosthesis(prosthesis) if prosthesis else None
        )

    guards.body_fks(ctx, ["prosthesis_id", "dental_lab_id"])  # rung 6

    # rung 7
    guards.require_string(ctx, "prosthesis_id")
    service_type = guards.require_enum_value(ctx, "service_type")
    guards.require_int(ctx, "expected_prosthesis_version")
    is_emergency_repair = guards.optional_bool(ctx, "is_emergency_repair", False)
    lab = None
    bench_line = None
    if service_type in pconst.LAB_SERVICE_TYPES:
        guards.require_string(ctx, "dental_lab_id")
        lab = db.labs[ctx.body["dental_lab_id"]]
        bench_line = guards.require_int(ctx, "bench_line", 1, lab["bench_line_count"])

    guards.check_enum("service_type", service_type)  # rung 8
    guards.occ(ctx, "expected_prosthesis_version", prosthesis)  # rung 9

    # rung 25 -- service-type eligibility for the prosthesis type
    ptype = prosthesis["prosthesis_type"]
    if service_type in pconst.PARTIAL_ONLY_SERVICE_TYPES:
        if ptype not in pconst.PARTIAL_PROSTHESIS_TYPES:
            raise ApiError("ERR_SERVICE_NOT_ELIGIBLE")
    if service_type == "REBASE" and ptype in pconst.REBASE_INELIGIBLE_PROSTHESIS_TYPES:
        raise ApiError("ERR_SERVICE_NOT_ELIGIBLE")

    # rung 26 -- per-service-type frequency limit
    completed = [
        r
        for r in nav.services_of_prosthesis(prosthesis)
        if r["service_type"] == service_type
        and r["service_status"] == "COMPLETED"
        and r["completed_at"] is not None
    ]
    if not calc.service_frequency_eligible(service_type, completed, now()):
        raise ApiError("ERR_SERVICE_FREQUENCY_LIMIT")

    # --- supersede an older un-completed service of the same type ----------
    for older in nav.services_of_prosthesis(prosthesis):
        if older["service_type"] != service_type:
            continue
        if older["service_status"] not in ("REQUESTED", "IN_CHAIR", "AT_LAB"):
            continue
        was_at_lab = older["service_status"] == "AT_LAB"
        older["service_status"] = "VOIDED"
        older["voided_at"] = now()
        touch(older)
        if was_at_lab and older["lab_case_id"]:
            linked = db.labcases.get(older["lab_case_id"])
            if linked is not None:
                domain.cancel_lab_case(linked)
            prosthesis["in_patient_possession"] = True

    # --- the chairside / laboratory fork -----------------------------------
    if service_type in pconst.CHAIRSIDE_SERVICE_TYPES:
        service = domain.create_service_row(
            prosthesis, service_type, "IN_CHAIR", None, is_emergency_repair
        )
    else:
        arch = nav.arch_of(prosthesis)
        lab_case = db.create(
            "labcases",
            {
                "case_arch_id": arch["id"],
                "dental_lab_id": lab["id"],
                "bench_line": bench_line,
                "turnaround_class": "STANDARD",
                "unit_count": 1,
                "lab_invoice_amount": pconst.LAB_DEFAULT_INVOICE_AMOUNT,
                "purpose": pconst.LAB_SERVICE_PURPOSE[service_type],
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
        service = domain.create_service_row(
            prosthesis, service_type, "AT_LAB", lab_case["id"], is_emergency_repair
        )
        prosthesis["in_patient_possession"] = False

    touch(prosthesis)
    return envelope.created(projections.service(service))


@bp.get("/prosthetics/services/<service_id>")
@guards.endpoint(SERVICE_READ + ["Patient"])
def get_service(ctx, service_id):
    row = guards.path_row("service_id", service_id)
    return envelope.ok(projections.service(row))


@bp.get("/prosthetics/services")
@guards.endpoint(SERVICE_READ)
def list_services(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.services.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("prosthesis_id", "prosthesis_id", None),
            ("lab_case_id", "lab_case_id", None),
            ("service_type", "service_type", pconst.ENUMS["service_type"]),
            (
                "service_status",
                "service_status",
                guards.status_members("service_status"),
            ),
        ],
    )
    return envelope.listing(
        [projections.service(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


@bp.post("/prosthetics/services/<service_id>/complete")
@guards.endpoint(["Prosthodontist"])
def complete_service(ctx, service_id):
    service = guards.path_row("service_id", service_id)  # rung 4
    # Outside the global write gate.
    guards.terminal_guard(service, "service_status")  # rung 10
    guards.from_state_guard(service, "service_status", ("IN_CHAIR", "AT_LAB"))  # rung 12

    if service["service_status"] == "AT_LAB":  # rung 13
        linked = db.labcases.get(service["lab_case_id"]) if service["lab_case_id"] else None
        if linked is None or linked["lab_status"] != "QC_PASSED":
            raise ApiError("ERR_CROSS_ENTITY_STATE")

    prosthesis = db.prostheses[service["prosthesis_id"]]
    was_at_lab = service["service_status"] == "AT_LAB"

    basis, amount = calc.post_delivery_service_charge(
        service, prosthesis, now(), _warranty_backed(service)
    )
    service["charge_basis"] = basis
    service["charge_amount"] = q2(amount)
    service["service_status"] = "COMPLETED"
    service["completed_at"] = now()
    touch(service)

    if service["service_type"] == "ADJUSTMENT" and basis == "INCLUDED":
        prosthesis["adjustments_used"] = prosthesis["adjustments_used"] + 1
    if was_at_lab:
        prosthesis["in_patient_possession"] = True

    case = nav.case_of_prosthesis(prosthesis)
    if case is not None:
        domain.recompute_case_totals(case)
    return envelope.ok(projections.service(service))


@bp.post("/prosthetics/services/<service_id>/void")
@guards.endpoint(["FrontOffice", "Prosthodontist"])
def void_service(ctx, service_id):
    service = guards.path_row("service_id", service_id)  # rung 4
    # Outside the global write gate.
    guards.terminal_guard(service, "service_status")  # rung 10
    guards.from_state_guard(  # rung 12
        service,
        "service_status",
        ("REQUESTED", "IN_CHAIR", "AT_LAB", "COMPLETED"),
    )

    prosthesis = db.prostheses[service["prosthesis_id"]]
    origin = service["service_status"]

    if origin == "AT_LAB":
        linked = db.labcases.get(service["lab_case_id"]) if service["lab_case_id"] else None
        if linked is not None:
            domain.cancel_lab_case(linked)
        prosthesis["in_patient_possession"] = True
    elif origin == "COMPLETED":
        # COMPENSATING ACTION of the adjustment-allowance conservation.
        if service["service_type"] == "ADJUSTMENT" and service["charge_basis"] == "INCLUDED":
            prosthesis["adjustments_used"] = max(
                0, prosthesis["adjustments_used"] - 1
            )
        service["charge_amount"] = ZERO

    service["service_status"] = "VOIDED"
    service["voided_at"] = now()
    touch(service)

    case = nav.case_of_prosthesis(prosthesis)
    if case is not None:
        domain.recompute_case_totals(case)
    return envelope.ok(projections.service(service))
