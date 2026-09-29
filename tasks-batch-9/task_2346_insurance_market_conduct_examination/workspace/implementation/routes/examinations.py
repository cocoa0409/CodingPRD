"""Examinations: opening, scope, workpapers, exposure, publication, abandonment."""

from flask import Blueprint

import validation as v
from db import db, new_record, now_iso, touch
from errors import ApiError, invalid
from middleware import (
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_INSURER_RESPONDENT,
    ROLE_MARKET_ANALYST,
    ROLE_MULTISTATE_COORDINATOR,
    ROLE_SUPERVISING_EXAMINER,
    authorize,
    current_user_id,
)
from response import paginated, success
from routes.common import filter_equals, str_query
from services import calculations as calc
from services import derive, serialize, transitions
from services.guards import (
    ensure_exam_subject,
    ensure_exam_writable,
    get_cycle,
    get_exam,
    get_insurer,
)

bp = Blueprint("examinations", __name__)

EXAM_TYPES = ("MARKET_CONDUCT_EXAM", "TARGETED_EXAM")
EXAM_MODES = ("ON_SITE", "DESK")
AREAS = ("UNDERWRITING", "RATING", "CLAIMS", "PRODUCER")
ACTIVITY_TYPES = ("INTERVIEW", "SYSTEM_WALKTHROUGH")
PENALTY_VARIANTS = ("PER_VIOLATION", "TIERED_AGGREGATE")
PLAN_STATUSES = ("PROPOSED", "REVISION_REQUESTED", "APPROVED", "REJECTED", "SUPERSEDED")

ALL_READ_ROLES = (
    ROLE_MARKET_ANALYST,
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_SUPERVISING_EXAMINER,
    ROLE_MULTISTATE_COORDINATOR,
    ROLE_INSURER_RESPONDENT,
)
EXAM_RECORD_READ_ROLES = (
    ROLE_EXAMINER_IN_CHARGE,
    ROLE_SUPERVISING_EXAMINER,
    ROLE_MULTISTATE_COORDINATOR,
    ROLE_INSURER_RESPONDENT,
)


# ------------------------------------------------------------------ examinations
@bp.post("/examinations")
@authorize(ROLE_SUPERVISING_EXAMINER)
def create_examination():
    payload = v.body()
    # Existence (band 5) is resolved before the remaining shape checks (band 6).
    insurer_id = v.get_str(payload, "insurer_id", min_len=1)
    cycle_id = v.get_str(payload, "cycle_id", required=False)
    insurer = get_insurer(insurer_id)
    cycle = get_cycle(cycle_id) if cycle_id else None

    exam_type = v.get_enum(payload, "exam_type", EXAM_TYPES)
    mode = v.get_enum(payload, "mode", EXAM_MODES)
    lead_state_code = v.require_state_code(payload, "lead_state_code")
    start_date = v.get_date(payload, "fieldwork_start_date")
    end_date = v.get_date(payload, "fieldwork_end_date")
    v.require_after(end_date, start_date, "fieldwork_end_date")

    if insurer["license_status"] == "WITHDRAWN":
        raise ApiError(
            "ERR_INSURER_NOT_EXAMINABLE",
            "A carrier whose licence has been withdrawn cannot be examined.",
        )
    for existing in derive.examinations_of_insurer(insurer["id"]):
        if existing["status"] in derive.TERMINAL_EXAM_STATES:
            continue
        if derive.windows_overlap(
            start_date,
            end_date,
            existing["fieldwork_start_date"],
            existing["fieldwork_end_date"],
        ):
            raise ApiError(
                "ERR_EXAM_WINDOW_CONFLICT",
                "The carrier already has a live examination occupying that window.",
            )
    if cycle is not None and derive.cycle_counters(cycle)["slots_available"] <= 0:
        raise ApiError(
            "ERR_CYCLE_SLOTS_EXHAUSTED", "The cycle has no examiner slot left to commit."
        )

    exam = new_record(
        {
            "insurer_id": insurer["id"],
            "cycle_id": cycle["id"] if cycle else None,
            "predecessor_exam_id": None,
            "exam_type": exam_type,
            "mode": mode,
            "lead_state_code": lead_state_code,
            "fieldwork_start_date": start_date,
            "fieldwork_end_date": end_date,
            "status": "SCOPING",
            "scope_locked": False,
            "criticism_phase_opened_at": None,
            "report_published_at": None,
            "public_summary": None,
            "followup_required": False,
            "followup_due_date": None,
            "abort_reason": None,
        }
    )
    db.examinations[exam["id"]] = exam
    return success(serialize.examination(exam), 201)


