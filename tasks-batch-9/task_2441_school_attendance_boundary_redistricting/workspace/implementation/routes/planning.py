"""Projection runs, boundary scenarios, area assignments and public comments."""

from flask import Blueprint, request

import calc
import services
from core import (
    COMMENT_PRIORITIES,
    COMMENT_THEMES,
    IMPACT_VARIANTS,
    MAX_REVISION_ROUNDS,
    PROGRAM_TYPES,
    READ_ROLES_INTERNAL,
    READ_ROLES_PUBLIC,
    RUN_VARIANTS,
    areas_of_study,
    as_enum,
    as_int,
    as_str,
    assignments_of_scenario,
    authenticate,
    bool_filter,
    body_json,
    comments_of_scenario,
    db,
    fail,
    get_area,
    get_assignment,
    get_comment,
    get_run,
    get_scenario,
    get_school,
    get_study,
    iso3,
    live_assignment_for_area,
    need,
    new_record,
    now,
    ordered,
    paginate,
    present,
    pub,
    recompute_study_values,
    respond,
    runs_of_study,
    scenarios_of_study,
    touch,
)

bp = Blueprint("planning", __name__)


def pre_resolve(getter, value):
    if isinstance(value, str) and value:
        return getter(value)
    return None


def _validate_placements(raw, key="program_placements"):
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % key)
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Each %s entry must be an object." % key)
        for field in ("program_type", "school_id", "seats"):
            if field not in item or item[field] is None:
                fail("ERR_INVALID_REQUEST", "%s entry is missing '%s'." % (key, field))
        entries.append({
            "program_type": as_enum(item["program_type"], "program_type", PROGRAM_TYPES),
            "school_id": as_str(item["school_id"], "school_id"),
            "seats": as_int(item["seats"], "seats", minimum=0),
        })
    return entries


def _pre_resolve_placement_schools(raw):
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("school_id"), str) and item["school_id"]:
                get_school(item["school_id"])


# ==========================================================================
# Projection runs
# ==========================================================================
@bp.post("/studies/<study_id>/projection-runs")
def create_projection_run(study_id):
    authenticate(["DistrictPlanner"])
    study = get_study(study_id)
    body = body_json()
    variant = as_enum(need(body, "variant"), "variant", RUN_VARIANTS)
    horizon_years = study["horizon_years"]
    if present(body, "horizon_years"):
        horizon_years = as_int(body["horizon_years"], "horizon_years", minimum=1, maximum=10)
    expected_version = as_int(need(body, "expected_study_version"), "expected_study_version")

    if study["status"] not in ("DATA_LOCKED", "SCENARIO_DEVELOPMENT", "ENGAGEMENT"):
        fail("ERR_STUDY_PHASE_INVALID")
    if expected_version != study["version"]:
        fail("ERR_STALE_STUDY_VERSION")

    epoch = now()
    public, internal, total, _ = services.execute_projection(study, variant, horizon_years, epoch)

    run = new_record()
    run.update({
        "study_id": study["id"],
        "variant": variant,
        "horizon_years": horizon_years,
        "status": "COMPLETE",
        "stale_reason": None,
        "area_projections": public,
        "projected_total_students": total,
        "_proj": internal,
    })
    for earlier in runs_of_study(study["id"]):  # ProjectionRun.created_at ASC
        if earlier["variant"] == variant and earlier["status"] in ("COMPLETE", "STALE"):
            earlier["status"] = "SUPERSEDED"
            touch(earlier)
    db.runs[run["id"]] = run

    if study["status"] == "DATA_LOCKED":
        study["status"] = "SCENARIO_DEVELOPMENT"
    recompute_study_values(study)
    touch(study)
    return respond(pub(run), 201)


