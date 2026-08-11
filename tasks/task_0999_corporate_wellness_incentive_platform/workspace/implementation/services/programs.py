"""WellnessProgram endpoints (PRD §3.2)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import require_roles
from response import success
from services import serializers
from services.cascade import (
    close_program_cascade, enrollments_of_program, ledger_of_enrollment,
    recompute_balances,
)
from services.common import (
    get_employer_or_404, get_program_or_404, invalid, list_response,
    parse_body, require_fields, stamp_new, touch,
)

bp = Blueprint("programs", __name__)


@bp.post("/wellness/programs")
@require_roles("BenefitsAdmin")
def create_program():
    body = parse_body()
    vals = require_fields(body, [
        ("employer_id", "string", True),
        ("name", "string", True),
        ("plan_year_start", "date", True),
        ("plan_year_end", "date", True),
        ("bronze_threshold", "int", True),
        ("silver_threshold", "int", True),
        ("gold_threshold", "int", True),
        ("bronze_award_cents", "int", True),
        ("silver_award_cents", "int", True),
        ("gold_award_cents", "int", True),
        ("premium_cap_pct", "number", True),
        ("coaching_required_sessions", "int", True),
    ])
    get_employer_or_404(vals["employer_id"])
    start, end = vals["plan_year_start"], vals["plan_year_end"]
    rec = stamp_new({
        **vals,
        "plan_year_start": start.isoformat(),
        "plan_year_end": end.isoformat(),
        "_pys": start,
        "_pye": end,
        "status": "DRAFT",
    })
    DB.programs[rec["id"]] = rec
    return success(serializers.program(rec), status=201)


@bp.get("/wellness/programs/<pid>")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def get_program(pid):
    return success(serializers.program(get_program_or_404(pid)))


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap; pure adjacency is allowed (PRD §3.2)."""
    return a_start < b_end and a_end > b_start


@bp.post("/wellness/programs/<pid>/activate")
@require_roles("BenefitsAdmin")
def activate_program(pid):
    prog = get_program_or_404(pid)
    if prog["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Program is not in DRAFT status")
    if not prog["_pye"] > prog["_pys"]:
        raise invalid("plan_year_end must be strictly after plan_year_start")
    for other in DB.programs.values():
        if other["id"] == prog["id"]:
            continue
        if other["employer_id"] != prog["employer_id"]:
            continue
        if other["status"] not in ("ACTIVE", "CLOSED"):
            continue
        if _windows_overlap(prog["_pys"], prog["_pye"], other["_pys"], other["_pye"]):
            raise ApiError(
                "ERR_PROGRAM_WINDOW_OVERLAP",
                "Overlapping ACTIVE/CLOSED program window for this employer",
            )
    prog["status"] = "ACTIVE"
    touch(prog)
    return success(serializers.program(prog))


@bp.post("/wellness/programs/<pid>/close")
@require_roles("BenefitsAdmin")
def close_program(pid):
    prog = get_program_or_404(pid)
    if prog["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Program is not in ACTIVE status")
    prog["status"] = "CLOSED"
    prog["_closed_seq"] = DB.next_seq()
    close_program_cascade(prog)
    touch(prog)
    return success(serializers.program(prog))


@bp.post("/wellness/programs/<pid>/settle")
@require_roles("BenefitsAdmin")
def settle_program(pid):
    prog = get_program_or_404(pid)
    if prog["status"] != "CLOSED":
        if prog["status"] == "SETTLED":
            raise ApiError("ERR_INVALID_STATE", "Program is already SETTLED")
        raise ApiError(
            "ERR_PROGRAM_NOT_CLOSED", "Settle requires program status CLOSED"
        )
    for award in DB.awards.values():
        if award["program_id"] == prog["id"] and award["status"] != "APPLIED":
            raise ApiError(
                "ERR_PROGRAM_HAS_OPEN_AWARDS",
                "Every IncentiveAward of the program must be APPLIED before settle",
            )
    prog["status"] = "SETTLED"
    touch(prog)
    return success(serializers.program(prog))


@bp.post("/wellness/programs/<pid>/finalize-points")
@require_roles("BenefitsAdmin")
def finalize_points(pid):
    prog = get_program_or_404(pid)
    if prog["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PROGRAM_NOT_ACTIVE", "Finalize-points requires program status ACTIVE"
        )
    finalized = 0
    for enr in enrollments_of_program(prog["id"]):
        entries = sorted(
            ledger_of_enrollment(enr["id"]), key=lambda le: le["created_at"]
        )
        changed = False
        for le in entries:
            if le["status"] == "PROVISIONAL":
                le["status"] = "POSTED"
                touch(le)
                finalized += 1
                changed = True
        if changed:
            recompute_balances(enr)
    return success({"finalized_count": finalized})


@bp.get("/wellness/programs/<pid>/enrollments")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_program_enrollments(pid):
    get_program_or_404(pid)
    return list_response(enrollments_of_program(pid), serializers.enrollment)


@bp.get("/wellness/programs/<pid>/challenges")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_program_challenges(pid):
    get_program_or_404(pid)
    items = [c for c in DB.challenges.values() if c["program_id"] == pid]
    return list_response(items, serializers.challenge)


@bp.get("/wellness/programs/<pid>/incentive-awards")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_program_awards(pid):
    get_program_or_404(pid)
    items = [a for a in DB.awards.values() if a["program_id"] == pid]
    return list_response(items, serializers.award)


@bp.get("/wellness/programs/<pid>/vendor-invoices")
@require_roles("PlatformAdmin", "BenefitsAdmin", "VendorManager")
def list_program_invoices(pid):
    get_program_or_404(pid)
    items = [i for i in DB.invoices.values() if i["program_id"] == pid]
    return list_response(items, serializers.invoice)


@bp.get("/wellness/programs/<pid>/aggregate-reports")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_program_reports(pid):
    get_program_or_404(pid)
    items = [r for r in DB.reports.values() if r["program_id"] == pid]
    return list_response(items, serializers.report)
