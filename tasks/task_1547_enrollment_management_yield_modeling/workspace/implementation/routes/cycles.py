"""AdmissionCycle endpoints."""
from flask import Blueprint, request

from db import store, clock, new_id, now_iso, _parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_PHASE_PRECONDITION_NOT_MET, ERR_CYCLE_HAS_NO_PROGRAMS,
    ERR_UNRESOLVED_APPLICATIONS,
)
from middleware import require_roles
from response import success_object
from services.derived import (
    recompute_cycle, recompute_program, recompute_all_programs_of_cycle,
)
from services.serializers import serialize_cycle, touch

bp = Blueprint("cycles", __name__, url_prefix="/enrollment/cycles")


def _get_cycle_or_404(cycle_id):
    c = store.cycles.get(cycle_id)
    if not c:
        raise ApiError(ERR_NOT_FOUND, 404, "Cycle not found")
    return c


@bp.route("", methods=["POST"])
def create_cycle():
    require_roles("EnrollmentManager")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    opens = body.get("application_opens_at")
    deadline = body.get("application_deadline_at")
    deposit_deadline = body.get("deposit_deadline_at")
    census = body.get("census_at")
    target = body.get("target_class_size")
    for v, n in [(name, "name"), (opens, "application_opens_at"),
                 (deadline, "application_deadline_at"),
                 (deposit_deadline, "deposit_deadline_at"),
                 (census, "census_at")]:
        if v is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} required")
    if target is None or not isinstance(target, int) or target < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "target_class_size must be >= 1")
    for v, n in [(opens, "application_opens_at"), (deadline, "application_deadline_at"),
                 (deposit_deadline, "deposit_deadline_at"), (census, "census_at")]:
        if _parse_iso(v) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} malformed")

    now = now_iso()
    cycle = {
        "id": new_id(),
        "name": name,
        "application_opens_at": opens,
        "application_deadline_at": deadline,
        "deposit_deadline_at": deposit_deadline,
        "census_at": census,
        "target_class_size": target,
        "status": "SETUP",
        "inquiry_count": 0,
        "application_count": 0,
        "admitted_count": 0,
        "deposited_count": 0,
        "enrolled_count": 0,
        "decisioned_count": 0,
        "admit_rate": 0.0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.cycles[cycle["id"]] = cycle
    return success_object(serialize_cycle(cycle), status=201)


@bp.route("/<cycleId>", methods=["GET"])
def get_cycle(cycleId):
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    cycle = _get_cycle_or_404(cycleId)
    recompute_cycle(cycle)
    return success_object(serialize_cycle(cycle))


ADVANCE_ORDER = ["SETUP", "OPEN", "REVIEW_CLOSED", "DECISIONS_RELEASED", "ENROLLMENT_TRACKING", "CLOSED"]


@bp.route("/<cycleId>/advance", methods=["POST"])
def advance_cycle(cycleId):
    require_roles("EnrollmentManager")
    cycle = _get_cycle_or_404(cycleId)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if not to_status:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_status required")

    current = cycle["status"]
    if to_status not in ADVANCE_ORDER:
        raise ApiError(ERR_INVALID_STATE, 409, f"Unknown status {to_status}")
    # Must be exactly one step forward in the order
    try:
        cur_idx = ADVANCE_ORDER.index(current)
        next_idx = ADVANCE_ORDER.index(to_status)
    except ValueError:
        raise ApiError(ERR_INVALID_STATE, 409, "Invalid transition")
    if next_idx != cur_idx + 1:
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Cannot advance from {current} to {to_status}")

    now = clock.now()
    if to_status == "OPEN":
        if now < _parse_iso(cycle["application_opens_at"]):
            raise ApiError(ERR_PHASE_PRECONDITION_NOT_MET, 409,
                           "application_opens_at not reached")
        has_program = any(p["cycle_id"] == cycle["id"] for p in store.programs.values())
        if not has_program:
            raise ApiError(ERR_CYCLE_HAS_NO_PROGRAMS, 409, "Cycle has no programs")
    elif to_status == "REVIEW_CLOSED":
        if now < _parse_iso(cycle["application_deadline_at"]):
            raise ApiError(ERR_PHASE_PRECONDITION_NOT_MET, 409,
                           "application_deadline_at not reached")
    elif to_status == "DECISIONS_RELEASED":
        unresolved = any(
            a["cycle_id"] == cycle["id"]
            and a["status"] in ("IN_REVIEW", "COMMITTEE_REVIEW", "DECISION_PENDING")
            for a in store.applications.values()
        )
        if unresolved:
            raise ApiError(ERR_UNRESOLVED_APPLICATIONS, 409,
                           "Applications remain unresolved")
    elif to_status == "ENROLLMENT_TRACKING":
        if now < _parse_iso(cycle["deposit_deadline_at"]):
            raise ApiError(ERR_PHASE_PRECONDITION_NOT_MET, 409,
                           "deposit_deadline_at not reached")
    elif to_status == "CLOSED":
        if now < _parse_iso(cycle["census_at"]):
            raise ApiError(ERR_PHASE_PRECONDITION_NOT_MET, 409,
                           "census_at not reached")
        # Close cascade
        from services.derived import cancel_assigned_reviews
        cycle_program_ids = {p["id"] for p in store.programs.values() if p["cycle_id"] == cycle["id"]}
        cycle_app_ids = {a["id"] for a in store.applications.values() if a["cycle_id"] == cycle["id"]}
        # Expire waitlist entries
        for e in store.waitlist_entries.values():
            if e["program_id"] in cycle_program_ids and e["status"] == "ACTIVE":
                e["status"] = "EXPIRED"
                touch(e)
                app = store.applications.get(e["application_id"])
                if app and app["status"] == "WAITLISTED":
                    app["status"] = "DENIED"
                    touch(app)
        # Cancel scheduled interventions
        for i in store.interventions.values():
            if i["application_id"] in cycle_app_ids and i["status"] == "SCHEDULED":
                i["status"] = "CANCELLED"
                touch(i)
        # Recompute programs and cycle aggregates
        for p in store.programs.values():
            if p["cycle_id"] == cycle["id"]:
                recompute_program(p)

    cycle["status"] = to_status
    recompute_cycle(cycle)
    touch(cycle)
    return success_object(serialize_cycle(cycle))


@bp.route("/<cycleId>/forecast", methods=["GET"])
def forecast(cycleId):
    require_roles("EnrollmentManager", "AdmissionsOfficer")
    cycle = _get_cycle_or_404(cycleId)
    variant = request.args.get("variant", "historical_band")
    if variant not in ("historical_band", "aid_adjusted"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "variant must be historical_band or aid_adjusted")

    recompute_cycle(cycle)
    pipeline = [
        a for a in store.applications.values()
        if a["cycle_id"] == cycle["id"] and a["status"] == "ADMITTED"
    ]

    def band_p(score):
        if score >= 90:
            return 0.65
        if score >= 70:
            return 0.45
        return 0.25

    total_p = 0.0
    for app in pipeline:
        p = band_p(app["academic_score"])
        if variant == "aid_adjusted":
            program = store.programs.get(app["program_id"])
            tuition = program["tuition_cents"] if program else 0
            if app["aid_accepted_cents"] == 0 or not tuition:
                coverage = 0.0
            else:
                from services.derived import q4
                coverage = q4(app["aid_accepted_cents"] / tuition)
            p = q4(min(1.0, p * (1 + coverage)))
        total_p += p

    from decimal import Decimal, ROUND_HALF_UP
    from services.derived import q4
    projected = int(
        (Decimal(cycle["enrolled_count"]) + Decimal(cycle["deposited_count"]) + Decimal(str(total_p)))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    return success_object({
        "variant": variant,
        "projected_enrollment": projected,
        "admit_rate": cycle["admit_rate"],
        "admitted_count": cycle["admitted_count"],
        "deposited_count": cycle["deposited_count"],
        "enrolled_count": cycle["enrolled_count"],
    })


@bp.route("/<cycleId>/funnel-report", methods=["GET"])
def funnel_report(cycleId):
    require_roles("EnrollmentManager", "AdmissionsOfficer")
    cycle = _get_cycle_or_404(cycleId)
    from services.derived import q4
    sources = ["WEB_FORM", "CAMPUS_VISIT", "COLLEGE_FAIR", "REFERRAL", "PURCHASED_LIST"]
    applicants = [a for a in store.applicants.values() if a["cycle_id"] == cycle["id"]]
    rows = []
    total_inquiries = 0
    total_applied = 0
    for s in sources:
        in_src = [a for a in applicants if a["inquiry_source"] == s]
        inquiries = len(in_src)
        applied = sum(1 for a in in_src if a["funnel_stage"] == "APPLIED")
        rate = q4(applied / inquiries) if inquiries > 0 else 0.0
        rows.append({
            "inquiry_source": s,
            "inquiries": inquiries,
            "applied": applied,
            "conversion_rate": rate,
        })
        total_inquiries += inquiries
        total_applied += applied
    overall = q4(total_applied / total_inquiries) if total_inquiries > 0 else 0.0
    return success_object({
        "rows": rows,
        "inquiry_count": total_inquiries,
        "applied_count": total_applied,
        "overall_conversion_rate": overall,
    })


@bp.route("/<cycleId>/melt-sweep", methods=["POST"])
def melt_sweep(cycleId):
    require_roles("EnrollmentManager")
    cycle = _get_cycle_or_404(cycleId)
    if cycle["status"] not in ("DECISIONS_RELEASED", "ENROLLMENT_TRACKING"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Cycle status {cycle['status']} does not permit melt sweep")

    from routes.applications import _melt_application
    melted_ids = []
    activated_ids = []
    apps = [
        a for a in store.applications.values()
        if a["cycle_id"] == cycle["id"] and a["status"] == "DEPOSITED"
    ]
    # deterministic order: sort by created_at then id
    apps.sort(key=lambda a: (a["created_at"], a["id"]))
    for app in apps:
        act = _melt_application(app)
        melted_ids.append(app["id"])
        activated_ids.extend(act)
    recompute_cycle(cycle)
    return success_object({
        "melted_count": len(melted_ids),
        "melted_application_ids": melted_ids,
        "activated_entry_ids": activated_ids,
    })