@bp.get("/examinations")
@authorize(*ALL_READ_ROLES)
def list_examinations():
    rows = derive.by_creation_examinations()
    rows = filter_equals(rows, "insurer_id", str_query("insurer_id"))
    rows = filter_equals(rows, "cycle_id", str_query("cycle_id"))
    rows = filter_equals(rows, "predecessor_exam_id", str_query("predecessor_exam_id"))
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.examination)


@bp.get("/examinations/<exam_id>")
@authorize(*ALL_READ_ROLES)
def read_examination(exam_id):
    exam = ensure_exam_subject(get_exam(exam_id))
    return success(serialize.examination(exam))


# ------------------------------------------------------------------- scope areas
@bp.post("/examinations/<exam_id>/scope-areas")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def create_scope_area(exam_id):
    exam = get_exam(exam_id)
    payload = v.body()
    area = v.get_enum(payload, "area", AREAS)
    population_size = v.get_int(payload, "population_size", minimum=1)
    sample_size = v.get_int(payload, "sample_size", minimum=1)
    tolerance = v.get_percentage(payload, "error_tolerance_pct", required=False)

    if any(row["area"] == area for row in derive.scope_areas_of_exam(exam["id"])):
        raise ApiError(
            "ERR_DUPLICATE_IDENTIFIER",
            "The examination already carries a %s scope area." % area,
        )
    ensure_exam_writable(exam)
    if exam["status"] != "SCOPING":
        raise ApiError(
            "ERR_EXAM_NOT_IN_SCOPING",
            "Scope areas may only be added while the examination is in SCOPING.",
        )
    minimum = calc.minimum_sample_size(exam["mode"])
    if sample_size < minimum:
        raise ApiError(
            "ERR_SAMPLE_SIZE_BELOW_MINIMUM",
            "A %s examination requires a sample_size of at least %d."
            % (exam["mode"], minimum),
        )
    if sample_size > population_size:
        raise ApiError(
            "ERR_SAMPLE_EXCEEDS_POPULATION",
            "sample_size may not exceed population_size.",
        )

    if tolerance is None:
        tolerance = calc.AREA_TOLERANCE_DEFAULTS[area]
    else:
        tolerance = calc.round_half_up(tolerance, 2)

    record = new_record(
        {
            "exam_id": exam["id"],
            "area": area,
            "population_size": population_size,
            "sample_size": sample_size,
            "error_tolerance_pct": tolerance,
            "status": "PLANNED",
            "tested_at": None,
        }
    )
    db.scope_areas[record["id"]] = record
    touch(exam)
    return success(serialize.scope_area(record), 201)


@bp.get("/examinations/<exam_id>/scope-areas")
@authorize(*ALL_READ_ROLES)
def list_scope_areas(exam_id):
    exam = ensure_exam_subject(get_exam(exam_id))
    rows = derive.scope_areas_of_exam(exam["id"])
    rows = filter_equals(rows, "status", str_query("status"))
    rows = filter_equals(rows, "area", str_query("area"))
    return paginated(rows, serialize.scope_area)


@bp.post("/examinations/<exam_id>/lock-scope")
@authorize(ROLE_SUPERVISING_EXAMINER)
def lock_scope(exam_id):
    exam = get_exam(exam_id)
    v.body()
    if not derive.scope_areas_of_exam(exam["id"]):
        raise invalid("An examination with no scope area at all cannot be locked.")
    ensure_exam_writable(exam)
    if exam["status"] != "SCOPING":
        raise ApiError(
            "ERR_EXAM_NOT_IN_SCOPING",
            "Locking is only possible from SCOPING; this examination is %s."
            % exam["status"],
        )
    insurer = db.insurers.get(exam["insurer_id"])
    if insurer is not None and insurer["license_status"] == "WITHDRAWN":
        raise ApiError(
            "ERR_INSURER_NOT_EXAMINABLE",
            "The carrier's licence has been withdrawn since the examination opened.",
        )

    exam["scope_locked"] = True
    exam["status"] = "DATA_CALL"
    touch(exam)
    return success(serialize.examination(exam))


