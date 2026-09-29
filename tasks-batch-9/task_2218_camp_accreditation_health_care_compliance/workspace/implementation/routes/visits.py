"""Accreditation visits: opening, confirming, starting and closing scoring."""

from flask import Blueprint

import clock
import db
import domain
import helpers
import response
import validators
from errors import api_error
from middleware import authenticate

bp = Blueprint("visits", __name__)

VISIT_WINDOW_MAX_DAYS = 14


@bp.get("/accreditation/visits/<visit_id>")
def get_visit(visit_id):
    ident = authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    visit = helpers.visit_or_404(visit_id)
    helpers.scope(ident, helpers.camp_id_of_visit(visit))
    return response.ok(helpers.public(visit))


@bp.get("/accreditation/visits")
def list_visits():
    authenticate(("CampDirector", "AccreditationOfficer", "Visitor"))
    return helpers.collection_response(db.visits, helpers.VISIT_FILTERS)


@bp.post("/accreditation/visits")
def open_visit():
    authenticate(("AccreditationOfficer",))
    data = validators.body()
    cycle_id = validators.require(data, "cycle_id")
    if not isinstance(cycle_id, str):
        raise api_error("ERR_INVALID_REQUEST", "Field 'cycle_id' must be a string.")
    window_start = validators.req_date(data, "window_start_date")
    window_end = validators.req_date(data, "window_end_date")
    expected_cycle_version = validators.req_int(data, "expected_cycle_version", 0)
    note = validators.opt_str(data, "scheduled_note", 0, 2000)

    cycle = helpers.cycle_or_404(cycle_id)
    camp = db.camps.get(cycle["camp_id"])

    if expected_cycle_version != cycle["version"]:
        raise api_error(
            "ERR_STALE_CYCLE_VERSION",
            "The cycle has moved on since the version you pinned.",
        )
    if cycle["status"] != "SELF_ASSESSMENT":
        raise api_error(
            "ERR_CYCLE_NOT_IN_SELF_ASSESSMENT", "The cycle is not in SELF_ASSESSMENT."
        )
    span = (window_end - window_start).days + 1
    if (
        window_start > window_end
        or span > VISIT_WINDOW_MAX_DAYS
        or window_start < clock.today()
    ):
        raise api_error(
            "ERR_VISIT_WINDOW_INVALID",
            "The agreed visit window is not a valid forward window of at most 14 days.",
        )

    visit = db.common_fields()
    visit.update(
        {
            "cycle_id": cycle_id,
            "window_start_date": window_start.isoformat(),
            "window_end_date": window_end.isoformat(),
            "status": "DRAFT",
            "lead_visitor_id": None,
            "team_size": 0,
            "required_specialist_domains": domain.required_specialist_domains(camp),
            "mandatory_scored_count": 0,
            "mandatory_met_count": 0,
            "provisional_mandatory_pct": None,
            "scheduled_by_user_id": None,
            "scheduled_note": note,
            "scored_at": None,
        }
    )
    db.visits[visit["id"]] = visit

    standing = None
    for existing in domain.cycle_visits(cycle_id):
        if existing["id"] == visit["id"]:
            continue
        if existing["status"] in ("DRAFT", "SCHEDULED"):
            standing = existing
    if standing is not None:
        was_scheduled = domain.rescind_visit(standing)
        if was_scheduled and cycle["status"] == "VISIT_SCHEDULED":
            cycle["status"] = "SELF_ASSESSMENT"

    db.touch(cycle)
    return response.created(helpers.public(visit))


@bp.post("/accreditation/visits/<visit_id>/schedule")
def schedule_visit(visit_id):
    ident = authenticate(("AccreditationOfficer",))
    visit = helpers.visit_or_404(visit_id)
    cycle = db.cycles.get(visit["cycle_id"])
    camp = db.camps.get(cycle["camp_id"]) if cycle else None

    if visit["status"] != "DRAFT":
        raise api_error("ERR_VISIT_INVALID_STATE", "Only a DRAFT visit may be confirmed.")
    if camp["compliance_posture"] == "FROZEN":
        raise api_error(
            "ERR_CAMP_POSTURE_FROZEN", "The camp's compliance posture is FROZEN."
        )
    if camp["state_license_status"] not in ("NONE", "ACTIVE", "PROBATION"):
        raise api_error(
            "ERR_STATE_LICENSE_BLOCKS_VISIT",
            "The camp's state licence status blocks a visit.",
        )
    if not domain.team_complete(visit):
        raise api_error(
            "ERR_TEAM_COMPOSITION_INCOMPLETE", "The visiting team is not complete."
        )
    if cycle["self_assessment_submitted_at"] is None:
        raise api_error(
            "ERR_SELF_ASSESSMENT_INCOMPLETE",
            "The camp's self-assessment has not been submitted.",
        )

    visit["status"] = "SCHEDULED"
    visit["scheduled_by_user_id"] = ident.user_id
    db.touch(visit)
    if cycle["status"] == "SELF_ASSESSMENT":
        cycle["status"] = "VISIT_SCHEDULED"
        db.touch(cycle)
    return response.ok(helpers.public(visit))