@bp.get("/studies/<study_id>/projection-runs")
def list_projection_runs(study_id):
    authenticate(READ_ROLES_INTERNAL)
    study = get_study(study_id)
    rows = runs_of_study(study["id"])
    for key in ("variant", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/projection-runs/<run_id>")
def read_projection_run(run_id):
    authenticate(READ_ROLES_INTERNAL)
    return respond(pub(get_run(run_id)))


# ==========================================================================
# Boundary scenarios
# ==========================================================================
@bp.post("/scenarios")
def create_scenario():
    user_id, _role = authenticate(["DistrictPlanner"])
    body = body_json()
    pre_resolve(get_study, body.get("study_id"))
    pre_resolve(get_run, body.get("projection_run_id"))
    _pre_resolve_placement_schools(body.get("program_placements"))

    study = get_study(as_str(need(body, "study_id"), "study_id"))
    run = get_run(as_str(need(body, "projection_run_id"), "projection_run_id"))
    name = as_str(need(body, "name"), "name")
    placements = []
    if present(body, "program_placements"):
        placements = _validate_placements(body["program_placements"])
    impact_variant = "RESIDENT_BASED"
    if present(body, "impact_variant"):
        impact_variant = as_enum(body["impact_variant"], "impact_variant", IMPACT_VARIANTS)

    if study["status"] not in ("DATA_LOCKED", "SCENARIO_DEVELOPMENT"):
        fail("ERR_STUDY_PHASE_INVALID")
    for entry in placements:
        if db.schools[entry["school_id"]]["status"] != "ACTIVE":
            fail("ERR_SCHOOL_NOT_ACTIVE")
    if run["study_id"] != study["id"]:
        fail("ERR_CROSS_STUDY_REFERENCE")
    for entry in placements:
        if db.schools[entry["school_id"]]["study_id"] != study["id"]:
            fail("ERR_CROSS_STUDY_REFERENCE")
    for entry in placements:
        if entry["program_type"] not in (db.schools[entry["school_id"]]["program_types"] or []):
            fail("ERR_PROGRAM_HOST_INCAPABLE")
    for existing in scenarios_of_study(study["id"]):
        if existing["name"] == name:
            fail("ERR_DUPLICATE_NAME")

    scenario = new_record()
    scenario.update({
        "study_id": study["id"],
        "projection_run_id": run["id"],
        "name": name,
        "author_user_id": user_id,
        "status": "DRAFT",
        "revision_round": 0,
        "revision_reason": None,
        "rejection_reason": None,
        "projection_stale": run["status"] == "STALE",
        "program_placements": placements,
        "impact_variant": impact_variant,
        "contiguity_ok": True,
        "noncontiguous_school_ids": [],
        "total_assigned_students": 0,
        "max_utilization_pct": 0.00,
        "walk_eligible_pct": 0.00,
        "transport_cost_annual_usd": 0.00,
        "students_reassigned_count": 0,
        "students_reassigned_pct": 0.00,
        "frl_dissimilarity_index": 0.0000,
    })
    db.scenarios[scenario["id"]] = scenario
    return respond(pub(scenario), 201)


@bp.get("/scenarios")
def list_scenarios():
    authenticate(READ_ROLES_PUBLIC)
    rows = ordered(list(db.scenarios.values()))
    for key in ("study_id", "projection_run_id", "status", "impact_variant"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/scenarios/<scenario_id>")
def read_scenario(scenario_id):
    authenticate(READ_ROLES_PUBLIC)
    return respond(pub(get_scenario(scenario_id)))


@bp.get("/scenarios/<scenario_id>/impact-analysis")
def impact_analysis(scenario_id):
    authenticate(READ_ROLES_PUBLIC)
    scenario = get_scenario(scenario_id)
    scores = services.score_scenario(scenario)
    return respond({
        "scenario_id": scenario["id"],
        "impact_variant": scenario["impact_variant"],
        "total_assigned_students": scores["total_assigned_students"],
        "frl_dissimilarity_index": scores["frl_dissimilarity_index"],
        "students_reassigned_count": scores["students_reassigned_count"],
        "students_reassigned_pct": scores["students_reassigned_pct"],
        "max_utilization_pct": scores["max_utilization_pct"],
        "critical_school_ids": scores["critical_school_ids"],
        "walk_eligible_pct": scores["walk_eligible_pct"],
        "transport_cost_annual_usd": scores["transport_cost_annual_usd"],
        "contiguity_ok": scores["contiguity_ok"],
        "noncontiguous_school_ids": scores["noncontiguous_school_ids"],
        "per_school": scores["per_school"],
    })


@bp.put("/scenarios/<scenario_id>/program-placements")
def replace_placements(scenario_id):
    authenticate(["DistrictPlanner"])
    scenario = get_scenario(scenario_id)
    body = body_json()
    _pre_resolve_placement_schools(body.get("program_placements"))

    raw = need(body, "program_placements")
    placements = _validate_placements(raw)
    if not placements:
        fail("ERR_INVALID_REQUEST", "program_placements may not be empty.")
    expected_version = as_int(need(body, "expected_scenario_version"), "expected_scenario_version")

    if scenario["status"] not in ("DRAFT", "REVISION"):
        fail("ERR_SCENARIO_NOT_EDITABLE")
    for entry in placements:
        if db.schools[entry["school_id"]]["status"] != "ACTIVE":
            fail("ERR_SCHOOL_NOT_ACTIVE")
    if expected_version != scenario["version"]:
        fail("ERR_STALE_SCENARIO_VERSION")
    study = db.studies[scenario["study_id"]]
    for entry in placements:
        if db.schools[entry["school_id"]]["study_id"] != study["id"]:
            fail("ERR_CROSS_STUDY_REFERENCE")
    for entry in placements:
        if entry["program_type"] not in (db.schools[entry["school_id"]]["program_types"] or []):
            fail("ERR_PROGRAM_HOST_INCAPABLE")

    scenario["program_placements"] = placements
    touch(scenario)
    return respond(pub(scenario))


@bp.post("/scenarios/<scenario_id>/submit-for-review")
def submit_for_review(scenario_id):
    authenticate(["DistrictPlanner"])
    scenario = get_scenario(scenario_id)
    body = body_json()
    if present(body, "planner_notes"):
        as_str(body["planner_notes"], "planner_notes", min_len=0)

    study = db.studies[scenario["study_id"]]
    if study["status"] not in ("DATA_LOCKED", "SCENARIO_DEVELOPMENT", "ENGAGEMENT"):
        fail("ERR_STUDY_PHASE_INVALID")
    if scenario["status"] not in ("DRAFT", "REVISION"):
        fail("ERR_SCENARIO_NOT_EDITABLE")
    run = db.runs.get(scenario["projection_run_id"])
    if run is None or run["status"] != "COMPLETE":
        fail("ERR_PROJECTION_STALE")

    scores = services.score_scenario(scenario)

    live = assignments_of_scenario(scenario["id"], live_only=True)
    assigned_counts = {}
    for row in live:
        assigned_counts[row["area_id"]] = assigned_counts.get(row["area_id"], 0) + 1
    for area in areas_of_study(study["id"]):
        if assigned_counts.get(area["id"], 0) != 1:
            fail("ERR_AREA_UNASSIGNED")
    if not scores["contiguity_ok"]:
        fail("ERR_CONTIGUITY_BROKEN")
    placements = scenario["program_placements"] or []
    for required in study["required_program_types"]:
        if sum(1 for p in placements if p["program_type"] == required) != 1:
            fail("ERR_PROGRAM_PLACEMENT_INCOMPLETE")
    hosted_ids = {row["assigned_school_id"] for row in live}
    for entry in placements:
        if entry["school_id"] not in hosted_ids:
            fail("ERR_PROGRAM_HOST_UNASSIGNED")

    if scenario["status"] == "REVISION" and scenario["revision_round"] >= MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED")
    if scores["_max_util"] >= calc.CRITICAL_UTILIZATION_PCT:
        fail("ERR_SCHOOL_CAPACITY_CRITICAL")

    for field in services.SCORE_FIELDS:
        scenario[field] = scores[field]
    scenario["status"] = "UNDER_REVIEW"
    scenario["revision_reason"] = None
    touch(scenario)
    return respond(pub(scenario))


@bp.post("/scenarios/<scenario_id>/request-revision")
def request_revision(scenario_id):
    user_id, role = authenticate(["EngagementCoordinator", "BoardMember"])
    scenario_probe = db.scenarios.get(scenario_id)
    if scenario_probe is not None and scenario_probe["author_user_id"] == user_id:
        fail("ERR_SELF_REVIEW_FORBIDDEN")
    scenario = get_scenario(scenario_id)
    body = body_json()

    raw_ids = body.get("cited_comment_ids")
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if isinstance(item, str) and item:
                get_comment(item)
    cited_ids = _as_id_list(need(body, "cited_comment_ids"), "cited_comment_ids")
    if present(body, "revision_notes"):
        as_str(body["revision_notes"], "revision_notes", min_len=0)

    study = db.studies[scenario["study_id"]]
    if scenario["status"] == "UNDER_REVIEW" and study["status"] not in ("ENGAGEMENT", "BOARD_DECISION"):
        fail("ERR_STUDY_PHASE_INVALID")
    if scenario["status"] not in ("UNDER_REVIEW", "BOARD_READY"):
        fail("ERR_SCENARIO_NOT_REVIEWABLE")

    cited = []
    for comment_id in cited_ids:
        comment = get_comment(comment_id)
        if comment["scenario_id"] != scenario["id"] or comment["status"] != "TRIAGED":
            fail("ERR_COMMENT_STATE_INVALID")
        cited.append(comment)

    if scenario["revision_round"] >= MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED")

    from_board_ready = scenario["status"] == "BOARD_READY"
    scenario["status"] = "REVISION"
    scenario["revision_reason"] = "COMMENT_CYCLE"
    scenario["revision_round"] = scenario["revision_round"] + 1
    touch(scenario)

    for comment in ordered(cited):  # PublicComment.created_at ASC
        if comment["status"] == "TRIAGED":
            comment["status"] = "ADDRESSED"
            touch(comment)

    if from_board_ready:
        remaining = [s for s in scenarios_of_study(study["id"]) if s["status"] == "BOARD_READY"]
        if not remaining and study["status"] == "BOARD_DECISION":
            study["status"] = "ENGAGEMENT"
            recompute_study_values(study)
            touch(study)
    return respond(pub(scenario))


def _as_id_list(value, key):
    if not isinstance(value, list) or not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or not item:
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain string ids." % key)
        out.append(item)
    return out


@bp.post("/scenarios/<scenario_id>/advance-to-board")
def advance_to_board(scenario_id):
    user_id, _role = authenticate(["EngagementCoordinator"])
    scenario_probe = db.scenarios.get(scenario_id)
    if scenario_probe is not None and scenario_probe["author_user_id"] == user_id:
        fail("ERR_SELF_REVIEW_FORBIDDEN")
    scenario = get_scenario(scenario_id)
    body = body_json()
    if present(body, "agenda_notes"):
        as_str(body["agenda_notes"], "agenda_notes", min_len=0)

    study = db.studies[scenario["study_id"]]
    if study["status"] != "ENGAGEMENT":
        fail("ERR_STUDY_PHASE_INVALID")
    if scenario["status"] != "UNDER_REVIEW":
        fail("ERR_SCENARIO_NOT_REVIEWABLE")
    if scenario["projection_stale"]:
        fail("ERR_PROJECTION_STALE")
    if any(c["status"] == "SUBMITTED" for c in comments_of_scenario(scenario["id"])):
        fail("ERR_UNADDRESSED_COMMENTS")

    scenario["status"] = "BOARD_READY"
    touch(scenario)
    study["status"] = "BOARD_DECISION"
    recompute_study_values(study)
    touch(study)
    return respond(pub(scenario))


# ==========================================================================
# Area assignments
# ==========================================================================
@bp.post("/assignments")
def create_assignment():
    authenticate(["DistrictPlanner"])
    body = body_json()
    pre_resolve(get_scenario, body.get("scenario_id"))
    pre_resolve(get_area, body.get("area_id"))
    pre_resolve(get_school, body.get("assigned_school_id"))

    scenario = get_scenario(as_str(need(body, "scenario_id"), "scenario_id"))
    area = get_area(as_str(need(body, "area_id"), "area_id"))
    school = get_school(as_str(need(body, "assigned_school_id"), "assigned_school_id"))
    expected_version = as_int(need(body, "expected_scenario_version"), "expected_scenario_version")

    if scenario["status"] not in ("DRAFT", "REVISION"):
        fail("ERR_SCENARIO_NOT_EDITABLE")
    if school["status"] != "ACTIVE":
        fail("ERR_SCHOOL_NOT_ACTIVE")
    if expected_version != scenario["version"]:
        fail("ERR_STALE_SCENARIO_VERSION")

    option = None
    for entry in area["travel_options"]:
        if entry["school_id"] == school["id"]:
            option = entry
            break
    if option is None:
        fail("ERR_TRAVEL_OPTION_MISSING")
    if school["level"] != area["grade_band"]:
        fail("ERR_SCHOOL_LEVEL_MISMATCH")
    if area["study_id"] != scenario["study_id"] or school["study_id"] != scenario["study_id"]:
        fail("ERR_CROSS_STUDY_REFERENCE")
    if not calc.walk_eligible(option, school["level"]):
        if calc.dec(option["bus_minutes"]) > calc.MAX_RIDE_MINUTES[school["level"]]:
            fail("ERR_RIDE_TIME_EXCEEDED")

    run = db.runs.get(scenario["projection_run_id"])
    snapshot = 0
    if run is not None:
        entry = run["_proj"].get(area["id"])
        if entry is not None:
            snapshot = entry["proj"]

    previous = live_assignment_for_area(scenario["id"], area["id"])
    assignment = new_record()
    assignment.update({
        "scenario_id": scenario["id"],
        "area_id": area["id"],
        "assigned_school_id": school["id"],
        "is_superseded": False,
        "superseded_at": None,
        "projected_students": snapshot,
    })
    if previous is not None:
        previous["is_superseded"] = True
        previous["superseded_at"] = iso3(now())
        touch(previous)
    db.assignments[assignment["id"]] = assignment
    touch(scenario)
    return respond(pub(assignment), 201)


@bp.get("/assignments")
def list_assignments():
    authenticate(READ_ROLES_INTERNAL)
    rows = ordered(list(db.assignments.values()))
    for key in ("scenario_id", "area_id", "assigned_school_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    superseded = bool_filter("is_superseded")
    if superseded is not None:
        rows = [r for r in rows if r["is_superseded"] is superseded]
    return paginate(rows, pub)


@bp.get("/assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate(READ_ROLES_INTERNAL)
    return respond(pub(get_assignment(assignment_id)))


# ==========================================================================
# Public comments
# ==========================================================================
@bp.post("/comments")
def create_comment():
    user_id, _role = authenticate(["Guardian"])
    body = body_json()
    pre_resolve(get_scenario, body.get("scenario_id"))
    pre_resolve(get_area, body.get("area_id"))

    scenario = get_scenario(as_str(need(body, "scenario_id"), "scenario_id"))
    area_id = None
    if present(body, "area_id"):
        area_id = get_area(as_str(body["area_id"], "area_id"))["id"]
    text = as_str(need(body, "body"), "body", min_len=1, max_len=4000)

    study = db.studies[scenario["study_id"]]
    if study["status"] != "ENGAGEMENT":
        fail("ERR_STUDY_PHASE_INVALID")

    comment = new_record()
    comment.update({
        "scenario_id": scenario["id"],
        "area_id": area_id,
        "guardian_user_id": user_id,
        "body": text,
        "theme": None,
        "priority": None,
        "status": "SUBMITTED",
        "dismissal_reason": None,
    })
    db.comments[comment["id"]] = comment
    return respond(pub(comment), 201)


@bp.get("/comments")
def list_comments():
    authenticate(READ_ROLES_PUBLIC)
    rows = ordered(list(db.comments.values()))
    for key in ("scenario_id", "area_id", "status", "theme", "priority"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/comments/<comment_id>")
def read_comment(comment_id):
    authenticate(READ_ROLES_PUBLIC)
    return respond(pub(get_comment(comment_id)))


@bp.post("/comments/<comment_id>/triage")
def triage_comment(comment_id):
    authenticate(["EngagementCoordinator"])
    comment = get_comment(comment_id)
    body = body_json()
    theme = as_enum(need(body, "theme"), "theme", COMMENT_THEMES)
    priority = as_enum(need(body, "priority"), "priority", COMMENT_PRIORITIES)

    scenario = db.scenarios.get(comment["scenario_id"])
    if comment["status"] != "SUBMITTED":
        fail("ERR_COMMENT_STATE_INVALID")
    if scenario is None or scenario["status"] not in ("UNDER_REVIEW", "BOARD_READY"):
        fail("ERR_COMMENT_STATE_INVALID")

    comment["status"] = "TRIAGED"
    comment["theme"] = theme
    comment["priority"] = priority
    touch(comment)
    return respond(pub(comment))


@bp.post("/comments/<comment_id>/dismiss")
def dismiss_comment(comment_id):
    authenticate(["EngagementCoordinator"])
    comment = get_comment(comment_id)
    body = body_json()
    if present(body, "dismissal_notes"):
        as_str(body["dismissal_notes"], "dismissal_notes", min_len=0)
    if comment["status"] not in ("SUBMITTED", "TRIAGED"):
        fail("ERR_COMMENT_STATE_INVALID")
    comment["status"] = "DISMISSED"
    comment["dismissal_reason"] = "OFFICER_DISMISSAL"
    touch(comment)
    return respond(pub(comment))