# ------------------------------------------------------------------- workpapers
@bp.post("/examinations/<exam_id>/fieldwork-activities")
@authorize(ROLE_EXAMINER_IN_CHARGE)
def create_fieldwork_activity(exam_id):
    exam = get_exam(exam_id)
    payload = v.body()
    activity_type = v.get_enum(payload, "activity_type", ACTIVITY_TYPES)
    area = v.get_enum(payload, "area", AREAS)
    participant_name = v.get_str(payload, "participant_name", min_len=1)
    participant_title = v.get_str(payload, "participant_title", min_len=1)
    # §2.11 band 6 lists `summary` among the free-text fields whose minimum is
    # twenty characters, and band 6 is evaluated before the lifecycle band.
    summary = v.require_narrative(payload, "summary")
    evidence_ref = v.get_str(payload, "evidence_ref", required=False, min_len=None)

    ensure_exam_writable(exam)
    if exam["status"] == "SCOPING":
        raise ApiError(
            "ERR_SCOPE_NOT_LOCKED",
            "Workpapers may only be recorded once the scope has been locked.",
        )

    documented = len(summary) >= v.MIN_NARRATIVE_CHARS and bool(
        evidence_ref and evidence_ref.strip()
    )
    record = new_record(
        {
            "exam_id": exam["id"],
            "activity_type": activity_type,
            "area": area,
            "participant_name": participant_name,
            "participant_title": participant_title,
            "summary": summary,
            "evidence_ref": evidence_ref,
            "conducted_at": now_iso(),
            "documented": documented,
        },
        versioned=False,
    )
    db.fieldwork_activities[record["id"]] = record
    return success(serialize.fieldwork_activity(record), 201)


@bp.get("/examinations/<exam_id>/fieldwork-activities")
@authorize(
    ROLE_EXAMINER_IN_CHARGE, ROLE_SUPERVISING_EXAMINER, ROLE_MULTISTATE_COORDINATOR
)
def list_fieldwork_activities(exam_id):
    exam = get_exam(exam_id)
    rows = derive.fieldwork_activities_of_exam(exam["id"])
    rows = filter_equals(rows, "activity_type", str_query("activity_type"))
    rows = filter_equals(rows, "area", str_query("area"))
    return paginated(rows, serialize.fieldwork_activity)


# -------------------------------------------------------------- exposure summary
@bp.get("/examinations/<exam_id>/exposure-summary")
@authorize(ROLE_SUPERVISING_EXAMINER, ROLE_MULTISTATE_COORDINATOR)
def exposure_summary(exam_id):
    exam = get_exam(exam_id)
    counters = derive.exam_counters(exam)
    restitution = counters["aggregate_restitution_cents"]
    per_violation = calc.penalty_chain(
        "PER_VIOLATION",
        restitution,
        counters["penalty_units_total"],
        counters["sustained_criticism_count"],
    )
    tiered = calc.penalty_chain(
        "TIERED_AGGREGATE",
        restitution,
        counters["penalty_units_total"],
        counters["sustained_criticism_count"],
    )
    return success(
        {
            "examination_id": exam["id"],
            "sustained_criticism_count": counters["sustained_criticism_count"],
            "aggregate_restitution_cents": restitution,
            "penalty_units_total": counters["penalty_units_total"],
            "per_violation_penalty_gross_cents": per_violation["penalty_gross_cents"],
            "per_violation_cooperation_credit_pct": per_violation[
                "cooperation_credit_pct"
            ],
            "per_violation_penalty_net_cents": per_violation["penalty_net_cents"],
            "per_violation_order_total_cents": per_violation["order_total_cents"],
            "tiered_penalty_gross_cents": tiered["penalty_gross_cents"],
            "tiered_cooperation_credit_pct": tiered["cooperation_credit_pct"],
            "tiered_penalty_net_cents": tiered["penalty_net_cents"],
            "tiered_order_total_cents": tiered["order_total_cents"],
        }
    )


# ------------------------------------------------- publication and abandonment
@bp.post("/examinations/<exam_id>/publish-report")
@authorize(ROLE_SUPERVISING_EXAMINER)
def publish_report(exam_id):
    exam = get_exam(exam_id)
    executed = derive.executed_order_of_exam(exam["id"])
    if executed is not None and executed["drafted_by_user_id"] == current_user_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The supervising examiner who drafted the executed order may not publish.",
        )
    payload = v.body()
    public_summary = v.require_narrative(payload, "public_summary")

    ensure_exam_writable(exam)
    counters = derive.exam_counters(exam)
    if exam["status"] not in ("CRITICISM", "ORDER_PENDING"):
        raise ApiError(
            "ERR_EXAM_NOT_READY_FOR_PUBLICATION",
            "Publication is legal only from CRITICISM or ORDER_PENDING; this "
            "examination is %s." % exam["status"],
        )
    if exam["status"] == "CRITICISM" and (
        counters["sustained_criticism_count"] > 0 or counters["open_criticism_count"] > 0
    ):
        raise ApiError(
            "ERR_EXAM_NOT_READY_FOR_PUBLICATION",
            "An examination with open or sustained criticisms must route through "
            "negotiation and an executed order.",
        )
    if exam["status"] == "ORDER_PENDING" and executed is None:
        raise ApiError(
            "ERR_ORDER_NOT_EXECUTED",
            "Publication from ORDER_PENDING requires an EXECUTED consent order.",
        )

    transitions.publish_examination(exam, public_summary)
    return success(serialize.examination(exam))