@bp.post("/accreditation/visits/<visit_id>/start")
def start_visit(visit_id):
    ident = authenticate(("Visitor",))
    visit = helpers.visit_or_404(visit_id)
    cycle = db.cycles.get(visit["cycle_id"])
    camp = db.camps.get(cycle["camp_id"]) if cycle else None

    if visit["lead_visitor_id"] != ident.user_id:
        raise api_error(
            "ERR_FORBIDDEN_SCOPE", "Only the lead visitor may open scoring on site."
        )
    if visit["status"] != "SCHEDULED":
        raise api_error(
            "ERR_VISIT_INVALID_STATE", "Only a SCHEDULED visit may be started."
        )
    if camp["compliance_posture"] == "FROZEN":
        raise api_error(
            "ERR_CAMP_POSTURE_FROZEN", "The camp's compliance posture is FROZEN."
        )
    today = clock.today().isoformat()
    if not (visit["window_start_date"] <= today <= visit["window_end_date"]):
        raise api_error(
            "ERR_OUTSIDE_VISIT_WINDOW",
            "The logical clock is outside the agreed visit window.",
        )

    visit["status"] = "IN_PROGRESS"
    db.touch(visit)
    return response.ok(helpers.public(visit))


@bp.post("/accreditation/visits/<visit_id>/finalize-scoring")
def finalize_scoring(visit_id):
    ident = authenticate(("Visitor",))
    visit = helpers.visit_or_404(visit_id)
    cycle = db.cycles.get(visit["cycle_id"])
    camp = db.camps.get(cycle["camp_id"]) if cycle else None

    if visit["lead_visitor_id"] != ident.user_id:
        raise api_error(
            "ERR_FORBIDDEN_SCOPE", "Only the lead visitor may close scoring."
        )
    if visit["status"] != "IN_PROGRESS":
        raise api_error(
            "ERR_VISIT_INVALID_STATE", "Only an IN_PROGRESS visit may be closed."
        )
    for row in domain.applicable_mandatory_rows(cycle["id"]):
        if row["visitor_score"] is None:
            raise api_error(
                "ERR_MANDATORY_SCORING_INCOMPLETE",
                "Every applicable mandatory standard must carry a visitor score.",
            )

    # 1. visit and cycle statuses
    visit["status"] = "SCORED"
    visit["scored_at"] = clock.now_iso()
    db.touch(visit)
    if cycle["status"] == "VISIT_SCHEDULED":
        cycle["status"] = "VISIT_COMPLETED"
    else:
        cycle["status"] = "VISIT_COMPLETED"
    db.touch(cycle)

    # 2. provisional mandatory percentage onto both rows
    _, _, provisional = domain.provisional_figures(cycle["id"])
    visit["provisional_mandatory_pct"] = provisional
    cycle["provisional_mandatory_pct"] = provisional

    # 3. lock every applicable evaluation
    not_met_rows = []
    for row in domain.cycle_evaluations(cycle["id"]):
        if not row["applicable"]:
            continue
        if row["visit_status"] != "LOCKED":
            row["visit_status"] = "LOCKED"
            db.touch(row)
        if row["visitor_score"] == "NOT_MET":
            not_met_rows.append(row)

    # 4. seats complete
    for seat in domain.visit_assignments(visit["id"]):
        if seat["status"] == "ASSIGNED":
            seat["status"] = "COMPLETED"
            db.touch(seat)

    # 5. deficiency batch
    findings = []
    base_total = 0
    for row in not_met_rows:
        standard = db.standards.get(row["standard_id"])
        severity = domain.classify_severity(row, standard)
        base_points = domain.SEVERITY_POINTS[severity] * row["scoring_weight"]
        base_total += base_points
        findings.append((row, severity, base_points))

    if findings:
        tier = domain.escalation_tier(base_total)
        surcharge = domain.TIER_SURCHARGE[tier]
        due_date = clock.plus_days(clock.today(), domain.TIER_WINDOW_DAYS[tier])
        for row, severity, base_points in findings:
            deficiency = db.common_fields()
            deficiency.update(
                {
                    "visit_id": visit["id"],
                    "standard_id": row["standard_id"],
                    "severity": severity,
                    "base_points": base_points,
                    "penalty_points": base_points + surcharge,
                    "correction_due_date": due_date.isoformat(),
                    "status": "OPEN",
                    "plan_revision_count": 0,
                    "correction_plan_text": None,
                    "last_plan_submitted_at": None,
                    "reviewer_user_id": None,
                    "reviewer_note": None,
                }
            )
            db.deficiencies[deficiency["id"]] = deficiency

    domain.recompute_penalty_balance(camp)
    domain.recompute_posture(camp)
    domain.recompute_open_deficiency_count(cycle)
    domain.recompute_risk_index(camp)
    return response.ok(helpers.public(visit))
