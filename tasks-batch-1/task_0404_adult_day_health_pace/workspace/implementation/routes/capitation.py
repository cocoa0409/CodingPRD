"""Capitation payment lifecycle: create / finalize (OCC) / reconcile / void.
PRD §2.8, §3.7."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c
from services import calculations as calc
from services.participant_helpers import loc_certified_and_valid

bp = Blueprint("capitation", __name__)

PRORATION_MODES = {"FULL_MONTH", "DAILY"}


def payment_view(p):
    return dict(p)


@bp.post("/pace/capitation-payments")
@require_roles("BillingSpecialist")
def create_payment():
    body = c.get_body()
    participant_id = c.as_str(body, "participant_id")
    service_month = c.parse_datetime(body, "service_month")
    proration_mode = c.as_enum(body, "proration_mode", PRORATION_MODES,
                               required=False, default="FULL_MONTH")
    c.find_or_404(db.participants, participant_id)

    sm_iso = c.iso_out(service_month)
    sm_ym = (service_month.year, service_month.month)
    # service_month unique per participant (priority 21)
    for p in db.capitation_payments.values():
        if p["participant_id"] == participant_id:
            existing = c.parse_iso(p["service_month"])
            if (existing.year, existing.month) == sm_ym:
                raise err("ERR_DUPLICATE_PERIOD", "Duplicate service_month for participant")

    p = c.base_fields()
    p.update({
        "participant_id": participant_id,
        "service_month": sm_iso,
        "medicaid_share_cents": 0,
        "medicare_share_cents": 0,
        "supplement_cents": 0,
        "total_billed_cents": 0,
        "proration_mode": proration_mode,
        "covered_days": 0,
        "reconciled_cents": 0,
        "recoup_cents": 0,
        "status": "DRAFT",
    })
    db.capitation_payments[p["id"]] = p
    return success(payment_view(p), status=201)


@bp.get("/pace/capitation-payments/<payment_id>")
@require_roles("ProgramAdmin", "BillingSpecialist", "IntakeCoordinator")
def get_payment(payment_id):
    p = c.find_or_404(db.capitation_payments, payment_id)
    return success(payment_view(p))


@bp.get("/pace/capitation-payments")
@require_roles("ProgramAdmin", "BillingSpecialist", "IntakeCoordinator")
def list_payments():
    limit, offset = c.get_pagination()
    items = list(db.capitation_payments.values())
    for key in ("participant_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([payment_view(p) for p in page], limit, offset, total)


def _enrollment_for_participant(participant_id):
    """Return the participant's Enrollment row (open or closed) used for coverage
    and proration. There is at most one enrollment per participant lifecycle here."""
    found = None
    for e in db.enrollments.values():
        if e["participant_id"] == participant_id:
            found = e
    return found


@bp.post("/pace/capitation-payments/<payment_id>/finalize")
@require_roles("BillingSpecialist")
def finalize_payment(payment_id):
    p = c.find_or_404(db.capitation_payments, payment_id)
    body = c.get_body()
    expected_version = c.as_int(body, "expected_participant_version")
    participant = db.participants.get(p["participant_id"])
    program = db.programs.get(participant["program_id"]) if participant else None

    # State (priority 5)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Payment not DRAFT")
    # Program OPEN (priority 6)
    if program["status"] != "OPEN":
        raise err("ERR_PROGRAM_SUSPENDED", "Program is suspended")

    sm_dt = c.parse_iso(p["service_month"])
    enrollment = _enrollment_for_participant(participant["id"])
    eff_dt = None
    dis_dt = None
    if enrollment:
        eff_dt = c.parse_iso(enrollment["enrollment_effective_date"])
        if enrollment.get("disenrollment_effective_date"):
            dis_dt = c.parse_iso(enrollment["disenrollment_effective_date"])

    covered_days, dim = (0, 0)
    if eff_dt is not None:
        covered_days, dim = calc.covered_days_in_month(sm_dt, eff_dt, dis_dt)

    # Coverage of >= 1 calendar day (priority 24)
    if covered_days < 1:
        raise err("ERR_NO_COVERAGE_FOR_MONTH", "No enrollment coverage for month")

    # LOC certified, first day of service_month <= expires_on (priority 8)
    if not loc_certified_and_valid(participant, sm_dt):
        raise err("ERR_LOC_NOT_CERTIFIED", "LOC not certified/expired for service month")

    # OCC (priority 26): expected_participant_version vs Participant.version
    if expected_version != participant["version"]:
        raise err("ERR_STALE_VERSION", "Participant version mismatch")

    shares = calc.capitation_amount(program, participant, p["proration_mode"],
                                    covered_days, dim)
    p["covered_days"] = covered_days
    p["medicare_share_cents"] = shares["medicare_share_cents"]
    p["medicaid_share_cents"] = shares["medicaid_share_cents"]
    p["supplement_cents"] = shares["supplement_cents"]
    p["total_billed_cents"] = shares["total_billed_cents"]
    p["status"] = "FINALIZED"
    c.touch(p)

    participant["ledger_billed_cents"] = (
        participant["ledger_billed_cents"] + p["total_billed_cents"]
    )
    c.touch(participant)
    return success(payment_view(p))


@bp.post("/pace/capitation-payments/<payment_id>/reconcile")
@require_roles("BillingSpecialist")
def reconcile_payment(payment_id):
    p = c.find_or_404(db.capitation_payments, payment_id)
    body = c.get_body()
    recoup = c.as_int(body, "recoup_cents", required=False, default=0, min_val=0)
    # State (priority 5)
    if p["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Payment not FINALIZED")
    # recoup <= total_billed (priority 25)
    if recoup > p["total_billed_cents"]:
        raise err("ERR_RECOUP_EXCEEDS_BILLED", "recoup exceeds billed")

    p["recoup_cents"] = recoup
    p["reconciled_cents"] = p["total_billed_cents"] - recoup
    p["status"] = "RECONCILED"
    c.touch(p)

    participant = db.participants.get(p["participant_id"])
    if participant:
        participant["ledger_reconciled_cents"] = (
            participant["ledger_reconciled_cents"] + p["reconciled_cents"]
        )
        c.touch(participant)
    return success(payment_view(p))


@bp.post("/pace/capitation-payments/<payment_id>/void")
@require_roles("BillingSpecialist")
def void_payment(payment_id):
    p = c.find_or_404(db.capitation_payments, payment_id)
    if p["status"] not in ("DRAFT", "FINALIZED"):
        raise err("ERR_INVALID_STATE", "Payment not DRAFT/FINALIZED")
    was_finalized = p["status"] == "FINALIZED"
    p["status"] = "VOID"
    c.touch(p)
    if was_finalized:
        participant = db.participants.get(p["participant_id"])
        if participant:
            participant["ledger_billed_cents"] = (
                participant["ledger_billed_cents"] - p["total_billed_cents"]
            )
            c.touch(participant)
    return success(payment_view(p))