@bp.post("/examinations/<exam_id>/abort")
@authorize(ROLE_SUPERVISING_EXAMINER)
def abort_report(exam_id):
    exam = get_exam(exam_id)
    payload = v.body()
    abort_reason = v.get_str(payload, "abort_reason", min_len=1)
    ensure_exam_writable(exam)
    transitions.abort_examination(exam, abort_reason)
    return success(serialize.examination(exam))


# ------------------------------------------------- corrective action plans (§3.8)
@bp.post("/examinations/<exam_id>/corrective-action-plans")
@authorize(ROLE_INSURER_RESPONDENT)
def create_plan(exam_id):
    exam = ensure_exam_subject(get_exam(exam_id))
    payload = v.body()
    expected_version = v.get_int(payload, "expected_examination_version", minimum=0)
    milestone_count = v.get_int(payload, "milestone_count", minimum=1)
    completion_due_date = v.get_date(payload, "completion_due_date")
    narrative = v.require_narrative(payload, "narrative")

    ensure_exam_writable(exam)
    if exam["status"] != "NEGOTIATION":
        raise ApiError(
            "ERR_EXAM_NOT_IN_NEGOTIATION",
            "A corrective action plan may only be proposed while the examination is "
            "in NEGOTIATION; this examination is %s." % exam["status"],
        )
    if expected_version != exam["version"]:
        raise ApiError(
            "ERR_STALE_EXAMINATION_VERSION",
            "expected_examination_version %d does not match the examination's current "
            "version %d." % (expected_version, exam["version"]),
        )

    revision_round = 1
    for prior in derive.plans_of_exam(exam["id"]):
        if prior["status"] in ("PROPOSED", "REVISION_REQUESTED"):
            prior["status"] = "SUPERSEDED"
            touch(prior)
            revision_round = prior["revision_round"] + 1

    plan = new_record(
        {
            "exam_id": exam["id"],
            "status": "PROPOSED",
            "revision_round": revision_round,
            "milestone_count": milestone_count,
            "completion_due_date": completion_due_date,
            "narrative": narrative,
            "reviewed_by_user_id": None,
            "review_note": None,
        }
    )
    db.plans[plan["id"]] = plan
    touch(exam)
    return success(serialize.corrective_action_plan(plan), 201)


@bp.get("/examinations/<exam_id>/corrective-action-plans")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_plans(exam_id):
    exam = ensure_exam_subject(get_exam(exam_id))
    rows = derive.plans_of_exam(exam["id"])
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.corrective_action_plan)


# ------------------------------------------------------- consent orders (§3.8)
@bp.post("/examinations/<exam_id>/consent-orders")
@authorize(ROLE_SUPERVISING_EXAMINER)
def create_consent_order(exam_id):
    exam = get_exam(exam_id)
    payload = v.body()
    expected_version = v.get_int(payload, "expected_examination_version", minimum=0)
    order_number = v.get_str(payload, "order_number", min_len=1)
    penalty_variant = v.get_enum(payload, "penalty_variant", PENALTY_VARIANTS)

    if any(
        row["order_number"] == order_number for row in db.consent_orders.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_IDENTIFIER",
            "That order_number already exists on another consent order.",
        )
    ensure_exam_writable(exam)
    if exam["status"] not in derive.ENFORCEMENT_EXAM_STATES:
        raise ApiError(
            "ERR_EXAM_NOT_IN_NEGOTIATION",
            "A consent order may only be drafted from NEGOTIATION or ORDER_PENDING; "
            "this examination is %s." % exam["status"],
        )
    if expected_version != exam["version"]:
        raise ApiError(
            "ERR_STALE_EXAMINATION_VERSION",
            "expected_examination_version %d does not match the examination's current "
            "version %d." % (expected_version, exam["version"]),
        )
    if derive.approved_plan_of_exam(exam["id"]) is None:
        raise ApiError(
            "ERR_CAP_NOT_APPROVED",
            "An APPROVED corrective action plan is required before drafting an order.",
        )

    counters = derive.exam_counters(exam)
    restitution = counters["aggregate_restitution_cents"]
    chain = calc.penalty_chain(
        penalty_variant,
        restitution,
        counters["penalty_units_total"],
        counters["sustained_criticism_count"],
    )
    if chain["penalty_gross_cents"] > calc.STATUTORY_CAP_CENTS:
        raise ApiError(
            "ERR_PENALTY_CAP_EXCEEDED",
            "The gross penalty of %d cents exceeds the statutory ceiling of %d cents."
            % (chain["penalty_gross_cents"], calc.STATUTORY_CAP_CENTS),
        )

    for prior in derive.orders_of_exam(exam["id"]):
        if prior["status"] == "DRAFT":
            prior["status"] = "VOIDED"
            touch(prior)

    order = new_record(
        {
            "exam_id": exam["id"],
            "order_number": order_number,
            "status": "DRAFT",
            "penalty_variant": penalty_variant,
            "restitution_cents": restitution,
            "penalty_gross_cents": chain["penalty_gross_cents"],
            "cooperation_credit_pct": chain["cooperation_credit_pct"],
            "penalty_net_cents": chain["penalty_net_cents"],
            "order_total_cents": chain["order_total_cents"],
            "drafted_by_user_id": current_user_id(),
            "signed_by": None,
            "executed_at": None,
        }
    )
    db.consent_orders[order["id"]] = order
    touch(exam)
    return success(serialize.consent_order(order), 201)


@bp.get("/examinations/<exam_id>/consent-orders")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_consent_orders(exam_id):
    exam = ensure_exam_subject(get_exam(exam_id))
    rows = derive.orders_of_exam(exam["id"])
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.consent_order)


# ------------------------------------------------------- collaborations (§3.9)
@bp.post("/examinations/<exam_id>/collaborations")
@authorize(ROLE_MULTISTATE_COORDINATOR)
def create_collaboration(exam_id):
    exam = get_exam(exam_id)
    payload = v.body()
    roster = _parse_roster(payload)
    call_reference = v.get_str(payload, "call_reference", required=False, min_len=None)

    if derive.collaborations_of_exam(exam["id"]):
        raise ApiError(
            "ERR_DUPLICATE_IDENTIFIER",
            "The examination already carries a multistate collaboration.",
        )
    ensure_exam_writable(exam)
    lead_state_code = calc.elect_lead_state(roster)
    if lead_state_code is None:
        raise ApiError(
            "ERR_NO_ELIGIBLE_LEAD_STATE",
            "No participating state declared examiner resources.",
        )

    collaboration = new_record(
        {
            "exam_id": exam["id"],
            "call_reference": call_reference,
            "participating_states": roster,
            "lead_state_code": lead_state_code,
            "status": "LEAD_ASSIGNED",
            "allocation_completed_at": None,
        }
    )
    db.collaborations[collaboration["id"]] = collaboration
    return success(serialize.collaboration(collaboration), 201)


def _parse_roster(payload):
    if not v.present(payload, "participating_states"):
        raise invalid("Field participating_states is required.")
    raw = payload["participating_states"]
    if not isinstance(raw, list) or not raw:
        raise invalid("Field participating_states must be a non-empty array.")
    if len(raw) > 12:
        raise invalid("Field participating_states may hold at most 12 participants.")
    roster = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise invalid("Each participating_states entry must be an object.")
        state_code = v.require_state_code(entry, "state_code")
        if state_code in seen:
            raise invalid("participating_states contains a duplicate state_code.")
        seen.add(state_code)
        policy_count = v.get_int(entry, "policy_count_in_state", minimum=1)
        has_resources = v.get_bool(entry, "has_examiner_resources")
        roster.append(
            {
                "state_code": state_code,
                "policy_count_in_state": policy_count,
                "has_examiner_resources": has_resources,
                "allocated_cents": 0,
            }
        )
    if sum(p["policy_count_in_state"] for p in roster) <= 0:
        raise invalid("participating_states policy counts may not total zero.")
    return roster


@bp.get("/examinations/<exam_id>/collaborations")
@authorize(*EXAM_RECORD_READ_ROLES)
def list_collaborations(exam_id):
    exam = ensure_exam_subject(get_exam(exam_id))
    rows = derive.collaborations_of_exam(exam["id"])
    rows = filter_equals(rows, "status", str_query("status"))
    return paginated(rows, serialize.collaboration)
